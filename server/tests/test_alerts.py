"""Local station alerts (JAE-65): stale data, freezing, backups, repetition, recovery."""

import os
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from conftest import make_reading
from fastapi.testclient import TestClient

from weather_station_server import alerts
from weather_station_server.db import init_db, store_reading, utc_text
from weather_station_server.models import Reading

T0 = datetime(2026, 12, 1, 6, 0, tzinfo=UTC)


class Ntfy:
    """A stand-in ntfy server recording what it receives."""

    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []
        self.fail = False
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers["Content-Length"])).decode()
                if outer.fail:
                    self.send_response(500)
                else:
                    outer.messages.append(
                        {
                            "title": self.headers["Title"],
                            "priority": self.headers["Priority"],
                            "body": body,
                        }
                    )
                    self.send_response(200)
                self.end_headers()

            def log_message(self, *args: Any) -> None:
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/weather"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def titles(self) -> list[str]:
        return [m["title"] for m in self.messages]


@pytest.fixture
def ntfy() -> Any:
    server = Ntfy()
    yield server
    server.server.shutdown()


@pytest.fixture
def settings(db_path: Path, tmp_path: Path, ntfy: Ntfy) -> alerts.Settings:
    init_db(str(db_path))
    backups = tmp_path / "backups"
    backups.mkdir()
    (backups / "weather-20261201T000000Z.db").write_bytes(b"")
    return alerts.Settings(str(db_path), "station-1", backups, ntfy.url, ZoneInfo("UTC"))


def add(settings: alerts.Settings, at: datetime, temp_c: float = 10.0, **kw: Any) -> None:
    """Store a reading received at ``at`` (the server clock is patched for it)."""
    reading = Reading(
        **make_reading(
            reading_id=f"x-{at.timestamp():.0f}", device_time=utc_text(at), temp_c=temp_c, **kw
        )
    )

    class Frozen(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            return at

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("weather_station_server.db.datetime", Frozen)
        store_reading(settings.db_path, reading)


def run(settings: alerts.Settings, states: dict, at: datetime) -> dict:
    return alerts.check_once(settings, states, at)


def fresh_backup(settings: alerts.Settings, at: datetime) -> None:
    """Make the backup look written at ``at``."""
    for path in settings.backup_dir.iterdir():
        os.utime(path, (at.timestamp(), at.timestamp()))


def test_no_readings_yet_is_quiet(settings: alerts.Settings, ntfy: Ntfy) -> None:
    fresh_backup(settings, T0)
    states = run(settings, {}, T0)
    assert not any(state["active"] for state in states.values())
    assert ntfy.messages == []


def test_stale_alert_fires_reminds_and_recovers(settings: alerts.Settings, ntfy: Ntfy) -> None:
    fresh_backup(settings, T0)
    add(settings, T0)
    states = run(settings, {}, T0 + timedelta(minutes=5))
    assert ntfy.messages == []

    # Silent past 15 minutes: one alert.
    states = run(settings, states, T0 + timedelta(minutes=16))
    assert ntfy.titles() == ["Weather station offline"]
    assert "No reading from station-1 for 16 min" in ntfy.messages[0]["body"]
    assert ntfy.messages[0]["priority"] == "high"

    # Repeated checks inside six hours send nothing more.
    for minute in range(17, 6 * 60, 30):
        fresh_backup(settings, T0 + timedelta(minutes=minute))
        states = run(settings, states, T0 + timedelta(minutes=minute))
    assert len(ntfy.messages) == 1

    # Six hours after the alert: one reminder.
    later = T0 + timedelta(minutes=16) + alerts.REMIND_EVERY
    fresh_backup(settings, later)
    states = run(settings, states, later)
    assert ntfy.titles()[-1] == "Weather station offline"
    assert ntfy.messages[-1]["body"].startswith("Still: ")

    # A reading arrives: one recovery.
    add(settings, later + timedelta(minutes=1))
    states = run(settings, states, later + timedelta(minutes=2))
    assert ntfy.titles()[-1] == "Weather station back online"
    assert ntfy.messages[-1]["priority"] == "default"
    assert len(ntfy.messages) == 3
    assert states["stale"]["active"] is False


def test_flapping_alert_is_announced_at_most_hourly(settings: alerts.Settings, ntfy: Ntfy) -> None:
    fresh_backup(settings, T0 + timedelta(hours=3))
    states: dict = {}
    t = T0
    # Every 20 minutes the station sends one reading and goes quiet again.
    for _ in range(6):
        add(settings, t)
        states = run(settings, states, t + timedelta(minutes=1))
        states = run(settings, states, t + timedelta(minutes=17))
        t += timedelta(minutes=20)
    # Two hours of flapping: not six alerts and six recoveries, but the first
    # pair and one more pair after the quiet hour.
    assert ntfy.titles() == [
        "Weather station offline",
        "Weather station back online",
        "Weather station offline",
        "Weather station back online",
    ]


def test_freeze_alert_with_hysteresis(settings: alerts.Settings, ntfy: Ntfy) -> None:
    fresh_backup(settings, T0 + timedelta(hours=1))
    states: dict = {}
    temps = [5.0, 1.5, 2.5, 1.0, 2.9, 3.4, 2.5]
    for i, temp in enumerate(temps):
        at = T0 + timedelta(minutes=5 * i)
        add(settings, at, temp_c=temp)
        states = run(settings, states, at + timedelta(seconds=30))
    assert ntfy.titles() == ["Freeze risk", "Freeze risk over"]
    assert ntfy.messages[0]["body"] == "Freeze risk: 34.7 °F (1.5 °C) at station-1."
    assert "38.1 °F (3.4 °C)" in ntfy.messages[1]["body"]


def test_freeze_ignores_flagged_and_old_temperatures(settings: alerts.Settings, ntfy: Ntfy) -> None:
    fresh_backup(settings, T0)
    add(settings, T0, temp_c=-35.0)  # out of range: flagged, not a frost
    run(settings, {}, T0 + timedelta(minutes=1))
    assert ntfy.messages == []


def test_missing_backup_alerts(settings: alerts.Settings, ntfy: Ntfy) -> None:
    fresh_backup(settings, T0 - timedelta(hours=27))
    states = run(settings, {}, T0)
    assert ntfy.titles() == ["Weather database backup missing"]
    fresh_backup(settings, T0 + timedelta(hours=1))
    run(settings, states, T0 + timedelta(hours=1))
    assert ntfy.titles()[-1] == "Weather database backups current"


def test_failed_delivery_is_retried(settings: alerts.Settings, ntfy: Ntfy) -> None:
    fresh_backup(settings, T0)
    add(settings, T0)
    ntfy.fail = True
    states = run(settings, {}, T0 + timedelta(minutes=16))
    assert states.get("stale", {}).get("active") is not True
    ntfy.fail = False
    run(settings, states, T0 + timedelta(minutes=17))
    assert ntfy.titles() == ["Weather station offline"]


def test_without_ntfy_alerts_only_log(
    settings: alerts.Settings, caplog: pytest.LogCaptureFixture
) -> None:
    settings.ntfy_url = None
    fresh_backup(settings, T0)
    add(settings, T0)
    run(settings, {}, T0 + timedelta(minutes=20))
    assert "alert stale alert: No reading from station-1" in caplog.text


def test_state_survives_a_restart(settings: alerts.Settings, ntfy: Ntfy, tmp_path: Path) -> None:
    fresh_backup(settings, T0)
    add(settings, T0)
    path = tmp_path / "alerts.json"
    alerts.save_states(path, run(settings, {}, T0 + timedelta(minutes=16)))
    run(settings, alerts.load_states(path), T0 + timedelta(minutes=17))
    assert len(ntfy.messages) == 1


def test_test_notification(
    settings: alerts.Settings, ntfy: Ntfy, monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    monkeypatch.setenv("WEATHER_STATION_NTFY_URL", ntfy.url)
    assert alerts.main(["--test"]) == 0
    assert ntfy.titles() == ["Weather station test"]


def test_damaged_state_file_is_dropped_not_fatal(
    settings: alerts.Settings, ntfy: Ntfy, tmp_path: Path
) -> None:
    path = tmp_path / "alerts.json"
    path.write_text(
        '{"stale": {"active": true, "announced": true},'
        ' "freeze": {"active": false, "announced": false, "recovered_at": "garbage"},'
        ' "backup": {"active": false, "announced": false}}'
    )
    states = alerts.load_states(path)
    assert list(states) == ["backup"]

    fresh_backup(settings, T0)
    add(settings, T0)
    run(settings, states, T0 + timedelta(minutes=16))
    assert ntfy.titles() == ["Weather station offline"]


def test_state_file_that_is_not_an_object_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "alerts.json"
    path.write_text("[1, 2]")
    assert alerts.load_states(path) == {}
