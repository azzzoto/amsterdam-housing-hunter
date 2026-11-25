from __future__ import annotations

import difflib
import hashlib
import json
import logging
import secrets
import sqlite3
import string
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from app.config import ROOT
from app.extraction import normalize_url
from app.models import Listing, iso_now
from app.scoring import ScoreResult

log = logging.getLogger(__name__)


class Database:
    def __init__(self, database_url: str, data_dir: Path | None = None):
        if not database_url.startswith("sqlite:///"):
            raise ValueError("This release supports SQLite URLs only; use sqlite:///./data/housing.db.")
        path_value = database_url.removeprefix("sqlite:///")
        if path_value in {":memory:", "file::memory:?cache=shared"}:
            path = ":memory:"
        else:
            path = Path(path_value)
            if not path.is_absolute():
                path = (ROOT / path).resolve()
            (data_dir or path.parent).mkdir(parents=True, exist_ok=True)
            path = str(path)
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.lock = RLock()
        migration = ROOT / "migrations" / "001_initial.sql"
        self.conn.executescript(migration.read_text())
        self._ensure_additive_schema()
        self.conn.execute(
            "UPDATE notification_history SET status='failed',error='Process restarted before notification completion' WHERE status='pending'"
        )
        self.conn.execute("INSERT OR IGNORE INTO app_state(key,value,updated_at) VALUES('monitoring_paused','false',?)", (iso_now(),))

    def _ensure_additive_schema(self) -> None:
        """Apply small backward-compatible additions to an existing SQLite file."""
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(listings)")}
        if "surface_sqm" not in columns:
            self.conn.execute("ALTER TABLE listings ADD COLUMN surface_sqm REAL")
        notification_columns = {row[1] for row in self.conn.execute("PRAGMA table_info(notification_history)")}
        if "change_details_json" not in notification_columns:
            self.conn.execute("ALTER TABLE notification_history ADD COLUMN change_details_json TEXT NOT NULL DEFAULT '{}'")

    def close(self) -> None:
        with self.lock:
            self.conn.close()

    def ensure_source(self, source: dict[str, Any]) -> None:
        with self.lock:
            self.conn.execute(
                """INSERT INTO sources(source_id,name,base_url,adapter_type,status,polling_interval_seconds)
                   VALUES(?,?,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET
                   name=excluded.name,base_url=excluded.base_url,adapter_type=excluded.adapter_type,
                   polling_interval_seconds=excluded.polling_interval_seconds""",
                (source["source_id"], source["name"], source["base_url"], source["adapter_type"], source["status"], source["polling_interval_seconds"]),
            )

    def update_source(self, source_id: str, status: str, success: bool = False, error: str | None = None) -> None:
        now = iso_now()
        with self.lock:
            self.conn.execute(
                "UPDATE sources SET status=?,last_attempt_at=?,last_success_at=CASE WHEN ? THEN ? ELSE last_success_at END,last_error=? WHERE source_id=?",
                (status, now, int(success), now, error[:500] if error else None, source_id),
            )

    def source_rows(self) -> list[dict[str, Any]]:
        with self.lock:
            return [dict(row) for row in self.conn.execute("SELECT * FROM sources ORDER BY name")]

    @staticmethod
    def _fingerprint(listing: Listing) -> str:
        if listing.address:
            base = "|".join((listing.address.lower().replace(",", " ").strip(), str(round(listing.base_rent_eur or 0)), listing.property_type))
        else:
            base = normalize_url(listing.url)
        return hashlib.sha256(base.encode("utf-8")).hexdigest()

    def _find_duplicate(self, listing: Listing) -> str | None:
        url = normalize_url(listing.url)
        row = self.conn.execute(
            "SELECT listing_id FROM listing_sources WHERE original_url=? LIMIT 1", (url,)
        ).fetchone()
        if row:
            return str(row[0])
        if listing.external_id:
            row = self.conn.execute(
                "SELECT listing_id FROM listing_sources WHERE source_id=? AND external_id=? LIMIT 1",
                (listing.source_id, listing.external_id),
            ).fetchone()
            if row:
                return str(row[0])
        if listing.address:
            address = " ".join(listing.address.lower().replace(",", " ").split())
            row = self.conn.execute("SELECT id,address,base_rent_eur,property_type,title FROM listings WHERE address IS NOT NULL ORDER BY first_detected_at DESC LIMIT 500").fetchall()
            for candidate in row:
                candidate_address = " ".join(str(candidate["address"]).lower().replace(",", " ").split())
                if candidate_address != address:
                    continue
                old_rent = candidate["base_rent_eur"]
                rent_matches = old_rent is not None and listing.base_rent_eur is not None and abs(float(old_rent) - listing.base_rent_eur) <= max(50, listing.base_rent_eur * 0.05)
                type_matches = listing.property_type == candidate["property_type"] or "unknown" in {listing.property_type, candidate["property_type"]}
                if rent_matches and type_matches:
                    return str(candidate["id"])
        # Conservative fallback: only merge nearly identical titles at same visible rent and locality.
        if listing.base_rent_eur is not None and len(listing.title.strip()) >= 12:
            candidates = self.conn.execute(
                "SELECT id,title,neighborhood,base_rent_eur FROM listings WHERE base_rent_eur BETWEEN ? AND ? ORDER BY first_detected_at DESC LIMIT 100",
                (listing.base_rent_eur - 5, listing.base_rent_eur + 5),
            ).fetchall()
            title = listing.title.lower().strip()
            for candidate in candidates:
                if listing.neighborhood and candidate["neighborhood"] and listing.neighborhood.lower() != candidate["neighborhood"].lower():
                    continue
                if difflib.SequenceMatcher(None, title, str(candidate["title"]).lower().strip()).ratio() >= 0.94:
                    return str(candidate["id"])
        return None

    def upsert_listing(self, listing: Listing, score: ScoreResult) -> dict[str, Any]:
        now = iso_now()
        normalized_url = normalize_url(listing.url)
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                listing_id = self._find_duplicate(listing)
                is_new = listing_id is None
                old = self.conn.execute("SELECT * FROM listings WHERE id=?", (listing_id,)).fetchone() if listing_id else None
                if is_new:
                    listing_id = str(uuid.uuid4())
                before = dict(old) if old else {}
                content = listing.asdict()
                fields = {
                    "title": listing.title,
                    "description": listing.description,
                    "city": listing.city,
                    "neighborhood": listing.neighborhood,
                    "address": listing.address,
                    "address_is_approximate": int(listing.address_is_approximate),
                    "base_rent_eur": listing.base_rent_eur,
                    "utilities_eur": listing.utilities_eur,
                    "mandatory_fees_eur": listing.mandatory_fees_eur,
                    "monthly_total_eur": listing.monthly_total_eur,
                    "cost_status": listing.cost_status,
                    "utilities_included": None if listing.utilities_included is None else int(listing.utilities_included),
                    "deposit_eur": listing.deposit_eur,
                    "property_type": listing.property_type,
                    "bedrooms": listing.bedrooms,
                    "bathrooms": listing.bathrooms,
                    "surface_sqm": listing.surface_sqm,
                    "housemates": listing.housemates,
                    "maximum_occupancy": listing.maximum_occupancy,
                    "furnishing": listing.furnishing,
                    "availability_date": listing.availability_date,
                    "registration": listing.registration,
                    "minimum_duration": listing.minimum_duration,
                    "maximum_duration": listing.maximum_duration,
                    "income_requirements": listing.income_requirements,
                    "student_eligibility": listing.student_eligibility,
                    "contract_type": listing.contract_type,
                    "agency_name": listing.agency_name,
                    "contact_email": listing.contact_email,
                    "contact_phone": listing.contact_phone,
                    "contact_url": listing.contact_url,
                    "application_instructions": listing.application_instructions,
                    "image_urls_json": json.dumps(listing.image_urls),
                    "latitude": listing.latitude,
                    "longitude": listing.longitude,
                    "cycling_minutes": listing.cycling_minutes,
                    "cycling_distance_m": listing.cycling_distance_m,
                    "cycling_status": listing.cycling_status,
                    "route_provider": listing.route_provider,
                    "route_calculated_at": listing.route_calculated_at,
                    "published_at": listing.published_at,
                    "updated_at": listing.updated_at,
                    "availability_status": listing.availability_status,
                    "last_seen_at": now,
                    "suitability_score": score.total_score,
                    "score_category": score.category,
                    "match_status": score.match_status,
                    "data_confidence": score.data_confidence,
                    "score_breakdown_json": json.dumps(score.breakdown, ensure_ascii=False),
                    "score_reasons_json": json.dumps(score.reasons, ensure_ascii=False),
                    "missing_information_json": json.dumps(score.missing_information, ensure_ascii=False),
                    "hard_exclusions_json": json.dumps(score.hard_exclusions, ensure_ascii=False),
                    "raw_data_json": json.dumps(content.get("raw_data", {}), ensure_ascii=False),
                }
                if is_new:
                    fields.update({"id": listing_id, "fingerprint": self._fingerprint(listing), "first_detected_at": listing.detected_at})
                    columns = ",".join(fields.keys())
                    marks = ",".join("?" for _ in fields)
                    self.conn.execute(f"INSERT INTO listings({columns}) VALUES({marks})", tuple(fields.values()))
                else:
                    fields["fingerprint"] = self._fingerprint(listing)
                    assignments = ",".join(f"{column}=?" for column in fields)
                    self.conn.execute(f"UPDATE listings SET {assignments} WHERE id=?", (*fields.values(), listing_id))
                ref = self.conn.execute(
                    "SELECT id,original_url FROM listing_sources WHERE source_id=? AND (external_id=? OR original_url=?) LIMIT 1",
                    (listing.source_id, listing.external_id, normalized_url),
                ).fetchone()
                source_link_changed = not ref or ref["original_url"] != normalized_url
                if ref:
                    self.conn.execute("UPDATE listing_sources SET last_seen_at=?,original_url=? WHERE id=?", (now, normalized_url, ref[0]))
                else:
                    self.conn.execute(
                        "INSERT INTO listing_sources(listing_id,source_id,external_id,original_url,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?)",
                        (listing_id, listing.source_id, listing.external_id, normalized_url, now, now),
                    )
                tracked = ("title", "base_rent_eur", "monthly_total_eur", "availability_status", "description", "address", "published_at", "updated_at")
                changes = [key for key in tracked if old and before.get(key) != fields.get(key)]
                if old and source_link_changed:
                    changes.append("source_url")
                changed = bool(changes)
                change_details = {
                    key: {"from": before.get(key), "to": fields.get(key)}
                    for key in changes
                    if key != "source_url"
                }
                if "source_url" in changes:
                    change_details["source_url"] = {"from": None, "to": normalized_url, "source_id": listing.source_id}
                # Keep cross-platform source links, but don't resend the same
                # property alert solely because another site has its own URL.
                notification_change_details = {key: value for key, value in change_details.items() if key != "source_url"}
                if is_new:
                    event_key = "initial"
                elif notification_change_details:
                    event_key = hashlib.sha256(json.dumps(notification_change_details, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:32]
                else:
                    event_key = "unchanged"
                    retry = self.conn.execute(
                        "SELECT event_key,change_details_json FROM notification_history WHERE listing_id=? AND status='failed' ORDER BY id DESC LIMIT 1",
                        (listing_id,),
                    ).fetchone()
                    if retry:
                        event_key = str(retry["event_key"])
                        change_details = json.loads(retry["change_details_json"] or "{}")
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
        return {"id": listing_id, "is_new": is_new, "changed": changed, "changes": changes, "change_details": change_details, "event_key": event_key, "should_notify": is_new or bool(notification_change_details) or event_key != "unchanged", "score": score}

    def get_listing(self, listing_id: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.conn.execute("SELECT * FROM listings WHERE id=?", (listing_id,)).fetchone()
            return self._listing_row(dict(row)) if row else None

    def has_source_listing(self, source_id: str, external_id: str | None, url: str) -> bool:
        normalized = normalize_url(url)
        with self.lock:
            row = self.conn.execute(
                "SELECT 1 FROM listing_sources WHERE source_id=? AND (original_url=? OR (? IS NOT NULL AND external_id=?)) LIMIT 1",
                (source_id, normalized, external_id, external_id),
            ).fetchone()
            return bool(row)

    def latest_listings(self, limit: int = 10) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.conn.execute("SELECT * FROM listings ORDER BY first_detected_at DESC LIMIT ?", (limit,)).fetchall()
            return [self._listing_row(dict(row)) for row in rows]

    def history_listings(self, days: int = 3, limit: int = 10) -> list[dict[str, Any]]:
        days = max(1, min(30, int(days)))
        limit = max(1, min(20, int(limit)))
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM listings WHERE first_detected_at >= ? ORDER BY first_detected_at DESC LIMIT ?",
                (cutoff, limit),
            ).fetchall()
            return [self._listing_row(dict(row)) for row in rows]

    def history_count(self, days: int = 3) -> int:
        days = max(1, min(30, int(days)))
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        with self.lock:
            return int(self.conn.execute("SELECT COUNT(*) FROM listings WHERE first_detected_at >= ?", (cutoff,)).fetchone()[0])

    def _listing_row(self, item: dict[str, Any]) -> dict[str, Any]:
        for key, target in (("image_urls_json", "image_urls"), ("score_breakdown_json", "score_breakdown"), ("score_reasons_json", "score_reasons"), ("missing_information_json", "missing_information"), ("hard_exclusions_json", "hard_exclusions"), ("raw_data_json", "raw_data")):
            try:
                item[target] = json.loads(item.get(key) or ("[]" if target != "score_breakdown" and target != "raw_data" else "{}"))
            except json.JSONDecodeError:
                item[target] = {} if target in {"score_breakdown", "raw_data"} else []
        with self.lock:
            refs = self.conn.execute(
                "SELECT s.name,ls.original_url,ls.source_id FROM listing_sources ls JOIN sources s ON s.source_id=ls.source_id WHERE ls.listing_id=? ORDER BY ls.first_seen_at",
                (item["id"],),
            ).fetchall()
        item["sources"] = [dict(ref) for ref in refs]
        return item

    def add_user_if_missing(self, telegram_id: int, username: str | None, role: str = "user", authorized: bool = False) -> None:
        now = iso_now()
        with self.lock:
            self.conn.execute(
                "INSERT INTO users(telegram_id,username,role,authorized,registered_at,last_interaction_at) VALUES(?,?,?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET username=excluded.username,role=CASE WHEN excluded.authorized=1 THEN excluded.role ELSE users.role END,authorized=CASE WHEN excluded.authorized=1 THEN 1 ELSE users.authorized END,last_interaction_at=excluded.last_interaction_at",
                (telegram_id, username, role, int(authorized), now, now),
            )

    def get_user(self, telegram_id: int) -> dict[str, Any] | None:
        with self.lock:
            row = self.conn.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
            if not row:
                return None
            user = dict(row)
            user["preferences"] = json.loads(user.pop("preferences_json", "{}"))
            return user

    def authorized_users(self) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.conn.execute("SELECT * FROM users WHERE authorized=1").fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["preferences"] = json.loads(item.pop("preferences_json", "{}"))
            output.append(item)
        return output

    def revoke_user(self, telegram_id: int) -> bool:
        with self.lock:
            cursor = self.conn.execute("UPDATE users SET authorized=0 WHERE telegram_id=?", (telegram_id,))
            return cursor.rowcount > 0

    def set_preferences(self, telegram_id: int, preferences: dict[str, Any]) -> None:
        with self.lock:
            self.conn.execute("UPDATE users SET preferences_json=?,last_interaction_at=? WHERE telegram_id=?", (json.dumps(preferences), iso_now(), telegram_id))

    def issue_activation_code(self, created_by: int, role: str = "user", hours: int = 24) -> str:
        alphabet = string.ascii_uppercase + string.digits
        code = "".join(secrets.choice(alphabet) for _ in range(10))
        code_hash = hashlib.sha256(code.encode()).hexdigest()
        now = datetime.now(timezone.utc)
        with self.lock:
            self.conn.execute(
                "INSERT INTO activation_codes(code_hash,role,created_by,created_at,expires_at) VALUES(?,?,?,?,?)",
                (code_hash, role, created_by, now.isoformat(), (now + timedelta(hours=hours)).isoformat()),
            )
        return code

    def redeem_activation_code(self, code: str, telegram_id: int, username: str | None) -> str | None:
        code_hash = hashlib.sha256(code.strip().upper().encode()).hexdigest()
        now = iso_now()
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                row = self.conn.execute("SELECT role,expires_at,used_by FROM activation_codes WHERE code_hash=?", (code_hash,)).fetchone()
                if not row or row["used_by"] is not None or row["expires_at"] < now:
                    self.conn.execute("ROLLBACK")
                    return None
                role = str(row["role"])
                self.conn.execute("UPDATE activation_codes SET used_by=?,used_at=? WHERE code_hash=?", (telegram_id, now, code_hash))
                self.conn.execute(
                    "INSERT INTO users(telegram_id,username,role,authorized,registered_at,last_interaction_at) VALUES(?,?,?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET username=excluded.username,role=excluded.role,authorized=1,last_interaction_at=excluded.last_interaction_at",
                    (telegram_id, username, role, 1, now, now),
                )
                self.conn.execute("COMMIT")
                return role
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    def record_notification(self, listing_id: str, telegram_user_id: int, score: dict[str, Any], event_key: str = "initial", change_details: dict[str, Any] | None = None) -> bool:
        with self.lock:
            try:
                cursor = self.conn.execute(
                    "INSERT INTO notification_history(listing_id,telegram_user_id,event_key,status,score_snapshot_json,change_details_json) VALUES(?,?,?,?,?,?) ON CONFLICT(listing_id,telegram_user_id,event_key) DO UPDATE SET status='pending',score_snapshot_json=excluded.score_snapshot_json,change_details_json=CASE WHEN excluded.change_details_json='{}' THEN notification_history.change_details_json ELSE excluded.change_details_json END,error=NULL WHERE notification_history.status='failed'",
                    (listing_id, telegram_user_id, event_key, "pending", json.dumps(score, ensure_ascii=False), json.dumps(change_details or {}, ensure_ascii=False)),
                )
                return cursor.rowcount == 1
            except sqlite3.IntegrityError:
                return False

    def notification_score(self, listing_id: str, telegram_user_id: int, event_key: str | None = None) -> dict[str, Any] | None:
        with self.lock:
            if event_key is None:
                row = self.conn.execute("SELECT score_snapshot_json FROM notification_history WHERE listing_id=? AND telegram_user_id=? ORDER BY id DESC LIMIT 1", (listing_id, telegram_user_id)).fetchone()
            else:
                row = self.conn.execute("SELECT score_snapshot_json FROM notification_history WHERE listing_id=? AND telegram_user_id=? AND event_key=?", (listing_id, telegram_user_id, event_key)).fetchone()
            return json.loads(row[0]) if row else None

    def finish_notification(self, listing_id: str, telegram_user_id: int, message_id: int | None, error: str | None = None, event_key: str = "initial") -> None:
        with self.lock:
            self.conn.execute(
                "UPDATE notification_history SET telegram_message_id=?,sent_at=?,status=?,error=? WHERE listing_id=? AND telegram_user_id=? AND event_key=?",
                (message_id, iso_now(), "sent" if message_id is not None else "failed", error[:500] if error else None, listing_id, telegram_user_id, event_key),
            )

    def record_interaction(self, listing_id: str, telegram_user_id: int, interaction: str, note: str | None = None) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT INTO user_interactions(listing_id,telegram_user_id,interaction,note,created_at) VALUES(?,?,?,?,?)",
                (listing_id, telegram_user_id, interaction, note, iso_now()),
            )

    def interactions_for_user(self, telegram_user_id: int) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT ui.*,l.title,l.base_rent_eur,l.url FROM user_interactions ui JOIN listings l ON l.id=ui.listing_id WHERE ui.telegram_user_id=? ORDER BY ui.created_at DESC LIMIT 50",
                (telegram_user_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def stats(self) -> dict[str, Any]:
        today = datetime.now(timezone.utc).date().isoformat()
        with self.lock:
            return {
                "sources": self.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
                "functioning_sources": self.conn.execute("SELECT COUNT(*) FROM sources WHERE status='ACTIVE'").fetchone()[0],
                "listings_today": self.conn.execute("SELECT COUNT(*) FROM listings WHERE first_detected_at >= ?", (today,)).fetchone()[0],
                "alerts_today": self.conn.execute("SELECT COUNT(*) FROM notification_history WHERE sent_at >= ? AND status='sent'", (today,)).fetchone()[0],
                "total_listings": self.conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0],
                "sources_by_status": {row[0]: row[1] for row in self.conn.execute("SELECT status,COUNT(*) FROM sources GROUP BY status")},
            }

    def is_paused(self) -> bool:
        with self.lock:
            row = self.conn.execute("SELECT value FROM app_state WHERE key='monitoring_paused'").fetchone()
            return bool(row and row[0] == "true")

    def set_paused(self, paused: bool) -> None:
        with self.lock:
            self.conn.execute("UPDATE app_state SET value=?,updated_at=? WHERE key='monitoring_paused'", ("true" if paused else "false", iso_now()))

    def get_adapter_state(self, key: str) -> str | None:
        with self.lock:
            row = self.conn.execute("SELECT value FROM adapter_state WHERE key=?", (key,)).fetchone()
            return str(row[0]) if row else None

    def set_adapter_state(self, key: str, value: str) -> None:
        with self.lock:
            self.conn.execute("INSERT INTO adapter_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at", (key, value, iso_now()))

    def get_route_cache(self, address_key: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.conn.execute("SELECT * FROM route_cache WHERE address_key=?", (address_key,)).fetchone()
            if not row:
                return None
            result = dict(row)
            # A failed external request is retried after one day; successful routes are reusable.
            try:
                updated = datetime.fromisoformat(result["updated_at"])
                if result["route_status"] != "OK" and (datetime.now(timezone.utc) - updated).total_seconds() > 86400:
                    return None
            except (ValueError, TypeError):
                return None
            return result

    def set_route_cache(self, address_key: str, latitude: float | None, longitude: float | None,
                        cycling_minutes: float | None, cycling_distance_m: float | None,
                        geocode_status: str, route_status: str) -> None:
        with self.lock:
            self.conn.execute(
                """INSERT INTO route_cache(address_key,latitude,longitude,geocode_status,cycling_minutes,cycling_distance_m,route_status,provider,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(address_key) DO UPDATE SET
                   latitude=excluded.latitude,longitude=excluded.longitude,geocode_status=excluded.geocode_status,
                   cycling_minutes=excluded.cycling_minutes,cycling_distance_m=excluded.cycling_distance_m,
                   route_status=excluded.route_status,provider=excluded.provider,updated_at=excluded.updated_at""",
                (address_key, latitude, longitude, geocode_status, cycling_minutes, cycling_distance_m, route_status, "OpenRouteService / OpenStreetMap", iso_now()),
            )

    def create_backup(self, backup_dir: Path) -> Path:
        backup_dir.mkdir(parents=True, exist_ok=True)
        destination = backup_dir / f"housing-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.sqlite3"
        with self.lock:
            backup_conn = sqlite3.connect(destination)
            self.conn.backup(backup_conn)
            backup_conn.close()
        return destination

    def healthcheck(self) -> bool:
        with self.lock:
            return self.conn.execute("SELECT 1").fetchone()[0] == 1
