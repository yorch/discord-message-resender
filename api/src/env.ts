import "dotenv/config";
import { z } from "zod";

const schema = z.object({
  DATABASE_URL: z.string().min(1, "DATABASE_URL is required"),
  API_PORT: z.coerce.number().int().positive().default(4000),
  API_TOKEN: z
    .string()
    .min(32, "API_TOKEN must be at least 32 characters. Generate with: openssl rand -hex 32"),
  NODE_ENV: z.enum(["development", "production", "test"]).default("production"),
});

const parsed = schema.safeParse(process.env);

if (!parsed.success) {
  // Print the field names and messages only. Never echo the values: this object
  // holds the database password.
  const issues = parsed.error.issues.map((i) => `  ${i.path.join(".")}: ${i.message}`).join("\n");
  throw new Error(`Invalid environment configuration:\n${issues}`);
}

export const env = parsed.data;
