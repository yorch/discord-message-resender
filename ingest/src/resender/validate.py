"""Validate the configured Discord user token before starting the stack.

This never fetches or derives a token. It only checks the one already placed in
the environment, so the token touches no process it would not otherwise touch.

The check is a single read-only REST call to /users/@me rather than a gateway
connection. A bad token on the gateway surfaces as a generic disconnect that
looks like a network fault; the REST call returns a clean 401 that says plainly
the token is the problem.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

import aiohttp
from dotenv import load_dotenv

log = logging.getLogger("resender.validate")

# Pinned API version. /users/@me is stable across versions, but pinning avoids a
# surprise if the unversioned endpoint ever changes its default.
_ME_URL = "https://discord.com/api/v10/users/@me"
_TIMEOUT_SECONDS = 15.0


class TokenInvalidError(Exception):
    """The token was rejected by Discord (HTTP 401)."""


class TokenCheckFailedError(Exception):
    """The check could not be completed (network, rate limit, unexpected status)."""


async def _fetch_me(token: str) -> dict[str, object]:
    # User accounts send the raw token as the Authorization header, with no
    # "Bot " prefix. A bot-style header would 401 a perfectly good user token,
    # which is the classic hand-rolled-check mistake.
    headers = {"Authorization": token}
    client_timeout = aiohttp.ClientTimeout(total=_TIMEOUT_SECONDS)

    async with aiohttp.ClientSession(timeout=client_timeout) as session:
        try:
            async with session.get(_ME_URL, headers=headers) as response:
                if response.status == 200:
                    return await response.json()
                if response.status == 401:
                    raise TokenInvalidError
                if response.status == 429:
                    retry = response.headers.get("Retry-After", "?")
                    raise TokenCheckFailedError(f"rate limited by Discord (retry after {retry}s)")
                body = (await response.text())[:200]
                raise TokenCheckFailedError(f"unexpected status {response.status}: {body}")
        except TimeoutError as exc:
            raise TokenCheckFailedError(f"request timed out after {_TIMEOUT_SECONDS}s") from exc
        except aiohttp.ClientError as exc:
            raise TokenCheckFailedError(f"network error: {exc}") from exc


async def _run(token: str) -> int:
    try:
        me = await _fetch_me(token)
    except TokenInvalidError:
        log.error(
            "token rejected by Discord (401). It is wrong, truncated, or expired. "
            "Changing your Discord password invalidates old tokens, so re-copy it "
            "from the Network tab. See docs/setup.md."
        )
        return 1
    except TokenCheckFailedError as exc:
        log.error("could not validate token: %s", exc)
        # Distinct exit code: the token might be fine; the check just failed.
        return 2

    username = me.get("username", "?")
    global_name = me.get("global_name") or username
    user_id = me.get("id", "?")
    log.info("token is valid: %s (@%s, id %s)", global_name, username, user_id)
    if me.get("bot"):
        # A bot token would authenticate here but cannot read the target channels
        # as a member, which is the entire premise of this project.
        log.warning(
            "this is a BOT token, not a user token. The ingest service reads "
            "channels as a member; a bot only sees channels it was invited to."
        )
    return 0


def main() -> int:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s", stream=sys.stdout)

    token = (os.environ.get("DISCORD_USER_TOKEN") or "").strip()
    if not token:
        log.error("DISCORD_USER_TOKEN is not set in the environment or .env file.")
        return 1

    return asyncio.run(_run(token))


if __name__ == "__main__":
    raise SystemExit(main())
