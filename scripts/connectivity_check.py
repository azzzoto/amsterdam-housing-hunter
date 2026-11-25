from __future__ import annotations

import asyncio
import logging

import httpx
from telegram import Bot

from app.config import settings


async def main() -> int:
    # Keep transport logs quiet so credentials in request paths/headers cannot leak.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    if not settings.telegram_token:
        print("Telegram: not configured")
        return 1

    try:
        bot = Bot(settings.telegram_token)
        identity = await bot.get_me()
        print(f"Telegram: connected as @{identity.username or identity.id}")
        print(f"Configured Telegram admins: {len(settings.telegram_admin_ids)}")
    except Exception as exc:
        print(f"Telegram: connection failed ({type(exc).__name__})")
        return 1

    if not settings.ors_api_key:
        print("OpenRouteService: not configured; cycling routes remain unverified")
        return 0
    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout) as client:
            headers = {"Authorization": settings.ors_api_key}
            async def geocode(address: str):
                response = await client.get(
                    "https://api.heigit.org/pelias/v1/search",
                    params={"text": address, "boundary.country": "NL", "size": 1},
                    headers=headers,
                )
                response.raise_for_status()
                features = response.json().get("features", [])
                return features[0]["geometry"]["coordinates"] if features else None

            reference = await geocode("Belly of the Beast, Singel 460, 1017 AW Amsterdam")
            sample = await geocode("Amsterdam Centraal Station")
            if not reference or not sample:
                print("OpenRouteService: authenticated geocoding succeeded, but a test point was not found")
                return 1
            route = await client.post(
                "https://api.heigit.org/openrouteservice/v2/directions/cycling-regular",
                headers={**headers, "Content-Type": "application/json"},
                json={"coordinates": [sample, reference], "instructions": False},
            )
            route.raise_for_status()
            summary = route.json()["routes"][0]["summary"]
            print(f"OpenRouteService: bicycle route succeeded ({summary['duration'] / 60:.1f} min, {summary['distance']:.0f} m)")
    except httpx.HTTPStatusError as exc:
        print(f"OpenRouteService: request returned HTTP {exc.response.status_code}")
        return 1
    except Exception as exc:
        print(f"OpenRouteService: connection failed ({type(exc).__name__})")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
