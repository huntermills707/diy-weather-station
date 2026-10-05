"""Nightly SQLite backup (JAE-63)."""

import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import make_reading
from fastapi.testclient import TestClient

from weather_station_server import backup
from weather_station_server.config import BACKUP_DIR_ENV_VAR, DB_PATH_ENV_VAR

NIGHT = datetime(2026, 10, 4, 10, 17, tzinfo=UTC)


def test_backup_restores_into_a_clean_database(
    client: TestClient, auth: dict, db_path: Path, tmp_path: Path
) -> None:
    for i in range(3):
        reading = make_reading(reading_id=f"c0ffee00-{i}", temp_c=10.0 + i)
        client.post("/readings", json=reading, headers=auth)

    path, readings = backup.backup(str(db_path), tmp_path / "backups", NIGHT)
    assert path.name == "weather-20261004T101700Z.db"
    assert readings == 3

    # Restore: copy the backup into place as a fresh database and query it.
    restored = tmp_path / "restored.db"
    restored.write_bytes(path.read_bytes())
    with sqlite3.connect(restored) as conn:
        rows = conn.execute("SELECT reading_id, temp_c FROM readings ORDER BY id").fetchall()
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert rows == [("c0ffee00-0", 10.0), ("c0ffee00-1", 11.0), ("c0ffee00-2", 12.0)]
    assert not list((tmp_path / "backups").glob(".*"))  # no partial file left


def test_backup_keeps_the_newest_copies(client: TestClient, db_path: Path, tmp_path: Path) -> None:
    dest = tmp_path / "backups"
    for night in range(backup.KEEP + 3):
        backup.backup(str(db_path), dest, NIGHT + timedelta(days=night))
    copies = sorted(p.name for p in dest.glob(backup.PATTERN))
    assert len(copies) == backup.KEEP
    assert copies[0] == "weather-20261007T101700Z.db"
    assert backup.latest_backup(dest) == dest / "weather-20261105T101700Z.db"


def test_backup_failure_is_logged_and_exits_non_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(DB_PATH_ENV_VAR, str(tmp_path / "missing.db"))
    monkeypatch.setenv(BACKUP_DIR_ENV_VAR, str(tmp_path / "backups"))
    assert backup.main() == 1
    assert "backup: FAILED" in caplog.text
    assert backup.latest_backup(tmp_path / "backups") is None


def test_backup_main_reports_success(
    client: TestClient,
    db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    monkeypatch.setenv(BACKUP_DIR_ENV_VAR, str(tmp_path / "backups"))
    assert backup.main() == 0
    assert "backup: wrote" in caplog.text
