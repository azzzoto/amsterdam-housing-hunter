from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./data/housing.db")
    data_dir: Path = Path(os.getenv("DATA_DIR", str(ROOT / "data")))
    telegram_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_admin_ids: tuple[int, ...] = tuple(
        int(part.strip()) for part in os.getenv("TELEGRAM_ADMIN_IDS", "").split(",") if part.strip().isdigit()
    )
    user_agent: str = os.getenv(
        "USER_AGENT",
        "AmsterdamHousingHunter/0.1 (personal housing search; contact: set-your-email@example.com)",
    )
    http_timeout: float = float(os.getenv("HTTP_TIMEOUT_SECONDS", "15"))
    max_concurrent_requests: int = max(1, int(os.getenv("MAX_CONCURRENT_REQUESTS", "2")))
    pararius_poll_seconds: int = max(60, int(os.getenv("PARARIUS_POLL_SECONDS", "120")))
    public_source_poll_seconds: int = max(120, int(os.getenv("PUBLIC_SOURCE_POLL_SECONDS", "300")))
    imap_host: str = os.getenv("IMAP_HOST", "")
    imap_port: int = int(os.getenv("IMAP_PORT", "993"))
    imap_username: str = os.getenv("IMAP_USERNAME", "")
    imap_password: str = os.getenv("IMAP_PASSWORD", "")
    imap_folder: str = os.getenv("IMAP_FOLDER", "INBOX")
    imap_poll_seconds: int = max(10, int(os.getenv("IMAP_POLL_SECONDS", "20")))
    imap_allowed_domains: tuple[str, ...] = tuple(
        d.strip().lower() for d in os.getenv("IMAP_ALLOWED_DOMAINS", "").split(",") if d.strip()
    )
    ors_api_key: str = os.getenv("ORS_API_KEY", "")
    backup_dir: Path = Path(os.getenv("BACKUP_DIR", str(ROOT / "backups")))


def load_scoring_settings(path: Path | None = None) -> dict:
    scoring_path = path or ROOT / "config" / "scoring.toml"
    with scoring_path.open("rb") as file:
        return tomllib.load(file)


settings = Settings()
