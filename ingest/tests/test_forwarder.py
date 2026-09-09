import pytest

from resender.forwarder import CONTENT_LIMIT, NothingToSendError, build_payload


def test_mentions_are_suppressed(make_message):
    # A relayed alert routinely contains @everyone that was meaningful in the
    # source server. Without this the relay would notify the whole destination.
    payload = build_payload(make_message(content="@everyone BUY NOW"))
    assert payload["allowed_mentions"] == {"parse": []}
    assert payload["content"] == "@everyone BUY NOW"


def test_attribution_rides_in_the_username_not_the_body(make_message):
    payload = build_payload(make_message())
    assert payload["username"] == "Alert Bot · #signals"
    # The forwarded text must stay byte-identical to the source.
    assert payload["content"] == "BUY SPY 500C"


def test_username_avoids_reserved_words(make_message):
    payload = build_payload(make_message(author_name="Discord Signals", channel_name=None))
    assert "discord" not in payload["username"].lower()


def test_username_is_truncated_to_the_api_limit(make_message):
    payload = build_payload(make_message(author_name="x" * 200))
    assert len(payload["username"]) <= 80


def test_long_content_is_truncated_with_an_ellipsis(make_message):
    payload = build_payload(make_message(content="y" * 5000))
    assert len(payload["content"]) == CONTENT_LIMIT
    assert payload["content"].endswith("…")


def test_attachment_urls_are_appended_so_images_survive(make_message):
    payload = build_payload(
        make_message(attachments=[{"url": "https://cdn.example/chart.png", "filename": "c.png"}])
    )
    assert "https://cdn.example/chart.png" in payload["content"]


def test_embed_only_message_still_sends(make_message):
    payload = build_payload(make_message(content="", embeds=[{"title": "Signal"}]))
    assert "content" not in payload
    assert payload["embeds"] == [{"title": "Signal"}]


def test_empty_message_raises_rather_than_sending_a_rejected_payload(make_message):
    # Discord rejects a webhook body with no content and no embeds. Detecting it
    # here turns a permanent 400 into a recorded skip.
    with pytest.raises(NothingToSendError):
        build_payload(make_message(content="", embeds=[], attachments=[]))
