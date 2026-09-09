"""Entry point: wires the gateway listener, the archive, and the forwarder."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import sys
from pathlib import Path

from dotenv import load_dotenv

from .config import ConfigError, Settings, load_settings
from .db import Database
from .forwarder import WebhookForwarder
from .listener import AlertListener
from .pipeline import Pipeline

log = logging.getLogger("resender")

DEFAULT_ROUTES_PATH = Path("config/routes.yaml")


class _RedactSecrets(logging.Filter):
    """Last line of defence against a secret reaching a log sink.

    The token bypasses two-factor authentication, so anything that could echo it
    (a traceback, an aiohttp error carrying a URL) gets scrubbed at the handler.
    """

    def __init__(self, secrets: list[str]) -> None:
        super().__init__()
        self._secrets = [s for s in secrets if s and len(s) > 8]

    def filter(self, record: logging.LogRecord) -> bool:
        if self._secrets:
            text = record.getMessage()
            if any(s in text for s in self._secrets):
                for secret in self._secrets:
                    text = text.replace(secret, "***REDACTED***")
                record.msg = text
                record.args = ()
        return True


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    # discord.py-self is chatty at INFO about gateway internals.
    logging.getLogger("discord").setLevel(logging.WARNING)


def _install_redaction(settings: Settings) -> None:
    secrets = [settings.token, settings.database_url]
    secrets += [r.webhook_url for r in settings.routes if r.webhook_url]
    log_filter = _RedactSecrets(secrets)
    for handler in logging.getLogger().handlers:
        handler.addFilter(log_filter)


async def _run(settings: Settings) -> None:
    database = Database(settings.database_url)
    forwarder = WebhookForwarder()
    await database.connect()
    await forwarder.start()

    pipeline = Pipeline(settings, database, forwarder)
    client = AlertListener(settings, pipeline)
    sweeper = asyncio.create_task(pipeline.run_retry_loop(), name="retry-sweeper")

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, lambda: asyncio.ensure_future(client.close()))

    try:
        # reconnect=True gives the library's own backoff and RESUME handling. A
        # hot reconnect loop is a strong automation signal, so this is never
        # reimplemented here.
        await client.start(settings.token, reconnect=True)
    finally:
        sweeper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sweeper
        await client.close()
        await forwarder.close()
        await database.close()
        log.info("shutdown complete")


def main() -> int:
    load_dotenv()
    _configure_logging(os.environ.get("LOG_LEVEL", "INFO"))

    routes_path = Path(os.environ.get("ROUTES_PATH", DEFAULT_ROUTES_PATH))
    try:
        settings = load_settings(routes_path)
    except ConfigError as exc:
        log.error("configuration error: %s", exc)
        return 1

    _install_redaction(settings)
    log.info(
        "loaded %d route(s) covering %d channel(s)",
        len(settings.routes),
        len(settings.watched_channel_ids),
    )

    try:
        asyncio.run(_run(settings))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
