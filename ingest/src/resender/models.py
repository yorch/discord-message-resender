"""Normalized message record shared by the store and the forwarder."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

# Discord embed keys that a webhook will accept on create. Everything else on an
# incoming embed is server-populated (type, provider, video, and the proxy_url
# variants) and is rejected or silently dropped when sent back.
_WRITABLE_EMBED_KEYS = frozenset(
    {
        "title",
        "description",
        "url",
        "timestamp",
        "color",
        "footer",
        "image",
        "thumbnail",
        "author",
        "fields",
    }
)


@dataclass(frozen=True)
class CapturedMessage:
    """A single message, flattened for storage and for filter evaluation."""

    id: str
    guild_id: str
    guild_name: str | None
    channel_id: str
    channel_name: str | None
    author_id: str
    author_name: str
    author_avatar_url: str | None
    author_is_bot: bool
    content: str
    embeds: list[dict[str, Any]]
    attachments: list[dict[str, Any]]
    raw: dict[str, Any]
    sent_at: datetime
    edited_at: datetime | None

    @property
    def searchable_text(self) -> str:
        """Content plus every human-readable string inside the embeds.

        Filters run against this rather than against content alone. Most alert
        bots post an empty content field and put the whole signal in an embed, so
        a filter that only sees content would match nothing.
        """
        parts: list[str] = [self.content]
        for embed in self.embeds:
            for key in ("title", "description"):
                value = embed.get(key)
                if isinstance(value, str):
                    parts.append(value)
            for key in ("footer", "author"):
                nested = embed.get(key)
                if isinstance(nested, dict):
                    for sub in ("text", "name"):
                        value = nested.get(sub)
                        if isinstance(value, str):
                            parts.append(value)
            fields = embed.get("fields")
            if isinstance(fields, list):
                for entry in fields:
                    if isinstance(entry, dict):
                        for sub in ("name", "value"):
                            value = entry.get(sub)
                            if isinstance(value, str):
                                parts.append(value)
        return "\n".join(p for p in parts if p)

    def webhook_embeds(self, limit: int = 10) -> list[dict[str, Any]]:
        """Embeds stripped down to the keys a webhook is allowed to set."""
        cleaned = []
        for embed in self.embeds[:limit]:
            kept = {k: v for k, v in embed.items() if k in _WRITABLE_EMBED_KEYS}
            if kept:
                cleaned.append(kept)
        return cleaned


def _serialize(obj: Any) -> Any:
    to_dict = getattr(obj, "to_dict", None)
    return to_dict() if callable(to_dict) else None


def from_discord_message(message: Any) -> CapturedMessage:
    """Flatten a discord.Message into a CapturedMessage.

    Typed as Any so the module imports without the discord package present,
    which keeps the normalizer unit-testable against plain stubs.
    """
    guild = getattr(message, "guild", None)
    channel = getattr(message, "channel", None)
    author = message.author

    embeds = [d for d in (_serialize(e) for e in message.embeds) if d is not None]
    attachments = [d for d in (_serialize(a) for a in message.attachments) if d is not None]

    avatar = getattr(author, "display_avatar", None)
    avatar_url = str(avatar.url) if avatar is not None and getattr(avatar, "url", None) else None

    # A faithful snapshot of the message as the library exposed it. discord.py
    # does not retain the original gateway frame, so this is reconstructed rather
    # than captured verbatim; it exists so a later schema change can be
    # backfilled from stored data instead of waiting for the traffic to recur.
    raw: dict[str, Any] = {
        "id": str(message.id),
        "type": getattr(getattr(message, "type", None), "name", None),
        "content": message.content or "",
        "embeds": embeds,
        "attachments": attachments,
        "author": {
            "id": str(author.id),
            "name": getattr(author, "name", None),
            "global_name": getattr(author, "global_name", None),
            "display_name": getattr(author, "display_name", None),
            "bot": bool(getattr(author, "bot", False)),
            "avatar_url": avatar_url,
        },
        "guild": {
            "id": str(guild.id) if guild is not None else None,
            "name": getattr(guild, "name", None),
        },
        "channel": {
            "id": str(channel.id) if channel is not None else None,
            "name": getattr(channel, "name", None),
            "type": getattr(getattr(channel, "type", None), "name", None),
        },
        "jump_url": getattr(message, "jump_url", None),
        "webhook_id": str(message.webhook_id) if getattr(message, "webhook_id", None) else None,
        "pinned": bool(getattr(message, "pinned", False)),
        "tts": bool(getattr(message, "tts", False)),
        "reference_id": (
            str(message.reference.message_id)
            if getattr(message, "reference", None) and message.reference.message_id
            else None
        ),
    }

    return CapturedMessage(
        id=str(message.id),
        guild_id=str(guild.id) if guild is not None else "",
        guild_name=getattr(guild, "name", None),
        channel_id=str(channel.id) if channel is not None else "",
        channel_name=getattr(channel, "name", None),
        author_id=str(author.id),
        author_name=getattr(author, "display_name", None) or getattr(author, "name", "") or "",
        author_avatar_url=avatar_url,
        author_is_bot=bool(getattr(author, "bot", False)),
        content=message.content or "",
        embeds=embeds,
        attachments=attachments,
        raw=raw,
        sent_at=message.created_at,
        edited_at=getattr(message, "edited_at", None),
    )
