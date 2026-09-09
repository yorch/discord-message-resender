import logging

import pytest

from resender import validate
from resender.validate import TokenCheckFailedError, TokenInvalidError, _run, main


@pytest.fixture
def stub_fetch(monkeypatch):
    """Replace the network call so _run's decision logic is tested in isolation."""

    def install(*, returns=None, raises=None):
        async def fake(_token):
            if raises is not None:
                raise raises
            return returns

        monkeypatch.setattr(validate, "_fetch_me", fake)

    return install


async def test_valid_user_token_returns_zero(stub_fetch, caplog):
    stub_fetch(returns={"username": "alice", "global_name": "Alice", "id": "42", "bot": False})
    with caplog.at_level(logging.INFO):
        assert await _run("tok") == 0
    assert "token is valid" in caplog.text
    assert "Alice" in caplog.text


async def test_bot_token_authenticates_but_warns(stub_fetch, caplog):
    # A bot token passes /users/@me but cannot read channels as a member, which
    # defeats the purpose. The check must flag it rather than report success.
    stub_fetch(returns={"username": "botto", "id": "9", "bot": True})
    with caplog.at_level(logging.WARNING):
        assert await _run("tok") == 0
    assert "BOT token" in caplog.text


async def test_invalid_token_returns_one(stub_fetch, caplog):
    stub_fetch(raises=TokenInvalidError())
    with caplog.at_level(logging.ERROR):
        assert await _run("tok") == 1
    assert "401" in caplog.text


async def test_check_failure_returns_two(stub_fetch, caplog):
    # Distinct from an invalid token: the token might be fine, the check could
    # not complete. A caller can tell "bad token" from "try again".
    stub_fetch(raises=TokenCheckFailedError("network error: boom"))
    with caplog.at_level(logging.ERROR):
        assert await _run("tok") == 2
    assert "could not validate" in caplog.text


def test_main_without_token_reports_and_exits(monkeypatch, caplog):
    monkeypatch.setattr(validate, "load_dotenv", lambda: None)
    monkeypatch.delenv("DISCORD_USER_TOKEN", raising=False)
    with caplog.at_level(logging.ERROR):
        assert main() == 1
    assert "DISCORD_USER_TOKEN is not set" in caplog.text


def test_main_strips_whitespace_from_token(monkeypatch):
    # A token pasted with a trailing newline is a common .env mistake. Capture
    # the token at the network boundary to prove it was normalized end to end.
    monkeypatch.setattr(validate, "load_dotenv", lambda: None)
    monkeypatch.setenv("DISCORD_USER_TOKEN", "  padded-token\n")
    seen = {}

    async def fake_fetch(token):
        seen["token"] = token
        return {"username": "alice", "id": "1", "bot": False}

    monkeypatch.setattr(validate, "_fetch_me", fake_fetch)
    assert main() == 0
    assert seen["token"] == "padded-token"
