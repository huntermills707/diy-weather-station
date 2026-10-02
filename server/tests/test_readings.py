import json
import sqlite3
from pathlib import Path

import pytest
from conftest import make_reading, stored_rows
from fastapi.testclient import TestClient

from weather_station_server import db


def test_valid_reading_is_stored(client: TestClient, auth: dict, db_path: Path) -> None:
    response = client.post("/readings", json=make_reading(), headers=auth)

    assert response.status_code == 201
    body = response.json()
    assert body["duplicate"] is False
    assert body["reading_id"] == "3f9a1c07-42"
    assert body["received_at"].endswith("Z")

    [row] = stored_rows(db_path)
    assert row["id"] == body["id"]
    assert row["received_at"] == body["received_at"]
    assert row["device_time"] == "2026-10-02T18:35:00.000Z"
    assert row["temp_c"] == 18.42
    assert row["rain_tips"] == 3
    assert row["bme280"] == "ok"


def test_device_time_offset_is_stored_as_utc(client: TestClient, auth: dict, db_path: Path) -> None:
    reading = make_reading(device_time="2026-10-02T11:35:00-07:00")
    assert client.post("/readings", json=reading, headers=auth).status_code == 201
    assert stored_rows(db_path)[0]["device_time"] == "2026-10-02T18:35:00.000Z"


def test_unsynced_clock_and_failed_sensors_store_nulls(
    client: TestClient, auth: dict, db_path: Path
) -> None:
    """Invalid sensor states arrive as null and are stored as NULL, not numbers."""
    reading = make_reading(
        device_time=None,
        wind_dir_deg=None,
        temp_c=None,
        rh_pct=None,
        press_hpa=None,
        bme280="error",
        rssi_dbm=None,
    )
    assert client.post("/readings", json=reading, headers=auth).status_code == 201

    [row] = stored_rows(db_path)
    for column in ("device_time", "wind_dir_deg", "temp_c", "rh_pct", "press_hpa", "rssi_dbm"):
        assert row[column] is None
    assert row["bme280"] == "error"


# --- Authentication -------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong-token"},
        {"Authorization": "test-token"},
        {"Authorization": "Basic test-token"},
        {"Authorization": "Bearer "},
    ],
    ids=["missing", "wrong", "no-scheme", "basic", "empty"],
)
def test_bad_token_is_rejected(client: TestClient, db_path: Path, headers: dict) -> None:
    response = client.post("/readings", json=make_reading(), headers=headers)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert stored_rows(db_path) == []


def test_auth_is_checked_before_body(client: TestClient) -> None:
    """Unauthenticated garbage gets 401, never a 422 describing the payload."""
    response = client.post("/readings", content=b"{not json")
    assert response.status_code == 401


# --- Validation -----------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"temp_c": 120.0},
        {"rh_pct": 101.0},
        {"press_hpa": 50.0},
        {"wind_dir_deg": 360.0},
        {"wind_avg_kmh": -1.0},
        {"rain_tips": -1},
        {"window_s": 0},
        {"rssi_dbm": 5},
        {"bme280": "broken"},
        {"station_id": ""},
        {"reading_id": "has spaces"},
        {"reading_id": "x" * 65},
        {"device_time": "2026-10-02T18:35:00"},  # no UTC offset
        {"device_time": "yesterday"},
        {"temp_c": "warm"},
        {"surprise": 1},  # unknown field
        {"bme280": "ok", "temp_c": None},  # ok but missing a value
        {"bme280": "error"},  # error but values present
    ],
)
def test_invalid_values_are_rejected(
    client: TestClient, auth: dict, db_path: Path, overrides: dict
) -> None:
    response = client.post("/readings", json=make_reading(**overrides), headers=auth)
    assert response.status_code == 422
    assert stored_rows(db_path) == []


def test_missing_field_is_rejected(client: TestClient, auth: dict, db_path: Path) -> None:
    reading = make_reading()
    del reading["rain_mm"]
    response = client.post("/readings", json=reading, headers=auth)
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["rain_mm"]


@pytest.mark.parametrize("body", [b"", b"{not json", b"[]"])
def test_malformed_body_is_rejected(
    client: TestClient, auth: dict, db_path: Path, body: bytes
) -> None:
    response = client.post(
        "/readings", content=body, headers={**auth, "Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert stored_rows(db_path) == []


def test_nan_value_is_rejected(client: TestClient, auth: dict, db_path: Path) -> None:
    """NaN is not valid JSON, but Python's encoder emits it; it must not be stored."""
    body = json.dumps(make_reading()).replace('"temp_c": 18.42', '"temp_c": NaN')
    response = client.post(
        "/readings", content=body, headers={**auth, "Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert stored_rows(db_path) == []


# --- Deduplication --------------------------------------------------------


def test_duplicate_reading_is_stored_once(client: TestClient, auth: dict, db_path: Path) -> None:
    first = client.post("/readings", json=make_reading(), headers=auth)
    # A retry after a lost response: same reading_id, sent again.
    second = client.post("/readings", json=make_reading(), headers=auth)
    third = client.post("/readings", json=make_reading(), headers=auth)

    assert first.status_code == 201
    assert second.status_code == 200
    assert third.status_code == 200
    assert second.json()["duplicate"] is True
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["received_at"] == first.json()["received_at"]
    assert len(stored_rows(db_path)) == 1


def test_same_reading_id_from_other_station_is_new(
    client: TestClient, auth: dict, db_path: Path
) -> None:
    client.post("/readings", json=make_reading(), headers=auth)
    response = client.post("/readings", json=make_reading(station_id="station-2"), headers=auth)
    assert response.status_code == 201
    assert len(stored_rows(db_path)) == 2


def test_sequence_of_readings_each_stored(client: TestClient, auth: dict, db_path: Path) -> None:
    for seq in range(1, 6):
        response = client.post(
            "/readings", json=make_reading(reading_id=f"3f9a1c07-{seq}"), headers=auth
        )
        assert response.status_code == 201
    assert [r["reading_id"] for r in stored_rows(db_path)] == [f"3f9a1c07-{n}" for n in range(1, 6)]


# --- Storage failures -----------------------------------------------------


def test_database_failure_returns_503(
    client: TestClient, auth: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_args: object) -> None:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(db, "store_reading", broken)
    response = client.post("/readings", json=make_reading(), headers=auth)
    assert response.status_code == 503


def test_init_db_is_idempotent(db_path: Path) -> None:
    db.init_db(str(db_path))
    db.init_db(str(db_path))
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        conn.close()


def test_newer_schema_refuses_to_start(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION + 1}")
    conn.close()
    with pytest.raises(RuntimeError, match="newer"):
        db.init_db(str(db_path))
