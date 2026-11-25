from collections.abc import AsyncIterator

from app.models import Listing
from app.scrapers.base import SourceAdapter


class RestrictedAdapter(SourceAdapter):
    def __init__(self, source_id: str, name: str, base_url: str, reason: str, status: str = "UNSUPPORTED", interval: int = 3600):
        # Restricted adapters do not issue requests or attempt authenticated browser access.
        self.source_id, self.name, self.base_url = source_id, name, base_url
        self.interval = interval
        self.adapter_type = "manual_or_authorized_email"
        self.initial_status = status
        self.status = status
        self.reason = reason

    def source_record(self) -> dict:
        return {"source_id": self.source_id, "name": self.name, "base_url": self.base_url, "adapter_type": self.adapter_type, "status": self.status, "polling_interval_seconds": self.interval}

    async def search_listings(self) -> AsyncIterator[Listing]:
        if False:
            yield Listing("", "", "", "")

    async def health_check(self) -> str:
        self.last_error = self.reason
        return self.status

    async def close(self) -> None:
        return None
