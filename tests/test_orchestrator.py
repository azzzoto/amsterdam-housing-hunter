import asyncio

from app.monitoring.orchestrator import Orchestrator


class FailingAdapter:
    source_id = "failing"
    name = "Failing"
    base_url = "https://example.test"
    adapter_type = "test"
    interval = 10
    status = "ACTIVE"
    initial_status = "ACTIVE"
    last_error = None

    def source_record(self):
        return {"source_id": self.source_id, "name": self.name, "base_url": self.base_url, "adapter_type": self.adapter_type, "status": self.status, "polling_interval_seconds": self.interval}

    async def health_check(self):
        return self.status

    async def search_listings(self):
        raise RuntimeError("adapter failed")
        yield

    async def close(self):
        pass


class HealthyAdapter(FailingAdapter):
    source_id = "healthy"
    name = "Healthy"
    status = "ACTIVE"
    hit = False

    async def search_listings(self):
        self.hit = True
        if False:
            yield


def test_one_adapter_failure_does_not_stop_another(db, scoring_config):
    bad, good = FailingAdapter(), HealthyAdapter()
    orchestrator = Orchestrator(db, [bad, good], type("Settings", (), {})(), scoring_config, router=None)

    async def exercise():
        task = asyncio.create_task(orchestrator.run())
        await asyncio.sleep(0.08)
        orchestrator.stop()
        await task

    asyncio.run(exercise())
    statuses = {row["source_id"]: row["status"] for row in db.source_rows()}
    assert statuses["failing"] == "DEGRADED"
    assert statuses["healthy"] == "ACTIVE"
    assert good.hit
