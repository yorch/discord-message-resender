# Architecture

## Shape

```
                       ┌──────────────────────────────────────┐
  Discord gateway ────▶│ ingest (Python)                      │
  (persistent WSS)     │                                      │
                       │  listener  ─▶ normalize ─▶ store ────┼──▶ Postgres
                       │                              │       │      ▲
                       │                              ▼       │      │
                       │                          forwarder ──┼──▶ webhook ──▶ your server
                       │                          (+ retry)   │      │
                       └──────────────────────────────────────┘      │
                                                                     │
                       ┌──────────────────────────────────────┐      │
  HTTP clients   ─────▶│ api (Fastify + Prisma), read-only    │──────┘
                       └──────────────────────────────────────┘
```

## Why the halves are in different languages

The ingest half depends on `discord.py-self`, which is the only actively maintained
self-bot library. Its TypeScript counterpart, `discord.js-selfbot-v13`, is marked
deprecated on npm and its repository is archived, with no release since October 2025.

That staleness matters more than usual here. A self-bot library's real job is
impersonating the official Discord client: the IDENTIFY payload, the super-properties
header, the client build number, the heartbeat cadence. Discord changes those, and
mismatches are precisely what account-automation detection looks for. A library frozen
for eleven months presents a fingerprint no real client sends.

So the fragile, account-adjacent half uses the maintained Python library, and the API
half uses the TypeScript tooling already standard in this environment. The two never
call each other. Postgres is the entire interface between them.

## Schema ownership

Prisma owns the schema and the migrations. The ingest service does not use an ORM; it
writes through `asyncpg` with hand-written parameterised SQL against the tables Prisma
creates. Every Prisma field carries an explicit `@map` to a snake_case column so the SQL
on the Python side stays stable and idiomatic.

This keeps one source of truth for the schema while avoiding a second migration tool.
The cost is that a schema change requires updating the Python insert statement by hand,
which the ingest test suite catches.

## Store before forward

The forwarder never runs before the row is committed. Ordering matters: if a message
were forwarded first and persisted second, a crash between the two would drop the
archive record of an alert you may already have acted on.

Writing first also makes reconnection idempotent. The Discord gateway replays events
after a resume, and the source message snowflake is the primary key, so a replayed
message is a no-op `ON CONFLICT DO NOTHING` rather than a duplicate.

## Delivery as its own table

Forwarding state lives in `deliveries`, not as columns on `messages`. One captured
message can fan out to several targets, each of which can fail independently. A separate
row per message and route gives per-target retry state and a natural unique constraint
that prevents double-sending after a restart.

Retries use exponential backoff stored in `next_attempt_at`, so a sweeper can select
work with a plain indexed query rather than holding a queue in memory that a restart
would lose.

## Embeds are the payload

Trading alerts are usually posted by other bots as rich embeds, not plain text. An
implementation that reads only `message.content` captures empty strings for most of the
interesting traffic. The normalizer stores content, embeds, and attachments separately,
plus the complete raw event payload, so a later schema decision can be backfilled from
data already captured rather than requiring the messages to arrive again.
