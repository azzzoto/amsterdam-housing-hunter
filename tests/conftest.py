from pathlib import Path

import pytest

from app.config import load_scoring_settings
from app.database import Database


@pytest.fixture
def scoring_config():
    return load_scoring_settings()


@pytest.fixture
def db(tmp_path: Path):
    database = Database(f"sqlite:///{tmp_path / 'test.sqlite3'}", tmp_path)
    yield database
    database.close()
