import Fastify from "fastify";
import { requireBearerToken } from "./auth.js";
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
