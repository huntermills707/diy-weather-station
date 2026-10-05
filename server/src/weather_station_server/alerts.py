"""Local station alerts (docs/alerts.md, JAE-65).

A small daemon, separate from the ingest service so it still notices when
that service is down. Once a minute it reads the database and checks three
conditions: no new readings (station offline), freezing temperature, and no
recent backup. Each alert is announced once when it starts, reminded every
REMIND_EVERY while it lasts, and announced again when it clears. Alerts go to
the journal and, when ``WEATHER_STATION_NTFY_URL`` is set, to ntfy.

    python -m weather_station_server.alerts           # run forever
    python -m weather_station_server.alerts --once    # one check, then exit
    python -m weather_station_server.alerts --test    # send a test notification
"""

import argparse
import json
import logging
import sqlite3
import sys
import time
import urllib.request
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from weather_station_server import backup, quality
from weather_station_server.config import (
    load_alert_state_path,
    load_backup_dir,
    load_db_path,
    load_ntfy_url,
    load_station,
    load_timezone,
)
from weather_station_server.db import READING_TIME, utc_text
from weather_station_server.history import connect_ro, parse_utc

log = logging.getLogger(__name__)

CHECK_EVERY_S = 60
# Three missed five-minute readings: longer than a WiFi reconnect or a
# service restart, short enough to act on.
STALE_AFTER = timedelta(minutes=15)
# Frost can form on the ground with the air a little above freezing. The
# alert clears only a degree higher, so a temperature hovering at the
# threshold does not flap.
FREEZE_AT_C = 2.0
FREEZE_CLEAR_C = 3.0
# Nightly backups, with two hours of slack.
BACKUP_MAX_AGE = timedelta(hours=26)
REMIND_EVERY = timedelta(hours=6)
# An alert that comes back within an hour of clearing is not announced again
# until the hour is up, so a flapping condition sends at most a few messages.
QUIET_AFTER_RECOVERY = timedelta(hours=1)

TITLES = {
    "stale": ("Weather station offline", "Weather station back online"),
    "freeze": ("Freeze risk", "Freeze risk over"),
    "backup": ("Weather database backup missing", "Weather database backups current"),
}


@dataclass
class Condition:
    """One check's result. ``active`` None means unknown: keep the current state."""

    active: bool | None
    text: str = ""
    clear_text: str = ""


@dataclass
class Settings:
    db_path: str
    station: str
    backup_dir: Path
    ntfy_url: str | None
    timezone: ZoneInfo


def load_settings() -> Settings:
    return Settings(
        db_path=load_db_path(),
        station=load_station(),
        backup_dir=load_backup_dir(),
        ntfy_url=load_ntfy_url(),
        timezone=load_timezone(),
    )


def fahrenheit(celsius: float) -> float:
    return celsius * 9 / 5 + 32


def minutes(span: timedelta) -> str:
    total = round(span.total_seconds() / 60)
    return f"{total} min" if total < 120 else f"{total / 60:.1f} h"


def check_stale(conn: sqlite3.Connection, s: Settings, now: datetime) -> Condition:
    last = conn.execute(
        "SELECT max(received_at) FROM readings WHERE station_id = ?", (s.station,)
    ).fetchone()[0]
    if last is None:
        return Condition(None)  # nothing to watch until the first reading
    received = parse_utc(last)
    age = now - received
    local = received.astimezone(s.timezone)
    return Condition(
        age > STALE_AFTER,
        f"No reading from {s.station} for {minutes(age)} (last at {local:%-I:%M %p}).",
        f"{s.station} is reporting again.",
    )


def check_freeze(conn: sqlite3.Connection, s: Settings, now: datetime) -> Condition:
    row = conn.execute(
        f"SELECT received_at, temp_c, quality FROM readings WHERE station_id = ? "
        f"ORDER BY {READING_TIME} DESC LIMIT 1",
        (s.station,),
    ).fetchone()
    # Unknown without a fresh, trustworthy temperature; the offline alert
    # covers missing data.
    if (
        row is None
        or row["temp_c"] is None
        or now - parse_utc(row["received_at"]) > STALE_AFTER
        or quality.is_flagged(row["quality"], "temp_c")
    ):
        return Condition(None)
    temp = row["temp_c"]
    reading = f"{fahrenheit(temp):.1f} °F ({temp:.1f} °C) at {s.station}"
    if temp <= FREEZE_AT_C:
        active = True
    elif temp >= FREEZE_CLEAR_C:
        active = False
    else:
        active = None
    return Condition(active, f"Freeze risk: {reading}.", f"Above freezing again: {reading}.")


def check_backup(s: Settings, now: datetime) -> Condition:
    newest = backup.latest_backup(s.backup_dir) if s.backup_dir.is_dir() else None
    if newest is None:
        return Condition(True, f"No database backups in {s.backup_dir}.")
    made = datetime.fromtimestamp(newest.stat().st_mtime, UTC)
    return Condition(
        now - made > BACKUP_MAX_AGE,
        f"Newest database backup is {minutes(now - made)} old ({newest.name}). "
        "Check: journalctl -u weather-station-backup",
        f"Database backup {newest.name} written.",
    )


def check_all(s: Settings, now: datetime) -> dict[str, Condition]:
    with closing(connect_ro(s.db_path)) as conn:
        return {
            "stale": check_stale(conn, s, now),
            "freeze": check_freeze(conn, s, now),
            "backup": check_backup(s, now),
        }


def step(previous: dict[str, Any] | None, active: bool | None, now: datetime):
    """Advance one alert's state; return it and the notification due, if any.

    The notification is ``"alert"``, ``"reminder"``, ``"recovered"``, or None.
    """
    state = dict(previous or {"active": False, "announced": False})
    if active is None:
        return state, None
    if active:
        if not state["active"]:
            state.update(active=True, announced=False, since=utc_text(now))
        if not state["announced"]:
            recovered = state.get("recovered_at")
            if recovered and now < parse_utc(recovered) + QUIET_AFTER_RECOVERY:
                return state, None
            state.update(announced=True, last_sent=utc_text(now))
            return state, "alert"
        if now >= parse_utc(state["last_sent"]) + REMIND_EVERY:
            state["last_sent"] = utc_text(now)
            return state, "reminder"
        return state, None
    if not state["active"]:
        return state, None
    kind = "recovered" if state["announced"] else None
    if kind:
        state["recovered_at"] = utc_text(now)
    state.update(active=False, announced=False)
    return state, kind


def notify(url: str | None, title: str, message: str, kind: str, name: str) -> None:
    """Log a notification and post it to ntfy. Raises OSError if ntfy fails."""
    log.warning("alert %s %s: %s", name, kind, message)
    if url is None:
        return
    tags = (
        "white_check_mark"
        if kind == "recovered"
        else "snowflake"
        if name == "freeze"
        else "warning"
    )
    request = urllib.request.Request(
        url,
        data=message.encode(),
        method="POST",
        headers={
            "Title": title,
            "Priority": "default" if kind == "recovered" else "high",
            "Tags": tags,
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        response.read()


def check_once(s: Settings, states: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Run every check and send what is due. Returns the new states.

    An alert whose notification fails keeps its old state, so the next check
    tries again.
    """
    states = dict(states)
    for name, condition in check_all(s, now).items():
        new, kind = step(states.get(name), condition.active, now)
        if kind is not None:
            title = TITLES[name][kind == "recovered"]
            text = condition.clear_text if kind == "recovered" else condition.text
            if kind == "reminder":
                text = f"Still: {text}"
            try:
                notify(s.ntfy_url, title, text, kind, name)
            except OSError as exc:
                log.error("alert %s: could not reach ntfy at %s: %s", name, s.ntfy_url, exc)
                continue
        elif new["active"] != (states.get(name) or {}).get("active", False):
            if new["active"]:
                log.info("alert %s active, not announced: it cleared less than an hour ago", name)
            else:
                log.info("alert %s cleared before it was announced", name)
        states[name] = new
    return states


def valid_state(state: Any) -> bool:
    """Whether a saved alert state is one ``step`` can continue from."""
    if not isinstance(state, dict) or not isinstance(state.get("active"), bool):
        return False
    if not isinstance(state.get("announced"), bool):
        return False
    if state["announced"] and "last_sent" not in state:
        return False
    try:
        for key in ("since", "last_sent", "recovered_at"):
            if key in state:
                parse_utc(state[key])
    except (TypeError, ValueError, AttributeError):
        return False
    return True


def load_states(path: Path) -> dict[str, Any]:
    """Saved alert states. A damaged entry is dropped (that alert starts over), not fatal."""
    try:
        states = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        log.error("alerts: ignoring unreadable state file %s: %s", path, exc)
        return {}
    if not isinstance(states, dict):
        log.error("alerts: ignoring state file %s: not an object", path)
        return {}
    for name in [name for name, state in states.items() if not valid_state(state)]:
        log.error("alerts: ignoring damaged state for %s in %s", name, path)
        del states[name]
    return states


def save_states(path: Path, states: dict[str, Any]) -> None:
    partial = path.with_name(path.name + ".partial")
    partial.write_text(json.dumps(states, indent=1, sort_keys=True))
    partial.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true", help="run one check and exit")
    parser.add_argument("--test", action="store_true", help="send a test notification and exit")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = load_settings()

    if args.test:
        try:
            notify(
                settings.ntfy_url,
                "Weather station test",
                "Alerts reach this device.",
                "alert",
                "test",
            )
        except OSError as exc:
            log.error("alerts: could not reach ntfy at %s: %s", settings.ntfy_url, exc)
            return 1
        return 0

    state_path = load_alert_state_path()
    states = load_states(state_path)
    log.info(
        "alerts: watching %s in %s; ntfy %s",
        settings.station,
        settings.db_path,
        settings.ntfy_url or "not set (journal only)",
    )
    while True:
        try:
            new = check_once(settings, states, datetime.now(UTC))
            if new != states:
                save_states(state_path, new)
                states = new
        except (OSError, sqlite3.Error) as exc:
            log.error("alerts: check failed: %s", exc)
        except Exception:
            # Last resort: one bad check must not stop alerting for good.
            log.exception("alerts: check failed unexpectedly")
        if args.once:
            return 0
        time.sleep(CHECK_EVERY_S)


if __name__ == "__main__":
    sys.exit(main())
