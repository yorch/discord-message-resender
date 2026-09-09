from datetime import UTC, datetime

from resender.models import from_discord_message


class _Asset:
    url = "https://cdn.example/avatar.png"


class _Author:
    id = 7
    name = "alertbot"
    global_name = None
    display_name = "Alert Bot"
    bot = True
    display_avatar = _Asset()


class _Named:
    def __init__(self, name):
        self.name = name


class _Channel:
    id = 200
    name = "signals"
    type = _Named("text")


class _Guild:
    id = 100
    name = "Alpha Server"


class _Embed:
    def __init__(self, data):
        self._data = data

    def to_dict(self):
        return self._data


class _Message:
    id = 900
    content = "heads up"
    author = _Author()
    channel = _Channel()
    guild = _Guild()
    attachments = ()
    created_at = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
    edited_at = None
    jump_url = "https://discord.com/channels/100/200/900"
    webhook_id = None
    pinned = False
    tts = False
    reference = None
    type = _Named("default")

    def __init__(self, embeds=()):
        self.embeds = [_Embed(e) for e in embeds]


def test_flattens_ids_to_strings():
    captured = from_discord_message(_Message())
    assert captured.id == "900"
    assert captured.guild_id == "100"
    assert captured.channel_id == "200"
    assert captured.author_id == "7"
    assert captured.author_is_bot is True


def test_searchable_text_reaches_inside_embeds():
    # Most alert bots leave content empty and put the signal in an embed, so a
    # filter that only saw content would match nothing.
    embed = {
        "title": "Entry Signal",
        "description": "SPY 500C",
        "fields": [{"name": "Target", "value": "512"}],
        "footer": {"text": "not financial advice"},
    }
    captured = from_discord_message(_Message(embeds=[embed]))
    text = captured.searchable_text
    for expected in ("heads up", "Entry Signal", "SPY 500C", "Target", "512", "not financial"):
        assert expected in text


def test_webhook_embeds_strip_server_populated_keys(make_message):
    # type, provider, and video are set by Discord on receipt and are rejected
    # or dropped when sent back through a webhook.
    captured = make_message(
        embeds=[{"title": "t", "type": "rich", "provider": {"name": "x"}, "video": {"url": "u"}}]
    )
    assert captured.webhook_embeds() == [{"title": "t"}]


def test_webhook_embeds_are_capped_at_ten(make_message):
    captured = make_message(embeds=[{"title": str(i)} for i in range(15)])
    assert len(captured.webhook_embeds()) == 10
