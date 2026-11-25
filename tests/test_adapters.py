import asyncio
from dataclasses import replace

import httpx

from app.config import settings
from app.scrapers.base import PublicSearchAdapter, _retry_after


class FixtureAdapter(PublicSearchAdapter):
    source_id = "fixture"
    name = "Fixture"
    base_url = "https://fixture.test"
    interval = 60
    search_urls = ("https://fixture.test/allowed",)


def test_adapter_obeys_robots_and_parses_permitted_search_result():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /allowed\nDisallow: /\n")
        return httpx.Response(200, text='<div><a href="/studio-for-rent/amsterdam/abc/singel-460/">Studio Singel</a><p>€850</p></div>', headers={"content-type": "text/html"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = FixtureAdapter(replace(settings, user_agent="test-agent"), client, asyncio.Semaphore(1))

    async def run():
        listings = [listing async for listing in adapter.search_listings()]
        await client.aclose()
        return listings

    listings = asyncio.run(run())
    assert len(listings) == 1
    assert calls == ["/robots.txt", "/allowed"]
    assert adapter.status == "ACTIVE"


def test_adapter_fails_closed_when_robots_disallows_route():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, text="User-agent: *\nDisallow: /\n")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = FixtureAdapter(replace(settings, user_agent="test-agent"), client, asyncio.Semaphore(1))

    async def run():
        listings = [listing async for listing in adapter.search_listings()]
        await client.aclose()
        return listings

    assert asyncio.run(run()) == []
    assert calls == ["/robots.txt"]
    assert adapter.status == "BLOCKED"


def test_retry_after_supports_seconds_http_dates_and_invalid_values():
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime

    assert _retry_after("90", 20) == 90
    deadline = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=120), usegmt=True)
    assert 100 <= _retry_after(deadline, 20) <= 120
    assert _retry_after("bad header", 20) == 20
