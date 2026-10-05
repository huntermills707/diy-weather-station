"""Backfilled readings (JAE-61): late, out-of-order, and repeated submissions.

The station queues readings during an outage and sends them oldest first when
the link returns, possibly repeating one whose response was lost.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from conftest import make_reading, stored_rows
from fastapi.testclient import TestClient

from weather_station_server.db import utc_text


def test_out_of_order_and_duplicate_backfill(client: TestClient, auth: dict, db_path: Path) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    times = [now - timedelta(minutes=5 * k) for k in range(6, 0, -1)]  # oldest first
    readings = [
        make_reading(
            reading_id=f"b00710ad-{i + 1}",
            device_time=utc_text(t),
            temp_c=10.0 + i,
            rain_mm=0.28,
            rain_tips=1,
        )
        for i, t in enumerate(times)
    ]

    # Live: reading 1 arrives. Then an outage: 2-5 queue on the station.
    # Reading 6 is taken after the link returns but the queue sends 2-5
    # first; 3 is retried after a lost response, and 4 arrives after 5.
    order = [0, 1, 2, 2, 4, 3, 5, 3]
    statuses = [client.post("/readings", json=readings[i], headers=auth).status_code for i in order]
    assert statuses == [201, 201, 201, 200, 201, 201, 201, 200]

    rows = stored_rows(db_path)
    assert len(rows) == 6
    # Each keeps the station's time, however late it arrived.
    by_id = {r["reading_id"]: r for r in rows}
    for reading in readings:
        assert by_id[reading["reading_id"]]["device_time"] == reading["device_time"]

    # Series puts them in reading-time order, without a gap.
    start = utc_text(times[0] - timedelta(minutes=1))
    points = client.get("/api/series", params={"start": start}).json()["points"]
    assert [p["temp_c"] for p in points] == [10.0, 11.0, 12.0, 13.0, 14.0, 15.0]
    assert all(p["n"] == 1 for p in points)

    current = client.get("/api/current").json()
    # The latest reading is the newest in time, not the last to arrive.
    assert current["reading"]["reading_id"] == "b00710ad-6"
    # Rain counts every reading exactly once.
    assert current["rain"]["last_hour_mm"] == round(6 * 0.28, 2)
    assert current["health"]["readings_24h"] == 6


def test_late_reading_does_not_replace_the_latest(
    client: TestClient, auth: dict, db_path: Path
) -> None:
    now = datetime.now(UTC)
    client.post(
        "/readings",
        json=make_reading(reading_id="a-2", device_time=utc_text(now), temp_c=20.0),
        headers=auth,
    )
    client.post(
        "/readings",
        json=make_reading(reading_id="a-1", device_time=utc_text(now - timedelta(hours=3))),
        headers=auth,
    )
    assert client.get("/api/current").json()["reading"]["reading_id"] == "a-2"


def test_telemetry_fields_are_stored(client: TestClient, auth: dict, db_path: Path) -> None:
    reading = make_reading(boot_count=17, reset_reason="task_watchdog", queue_dropped=3)
    assert client.post("/readings", json=reading, headers=auth).status_code == 201
    [row] = stored_rows(db_path)
    assert (row["boot_count"], row["reset_reason"], row["queue_dropped"]) == (
        17,
        "task_watchdog",
        3,
    )


def test_telemetry_fields_are_optional(client: TestClient, auth: dict, db_path: Path) -> None:
    """Firmware from before M4 sends none of them."""
    assert client.post("/readings", json=make_reading(), headers=auth).status_code == 201
    assert stored_rows(db_path)[0]["boot_count"] is None


def test_bad_reset_reason_is_rejected(client: TestClient, auth: dict) -> None:
    response = client.post(
        "/readings", json=make_reading(reset_reason="Robert'); DROP"), headers=auth
    )
    assert response.status_code == 422
