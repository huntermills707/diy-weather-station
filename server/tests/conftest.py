import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from weather_station_server.config import DB_PATH_ENV_VAR, INGEST_TOKEN_ENV_VAR
from weather_station_server.main import app

TOKEN = "test-token"

os.environ.setdefault(INGEST_TOKEN_ENV_VAR, TOKEN)


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fresh SQLite file per test, so no test sees another's rows."""
    path = tmp_path / "weather.db"
    monkeypatch.setenv(INGEST_TOKEN_ENV_VAR, TOKEN)
    monkeypatch.setenv(DB_PATH_ENV_VAR, str(path))
    return path


@pytest.fixture
def client(db_path: Path) -> Iterator[TestClient]:
    """A client with the app started (lifespan run) against the test database."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def make_reading(**overrides: Any) -> dict[str, Any]:
    """A valid payload, matching the example in docs/ingest-api.md."""
    reading = {
        "station_id": "station-1",
        "reading_id": "3f9a1c07-42",
        "device_time": "2026-10-02T18:35:00Z",
        "uptime_ms": 12600417,
        "window_s": 300,
        "rain_tips": 3,
        "rain_mm": 0.84,
        "wind_avg_kmh": 7.2,
        "wind_peak_kmh": 19.2,
        "wind_dir_deg": 225.0,
        "temp_c": 18.42,
        "rh_pct": 61.5,
        "press_hpa": 1004.2,
        "bme280": "ok",
        "rssi_dbm": -63,
    }
    reading.update(overrides)
    return reading


def stored_rows(path: Path) -> list[sqlite3.Row]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute("SELECT * FROM readings ORDER BY id").fetchall()
    finally:
        conn.close()
