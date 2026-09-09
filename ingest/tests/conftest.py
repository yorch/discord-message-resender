from datetime import UTC, datetime

import pytest

from resender.models import CapturedMessage


def _make(**overrides) -> CapturedMessage:
    defaults = {
        "id": "900",
        "guild_id": "100",
        "guild_name": "Alpha Server",
        "channel_id": "200",
        "channel_name": "signals",
        "author_id": "7",
        "author_name": "Alert Bot",
        "author_avatar_url": "https://cdn.example/avatar.png",
        "author_is_bot": True,
        "content": "BUY SPY 500C",
        "embeds": [],
        "attachments": [],
        "raw": {},
        "sent_at": datetime(2026, 9, 9, 12, 0, tzinfo=UTC),
        "edited_at": None,
    }
    defaults.update(overrides)
    return CapturedMessage(**defaults)


@pytest.fixture
def make_message():
    """Factory for a CapturedMessage with sensible defaults."""
    return _make
