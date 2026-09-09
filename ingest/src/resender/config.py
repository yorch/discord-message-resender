"""Configuration loading for routes and secrets.

Route definitions live in a YAML file that is safe to read; the credentials they
need are pulled from the environment by name. That split is deliberate: a route
file can be committed or shared for review without leaking a webhook URL, which
is itself a post-anywhere credential for the target channel.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


class ConfigError(Exception):
    """Raised when the route file or environment is unusable."""


@dataclass(frozen=True)
class Filters:
    """Forwarding predicates. Empty collections mean "no restriction"."""

    author_ids: frozenset[str] = frozenset()
    match_any: tuple[re.Pattern[str], ...] = ()
    exclude_any: tuple[re.Pattern[str], ...] = ()

    def allows(self, author_id: str, text: str) -> bool:
        if self.author_ids and author_id not in self.author_ids:
            return False
        if self.match_any and not any(p.search(text) for p in self.match_any):
            return False
        # Exclusions are evaluated last so they can veto an explicit match.
        return not any(p.search(text) for p in self.exclude_any)


@dataclass(frozen=True)
class Route:
    name: str
    guild_id: str
    channel_ids: frozenset[str]
    webhook_url: str | None
    filters: Filters = field(default_factory=Filters)

    @property
    def forwards(self) -> bool:
        """False for archive-only routes, which store without fanning out."""
        return self.webhook_url is not None


@dataclass(frozen=True)
class Settings:
    token: str
    database_url: str
    routes: tuple[Route, ...]
    retry_interval_seconds: float = 30.0
    max_delivery_attempts: int = 8

    @property
    def watched_channel_ids(self) -> frozenset[str]:
        return frozenset(cid for route in self.routes for cid in route.channel_ids)

    def routes_for_channel(self, channel_id: str) -> tuple[Route, ...]:
        return tuple(r for r in self.routes if channel_id in r.channel_ids)


def _compile(patterns: object, where: str) -> tuple[re.Pattern[str], ...]:
    if patterns is None:
        return ()
    if not isinstance(patterns, list):
        raise ConfigError(f"{where} must be a list of regular expressions")
    compiled = []
    for raw in patterns:
        try:
            compiled.append(re.compile(str(raw), re.IGNORECASE))
        except re.error as exc:
            raise ConfigError(f"{where}: invalid regular expression {raw!r}: {exc}") from exc
    return tuple(compiled)


def _str_list(value: object, where: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigError(f"{where} must be a list")
    # Snowflakes may be written quoted or bare; Python ints are arbitrary
    # precision so both round-trip exactly. Normalize to str and require digits,
    # which catches typos like a pasted channel mention or a trailing comma.
    out = []
    for item in value:
        text = str(item)
        if not text.isdigit():
            raise ConfigError(f"{where}: {text!r} is not a Discord ID (digits only)")
        out.append(text)
    return out


def load_routes(path: Path, environ: dict[str, str] | None = None) -> tuple[Route, ...]:
    env = os.environ if environ is None else environ

    if not path.exists():
        raise ConfigError(
            f"route file not found at {path}. Copy config/routes.example.yaml to "
            f"config/routes.yaml and fill in your guild and channel IDs."
        )

    document = yaml.safe_load(path.read_text()) or {}
    entries = document.get("routes")
    if not isinstance(entries, list) or not entries:
        raise ConfigError(f"{path} must define a non-empty 'routes' list")

    routes: list[Route] = []
    seen: set[str] = set()

    for index, entry in enumerate(entries):
        where = f"{path} routes[{index}]"
        if not isinstance(entry, dict):
            raise ConfigError(f"{where} must be a mapping")
        if not entry.get("enabled", True):
            continue

        name = str(entry.get("name") or "").strip()
        if not name:
            raise ConfigError(f"{where} is missing a name")
        if name in seen:
            # Route names are the delivery table's key half; duplicates would
            # collapse two targets into one row and silently drop a send.
            raise ConfigError(f"{where}: duplicate route name {name!r}")
        seen.add(name)

        source = entry.get("source") or {}
        guild_id = str(source.get("guild_id") or "").strip()
        if not guild_id.isdigit():
            raise ConfigError(f"{where}: source.guild_id must be a Discord ID")
        channel_ids = _str_list(source.get("channel_ids"), f"{where}.source.channel_ids")
        if not channel_ids:
            raise ConfigError(f"{where}: source.channel_ids must list at least one channel")

        target = entry.get("target") or {}
        env_name = target.get("webhook_url_env")
        webhook_url: str | None = None
        if env_name:
            webhook_url = (env.get(str(env_name)) or "").strip() or None
            if webhook_url is None:
                raise ConfigError(
                    f"{where}: target.webhook_url_env names {env_name!r} but that "
                    f"environment variable is empty or unset"
                )
            if not webhook_url.startswith("https://"):
                raise ConfigError(f"{where}: {env_name} does not look like a webhook URL")

        raw_filters = entry.get("filters") or {}
        if not isinstance(raw_filters, dict):
            raise ConfigError(f"{where}.filters must be a mapping")

        routes.append(
            Route(
                name=name,
                guild_id=guild_id,
                channel_ids=frozenset(channel_ids),
                webhook_url=webhook_url,
                filters=Filters(
                    author_ids=frozenset(
                        _str_list(raw_filters.get("author_ids"), f"{where}.filters.author_ids")
                    ),
                    match_any=_compile(raw_filters.get("match_any"), f"{where}.filters.match_any"),
                    exclude_any=_compile(
                        raw_filters.get("exclude_any"), f"{where}.filters.exclude_any"
                    ),
                ),
            )
        )

    if not routes:
        raise ConfigError(f"{path} has no enabled routes")
    return tuple(routes)


def load_settings(routes_path: Path, environ: dict[str, str] | None = None) -> Settings:
    env = os.environ if environ is None else environ

    token = (env.get("DISCORD_USER_TOKEN") or "").strip()
    if not token:
        raise ConfigError("DISCORD_USER_TOKEN is not set. See docs/risk.md before setting it.")

    database_url = (env.get("DATABASE_URL") or "").strip()
    if not database_url:
        raise ConfigError("DATABASE_URL is not set")

    return Settings(
        token=token,
        database_url=database_url,
        routes=load_routes(routes_path, env),
    )
