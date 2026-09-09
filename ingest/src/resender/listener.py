"""Adapter from Discord gateway events to the pipeline."""

from __future__ import annotations

import logging
from typing import Any

import discord

from .config import Settings
from .models import from_discord_message
from .pipeline import Pipeline

log = logging.getLogger(__name__)

# discord.ChannelType.news is what the client calls an Announcement channel.
_ANNOUNCEMENT = "news"


class AlertListener(discord.Client):
    def __init__(self, settings: Settings, pipeline: Pipeline, **options: Any) -> None:
        # Guild member chunking on connect is a large burst of traffic that this
        # service has no use for: everything needed is on the message itself.
        options.setdefault("chunk_guilds_at_startup", False)
        super().__init__(**options)
        self._settings = settings
        self._pipeline = pipeline
        self._watched = settings.watched_channel_ids

    async def on_ready(self) -> None:
        who = getattr(self.user, "name", "unknown")
        log.info("connected as %s, watching %d channel(s)", who, len(self._watched))

        for channel_id in sorted(self._watched):
            channel = self.get_channel(int(channel_id))
            if channel is None:
                log.warning(
                    "channel %s is not visible to this account. Check the ID and "
                    "confirm the account can still read that channel.",
                    channel_id,
                )
                continue

            kind = getattr(getattr(channel, "type", None), "name", "")
            log.info("  #%s (%s)", getattr(channel, "name", channel_id), kind or "unknown")

            if kind == _ANNOUNCEMENT:
                # Worth surfacing loudly: this specific channel can be mirrored
                # with Discord's built-in Follow button, which needs no token and
                # carries no Terms of Service exposure.
                log.warning(
                    "  #%s is an Announcement channel. Discord's native Follow "
                    "feature can mirror it into your server with no account "
                    "automation. See docs/risk.md.",
                    getattr(channel, "name", channel_id),
                )

    async def on_message(self, message: discord.Message) -> None:
        if str(message.channel.id) not in self._watched:
            return
        await self._pipeline.ingest(from_discord_message(message))

    async def on_message_edit(self, _before: discord.Message, after: discord.Message) -> None:
        if str(after.channel.id) not in self._watched:
            return
        await self._pipeline.apply_edit(from_discord_message(after))
