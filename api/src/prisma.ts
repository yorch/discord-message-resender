import { PrismaPg } from "@prisma/adapter-pg";
import { env } from "./env.js";
import { PrismaClient } from "./generated/client/client.js";

// Prisma 7 requires an explicit driver adapter; the client does not read
// prisma.config.ts and has no other way to learn the connection string.
const adapter = new PrismaPg({ connectionString: env.DATABASE_URL });

export const prisma = new PrismaClient({
  adapter,
  log: env.NODE_ENV === "development" ? ["query", "warn", "error"] : ["error"],
});
