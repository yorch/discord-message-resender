"""Live check that the ingest SQL still matches the Prisma-managed schema.

The two services are in different languages and the Python side writes with
hand-written SQL, so the column contract is the one thing no unit test can
verify. Run this against a real database after any schema change:

    docker compose run --rm -T ingest python - < scripts/check_schema_contract.py
"""

import asyncio
import os
import sys
from dataclasses import replace
from datetime import UTC, datetime

from resender.db import Database
from resender.models import CapturedMessage

MESSAGE = CapturedMessage(
    id="999000111222333444",
    guild_id="100",
    guild_name="Alpha Server",
    channel_id="200",
    channel_name="signals",
    author_id="7",
    author_name="Alert Bot",
    author_avatar_url="https://cdn.example/a.png",
    author_is_bot=True,
    content="BUY SPY 500C",
    embeds=[{"title": "Entry", "description": "SPY 500C", "fields": [{"name": "T", "value": "512"}]}],
    attachments=[{"url": "https://cdn.example/chart.png"}],
    raw={"author": {"avatar_url": "https://cdn.example/a.png"}},
    sent_at=datetime.now(UTC),
    edited_at=None,
)

failures: list[str] = []


def check(label: str, actual: object, expected: object) -> None:
    ok = actual == expected
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: {actual!r}")
    if not ok:
        failures.append(f"{label}: expected {expected!r}, got {actual!r}")


async def main() -> int:
    db = Database(os.environ["DATABASE_URL"])
    await db.connect()
    await db.pool.execute("DELETE FROM messages WHERE id = $1", MESSAGE.id)

    print("insert and dedup")
    check("first store inserts", await db.store_message(MESSAGE), True)
    check("replayed store is a no-op", await db.store_message(MESSAGE), False)

    print("search text")
    search_text = await db.pool.fetchval(
        "SELECT search_text FROM messages WHERE id = $1", MESSAGE.id
    )
    # The ingest writes content + embed text so search reaches embed-only alerts.
    check("search_text includes content", "BUY SPY 500C" in (search_text or ""), True)
    check("search_text includes embed field", "512" in (search_text or ""), True)

    print("delivery rows")
    check("first queue creates row", await db.queue_delivery(MESSAGE.id, "alpha", "PENDING"), True)
    check("repeat queue is a no-op", await db.queue_delivery(MESSAGE.id, "alpha", "PENDING"), False)
    await db.mark_delivered(MESSAGE.id, "alpha")

    print("edits")
    edited = replace(MESSAGE, content="BUY SPY 505C", edited_at=datetime.now(UTC))
    check("edit applies", await db.record_edit(edited), True)

    print("retry sweep")
    await db.queue_delivery(MESSAGE.id, "beta", "PENDING")
    due = await db.due_deliveries(8)
    # Regression guard: at Timestamptz(3) the default next_attempt_at rounded up
    # to half a millisecond into the future and this came back empty.
    check("freshly queued row is immediately due", [d.route for d in due], ["beta"])

    if due:
        row = due[0].message
        print("roundtrip fidelity")
        check("content", row.content, "BUY SPY 505C")
        check("embeds survive jsonb", row.embeds, edited.embeds)
        check("attachments survive jsonb", row.attachments, edited.attachments)
        check("avatar recovered from raw", row.author_avatar_url, "https://cdn.example/a.png")
        check("sent_at is timezone aware", row.sent_at.tzinfo is not None, True)
        check("author_is_bot", row.author_is_bot, True)

    print("soft delete")
    check("delete marks a stored message", await db.record_delete(MESSAGE.id), True)
    is_deleted = await db.pool.fetchval(
        "SELECT deleted_at IS NOT NULL FROM messages WHERE id=$1", MESSAGE.id
    )
    check("deleted_at is set", is_deleted, True)
    check("repeated delete is a no-op", await db.record_delete(MESSAGE.id), False)
    check("bulk delete counts only known ids", await db.record_bulk_delete([MESSAGE.id, "1"]), 0)

    print("failure handling")
    await db.mark_attempt_failed(MESSAGE.id, "beta", "simulated 503", 0, 8)
    status = await db.pool.fetchval(
        "SELECT status::text FROM deliveries WHERE message_id=$1 AND route='beta'", MESSAGE.id
    )
    check("retryable failure stays PENDING", status, "PENDING")

    await db.mark_attempt_failed(MESSAGE.id, "beta", "simulated 404", 1, 8, retryable=False)
    status = await db.pool.fetchval(
        "SELECT status::text FROM deliveries WHERE message_id=$1 AND route='beta'", MESSAGE.id
    )
    check("non-retryable failure goes straight to FAILED", status, "FAILED")

    await db.pool.execute("DELETE FROM messages WHERE id = $1", MESSAGE.id)
    await db.close()

    if failures:
        print(f"\n{len(failures)} check(s) failed:")
        for line in failures:
            print(f"  - {line}")
        return 1
    print("\nall schema contract checks passed")
    return 0


sys.exit(asyncio.run(main()))
