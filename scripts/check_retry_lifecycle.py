"""Live check of the delivery retry lifecycle against a real database.

The retry sweep depends on Postgres time semantics: a failed delivery becomes
PENDING with next_attempt_at in the future, is invisible to the sweep until that
moment passes, and recovers when a later attempt succeeds. None of that can be
proven against a fake, so this exercises it end to end with the clock advanced
by rewriting next_attempt_at rather than by waiting out real backoff.

    docker compose run --rm -T ingest python - < scripts/check_retry_lifecycle.py
"""

import asyncio
import os
import sys
from datetime import UTC, datetime

from resender.db import Database
from resender.models import CapturedMessage

MAX_ATTEMPTS = 8

failures: list[str] = []


def check(label: str, actual: object, expected: object) -> None:
    ok = actual == expected
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: {actual!r}")
    if not ok:
        failures.append(f"{label}: expected {expected!r}, got {actual!r}")


def message(msg_id: str) -> CapturedMessage:
    return CapturedMessage(
        id=msg_id,
        guild_id="100",
        guild_name="Alpha",
        channel_id="200",
        channel_name="signals",
        author_id="7",
        author_name="Bot",
        author_avatar_url=None,
        author_is_bot=True,
        content="BUY",
        embeds=[],
        attachments=[],
        raw={"author": {}},
        sent_at=datetime.now(UTC),
        edited_at=None,
    )


async def status_of(db: Database, msg_id: str, route: str) -> str:
    return await db.pool.fetchval(
        "SELECT status::text FROM deliveries WHERE message_id=$1 AND route=$2", msg_id, route
    )


async def next_attempt_of(db: Database, msg_id: str, route: str) -> datetime:
    return await db.pool.fetchval(
        "SELECT next_attempt_at FROM deliveries WHERE message_id=$1 AND route=$2", msg_id, route
    )


async def main() -> int:
    db = Database(os.environ["DATABASE_URL"])
    await db.connect()
    await db.pool.execute("DELETE FROM messages WHERE id LIKE '5000%'")

    msg = message("50000000000000001")
    await db.store_message(msg)
    await db.queue_delivery(msg.id, "alpha", "PENDING")

    print("first failure backs off into the future")
    await db.mark_attempt_failed(msg.id, "alpha", "boom", 0, MAX_ATTEMPTS)
    check("status is still PENDING", await status_of(db, msg.id, "alpha"), "PENDING")
    future = await next_attempt_of(db, msg.id, "alpha")
    check("next_attempt_at is in the future", future > datetime.now(UTC), True)
    check("not yet due", [d.route for d in await db.due_deliveries(MAX_ATTEMPTS)], [])

    print("becomes due once its backoff elapses")
    # Advance the clock by moving next_attempt_at into the past.
    await db.pool.execute(
        "UPDATE deliveries SET next_attempt_at = now() - interval '1 second' "
        "WHERE message_id=$1 AND route='alpha'",
        msg.id,
    )
    due = await db.due_deliveries(MAX_ATTEMPTS)
    check("now due", [d.route for d in due], ["alpha"])
    check("carries the attempt count", due[0].attempts if due else None, 1)

    print("recovers on a successful retry")
    await db.mark_delivered(msg.id, "alpha")
    check("status is DELIVERED", await status_of(db, msg.id, "alpha"), "DELIVERED")
    check("no longer due", [d.route for d in await db.due_deliveries(MAX_ATTEMPTS)], [])

    print("backoff grows with each attempt, capped at 15 minutes")
    await db.queue_delivery(msg.id, "beta", "PENDING")
    deltas = []
    for attempt in range(4):
        before = datetime.now(UTC)
        await db.mark_attempt_failed(msg.id, "beta", "boom", attempt, MAX_ATTEMPTS)
        scheduled = await next_attempt_of(db, msg.id, "beta")
        deltas.append((scheduled - before).total_seconds())
    # ~1, 2, 4, 8 seconds (2**attempt), strictly increasing while under the cap.
    check("delays strictly increase", all(b > a for a, b in zip(deltas, deltas[1:])), True)
    check("all delays under the 900s cap", all(d <= 901 for d in deltas), True)

    print("exhausts to FAILED and drops out of the sweep")
    await db.pool.execute(
        "UPDATE deliveries SET attempts=$1, next_attempt_at=now() "
        "WHERE message_id=$2 AND route='beta'",
        MAX_ATTEMPTS - 1,
        msg.id,
    )
    await db.mark_attempt_failed(msg.id, "beta", "final", MAX_ATTEMPTS - 1, MAX_ATTEMPTS)
    check("status is FAILED", await status_of(db, msg.id, "beta"), "FAILED")
    routes_due = [d.route for d in await db.due_deliveries(MAX_ATTEMPTS)]
    check("FAILED row is not swept again", "beta" not in routes_due, True)

    print("a non-retryable error fails immediately, without exhausting attempts")
    await db.queue_delivery(msg.id, "gamma", "PENDING")
    await db.mark_attempt_failed(msg.id, "gamma", "404", 0, MAX_ATTEMPTS, retryable=False)
    check("status is FAILED after one attempt", await status_of(db, msg.id, "gamma"), "FAILED")

    await db.pool.execute("DELETE FROM messages WHERE id LIKE '5000%'")
    await db.close()

    if failures:
        print(f"\n{len(failures)} check(s) failed:")
        for line in failures:
            print(f"  - {line}")
        return 1
    print("\nall retry lifecycle checks passed")
    return 0


sys.exit(asyncio.run(main()))
