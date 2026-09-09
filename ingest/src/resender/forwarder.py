"""Webhook fan-out into the destination server.

Forwarding deliberately uses a Discord webhook rather than the user account. A
webhook URL is an independent credential scoped to one channel, so the captured
account is never used to write anything anywhere, which keeps its behaviour
indistinguishable from an idle client.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

import aiohttp

from .models import CapturedMessage

log = logging.getLogger(__name__)

CONTENT_LIMIT = 2000
USERNAME_LIMIT = 80

# Discord rejects webhook usernames containing these, case-insensitively.
_FORBIDDEN_USERNAME = re.compile(r"discord|clyde|wumpus", re.IGNORECASE)

# The per-webhook bucket is five requests per two seconds. Half a second between
# sends stays under it without needing to parse the bucket headers.
MIN_INTERVAL_SECONDS = 0.5


class DeliveryError(Exception):
    """A send failed. `retryable` decides whether the backoff schedule applies."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class NothingToSendError(Exception):
    """The message carried no content, embeds, or attachments worth forwarding."""


def _sanitize_username(name: str) -> str:
    cleaned = _FORBIDDEN_USERNAME.sub("*", name).strip()
    return cleaned[:USERNAME_LIMIT] or "alert"


def build_payload(message: CapturedMessage) -> dict[str, Any]:
    """Assemble the webhook body. Pure, so the shaping rules are unit-testable."""
    content = message.content

    # Attachment URLs are appended so images survive the hop. Discord signs these
    # and they expire within about a day, which is fine for a live relay and is
    # why the archive keeps the metadata separately.
    urls = [str(a["url"]) for a in message.attachments if isinstance(a, dict) and a.get("url")]
    if urls:
        content = f"{content}\n{chr(10).join(urls)}".strip() if content else "\n".join(urls)

    embeds = message.webhook_embeds()

    if not content and not embeds:
        raise NothingToSendError(message.id)

    if len(content) > CONTENT_LIMIT:
        content = content[: CONTENT_LIMIT - 1] + "…"

    # Attribution rides in the username rather than being appended to the body,
    # so the forwarded text stays byte-identical to the source.
    label = message.author_name
    if message.channel_name:
        label = f"{label} · #{message.channel_name}"

    payload: dict[str, Any] = {
        "username": _sanitize_username(label),
        # A relayed alert routinely contains @everyone or a role ping that was
        # meaningful in the source server. Without this, forwarding it would
        # notify your entire server every time.
        "allowed_mentions": {"parse": []},
    }
    if content:
        payload["content"] = content
    if embeds:
        payload["embeds"] = embeds
    if message.author_avatar_url:
        payload["avatar_url"] = message.author_avatar_url
    return payload


class WebhookForwarder:
    def __init__(self, *, min_interval: float = MIN_INTERVAL_SECONDS, timeout: float = 15.0):
        self._min_interval = min_interval
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: aiohttp.ClientSession | None = None
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_sent: dict[str, float] = {}

    async def start(self) -> None:
        self._session = aiohttp.ClientSession(timeout=self._timeout)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def _throttle(self, webhook_url: str) -> None:
        elapsed = time.monotonic() - self._last_sent.get(webhook_url, 0.0)
        if elapsed < self._min_interval:
            await asyncio.sleep(self._min_interval - elapsed)
        self._last_sent[webhook_url] = time.monotonic()

    async def send(self, webhook_url: str, message: CapturedMessage) -> None:
        if self._session is None:
            raise RuntimeError("WebhookForwarder.start() has not been awaited")

        payload = build_payload(message)
        lock = self._locks.setdefault(webhook_url, asyncio.Lock())

        # One in-flight request per webhook keeps the throttle honest when several
        # messages arrive in the same burst.
        async with lock:
            for attempt in range(3):
                await self._throttle(webhook_url)
                try:
                    async with self._session.post(webhook_url, json=payload) as response:
                        if response.status in (200, 204):
                            return
                        body = (await response.text())[:500]

                        if response.status == 429:
                            retry_after = await self._retry_after(response)
                            log.warning(
                                "webhook rate limited, waiting %.2fs (attempt %d)",
                                retry_after,
                                attempt + 1,
                            )
                            await asyncio.sleep(retry_after)
                            continue

                        # 401/403/404 mean the webhook was deleted or the URL is
                        # wrong. Retrying cannot fix that, so fail it immediately
                        # instead of spending the whole attempt budget.
                        retryable = response.status >= 500
                        raise DeliveryError(
                            f"webhook responded {response.status}: {body}", retryable=retryable
                        )
                except TimeoutError as exc:
                    raise DeliveryError(f"webhook timed out: {exc}") from exc
                except aiohttp.ClientError as exc:
                    raise DeliveryError(f"webhook request failed: {exc}") from exc

            raise DeliveryError("webhook still rate limited after 3 attempts")

    @staticmethod
    async def _retry_after(response: aiohttp.ClientResponse) -> float:
        try:
            data = await response.json()
            return min(float(data.get("retry_after", 1.0)), 60.0)
        except (aiohttp.ContentTypeError, ValueError, TypeError):
            return float(response.headers.get("Retry-After", "1") or 1)
