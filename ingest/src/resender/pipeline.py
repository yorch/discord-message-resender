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

# Cap on remembered deletes that arrived before their create. Bounded so a stream
# of deletes for messages we never stored cannot grow without limit.
_MAX_PENDING_DELETES = 2048


class Pipeline:
    def __init__(self, settings: Settings, database: Database, forwarder: WebhookForwarder):
        self._settings = settings
        self._db = database
        self._forwarder = forwarder
        # Message IDs whose delete event arrived before the create was stored.
        # Insertion-ordered so the oldest can be evicted when the cap is hit.
        self._pending_deletes: dict[str, None] = {}

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

        # A delete for this message may have arrived before the create was
        # stored (gateway events dispatch as independent tasks). If so, mark it
        # deleted now and do not forward a message that was already retracted.
        if captured.id in self._pending_deletes:
            del self._pending_deletes[captured.id]
            await self._db.record_delete(captured.id)
            log.info("reconciled delete that arrived before create: %s", captured.id)
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

    async def apply_delete(self, message_id: str) -> None:
        """Mark a stored message deleted. Deletes are archived, not forwarded."""
        if await self._db.record_delete(message_id):
            log.info("marked %s as deleted", message_id)
            return
        # No live row matched. Either the message predates our joining (a
        # harmless miss that expires) or its create is still in flight and will
        # reconcile in ingest(). A residual sub-millisecond window remains where
        # a create commits and checks the pending set before this line runs;
        # fully closing it would require a DB tombstone that reworks the fan-out
        # dedup contract, which is not worth it for how rare it is.
        self._remember_pending_delete(message_id)
        log.debug("delete for unstored message %s; queued for reconciliation", message_id)

    def _remember_pending_delete(self, message_id: str) -> None:
        self._pending_deletes[message_id] = None
        if len(self._pending_deletes) > _MAX_PENDING_DELETES:
            oldest = next(iter(self._pending_deletes))
            del self._pending_deletes[oldest]

    async def apply_bulk_delete(self, message_ids: list[str]) -> None:
        if marked := await self._db.record_bulk_delete(message_ids):
            log.info("marked %d message(s) as deleted (bulk)", marked)

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
