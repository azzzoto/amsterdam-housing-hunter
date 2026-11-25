from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from app.config import Settings
from app.extraction import enrich_detail_html, parse_public_listing_cards
from app.models import Listing

log = logging.getLogger(__name__)


class SourceAdapter(ABC):
    source_id: str
    name: str
    base_url: str
    interval: int
    initial_status: str = "ACTIVE"
    adapter_type: str = "public_html"

    def __init__(self, settings: Settings, client: httpx.AsyncClient, semaphore: asyncio.Semaphore):
        self.settings = settings
        self.client = client
        self.semaphore = semaphore
        self.status = self.initial_status
        self.last_success: str | None = None
        self.last_error: str | None = None
        self._robots: RobotFileParser | None = None
        self._robots_loaded = False
        self._backoff_until = 0.0
        self._last_host_request = 0.0

    def source_record(self) -> dict:
        return {"source_id": self.source_id, "name": self.name, "base_url": self.base_url, "adapter_type": self.adapter_type, "status": self.status, "polling_interval_seconds": self.interval}

    async def _load_robots(self) -> bool:
        if self._robots_loaded:
            return self._robots is not None
        self._robots_loaded = True
        robots_url = urljoin(self.base_url, "/robots.txt")
        try:
            response = await self.client.get(robots_url, timeout=self.settings.http_timeout)
            if response.status_code in {403, 429}:
                self.status = "BLOCKED"
                self.last_error = f"robots.txt returned HTTP {response.status_code}"
                return False
            if response.status_code >= 400:
                # Unknown robots policy is a fail-closed state.
                self.status = "DEGRADED"
                self.last_error = f"robots.txt unavailable (HTTP {response.status_code}); adapter paused"
                return False
            parser = RobotFileParser(robots_url)
            parser.parse(response.text.splitlines())
            self._robots = parser
            return True
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            self.status = "DEGRADED"
            self.last_error = f"robots.txt check failed: {type(exc).__name__}"
            return False

    async def allowed_by_robots(self, url: str) -> bool:
        if not await self._load_robots() or self._robots is None:
            return False
        return self._robots.can_fetch(self.settings.user_agent, url)

    async def request(self, url: str) -> httpx.Response | None:
        if self.status == "BLOCKED":
            return None
        if time.monotonic() < self._backoff_until:
            return None
        if not await self.allowed_by_robots(url):
            self.status = "BLOCKED"
            self.last_error = "Requested route is disallowed by the source robots.txt"
            return None
        async with self.semaphore:
            host_delay = 1.0 - (time.monotonic() - self._last_host_request)
            if host_delay > 0:
                await asyncio.sleep(host_delay)
            self._last_host_request = time.monotonic()
            for attempt in range(3):
                try:
                    response = await self.client.get(url, timeout=self.settings.http_timeout, follow_redirects=False)
                    if response.is_redirect:
                        self.status = "DEGRADED"
                        self.last_error = "Source redirected the request; automatic redirect following is disabled"
                        return None
                    if response.status_code == 429:
                        wait = _retry_after(response.headers.get("Retry-After"), default=300)
                        self._backoff_until = time.monotonic() + wait
                        self.status = "DEGRADED"
                        self.last_error = f"HTTP 429; paused for {wait}s"
                        return None
                    if response.status_code in {401, 403}:
                        self.status = "BLOCKED"
                        self.last_error = f"HTTP {response.status_code}; access controls are respected"
                        return None
                    if response.status_code >= 500:
                        if attempt < 2:
                            await asyncio.sleep(2**attempt)
                            continue
                        self.status = "DEGRADED"
                        self.last_error = f"HTTP {response.status_code} after retries"
                        return None
                    response.raise_for_status()
                    self.status = "ACTIVE"
                    self.last_error = None
                    return response
                except httpx.HTTPStatusError as exc:
                    self.status = "DEGRADED"
                    self.last_error = f"HTTP {exc.response.status_code}"
                    return None
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    if attempt < 2:
                        await asyncio.sleep(2**attempt)
                        continue
                    self.status = "DEGRADED"
                    self.last_error = type(exc).__name__
                    return None
        return None

    @abstractmethod
    async def search_listings(self) -> AsyncIterator[Listing]:
        raise NotImplementedError

    async def fetch_listing_details(self, listing: Listing) -> Listing:
        # Detail retrieval is optional; only request it if robots explicitly permits the URL.
        if not await self.allowed_by_robots(listing.url):
            return listing
        response = await self.request(listing.url)
        if response is None or "text/html" not in response.headers.get("content-type", ""):
            return listing
        return enrich_detail_html(listing, response.text, listing.url)

    async def health_check(self) -> str:
        await self._load_robots()
        return self.status

    async def close(self) -> None:
        return None


def _retry_after(value: str | None, default: int) -> int:
    try:
        return max(1, int(value)) if value else default
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value or "")
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return max(1, int((retry_at - datetime.now(timezone.utc)).total_seconds()))
        except (TypeError, ValueError, OverflowError):
            return default


class PublicSearchAdapter(SourceAdapter):
    initial_status = "DEGRADED"  # Becomes ACTIVE only after a permitted successful request.
    search_urls: tuple[str, ...]

    async def search_listings(self) -> AsyncIterator[Listing]:
        found = 0
        for search_url in self.search_urls:
            response = await self.request(search_url)
            if response is None:
                continue
            try:
                listings = parse_public_listing_cards(response.text, self.base_url, self.source_id, self.name)
            except Exception as exc:
                self.status = "DEGRADED"
                self.last_error = f"Listing parser failed: {type(exc).__name__}"
                log.warning("Listing parser failed for %s (%s)", self.source_id, type(exc).__name__)
                continue
            for listing in listings:
                found += 1
                yield listing
        if found == 0 and self.status != "BLOCKED":
            self.status = "DEGRADED"
            self.last_error = "No listing cards recognized; source markup may have changed or the results are empty"


def absolute(base_url: str, path: str) -> str:
    return urljoin(base_url, path)


def source_domain(url: str) -> str:
    return urlsplit(url).hostname or ""
