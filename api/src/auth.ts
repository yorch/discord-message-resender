import { timingSafeEqual } from "node:crypto";
import type { FastifyReply, FastifyRequest } from "fastify";
import { env } from "./env.js";

const expected = Buffer.from(env.API_TOKEN, "utf8");

/// Constant-time bearer check. A plain === leaks the token prefix through
/// response timing to anyone who can measure it, which is cheap on a LAN.
function tokenMatches(candidate: string): boolean {
  const given = Buffer.from(candidate, "utf8");
  if (given.length !== expected.length) return false;
  return timingSafeEqual(given, expected);
}

export async function requireBearerToken(request: FastifyRequest, reply: FastifyReply) {
  const header = request.headers.authorization;
  if (!header?.startsWith("Bearer ")) {
    return reply.code(401).send({ error: "missing bearer token" });
  }
  if (!tokenMatches(header.slice("Bearer ".length))) {
    return reply.code(401).send({ error: "invalid bearer token" });
  }
}
