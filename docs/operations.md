# Operations

## Day to day

```bash
docker compose up -d          # start
docker compose logs -f ingest # watch captures and deliveries
docker compose ps             # health
docker compose down           # stop, keeping data
```

`docker compose down -v` deletes the archive. There is no confirmation.

## The dashboard

A read-only web view is served by the API at `http://localhost:4000/`. Paste
your `API_TOKEN` once; it is kept in that browser's local storage and sent only
on the page's own calls to the API. The page lists captured messages with their
embeds and delivery status, searches content, filters by channel, and toggles
between all, live-only, and deleted-only. Deleted alerts appear struck through.

The page itself is unauthenticated markup. Every request for actual data still
carries the bearer token, so the archive is not exposed by the dashboard route.

## Querying the archive

```bash
TOKEN=$(grep '^API_TOKEN=' .env | cut -d= -f2-)
AUTH="Authorization: Bearer $TOKEN"

curl -H "$AUTH" 'http://localhost:4000/stats'
curl -H "$AUTH" 'http://localhost:4000/alerts?limit=20'
curl -H "$AUTH" 'http://localhost:4000/alerts?channelId=111&since=2026-09-01'
curl -H "$AUTH" 'http://localhost:4000/alerts?q=SPY'
```

Paging follows `page.nextCursor`; pass it back as `cursor`. The cursor is a
keyset over sent time and ID rather than an offset, so new arrivals at the head
do not cause a page to repeat or skip rows.

Note that `q` searches the plain-text content column only. Alerts that live
entirely in an embed will not match it. Filter by channel and read the embeds
from the response instead.

## Delivery failures

`/stats` reports delivery counts per route and status.

- `PENDING` is queued or waiting out a backoff.
- `DELIVERED` succeeded.
- `SKIPPED` matched a route but was filtered out, or carried nothing sendable.
- `FAILED` exhausted its attempts, or hit an error that retrying cannot fix.

A `FAILED` row usually means the webhook was deleted or its URL is wrong; those
return 401, 403, or 404 and fail immediately rather than spending the attempt
budget. Read the reason directly:

```sql
SELECT route, attempts, last_error
  FROM deliveries WHERE status = 'FAILED' ORDER BY created_at DESC LIMIT 20;
```

After fixing the webhook, requeue them:

```sql
UPDATE deliveries
   SET status = 'PENDING', attempts = 0, next_attempt_at = now()
 WHERE status = 'FAILED';
```

The sweeper picks them up within its interval.

## Deleted alerts

A message deleted in the source channel is not removed from the archive. Its
`deleted_at` is set and the row is kept, because a retracted alert is itself a
signal. Both single deletes and channel purges (bulk deletes) are captured, and
they fire even for messages the client never cached.

Filter them through the API:

```bash
curl -H "$AUTH" 'http://localhost:4000/alerts?deleted=only'      # retracted only
curl -H "$AUTH" 'http://localhost:4000/alerts?deleted=exclude'   # live only
```

`/stats` reports `deletedMessages` alongside the total.

## Backups

The archive is the point of the system, so back it up rather than the container.

```bash
docker compose exec -T postgres pg_dump -U resender resender | gzip > backup.sql.gz
gunzip -c backup.sql.gz | docker compose exec -T postgres psql -U resender resender
```

The named volume is mounted at `/var/lib/postgresql`, which is where Postgres 18
declares its VOLUME. If you ever change that mount path, check
`docker inspect postgres:18-alpine` first: mounting the wrong path appears to
work while writing to an anonymous volume that a prune destroys.

## Changing the schema

Prisma owns migrations, and the ingest service writes hand-written SQL against
the same tables, so a schema change is a two-sided edit.

1. Edit `api/prisma/schema.prisma`, keeping the explicit `@map` on every field.
2. Generate the migration:
   ```bash
   cd api && pnpm exec prisma migrate diff --from-migrations prisma/migrations \
     --to-schema prisma/schema.prisma --script \
     --output prisma/migrations/$(date +%Y%m%d%H%M%S)_change/migration.sql
   ```
3. Update the SQL constants and the row mapper in `ingest/src/resender/db.py`.
4. Run `./scripts/verify-stack.sh`. The contract check is what catches a column
   the Python side missed; no unit test can see across the language boundary.

## Upgrading the self-bot library

`discord.py-self` tracks changes to the official client that the account is
impersonating. A stale version sends a fingerprint no real client sends, which
is the main thing automated detection looks for. Check for releases periodically
and upgrade promptly rather than pinning indefinitely:

```bash
cd ingest && uv lock --upgrade-package discord.py-self && uv sync
uv run pytest && docker compose build ingest
```

## Restarting

Restarts are safe at any point. The archive write commits before the forward, so
a message that was stored but not yet delivered keeps its `PENDING` delivery row
and is retried. The unique key on message and route is what prevents a second
copy being sent.

Run only one instance. Two processes holding gateway sessions for the same
account is not a pattern a real client produces.
