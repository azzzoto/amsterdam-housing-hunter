from dataclasses import replace
from datetime import datetime, timedelta, timezone

from app.models import Listing
from app.scoring import score_listing


def make_listing(source_id: str, title: str, url: str, address: str = "Singel 460, Amsterdam"):
    return Listing(source_id=source_id, source_name=source_id.title(), url=url, title=title, city="Amsterdam", address=address,
                   base_rent_eur=950, monthly_total_eur=950, cost_status="CONFIRMED", property_type="studio", housemates=0)


def test_sqlite_persistence_and_cross_platform_duplicate_sources(db, scoring_config, tmp_path):
    db.ensure_source({"source_id": "pararius", "name": "Pararius", "base_url": "https://pararius.com", "adapter_type": "html", "status": "ACTIVE", "polling_interval_seconds": 120})
    db.ensure_source({"source_id": "iamexpat", "name": "IamExpat", "base_url": "https://iamexpat.nl", "adapter_type": "html", "status": "ACTIVE", "polling_interval_seconds": 300})
    first = make_listing("pararius", "Studio Singel 460", "https://pararius.com/listing/1")
    first_result = score_listing(first, scoring_config)
    saved_first = db.upsert_listing(first, first_result)
    assert saved_first["is_new"]

    other = make_listing("iamexpat", "Furnished studio at Singel 460", "https://iamexpat.nl/listing/2")
    second_result = db.upsert_listing(other, score_listing(other, scoring_config))
    assert second_result["id"] == saved_first["id"]
    assert not second_result["is_new"]
    item = db.get_listing(saved_first["id"])
    assert len(item["sources"]) == 2

    backup = db.create_backup(tmp_path / "backup")
    assert backup.exists()


def test_activation_codes_are_single_use_and_users_are_isolated(db):
    db.add_user_if_missing(100, "admin", role="admin", authorized=True)
    code = db.issue_activation_code(100)
    assert db.redeem_activation_code(code, 200, "guest") == "user"
    assert db.redeem_activation_code(code, 201, "other") is None
    assert db.get_user(200)["authorized"] == 1
    assert db.get_user(201) is None


def test_listing_survives_database_reopen(scoring_config, tmp_path):
    path = tmp_path / "restart.sqlite3"
    first_db = __import__("app.database", fromlist=["Database"]).Database(f"sqlite:///{path}", tmp_path)
    first_db.ensure_source({"source_id": "pararius", "name": "Pararius", "base_url": "https://pararius.com", "adapter_type": "html", "status": "ACTIVE", "polling_interval_seconds": 120})
    item = make_listing("pararius", "Studio restart", "https://pararius.com/listing/restart")
    item.surface_sqm = 28
    listing_id = first_db.upsert_listing(item, score_listing(item, scoring_config))["id"]
    first_db.close()
    second_db = __import__("app.database", fromlist=["Database"]).Database(f"sqlite:///{path}", tmp_path)
    restored = second_db.get_listing(listing_id)
    assert restored["title"] == "Studio restart"
    assert restored["surface_sqm"] == 28
    second_db.close()


def test_recent_history_filters_by_days_and_keeps_the_newest_first(db, scoring_config):
    db.ensure_source({"source_id": "pararius", "name": "Pararius", "base_url": "https://pararius.com", "adapter_type": "html", "status": "ACTIVE", "polling_interval_seconds": 120})
    current = make_listing("pararius", "Recent studio listing", "https://pararius.com/listing/recent", "Recent address, Amsterdam")
    current.detected_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    old = make_listing("pararius", "Older studio listing", "https://pararius.com/listing/old", "Older address, Amsterdam")
    old.detected_at = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(timespec="seconds")
    db.upsert_listing(old, score_listing(old, scoring_config))
    db.upsert_listing(current, score_listing(current, scoring_config))

    assert db.history_count(3) == 1
    assert [item["title"] for item in db.history_listings(3)] == ["Recent studio listing"]
    assert [item["title"] for item in db.history_listings(30)] == ["Recent studio listing", "Older studio listing"]


def test_listing_updates_create_distinct_notification_events(db, scoring_config):
    db.ensure_source({"source_id": "pararius", "name": "Pararius", "base_url": "https://pararius.com", "adapter_type": "html", "status": "ACTIVE", "polling_interval_seconds": 120})
    db.add_user_if_missing(88, "admin", role="admin", authorized=True)
    initial = make_listing("pararius", "Studio Singel", "https://pararius.com/listing/update")
    original = db.upsert_listing(initial, score_listing(initial, scoring_config))
    assert original["should_notify"] and original["event_key"] == "initial"
    assert db.record_notification(original["id"], 88, score_listing(initial, scoring_config).asdict(), original["event_key"])
    db.finish_notification(original["id"], 88, 10, event_key=original["event_key"])

    unchanged = db.upsert_listing(initial, score_listing(initial, scoring_config))
    assert not unchanged["should_notify"]
    assert not db.record_notification(original["id"], 88, score_listing(initial, scoring_config).asdict(), original["event_key"])

    repriced = replace(initial, base_rent_eur=900, monthly_total_eur=900)
    update = db.upsert_listing(repriced, score_listing(repriced, scoring_config))
    assert update["should_notify"] and update["changed"]
    assert update["event_key"] != original["event_key"]
    assert db.record_notification(update["id"], 88, score_listing(repriced, scoring_config).asdict(), update["event_key"])
    db.finish_notification(update["id"], 88, 11, event_key=update["event_key"])
    assert db.stats()["alerts_today"] == 2


def test_new_cross_platform_source_link_is_preserved_and_reported_as_change(db, scoring_config):
    db.ensure_source({"source_id": "pararius", "name": "Pararius", "base_url": "https://pararius.com", "adapter_type": "html", "status": "ACTIVE", "polling_interval_seconds": 120})
    db.ensure_source({"source_id": "iamexpat", "name": "IamExpat", "base_url": "https://iamexpat.nl", "adapter_type": "html", "status": "ACTIVE", "polling_interval_seconds": 300})
    original = make_listing("pararius", "Furnished studio at Singel 460", "https://pararius.com/listing/1")
    saved = db.upsert_listing(original, score_listing(original, scoring_config))
    duplicate = make_listing("iamexpat", "Furnished studio at Singel 460", "https://iamexpat.nl/listing/2")
    update = db.upsert_listing(duplicate, score_listing(duplicate, scoring_config))
    assert update["id"] == saved["id"]
    assert update["should_notify"]
    assert "source_url" in update["changes"]
    assert {source["source_id"] for source in db.get_listing(saved["id"])["sources"]} == {"pararius", "iamexpat"}


def test_failed_notification_is_retried_on_next_observation(db, scoring_config):
    db.ensure_source({"source_id": "pararius", "name": "Pararius", "base_url": "https://pararius.com", "adapter_type": "html", "status": "ACTIVE", "polling_interval_seconds": 120})
    db.add_user_if_missing(89, "admin", role="admin", authorized=True)
    item = make_listing("pararius", "Studio Retry", "https://pararius.com/listing/retry")
    saved = db.upsert_listing(item, score_listing(item, scoring_config))
    assert db.record_notification(saved["id"], 89, {}, saved["event_key"])
    db.finish_notification(saved["id"], 89, None, "network", saved["event_key"])
    repeated = db.upsert_listing(item, score_listing(item, scoring_config))
    assert repeated["should_notify"]
    assert repeated["event_key"] == saved["event_key"]
    assert db.record_notification(repeated["id"], 89, {}, repeated["event_key"])
