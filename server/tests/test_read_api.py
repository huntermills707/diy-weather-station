import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from conftest import make_reading
from fastapi.testclient import TestClient

from weather_station_server import history
from weather_station_server.config import ALTITUDE_ENV_VAR
from weather_station_server.db import init_db, utc_text

NOW = datetime.now(UTC)


def insert(path: Path, time: datetime, received: datetime | None = None, **overrides: Any) -> None:
    """Store a reading as the ingest service would, with chosen timestamps.

    ``time`` is the device time; ``device_time=None`` in overrides makes it
    an unsynced reading placed by ``received`` (default: ``time``).
    """
    reading = make_reading(device_time=utc_text(time), reading_id=f"t-{time.timestamp():.0f}")
    reading.update(overrides, received_at=utc_text(received or time))
    columns = ", ".join(reading)
    conn = sqlite3.connect(path)
    with conn:
        conn.execute(
            f"INSERT INTO readings ({columns}) VALUES ({', '.join('?' * len(reading))})",
            list(reading.values()),
        )
    conn.close()


def iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


# --- /api/current ----------------------------------------------------------


def test_current_with_no_readings(client: TestClient) -> None:
    body = client.get("/api/current").json()
    assert body["reading"] is None
    assert body["derived"] is None
    assert body["health"] is None
    assert body["rain"] == {"last_hour_mm": 0, "today_mm": 0, "month_mm": 0}


def test_current_returns_latest_reading_with_derived_metrics(
    client: TestClient, db_path: Path
) -> None:
    insert(db_path, NOW - timedelta(minutes=10), temp_c=10.0)
    insert(db_path, NOW - timedelta(minutes=5), temp_c=25.0, rh_pct=60.0, wind_dir_deg=225.0)

    body = client.get("/api/current").json()

    assert body["reading"]["temp_c"] == 25.0
    assert body["reading"]["wind_dir_label"] == "SW"
    assert body["derived"]["dew_point_c"] == pytest.approx(16.7, abs=0.1)
    assert body["derived"]["heat_index_c"] is not None
    # No altitude configured: sea-level pressure is unavailable, not guessed.
    assert body["derived"]["sea_level_hpa"] is None
    assert body["derived"]["altitude_m"] is None


def test_current_uses_configured_altitude(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ALTITUDE_ENV_VAR, "100")
    from weather_station_server.main import app

    with TestClient(app) as client:
        insert(db_path, NOW, press_hpa=1000.0, temp_c=15.0)
        derived = client.get("/api/current").json()["derived"]
    assert derived["altitude_m"] == 100
    assert derived["sea_level_hpa"] == pytest.approx(1011.9, abs=0.1)


def test_current_failed_sensor_gives_unavailable_metrics(client: TestClient, db_path: Path) -> None:
    insert(
        db_path,
        NOW,
        temp_c=None,
        rh_pct=None,
        press_hpa=None,
        bme280="error",
        wind_dir_deg=None,
    )
    body = client.get("/api/current").json()
    assert body["reading"]["wind_dir_label"] is None
    assert body["derived"]["dew_point_c"] is None
    assert body["derived"]["heat_index_c"] is None
    assert body["health"]["bme280"] == "error"


def test_current_health_fresh_and_stale(client: TestClient, db_path: Path) -> None:
    insert(db_path, NOW - timedelta(minutes=3))
    health = client.get("/api/current").json()["health"]
    assert health["stale"] is False
    assert health["age_s"] == pytest.approx(180, abs=5)
    assert health["clock_synced"] is True

    insert(db_path, NOW - timedelta(minutes=12), received=NOW - timedelta(minutes=12))
    # The latest reading is still 3 minutes old.
    assert client.get("/api/current").json()["health"]["stale"] is False


def test_current_stale_after_two_missed_readings(client: TestClient, db_path: Path) -> None:
    insert(db_path, NOW - timedelta(minutes=12))
    health = client.get("/api/current").json()["health"]
    assert health["stale"] is True
    assert health["stale_after_s"] == 660


def test_current_health_counts_readings_and_boots(client: TestClient, db_path: Path) -> None:
    for i in range(1, 4):
        insert(db_path, NOW - timedelta(minutes=40 - 5 * i), reading_id=f"aaaa0000-{i}")
    insert(db_path, NOW - timedelta(minutes=2), reading_id="bbbb1111-1", uptime_ms=15000)
    insert(db_path, NOW - timedelta(hours=30), reading_id="cccc2222-9")

    health = client.get("/api/current").json()["health"]
    assert health["readings_24h"] == 4
    assert health["expected_24h"] == 288
    assert health["boots_24h"] == 2
    assert health["boot_id"] == "bbbb1111"
    assert health["uptime_s"] == 15


def test_current_unsynced_reading(client: TestClient, db_path: Path) -> None:
    insert(db_path, NOW, device_time=None)
    body = client.get("/api/current").json()
    assert body["health"]["clock_synced"] is False
    assert body["health"]["clock_offset_s"] is None
    assert body["reading"]["time"] == body["reading"]["received_at"]


# --- Rain totals ------------------------------------------------------------

LA = ZoneInfo("America/Los_Angeles")


def rain_at(path: Path, time: datetime, mm: float, reading_id: str) -> None:
    insert(path, time, rain_mm=mm, rain_tips=round(mm / 0.2794), reading_id=reading_id)


def test_rain_totals_follow_local_day_and_month(db_path: Path) -> None:
    init_db(str(db_path))
    # 10:00 PDT on 3 October = 17:00 UTC.
    now = datetime(2026, 10, 3, 17, 0, tzinfo=UTC)
    rain_at(db_path, datetime(2026, 9, 30, 6, 59, tzinfo=UTC), 1.0, "a-1")  # 29 Sep local
    rain_at(db_path, datetime(2026, 10, 1, 6, 59, tzinfo=UTC), 2.0, "a-2")  # 30 Sep 23:59 local
    rain_at(db_path, datetime(2026, 10, 1, 7, 1, tzinfo=UTC), 4.0, "a-3")  # 1 Oct 00:01 local
    rain_at(db_path, datetime(2026, 10, 3, 6, 59, tzinfo=UTC), 8.0, "a-4")  # 2 Oct 23:59 local
    rain_at(db_path, datetime(2026, 10, 3, 7, 0, tzinfo=UTC), 16.0, "a-5")  # midnight: 2 Oct
    rain_at(db_path, datetime(2026, 10, 3, 7, 5, tzinfo=UTC), 32.0, "a-6")  # 3 Oct 00:05 local
    rain_at(db_path, datetime(2026, 10, 3, 15, 59, tzinfo=UTC), 64.0, "a-7")  # 61 min ago
    rain_at(db_path, datetime(2026, 10, 3, 16, 30, tzinfo=UTC), 128.0, "a-8")  # 30 min ago

    totals = history.rain_totals(str(db_path), "station-1", now, LA)

    assert totals == {
        "last_hour_mm": 128.0,
        "today_mm": 32.0 + 64.0 + 128.0,
        "month_mm": 4.0 + 8.0 + 16.0 + 32.0 + 64.0 + 128.0,
    }


def test_rain_totals_in_utc_use_utc_midnight(db_path: Path) -> None:
    init_db(str(db_path))
    now = datetime(2026, 10, 3, 17, 0, tzinfo=UTC)
    rain_at(db_path, datetime(2026, 10, 2, 23, 0, tzinfo=UTC), 1.0, "a-1")
    rain_at(db_path, datetime(2026, 10, 3, 1, 0, tzinfo=UTC), 2.0, "a-2")
    totals = history.rain_totals(str(db_path), "station-1", now, ZoneInfo("UTC"))
    assert totals["today_mm"] == 2.0
    assert totals["month_mm"] == 3.0


def test_rain_totals_across_reboot_are_not_negative_or_inflated(db_path: Path) -> None:
    """Tips are per window, so a reboot (new boot ID, short window) just adds its window."""
    init_db(str(db_path))
    now = datetime(2026, 10, 3, 17, 0, tzinfo=UTC)
    base = datetime(2026, 10, 3, 16, 0, tzinfo=UTC)
    insert(db_path, base + timedelta(minutes=5), reading_id="aaaa0000-11", rain_tips=5, rain_mm=1.4)
    insert(
        db_path, base + timedelta(minutes=10), reading_id="aaaa0000-12", rain_tips=3, rain_mm=0.84
    )
    # Reboot: a new boot ID whose first window is short and counts from zero.
    insert(
        db_path,
        base + timedelta(minutes=12),
        reading_id="bbbb1111-1",
        window_s=60,
        uptime_ms=60000,
        rain_tips=1,
        rain_mm=0.28,
    )
    insert(db_path, base + timedelta(minutes=17), reading_id="bbbb1111-2", rain_tips=0, rain_mm=0.0)

    totals = history.rain_totals(str(db_path), "station-1", now, LA)
    assert totals["last_hour_mm"] == pytest.approx(1.4 + 0.84 + 0.28)


def test_rain_duplicate_submission_is_counted_once(
    client: TestClient, auth: dict, db_path: Path
) -> None:
    reading = make_reading(device_time=iso(NOW), rain_tips=2, rain_mm=0.56)
    assert client.post("/readings", json=reading, headers=auth).status_code == 201
    assert client.post("/readings", json=reading, headers=auth).status_code == 200
    assert client.get("/api/current").json()["rain"]["last_hour_mm"] == 0.56


# --- /api/series ------------------------------------------------------------

START = datetime(2026, 10, 1, tzinfo=UTC)


def series(client: TestClient, start: datetime, end: datetime) -> dict[str, Any]:
    response = client.get("/api/series", params={"start": iso(start), "end": iso(end)})
    assert response.status_code == 200, response.text
    return response.json()


def test_series_empty_range(client: TestClient) -> None:
    body = series(client, START, START + timedelta(hours=24))
    assert body["points"] == []
    assert body["bucket_s"] == 300


@pytest.mark.parametrize(
    ("span", "bucket_s"),
    [
        (timedelta(hours=1), 300),
        (timedelta(hours=24), 300),
        (timedelta(days=7), 1800),
        (timedelta(days=30), 7200),
        (timedelta(days=366), 86400),
    ],
)
def test_series_downsamples_large_ranges(
    client: TestClient, span: timedelta, bucket_s: int
) -> None:
    body = series(client, START, START + span)
    assert body["bucket_s"] == bucket_s
    assert span.total_seconds() / body["bucket_s"] <= history.MAX_POINTS


def test_series_raw_readings_with_a_gap(client: TestClient, db_path: Path) -> None:
    # Readings every 5 minutes at :02:39, one missing at 00:17:39.
    times = [START + timedelta(minutes=2 + 5 * i, seconds=39) for i in range(6) if i != 3]
    for i, time in enumerate(times):
        insert(db_path, time, temp_c=10.0 + i)

    points = series(client, START, START + timedelta(hours=24))["points"]

    assert [p["n"] for p in points] == [1, 1, 1, 0, 1, 1]
    assert points[0]["time"] == "2026-10-01T00:02:39.000Z"
    assert points[0]["temp_c"] == 10.0
    gap = points[3]
    assert gap["time"] == "2026-10-01T00:17:39.000Z"
    assert all(gap[name] is None for name in gap if name not in ("time", "n"))


def test_series_aggregates_buckets(client: TestClient, db_path: Path) -> None:
    # 7-day range: 30-minute buckets. Six readings in the first bucket.
    for i in range(6):
        insert(
            db_path,
            START + timedelta(minutes=5 * i),
            temp_c=10.0 + i,
            rh_pct=50.0,
            wind_avg_kmh=float(i),
            wind_peak_kmh=float(10 * i),
            rain_tips=1,
            rain_mm=0.2794,
        )

    body = series(client, START, START + timedelta(days=7))

    assert body["bucket_s"] == 1800
    [point] = body["points"]
    assert point["n"] == 6
    assert point["time"] == "2026-10-01T00:12:30.000Z"
    assert point["temp_c"] == 12.5
    assert point["temp_min_c"] == 10.0
    assert point["temp_max_c"] == 15.0
    assert point["wind_avg_kmh"] == 2.5
    assert point["wind_peak_kmh"] == 50.0
    assert point["rain_mm"] == pytest.approx(1.68, abs=0.01)


def test_series_bucket_boundary_jitter_is_not_a_gap(client: TestClient, db_path: Path) -> None:
    """Two readings land in one bucket and none in the next: still 5 minutes apart."""
    insert(db_path, START + timedelta(minutes=4, seconds=59))
    insert(db_path, START + timedelta(minutes=5, seconds=1))
    insert(db_path, START + timedelta(minutes=9, seconds=58))
    insert(db_path, START + timedelta(minutes=15, seconds=2))
    points = series(client, START, START + timedelta(hours=24))["points"]
    assert all(p["n"] > 0 for p in points)


def test_series_keeps_unavailable_values_null(client: TestClient, db_path: Path) -> None:
    insert(db_path, START, temp_c=None, rh_pct=None, press_hpa=None, bme280="error")
    [point] = series(client, START, START + timedelta(hours=1))["points"]
    assert point["n"] == 1
    assert point["temp_c"] is None
    assert point["wind_avg_kmh"] == 7.2


def test_series_places_readings_by_device_time(client: TestClient, db_path: Path) -> None:
    """A late-arriving reading sits at its device time; unsynced ones at receive time."""
    insert(db_path, START + timedelta(minutes=5), received=START + timedelta(hours=2), temp_c=1.0)
    insert(db_path, START + timedelta(minutes=10), temp_c=2.0)
    insert(
        db_path,
        START + timedelta(minutes=15),
        received=START + timedelta(minutes=15),
        device_time=None,
        reading_id="aaaa0000-x",
        temp_c=3.0,
    )
    points = series(client, START, START + timedelta(hours=1))["points"]
    assert [p["temp_c"] for p in points] == [1.0, 2.0, 3.0]


def test_series_only_returns_the_requested_station(client: TestClient, db_path: Path) -> None:
    insert(db_path, START, station_id="other")
    assert series(client, START, START + timedelta(hours=1))["points"] == []


def test_series_defaults_to_the_last_24_hours(client: TestClient, db_path: Path) -> None:
    insert(db_path, NOW - timedelta(hours=2))
    insert(db_path, NOW - timedelta(hours=25))
    body = client.get("/api/series").json()
    assert body["bucket_s"] == 300
    assert len(body["points"]) == 1


@pytest.mark.parametrize(
    ("params", "detail"),
    [
        ({"start": "2026-10-02T00:00:00Z", "end": "2026-10-01T00:00:00Z"}, "before end"),
        ({"start": "2026-10-01T00:00:00Z", "end": "2026-10-01T00:00:00Z"}, "before end"),
        ({"start": "2024-01-01T00:00:00Z", "end": "2026-01-01T00:00:00Z"}, "366-day maximum"),
        ({"start": "2026-10-01T00:00:00"}, "timezone"),
        ({"start": "yesterday"}, "datetime"),
        ({"station": "bad station!"}, "pattern"),
    ],
)
@pytest.mark.parametrize("path", ["/api/series", "/api/wind"])
def test_invalid_ranges_are_rejected(
    client: TestClient, path: str, params: dict[str, str], detail: str
) -> None:
    response = client.get(path, params=params)
    assert response.status_code == 422
    assert detail in response.text


# --- /api/wind --------------------------------------------------------------


def test_wind_rose_bins_directions_and_speeds(client: TestClient, db_path: Path) -> None:
    fixtures = [
        (0.0, 5.0),  # N, 2-10
        (350.0, 15.0),  # nearest sector N, 10-20
        (11.25, 25.0),  # boundary goes clockwise: NNE, 20-30
        (225.0, 40.0),  # SW, 30+
        (225.0, 2.0),  # SW, 2-10 (2 is not calm)
        (90.0, 1.9),  # calm
        (None, 20.0),  # vane unknown: never a sector
        (None, 0.0),  # unknown even when calm
    ]
    for i, (direction, speed) in enumerate(fixtures):
        insert(
            db_path,
            START + timedelta(minutes=5 * i),
            wind_dir_deg=direction,
            wind_avg_kmh=speed,
        )

    response = client.get(
        "/api/wind", params={"start": iso(START), "end": iso(START + timedelta(hours=1))}
    )
    body = response.json()

    assert body["total"] == 8
    assert body["calm"] == 1
    assert body["unknown"] == 2
    assert body["speed_classes_kmh"] == [2.0, 10.0, 20.0, 30.0]
    sectors = {s["label"]: s["counts"] for s in body["sectors"]}
    assert len(sectors) == 16
    assert sectors["N"] == [1, 1, 0, 0]
    assert sectors["NNE"] == [0, 0, 1, 0]
    assert sectors["SW"] == [1, 0, 0, 1]
    assert sectors["E"] == [0, 0, 0, 0]
    binned = sum(sum(c) for c in sectors.values())
    assert binned + body["calm"] + body["unknown"] == body["total"]


def test_wind_rose_empty_range(client: TestClient) -> None:
    body = client.get(
        "/api/wind", params={"start": iso(START), "end": iso(START + timedelta(days=30))}
    ).json()
    assert body["total"] == 0
    assert all(sum(s["counts"]) == 0 for s in body["sectors"])


@pytest.mark.parametrize(
    ("direction", "label"),
    [(0, "N"), (11.24, "N"), (11.25, "NNE"), (348.75, "N"), (348.74, "NNW"), (359.9, "N")],
)
def test_sector_of(direction: float, label: str) -> None:
    assert history.SECTOR_LABELS[history.sector_of(direction)] == label


# --- Database errors and the dashboard ---------------------------------------


def test_read_api_reports_unreadable_database(client: TestClient, db_path: Path) -> None:
    db_path.unlink()
    for path in ("/api/current", "/api/series", "/api/wind"):
        response = client.get(path)
        assert response.status_code == 503
        assert response.json() == {"detail": "Database unavailable"}


def test_read_api_never_writes(client: TestClient, db_path: Path) -> None:
    insert(db_path, NOW)
    before = db_path.stat().st_mtime_ns
    for path in ("/api/current", "/api/series", "/api/wind"):
        assert client.get(path).status_code == 200
    assert db_path.stat().st_mtime_ns == before


def test_dashboard_is_served_at_root(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert client.get("/app.js").status_code == 200
    # API routes still win over the static mount.
    assert client.get("/health").json() == {"status": "ok"}
