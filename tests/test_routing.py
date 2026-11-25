import asyncio

import httpx
from dataclasses import replace

from app.config import settings
from app.models import Listing
from app.routing import CyclingRouter


def test_real_route_profile_is_used_and_cached(db):
    requests = []

    def handler(request: httpx.Request):
        requests.append(request)
        if request.url.path.endswith("/pelias/v1/search"):
            text = request.url.params.get("text", "")
            coordinates = [4.9, 52.37] if "Singel" in text else [4.91, 52.38]
            return httpx.Response(200, json={"features": [{"geometry": {"coordinates": coordinates}}]})
        return httpx.Response(200, json={"routes": [{"summary": {"duration": 900, "distance": 2400}}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    router = CyclingRouter(replace(settings, ors_api_key="test-key"), db, client, "Belly of the Beast, Singel 460")
    async def no_wait():
        pass
    router._pace = no_wait
    item = Listing(source_id="test", source_name="Test", url="https://example.test", title="Studio", address="Lindengracht 10, Amsterdam", city="Amsterdam", base_rent_eur=900)

    async def exercise():
        result = await router.enrich(item)
        cached = await router.enrich(item)
        await client.aclose()
        return result, cached

    result, cached = asyncio.run(exercise())
    directions = [request for request in requests if "/directions/cycling-regular" in request.url.path]
    assert len(directions) == 1
    assert result.cycling_minutes == 15
    assert result.cycling_status == "CONFIRMED"
    assert cached.cycling_minutes == 15


def test_missing_address_is_kept_and_flagged_approximate_without_a_routing_key(db):
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500)))
    router = CyclingRouter(settings, db, client, "Belly of the Beast, Singel 460")
    item = Listing(source_id="test", source_name="Test", url="https://example.test", title="Room", city="Amsterdam")

    async def exercise():
        result = await router.enrich(item)
        await client.aclose()
        return result

    result = asyncio.run(exercise())
    assert result.cycling_status == "UNVERIFIED"
    assert result.address_is_approximate
