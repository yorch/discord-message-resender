"""Postgres access for the ingest service.

Prisma owns the schema; this module writes to it with hand-written SQL. The
snake_case column names below are a contract with api/prisma/schema.prisma,
where every field carries an explicit @map to keep them stable.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg

from .models import CapturedMessage

log = logging.getLogger(__name__)

_INSERT_MESSAGE = """
INSERT INTO messages (
    id, guild_id, guild_name, channel_id, channel_name,
    author_id, author_name, author_is_bot,
    content, search_text, embeds, attachments, raw, sent_at, edited_at
) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
ON CONFLICT (id) DO NOTHING
RETURNING id
"""

_UPDATE_MESSAGE = """
UPDATE messages
   SET content = $2, search_text = $3, embeds = $4, attachments = $5, raw = $6, edited_at = $7
 WHERE id = $1
RETURNING id
"""

_SOFT_DELETE_MESSAGE = """
UPDATE messages
   SET deleted_at = now()
 WHERE id = $1 AND deleted_at IS NULL
RETURNING id
"""

_INSERT_DELIVERY = """
INSERT INTO deliveries (message_id, route, status)
VALUES ($1, $2, $3::delivery_status)
ON CONFLICT (message_id, route) DO NOTHING
RETURNING message_id
"""

_MARK_DELIVERED = """
UPDATE deliveries
   SET status = 'DELIVERED', attempts = attempts + 1,
       delivered_at = now(), last_error = NULL
 WHERE message_id = $1 AND route = $2
"""

_MARK_SKIPPED = """
UPDATE deliveries
   SET status = 'SKIPPED', last_error = NULL
 WHERE message_id = $1 AND route = $2
"""

_MARK_ATTEMPT_FAILED = """
UPDATE deliveries
   SET status = $3::delivery_status, attempts = attempts + 1,
       last_error = $4, next_attempt_at = $5
 WHERE message_id = $1 AND route = $2
"""

# Retryable work is exactly the PENDING rows whose backoff has elapsed. FAILED
# means the attempt budget is spent and a human should look at last_error.
_DUE_DELIVERIES = """
SELECT d.route, d.attempts, m.*
  FROM deliveries d
  JOIN messages m ON m.id = d.message_id
 WHERE d.status = 'PENDING'
   AND d.next_attempt_at <= now()
   AND d.attempts < $1
 ORDER BY d.next_attempt_at
 LIMIT $2
"""


@dataclass(frozen=True)
class DueDelivery:
    route: str
    attempts: int
    message: CapturedMessage


async def _register_codecs(conn: asyncpg.Connection) -> None:
    # asyncpg hands back jsonb as a string and refuses to encode dicts unless a
    # codec is registered on the connection.
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


def _row_to_message(row: asyncpg.Record) -> CapturedMessage:
    raw: dict[str, Any] = row["raw"] or {}
    author = raw.get("author") or {}
    return CapturedMessage(
        id=row["id"],
        guild_id=row["guild_id"],
        guild_name=row["guild_name"],
        channel_id=row["channel_id"],
        channel_name=row["channel_name"],
        author_id=row["author_id"],
        author_name=row["author_name"],
        author_avatar_url=author.get("avatar_url"),
        author_is_bot=row["author_is_bot"],
        content=row["content"],
        embeds=row["embeds"] or [],
        attachments=row["attachments"] or [],
        raw=raw,
        sent_at=row["sent_at"],
        edited_at=row["edited_at"],
    )


class Database:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Database.connect() has not been awaited")
        return self._pool

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(
            self._dsn, min_size=1, max_size=5, init=_register_codecs
        )
        log.info("connected to postgres")

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def store_message(self, message: CapturedMessage) -> bool:
        """Insert a captured message. Returns False if it was already stored.

        A gateway resume replays events, so a repeat is expected rather than
        exceptional; the snowflake primary key makes it a no-op.
        """
        inserted = await self.pool.fetchval(
            _INSERT_MESSAGE,
            message.id,
            message.guild_id,
            message.guild_name,
            message.channel_id,
            message.channel_name,
            message.author_id,
            message.author_name,
            message.author_is_bot,
            message.content,
            message.searchable_text,
            message.embeds,
            message.attachments,
            message.raw,
            message.sent_at,
            message.edited_at,
        )
        return inserted is not None

    async def record_edit(self, message: CapturedMessage) -> bool:
        """Apply an edit to an already-stored message. False if it is unknown."""
        updated = await self.pool.fetchval(
            _UPDATE_MESSAGE,
            message.id,
            message.content,
            message.searchable_text,
            message.embeds,
            message.attachments,
            message.raw,
            message.edited_at or datetime.now(UTC),
        )
        return updated is not None

    async def record_delete(self, message_id: str) -> bool:
        """Soft-delete a stored message. False if it was unknown or already deleted.

        The row is kept: a deleted alert is itself a signal, and the WHERE guard
        on deleted_at makes a repeated delete event a no-op rather than moving
        the timestamp each time the gateway replays it.
        """
        deleted = await self.pool.fetchval(_SOFT_DELETE_MESSAGE, message_id)
        return deleted is not None

    async def record_bulk_delete(self, message_ids: list[str]) -> int:
        """Soft-delete many messages at once, as when a channel is purged.

        Returns how many rows this actually flipped, which is only the ones we
        had stored; unknown IDs in the purge are ignored.
        """
        if not message_ids:
            return 0
        rows = await self.pool.fetch(
            "UPDATE messages SET deleted_at = now() "
            "WHERE id = ANY($1::text[]) AND deleted_at IS NULL RETURNING id",
            message_ids,
        )
        return len(rows)

    async def queue_delivery(self, message_id: str, route: str, status: str) -> bool:
        """Create the delivery row. False if this route already has one."""
        created = await self.pool.fetchval(_INSERT_DELIVERY, message_id, route, status)
        return created is not None

    async def mark_delivered(self, message_id: str, route: str) -> None:
        await self.pool.execute(_MARK_DELIVERED, message_id, route)

    async def mark_skipped(self, message_id: str, route: str) -> None:
        await self.pool.execute(_MARK_SKIPPED, message_id, route)

    async def mark_attempt_failed(
        self,
        message_id: str,
        route: str,
        error: str,
        attempts_so_far: int,
        max_attempts: int,
        *,
        retryable: bool = True,
    ) -> None:
        # A deleted webhook or a malformed payload cannot be fixed by waiting, so
        # those fail straight away rather than spending the whole attempt budget.
        exhausted = not retryable or attempts_so_far + 1 >= max_attempts
        status = "FAILED" if exhausted else "PENDING"
        # Exponential backoff capped at fifteen minutes. Stored rather than held
        # in memory so a restart resumes the schedule instead of retrying at once.
        delay = min(2**attempts_so_far, 900)
        next_attempt = datetime.now(UTC) + timedelta(seconds=delay)
        await self.pool.execute(
            _MARK_ATTEMPT_FAILED, message_id, route, status, error[:2000], next_attempt
        )
        if exhausted:
            log.error("delivery permanently failed: route=%s message=%s", route, message_id)

    async def due_deliveries(self, max_attempts: int, limit: int = 50) -> list[DueDelivery]:
        rows = await self.pool.fetch(_DUE_DELIVERIES, max_attempts, limit)
        return [
            DueDelivery(route=row["route"], attempts=row["attempts"], message=_row_to_message(row))
            for row in rows
        ]
