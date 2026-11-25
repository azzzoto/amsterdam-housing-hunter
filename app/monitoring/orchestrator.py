from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from app.config import Settings
from app.database import Database
from app.models import Listing
from app.routing import CyclingRouter
from app.scoring import ScoreResult, score_listing

log = logging.getLogger(__name__)
ListingNotifier = Callable[[str, Listing, ScoreResult, str, dict], Awaitable[None]]


class Orchestrator:
    def __init__(self, db: Database, adapters: list, settings: Settings, scoring_config: dict, router: CyclingRouter | None, notifier: ListingNotifier | None = None):
        self.db = db
        self.adapters = adapters
        self.settings = settings
        self.scoring_config = scoring_config
        self.router = router
        self.notifier = notifier
        self.stop_event = asyncio.Event()
        for adapter in adapters:
            self.db.ensure_source(adapter.source_record())

    async def run(self) -> None:
        tasks = [asyncio.create_task(self._worker(adapter), name=f"source:{adapter.source_id}") for adapter in self.adapters]
        try:
            await self.stop_event.wait()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for adapter in self.adapters:
                try:
                    await adapter.close()
                except Exception:
                    log.exception("Adapter close failed: %s", adapter.source_id)

    def stop(self) -> None:
        self.stop_event.set()

    async def scan_once(self) -> None:
        for adapter in self.adapters:
            if adapter.initial_status in {"UNSUPPORTED", "DISABLED", "REQUIRES_AUTHENTICATION"}:
                self.db.update_source(adapter.source_id, await adapter.health_check(), error=adapter.last_error)
                continue
            try:
                await adapter.health_check()
                detail_fetches = 0
                async for listing in adapter.search_listings():
                    if adapter.adapter_type == "public_html" and detail_fetches < 5 and not self.db.has_source_listing(adapter.source_id, listing.external_id, listing.url):
                        try:
                            listing = await adapter.fetch_listing_details(listing)
                        except Exception as exc:
                            log.warning("Detail extraction failed for %s (%s); retaining search-card data", adapter.source_id, type(exc).__name__)
                        detail_fetches += 1
                    await self._handle_listing(listing)
                self.db.update_source(adapter.source_id, adapter.status, success=adapter.status == "ACTIVE", error=adapter.last_error)
            except Exception as exc:
                adapter.status = "DEGRADED"
                adapter.last_error = f"{type(exc).__name__}: {str(exc)[:180]}"
                self.db.update_source(adapter.source_id, adapter.status, error=adapter.last_error)
                log.exception("One-time scan failed: %s", adapter.source_id)

    async def _worker(self, adapter) -> None:
        failure_count = 0
        while not self.stop_event.is_set():
            started = time.monotonic()
            if self.db.is_paused():
                await self._sleep(5)
                continue
            if adapter.initial_status in {"UNSUPPORTED", "DISABLED", "REQUIRES_AUTHENTICATION"}:
                status = await adapter.health_check()
                self.db.update_source(adapter.source_id, status, error=adapter.last_error)
                await self._sleep(max(60, adapter.interval))
                continue
            try:
                await adapter.health_check()
                async for listing in adapter.search_listings():
                    if adapter.adapter_type == "public_html" and not self.db.has_source_listing(adapter.source_id, listing.external_id, listing.url):
                        try:
                            listing = await adapter.fetch_listing_details(listing)
                        except Exception as exc:
                            log.warning("Detail extraction failed for %s (%s); retaining search-card data", adapter.source_id, type(exc).__name__)
                    await self._handle_listing(listing)
                failure_count = 0 if adapter.status == "ACTIVE" else min(failure_count + 1, 8)
                self.db.update_source(adapter.source_id, adapter.status, success=adapter.status == "ACTIVE", error=adapter.last_error)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failure_count = min(failure_count + 1, 8)
                adapter.status = "DEGRADED"
                adapter.last_error = f"{type(exc).__name__}: {str(exc)[:180]}"
                self.db.update_source(adapter.source_id, "DEGRADED", error=adapter.last_error)
                log.exception("Source worker failed: %s", adapter.source_id)
            elapsed = time.monotonic() - started
            base = max(10, int(adapter.interval))
            delay = max(0, base - elapsed)
            if failure_count:
                delay = max(delay, min(15 * (2 ** (failure_count - 1)), 900))
            await self._sleep(delay)

    async def _handle_listing(self, listing: Listing) -> None:
        if self.router:
            listing = await self.router.enrich(listing)
        result = score_listing(listing, self.scoring_config)
        saved = self.db.upsert_listing(listing, result)
        if not saved["should_notify"] or not self.notifier:
            return
        await self.notifier(saved["id"], listing, result, saved.get("event_key", "initial"), saved.get("change_details", {}))

    async def _sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self.stop_event.wait(), timeout=max(0.1, seconds))
        except TimeoutError:
            pass
