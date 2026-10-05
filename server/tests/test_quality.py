"""Data-quality flags (docs/data-quality.md, JAE-64): rules, storage, and the read API."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import make_reading, stored_rows
from fastapi.testclient import TestClient

from weather_station_server import db, quality
from weather_station_server.db import utc_text

START = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)


def reading_at(i: int, **overrides: object) -> dict:
    """The i-th reading of a run, five minutes apart, with a varying temperature."""
    values = {
        "reading_id": f"aaaa0001-{i + 1}",
        "device_time": utc_text(START + timedelta(minutes=5 * i)),
        "temp_c": 15.0 + i / 100,
        "rh_pct": 50.0 + (i % 7) / 10,
        "press_hpa": 1010.0 + (i % 5) / 10,
    }
    return make_reading(**{**values, **overrides})


# --- Rules -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value", "flag"),
    [
        ("temp_c", 60.0, "temp_range"),
        ("temp_c", -35.0, "temp_range"),
        ("rh_pct", 0.0, "rh_range"),
        ("press_hpa", 800.0, "press_range"),
        ("wind_avg_kmh", 200.0, "wind_range"),
        ("wind_peak_kmh", 400.0, "gust_range"),
    ],
)
def test_range_rules(field: str, value: float, flag: str) -> None:
    assert quality.evaluate(make_reading(**{field: value}), []) == [flag]


def test_plausible_reading_has_no_flags() -> None:
    assert quality.evaluate(make_reading(), []) == []


def test_missing_values_are_not_flagged() -> None:
    reading = make_reading(temp_c=None, rh_pct=None, press_hpa=None, bme280="error")
    assert quality.evaluate(reading, []) == []


def test_rain_rate_rule_scales_with_the_window() -> None:
    # 200 mm/h over five minutes is 16.7 mm.
    assert quality.evaluate(make_reading(rain_mm=16.0), []) == []
    assert quality.evaluate(make_reading(rain_mm=20.0), []) == ["rain_range"]
    # A tip or two in a one-second window (an `s` report) is not a cloudburst.
    assert quality.evaluate(make_reading(window_s=1, rain_mm=0.56), []) == []


def test_stuck_needs_two_hours_of_identical_values() -> None:
    same = {"temp_c": 20.0, "rh_pct": 40.0, "press_hpa": 1000.0}
    previous = [dict(same) for _ in range(quality.STUCK_READINGS - 1)]
    reading = make_reading(**same)

    assert quality.evaluate(reading, previous) == ["temp_stuck", "rh_stuck", "press_stuck"]
    # One reading short, or one value different, is not stuck.
    assert quality.evaluate(reading, previous[:-1]) == []
    previous[5] = {**same, "temp_c": 20.01}
    assert quality.evaluate(reading, previous) == ["rh_stuck", "press_stuck"]


def test_saturated_humidity_is_not_stuck() -> None:
    previous = [{"temp_c": i, "rh_pct": 100.0, "press_hpa": i} for i in range(30)]
    assert quality.evaluate(make_reading(rh_pct=100.0), previous) == []


def test_is_flagged_matches_the_field() -> None:
    assert quality.is_flagged("temp_range rh_stuck", "temp_c")
    assert quality.is_flagged("temp_range rh_stuck", "rh_pct")
    assert not quality.is_flagged("temp_range rh_stuck", "press_hpa")
    assert not quality.is_flagged("", "rain_mm")


# --- Storage -----------------------------------------------------------------


def test_flagged_reading_keeps_its_raw_values(
    client: TestClient, auth: dict, db_path: Path
) -> None:
    response = client.post(
        "/readings", json=make_reading(temp_c=70.0, wind_peak_kmh=450.0), headers=auth
    )
    assert response.status_code == 201
    [row] = stored_rows(db_path)
    assert row["temp_c"] == 70.0
    assert row["wind_peak_kmh"] == 450.0
    assert row["quality"] == "temp_range gust_range"


def test_stuck_sensor_is_flagged_at_ingest(client: TestClient, auth: dict, db_path: Path) -> None:
    n = quality.STUCK_READINGS
    for i in range(n + 1):
        client.post("/readings", json=reading_at(i, temp_c=21.5), headers=auth)

    flags = [row["quality"] for row in stored_rows(db_path)]
    assert flags[: n - 1] == [""] * (n - 1)
    assert flags[n - 1 :] == ["temp_stuck", "temp_stuck"]


def test_backfilled_reading_is_judged_by_readings_before_it_in_time(
    client: TestClient, auth: dict, db_path: Path
) -> None:
    """A late reading is compared with its neighbours in time, not arrival order."""
    n = quality.STUCK_READINGS
    # Readings 0..n-2 stuck at 21.5, then later readings vary.
    for i in range(n - 1):
        client.post("/readings", json=reading_at(i, temp_c=21.5), headers=auth)
    for i in range(n, n + 3):
        client.post("/readings", json=reading_at(i, temp_c=30.0 + i), headers=auth)
    # Reading n-1 arrives last, after the later ones.
    client.post("/readings", json=reading_at(n - 1, temp_c=21.5), headers=auth)

    late = [r for r in stored_rows(db_path) if r["reading_id"] == f"aaaa0001-{n}"][0]
    assert late["quality"] == "temp_stuck"


def test_migration_from_v1_adds_columns_and_flags_old_rows(db_path: Path) -> None:
    v1_schema = db.SCHEMA.split("    boot_count")[0] + "    UNIQUE (station_id, reading_id)\n);"
    conn = sqlite3.connect(db_path)
    conn.executescript(v1_schema)
    conn.execute("PRAGMA user_version = 1")
    for i, temp in enumerate([18.0, 99.0, 19.0]):
        conn.execute(
            "INSERT INTO readings (station_id, reading_id, received_at, device_time, uptime_ms, "
            "window_s, rain_tips, rain_mm, wind_avg_kmh, wind_peak_kmh, temp_c, rh_pct, "
            "press_hpa, bme280) VALUES ('station-1', ?, ?, ?, 0, 300, 0, 0, 0, 0, ?, 50, 1000, "
            "'ok')",
            (f"old-{i}", utc_text(START), utc_text(START + timedelta(minutes=5 * i)), temp),
        )
    conn.commit()
    conn.close()

    db.init_db(str(db_path))

    rows = stored_rows(db_path)
    assert [r["quality"] for r in rows] == ["", "temp_range", ""]
    assert rows[1]["temp_c"] == 99.0
    assert rows[0]["boot_count"] is None
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


# --- Read API ----------------------------------------------------------------


def test_current_shows_flags_and_withholds_derived_values(client: TestClient, auth: dict) -> None:
    now = datetime.now(UTC)
    reading = make_reading(device_time=utc_text(now), temp_c=70.0, rh_pct=50.0)
    client.post("/readings", json=reading, headers=auth)

    body = client.get("/api/current").json()
    assert body["reading"]["temp_c"] == 70.0
    assert body["reading"]["quality"] == ["temp_range"]
    assert body["derived"]["dew_point_c"] is None
    assert body["derived"]["heat_index_c"] is None
    assert body["health"]["flagged_24h"] == 1


def test_series_leaves_flagged_values_out(client: TestClient, auth: dict) -> None:
    for i, (temp, rain) in enumerate([(10.0, 0.5), (80.0, 30.0), (12.0, 0.5)]):
        client.post("/readings", json=reading_at(i, temp_c=temp, rain_mm=rain), headers=auth)

    params = {"start": "2026-10-03T11:00:00Z", "end": "2026-10-03T14:00:00Z"}
    points = client.get("/api/series", params=params).json()["points"]
    assert [p["temp_c"] for p in points] == [10.0, None, 12.0]
    assert [p["rain_mm"] for p in points] == [0.5, None, 0.5]
    assert [p["flagged"] for p in points] == [0, 1, 0]
    # The flagged reading's other fields still count.
    assert points[1]["rh_pct"] is not None


def test_rain_totals_skip_flagged_rain(client: TestClient, auth: dict) -> None:
    now = datetime.now(UTC)
    for i, rain in enumerate([1.0, 40.0]):
        reading = make_reading(
            reading_id=f"r-{i}",
            device_time=utc_text(now - timedelta(minutes=10 - 5 * i)),
            rain_mm=rain,
        )
        client.post("/readings", json=reading, headers=auth)
    assert client.get("/api/current").json()["rain"]["last_hour_mm"] == 1.0


def test_wind_rose_counts_flagged_wind_separately(client: TestClient, auth: dict) -> None:
    client.post("/readings", json=reading_at(0, wind_avg_kmh=15.0), headers=auth)
    client.post("/readings", json=reading_at(1, wind_avg_kmh=300.0), headers=auth)
    params = {"start": "2026-10-03T11:00:00Z", "end": "2026-10-03T14:00:00Z"}
    rose = client.get("/api/wind", params=params).json()
    assert rose["total"] == 2
    assert rose["flagged"] == 1
    assert sum(sum(s["counts"]) for s in rose["sectors"]) == 1
