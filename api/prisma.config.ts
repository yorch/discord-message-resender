import "dotenv/config";
import { defineConfig, env } from "prisma/config";

// CLI-only: read by `prisma migrate` and `prisma generate`. The runtime client
// ignores this file entirely and takes its connection string from the driver
// adapter in src/prisma.ts.
export default defineConfig({
  schema: "prisma/schema.prisma",
  migrations: { path: "prisma/migrations" },
  datasource: { url: env("DATABASE_URL") },
});
