import { randomBytes } from "node:crypto";
import Fastify from "fastify";
import { requireBearerToken } from "./auth.js";
import { renderDashboard } from "./dashboard.js";
import { env } from "./env.js";
import { prisma } from "./prisma.js";
import { alertRoutes } from "./routes/alerts.js";

const app = Fastify({
  logger: {
    level: env.NODE_ENV === "development" ? "debug" : "info",
    // The connection string carries the database password and shows up in
    // Prisma error objects, so scrub it from every log record.
    redact: ["req.headers.authorization", "*.connectionString", "*.DATABASE_URL"],
  },
});

// Unauthenticated markup. The bearer token is entered in the page and used only
// on its calls to /alerts and /stats, which stay behind the auth hook below.
app.get("/", async (_request, reply) => {
  // Per-request nonce ties the CSP to exactly this response's inline blocks.
  const nonce = randomBytes(16).toString("base64");
  const csp = [
    "default-src 'none'",
    `style-src 'nonce-${nonce}'`,
    `script-src 'nonce-${nonce}'`,
    // Message images are Discord-hosted; scope img-src to Discord's CDNs (plus
    // data: for inline placeholders) so a non-Discord URL in a captured message
    // cannot be used to beacon the viewer.
    // Discord serves attachments from cdn.discordapp.com and proxies embed images
    // through media/images-ext hosts on discordapp.net; scope to those, not all https.
    "img-src https://cdn.discordapp.com https://*.discordapp.net data:",
    // The dashboard's fetch() calls to /alerts and /stats are same-origin.
    "connect-src 'self'",
    "frame-ancestors 'none'",
    "base-uri 'none'",
    "form-action 'none'",
  ].join("; ");
  return reply
    .type("text/html")
    .header("Content-Security-Policy", csp)
    .header("X-Content-Type-Options", "nosniff")
    .header("X-Frame-Options", "DENY")
    .header("Referrer-Policy", "no-referrer")
    .send(renderDashboard(nonce));
});

// Unauthenticated: this is what the container healthcheck hits.
app.get("/health", async (_request, reply) => {
  try {
    await prisma.$queryRaw`SELECT 1`;
    return { status: "ok", database: "up" };
  } catch {
    return reply.code(503).send({ status: "degraded", database: "down" });
  }
});

await app.register(
  async (instance) => {
    instance.addHook("preHandler", requireBearerToken);
    await instance.register(alertRoutes);
  },
  { prefix: "/" },
);

async function shutdown(signal: string) {
  app.log.info({ signal }, "shutting down");
  await app.close();
  await prisma.$disconnect();
  process.exit(0);
}

for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.on(signal, () => void shutdown(signal));
}

await app.listen({ port: env.API_PORT, host: "0.0.0.0" });
