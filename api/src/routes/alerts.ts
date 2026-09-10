import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { prisma } from "../prisma.js";

const MAX_LIMIT = 200;

const listQuery = z.object({
  guildId: z.string().optional(),
  channelId: z.string().optional(),
  authorId: z.string().optional(),
  /// Case-insensitive substring match against searchText, which the ingest
  /// service fills with the content plus every embed's text.
  q: z.string().min(1).optional(),
  since: z.coerce.date().optional(),
  until: z.coerce.date().optional(),
  /// any (default) returns live and deleted; only returns deleted; exclude hides them.
  deleted: z.enum(["any", "only", "exclude"]).default("any"),
  /// When true, only messages that have at least one FAILED delivery.
  failed: z.coerce.boolean().optional(),
  limit: z.coerce.number().int().positive().max(MAX_LIMIT).default(50),
  cursor: z.string().optional(),
});

type Cursor = { sentAt: Date; id: string };

/// Keyset pagination over (sent_at desc, id desc). Offset pagination would drift
/// as new messages arrive at the head, silently repeating or skipping rows.
function encodeCursor(row: Cursor): string {
  return Buffer.from(`${row.sentAt.toISOString()}|${row.id}`, "utf8").toString("base64url");
}

function decodeCursor(raw: string): Cursor {
  const decoded = Buffer.from(raw, "base64url").toString("utf8");
  const sep = decoded.lastIndexOf("|");
  const sentAt = new Date(decoded.slice(0, sep));
  const id = decoded.slice(sep + 1);
  if (sep === -1 || Number.isNaN(sentAt.getTime()) || !id) {
    throw new Error("malformed cursor");
  }
  return { sentAt, id };
}

export async function alertRoutes(app: FastifyInstance) {
  app.get("/alerts", async (request, reply) => {
    const parsed = listQuery.safeParse(request.query);
    if (!parsed.success) {
      return reply.code(400).send({ error: "invalid query", issues: parsed.error.issues });
    }
    const { guildId, channelId, authorId, q, since, until, deleted, failed, limit, cursor } =
      parsed.data;

    let after: Cursor | undefined;
    if (cursor) {
      try {
        after = decodeCursor(cursor);
      } catch {
        return reply.code(400).send({ error: "invalid cursor" });
      }
    }

    const rows = await prisma.message.findMany({
      where: {
        ...(guildId && { guildId }),
        ...(channelId && { channelId }),
        ...(authorId && { authorId }),
        ...(q && { searchText: { contains: q, mode: "insensitive" } }),
        ...((since || until) && {
          sentAt: { ...(since && { gte: since }), ...(until && { lte: until }) },
        }),
        ...(deleted === "only" && { deletedAt: { not: null } }),
        ...(deleted === "exclude" && { deletedAt: null }),
        ...(failed && { deliveries: { some: { status: "FAILED" } } }),
        // Row-value comparison expressed as OR, since Prisma has no tuple
        // comparison. Equivalent to (sent_at, id) < (cursor.sentAt, cursor.id).
        ...(after && {
          OR: [{ sentAt: { lt: after.sentAt } }, { sentAt: after.sentAt, id: { lt: after.id } }],
        }),
      },
      orderBy: [{ sentAt: "desc" }, { id: "desc" }],
      // One extra row tells us whether another page exists without a count query.
      take: limit + 1,
      // The full raw snapshot is large and unused by list clients; /alerts/:id
      // still returns it for the rare case that needs the complete payload.
      omit: { raw: true },
      include: {
        deliveries: {
          select: {
            route: true,
            status: true,
            attempts: true,
            deliveredAt: true,
            lastError: true,
          },
        },
      },
    });

    const hasMore = rows.length > limit;
    const page = hasMore ? rows.slice(0, limit) : rows;
    const last = page.at(-1);

    return {
      data: page,
      page: {
        limit,
        hasMore,
        nextCursor: hasMore && last ? encodeCursor(last) : null,
      },
    };
  });

  app.get("/alerts/:id", async (request, reply) => {
    const params = z.object({ id: z.string().min(1) }).safeParse(request.params);
    if (!params.success) {
      return reply.code(400).send({ error: "invalid id" });
    }
    const message = await prisma.message.findUnique({
      where: { id: params.data.id },
      include: { deliveries: true },
    });
    if (!message) {
      return reply.code(404).send({ error: "not found" });
    }
    return message;
  });

  app.get("/stats", async () => {
    const [byChannel, byAuthor, byDeliveryStatus, total, deletedCount, latest] = await Promise.all([
      prisma.message.groupBy({
        by: ["guildId", "guildName", "channelId", "channelName"],
        _count: { _all: true },
        _max: { sentAt: true },
      }),
      prisma.message.groupBy({
        by: ["authorId", "authorName"],
        _count: { _all: true },
        orderBy: { _count: { authorId: "desc" } },
        take: 100,
      }),
      prisma.delivery.groupBy({ by: ["route", "status"], _count: { _all: true } }),
      prisma.message.count(),
      prisma.message.count({ where: { deletedAt: { not: null } } }),
      prisma.message.findFirst({ orderBy: { sentAt: "desc" }, select: { sentAt: true } }),
    ]);

    return {
      totalMessages: total,
      deletedMessages: deletedCount,
      latestMessageAt: latest?.sentAt ?? null,
      channels: byChannel.map((c) => ({
        guildId: c.guildId,
        guildName: c.guildName,
        channelId: c.channelId,
        channelName: c.channelName,
        messages: c._count._all,
        latestMessageAt: c._max.sentAt,
      })),
      authors: byAuthor.map((a) => ({
        authorId: a.authorId,
        authorName: a.authorName,
        messages: a._count._all,
      })),
      deliveries: byDeliveryStatus.map((d) => ({
        route: d.route,
        status: d.status,
        count: d._count._all,
      })),
    };
  });
}
