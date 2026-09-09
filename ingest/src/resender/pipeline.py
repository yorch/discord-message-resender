"""Capture, store, and fan-out logic, independent of the Discord client.

Kept separate from listener.py so the ordering guarantees below can be tested
against a fake database and forwarder without a gateway connection.
"""

from __future__ import annotations

import asyncio
import logging

from .config import Route, Settings
from .db import Database
from .forwarder import DeliveryError, NothingToSendError, WebhookForwarder
from .models import CapturedMessage

log = logging.getLogger(__name__)


class Pipeline:
    def __init__(self, settings: Settings, database: Database, forwarder: WebhookForwarder):
        self._settings = settings
        self._db = database
        self._forwarder = forwarder

    async def ingest(self, captured: CapturedMessage) -> None:
        """Archive a message, then fan it out.

        The store always completes first. Forwarding before persisting would mean
        a crash between the two loses the record of an alert that was already
        relayed and possibly acted upon.
        """
        stored = await self._db.store_message(captured)
        if not stored:
            # Expected after a gateway resume, which replays recent events.
            log.debug("message %s already stored, skipping fan-out", captured.id)
            return

        log.info(
            "captured %s from #%s by %s (%d embeds)",
            captured.id,
            captured.channel_name or captured.channel_id,
            captured.author_name,
            len(captured.embeds),
        )

        for route in self._settings.routes_for_channel(captured.channel_id):
            await self._dispatch(route, captured)

    async def apply_edit(self, captured: CapturedMessage) -> None:
        """Record an edit. Alerts get corrected, and the correction is the signal."""
        if await self._db.record_edit(captured):
            log.info("recorded edit to %s", captured.id)

    async def _dispatch(self, route: Route, captured: CapturedMessage) -> None:
        if not route.forwards:
            return  # archive-only route

        allowed = route.filters.allows(captured.author_id, captured.searchable_text)
        status = "PENDING" if allowed else "SKIPPED"

        # The unique (message, route) key is what stops a restart from sending a
        # second copy: if the row already exists, this delivery is not ours.
        if not await self._db.queue_delivery(captured.id, route.name, status):
            return
        if not allowed:
            log.debug("filtered out %s for route %s", captured.id, route.name)
            return

        await self.deliver(route, captured, attempts=0)

    async def deliver(self, route: Route, captured: CapturedMessage, attempts: int) -> None:
        if route.webhook_url is None:
            return
        try:
            await self._forwarder.send(route.webhook_url, captured)
        except NothingToSendError:
            log.debug("nothing forwardable in %s", captured.id)
            await self._db.mark_skipped(captured.id, route.name)
        except DeliveryError as exc:
            log.warning("delivery failed for %s via %s: %s", captured.id, route.name, exc)
            await self._db.mark_attempt_failed(
                captured.id,
                route.name,
                str(exc),
                attempts,
                self._settings.max_delivery_attempts,
                retryable=exc.retryable,
            )
        else:
            await self._db.mark_delivered(captured.id, route.name)
            log.info("forwarded %s via %s", captured.id, route.name)

    async def retry_due(self) -> int:
        """Retry every delivery whose backoff has elapsed. Returns how many ran."""
        due = await self._db.due_deliveries(self._settings.max_delivery_attempts)
        by_name = {route.name: route for route in self._settings.routes}
        handled = 0
        for item in due:
            route = by_name.get(item.route)
            if route is None:
                # The route was renamed or removed from the config while rows for
                # it were still pending. Leave them alone rather than guessing.
                log.warning("pending delivery for unknown route %r, leaving in place", item.route)
                continue
            await self.deliver(route, item.message, attempts=item.attempts)
            handled += 1
        return handled

    async def run_retry_loop(self) -> None:
        interval = self._settings.retry_interval_seconds
        while True:
            try:
                if handled := await self.retry_due():
                    log.info("retried %d pending deliveries", handled)
            except asyncio.CancelledError:
                raise
            except Exception:
                # A sweep failure must not kill the loop; the gateway listener is
                # still capturing and those rows stay queued for the next pass.
                log.exception("retry sweep failed")
            await asyncio.sleep(interval)
