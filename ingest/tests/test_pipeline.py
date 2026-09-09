import re

import pytest

from resender.config import Filters, Route, Settings
from resender.forwarder import DeliveryError, NothingToSendError
from resender.pipeline import Pipeline


class FakeDb:
    """Records an ordered event log so ordering guarantees can be asserted."""

    def __init__(self, log, already_stored=()):
        self.log = log
        self._stored = set(already_stored)
        self.failures = []

    async def store_message(self, message):
        if message.id in self._stored:
            return False
        self._stored.add(message.id)
        self.log.append(f"store:{message.id}")
        return True

    async def record_edit(self, message):
        self.log.append(f"edit:{message.id}")
        return True

    async def queue_delivery(self, message_id, route, status):
        self.log.append(f"queue:{message_id}:{route}:{status}")
        return True

    async def mark_delivered(self, message_id, route):
        self.log.append(f"delivered:{message_id}:{route}")

    async def mark_skipped(self, message_id, route):
        self.log.append(f"skipped:{message_id}:{route}")

    async def mark_attempt_failed(
        self, message_id, route, error, attempts, max_attempts, *, retryable=True
    ):
        self.log.append(f"failed:{message_id}:{route}:retryable={retryable}")
        self.failures.append((error, attempts, max_attempts, retryable))

    async def due_deliveries(self, max_attempts, limit=50):
        return []


class FakeForwarder:
    def __init__(self, log, error=None):
        self.log = log
        self.error = error
        self.sent = []

    async def send(self, webhook_url, message):
        if self.error is not None:
            raise self.error
        self.sent.append((webhook_url, message.id))
        self.log.append(f"send:{message.id}")


def build(routes, log, forwarder=None, already_stored=()):
    settings = Settings(
        token="t" * 40,
        database_url="postgresql://x/y",
        routes=tuple(routes),
    )
    db = FakeDb(log, already_stored)
    fw = forwarder or FakeForwarder(log)
    return Pipeline(settings, db, fw), db, fw


def route(**kw):
    defaults = {
        "name": "alpha",
        "guild_id": "100",
        "channel_ids": frozenset({"200"}),
        "webhook_url": "https://discord.com/api/webhooks/1/x",
        "filters": Filters(),
    }
    defaults.update(kw)
    return Route(**defaults)


async def test_archive_completes_before_the_forward(make_message):
    # If the forward went first, a crash between the two would lose the record of
    # an alert that had already been relayed and possibly acted on.
    log = []
    pipeline, _, _ = build([route()], log)
    await pipeline.ingest(make_message())
    assert log.index("store:900") < log.index("send:900")
    assert log == [
        "store:900",
        "queue:900:alpha:PENDING",
        "send:900",
        "delivered:900:alpha",
    ]


async def test_replayed_message_is_not_forwarded_twice(make_message):
    # The gateway replays events after a resume; the snowflake primary key makes
    # the repeat a no-op instead of a duplicate send.
    log = []
    pipeline, _, fw = build([route()], log, already_stored={"900"})
    await pipeline.ingest(make_message())
    assert fw.sent == []
    assert log == []


async def test_filtered_message_is_recorded_as_skipped_not_dropped(make_message):
    # Recording the skip lets the filters be audited against real traffic.
    log = []
    filters = Filters(match_any=(re.compile("sell", re.I),))
    pipeline, _, fw = build([route(filters=filters)], log)
    await pipeline.ingest(make_message(content="BUY SPY 500C"))
    assert fw.sent == []
    assert log == ["store:900", "queue:900:alpha:SKIPPED"]


async def test_archive_only_route_stores_without_a_delivery_row(make_message):
    log = []
    pipeline, _, fw = build([route(webhook_url=None)], log)
    await pipeline.ingest(make_message())
    assert fw.sent == []
    assert log == ["store:900"]


async def test_one_message_fans_out_to_every_matching_route(make_message):
    log = []
    routes = [
        route(name="alpha"),
        route(name="beta", webhook_url="https://discord.com/api/webhooks/2/y"),
    ]
    pipeline, _, fw = build(routes, log)
    await pipeline.ingest(make_message())
    assert len(fw.sent) == 2
    assert {"delivered:900:alpha", "delivered:900:beta"} <= set(log)


async def test_deleted_webhook_fails_immediately_instead_of_retrying(make_message):
    # A 404 cannot be fixed by waiting, so it must not burn the attempt budget.
    log = []
    error = DeliveryError("webhook responded 404", retryable=False)
    pipeline, db, _ = build([route()], log, forwarder=FakeForwarder(log, error=error))
    await pipeline.ingest(make_message())
    assert log[-1] == "failed:900:alpha:retryable=False"
    assert db.failures[0][3] is False


async def test_server_error_is_marked_retryable(make_message):
    log = []
    error = DeliveryError("webhook responded 503", retryable=True)
    pipeline, db, _ = build([route()], log, forwarder=FakeForwarder(log, error=error))
    await pipeline.ingest(make_message())
    assert db.failures[0][3] is True


async def test_unsendable_message_is_skipped_not_failed(make_message):
    log = []
    fw = FakeForwarder(log, error=NothingToSendError("900"))
    pipeline, db, _ = build([route()], log, forwarder=fw)
    await pipeline.ingest(make_message())
    assert log[-1] == "skipped:900:alpha"
    assert db.failures == []


async def test_retry_leaves_rows_for_routes_that_no_longer_exist(make_message, caplog):
    # A renamed route must not have its pending rows silently reassigned.
    log = []
    pipeline, db, fw = build([route(name="alpha")], log)

    async def due(max_attempts, limit=50):
        from resender.db import DueDelivery

        return [DueDelivery(route="removed", attempts=2, message=make_message())]

    db.due_deliveries = due
    with caplog.at_level("WARNING"):
        handled = await pipeline.retry_due()
    assert handled == 0
    assert fw.sent == []
    assert "unknown route" in caplog.text


@pytest.mark.parametrize("channel_id", ["999", ""])
async def test_message_from_an_unrouted_channel_is_archived_only(make_message, channel_id):
    log = []
    pipeline, _, fw = build([route()], log)
    await pipeline.ingest(make_message(channel_id=channel_id))
    assert fw.sent == []
    assert log == ["store:900"]
