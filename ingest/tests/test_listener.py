"""Listener-level tests for the raw delete handlers.

These exist because the channel guard compares a stringified payload ID against
a frozenset of string IDs. If the str() coercion regressed, an int would never
match the set and every delete would be silently dropped, yet the pipeline-level
tests would still pass. These lock that boundary down.
"""

from types import SimpleNamespace

import pytest

from resender.config import Filters, Route, Settings
from resender.listener import AlertListener


class FakePipeline:
    def __init__(self):
        self.calls: list[tuple[str, object]] = []

    async def apply_delete(self, message_id):
        self.calls.append(("delete", message_id))

    async def apply_bulk_delete(self, message_ids):
        self.calls.append(("bulk", message_ids))


def make_listener(watched: set[str]):
    settings = Settings(
        token="t" * 40,
        database_url="postgresql://x/y",
        routes=(
            Route(
                name="r",
                guild_id="100",
                channel_ids=frozenset(watched),
                webhook_url=None,
                filters=Filters(),
            ),
        ),
    )
    pipeline = FakePipeline()
    return AlertListener(settings, pipeline), pipeline


async def test_raw_delete_in_watched_channel_stringifies_id():
    listener, pipeline = make_listener({"200"})
    # Discord hands these back as ints, the watched set holds strings.
    payload = SimpleNamespace(message_id=900, channel_id=200, guild_id=100)
    await listener.on_raw_message_delete(payload)
    assert pipeline.calls == [("delete", "900")]


async def test_raw_delete_in_unwatched_channel_is_ignored():
    listener, pipeline = make_listener({"200"})
    payload = SimpleNamespace(message_id=900, channel_id=999, guild_id=100)
    await listener.on_raw_message_delete(payload)
    assert pipeline.calls == []


async def test_raw_bulk_delete_stringifies_every_id():
    listener, pipeline = make_listener({"200"})
    # message_ids is a set of ints on the real event.
    payload = SimpleNamespace(message_ids={1, 2, 3}, channel_id=200, guild_id=100)
    await listener.on_raw_bulk_message_delete(payload)
    assert pipeline.calls[0][0] == "bulk"
    assert sorted(pipeline.calls[0][1]) == ["1", "2", "3"]


async def test_raw_bulk_delete_in_unwatched_channel_is_ignored():
    listener, pipeline = make_listener({"200"})
    payload = SimpleNamespace(message_ids={1, 2}, channel_id=999, guild_id=100)
    await listener.on_raw_bulk_message_delete(payload)
    assert pipeline.calls == []


@pytest.mark.parametrize("channel_id", [200, "200"])
async def test_guard_matches_regardless_of_int_or_str_channel(channel_id):
    listener, pipeline = make_listener({"200"})
    payload = SimpleNamespace(message_id=5, channel_id=channel_id, guild_id=100)
    await listener.on_raw_message_delete(payload)
    assert pipeline.calls == [("delete", "5")]
