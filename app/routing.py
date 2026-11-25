from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timezone

import httpx

from app.config import Settings
from app.database import Database
from app.extraction import normalize_url
from app.models import Listing, iso_now
from app.scrapers.base import _retry_after

log = logging.getLogger(__name__)
ORS = "https://api.heigit.org"


class CyclingRouter:
    """Geocode once and calculate real cycling routes through OpenRouteService."""

    def __init__(self, settings: Settings, db: Database, client: httpx.AsyncClient, reference_address: str):
        self.settings = settings
        self.db = db
        self.client = client
        self.reference_address = reference_address
        self._reference: tuple[float, float] | None = None
        self._lock = asyncio.Lock()
        self._last_request = 0.0
        self._disabled = False
        self._backoff_until = 0.0

    async def enrich(self, listing: Listing) -> Listing:
        has_location = bool(listing.address or listing.neighborhood or listing.city)
        approximate = has_location and (listing.address_is_approximate or not bool(re.search(r"\d", listing.address or "")))
        listing.address_is_approximate = approximate
        if not self.settings.ors_api_key:
            listing.cycling_status = "UNVERIFIED"
            return listing
        if self._disabled or time.monotonic() < self._backoff_until:
            listing.cycling_status = "UNVERIFIED"
            return listing
        query = listing.address or ", ".join(part for part in (listing.neighborhood, listing.city or "Amsterdam", "Netherlands") if part)
        if not query.strip():
            listing.cycling_status = "UNVERIFIED"
            return listing
        key = " ".join(query.lower().split())
        cached = self.db.get_route_cache(key)
        if cached and cached.get("route_status") in {"OK", "GEOCODE_FAILED", "ROUTE_FAILED"}:
            listing.latitude = cached.get("latitude")
            listing.longitude = cached.get("longitude")
            listing.cycling_minutes = cached.get("cycling_minutes")
            listing.cycling_distance_m = cached.get("cycling_distance_m")
            listing.route_provider = cached.get("provider")
            listing.route_calculated_at = cached.get("updated_at")
            listing.cycling_status = "APPROXIMATE" if approximate and cached.get("route_status") == "OK" else "CONFIRMED" if cached.get("route_status") == "OK" else "UNVERIFIED"
            return listing
        async with self._lock:
            try:
                coords = await self._geocode(query)
                if not coords:
                    self.db.set_route_cache(key, None, None, None, None, "FAILED", "GEOCODE_FAILED")
                    listing.cycling_status = "UNVERIFIED"
                    return listing
                reference = await self._get_reference()
                if not reference:
                    listing.cycling_status = "UNVERIFIED"
                    return listing
                route = await self._directions(coords, reference)
                if not route:
                    self.db.set_route_cache(key, coords[0], coords[1], None, None, "OK", "ROUTE_FAILED")
                    listing.latitude, listing.longitude = coords
                    listing.cycling_status = "UNVERIFIED"
                    return listing
                minutes, distance_m = route
                listing.latitude, listing.longitude = coords
                listing.cycling_minutes = minutes
                listing.cycling_distance_m = distance_m
                listing.route_provider = "OpenRouteService / OpenStreetMap"
                listing.route_calculated_at = iso_now()
                listing.cycling_status = "APPROXIMATE" if approximate else "CONFIRMED"
                self.db.set_route_cache(key, coords[0], coords[1], minutes, distance_m, "OK", "OK")
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in {401, 403}:
                    self._disabled = True
                    log.warning("OpenRouteService rejected the configured key (HTTP %s); routing disabled until restart", exc.response.status_code)
                elif exc.response.status_code == 429:
                    wait = _retry_after(exc.response.headers.get("Retry-After"), 300)
                    self._backoff_until = time.monotonic() + wait
                    log.info("OpenRouteService rate limited routing; pausing for %ss", wait)
                listing.cycling_status = "UNVERIFIED"
            except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
                log.info("Cycling route unavailable (%s)", type(exc).__name__)
                listing.cycling_status = "UNVERIFIED"
        return listing

    async def _pace(self) -> None:
        delay = 1.0 - (asyncio.get_running_loop().time() - self._last_request)
        if delay > 0:
            await asyncio.sleep(delay)
        self._last_request = asyncio.get_running_loop().time()

    async def _geocode(self, address: str) -> tuple[float, float] | None:
        await self._pace()
        response = await self.client.get(
            f"{ORS}/pelias/v1/search",
            params={"text": address, "boundary.country": "NL", "size": 1},
            headers={"Authorization": self.settings.ors_api_key},
            timeout=self.settings.http_timeout,
        )
        response.raise_for_status()
        features = response.json().get("features", [])
        if not features:
            return None
        lon, lat = features[0]["geometry"]["coordinates"]
        return float(lon), float(lat)

    async def _get_reference(self) -> tuple[float, float] | None:
        if self._reference:
            return self._reference
        self._reference = await self._geocode(self.reference_address)
        return self._reference

    async def _directions(self, origin: tuple[float, float], destination: tuple[float, float]) -> tuple[float, float] | None:
        await self._pace()
        response = await self.client.post(
            f"{ORS}/openrouteservice/v2/directions/cycling-regular",
            headers={"Authorization": self.settings.ors_api_key, "Content-Type": "application/json"},
            json={"coordinates": [list(origin), list(destination)], "instructions": False},
            timeout=self.settings.http_timeout,
        )
        response.raise_for_status()
        summary = response.json()["routes"][0]["summary"]
        return float(summary["duration"]) / 60, float(summary["distance"])
