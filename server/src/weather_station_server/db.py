"""SQLite storage for readings (docs/database.md).

Plain ``sqlite3`` with one short-lived connection per request: at one write
every five minutes there is nothing to pool.
"""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime

from weather_station_server.models import Reading, ReadingReceipt

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    id            INTEGER PRIMARY KEY,
    station_id    TEXT    NOT NULL,
    reading_id    TEXT    NOT NULL,
    received_at   TEXT    NOT NULL,
    device_time   TEXT,
    uptime_ms     INTEGER NOT NULL,
    window_s      INTEGER NOT NULL,
    rain_tips     INTEGER NOT NULL,
    rain_mm       REAL    NOT NULL,
    wind_avg_kmh  REAL    NOT NULL,
    wind_peak_kmh REAL    NOT NULL,
    wind_dir_deg  REAL,
    temp_c        REAL,
    rh_pct        REAL,
    press_hpa     REAL,
    bme280        TEXT    NOT NULL,
    rssi_dbm      INTEGER,
    UNIQUE (station_id, reading_id)
);
CREATE INDEX IF NOT EXISTS readings_station_time ON readings (station_id, received_at);
-- Reading time (docs/database.md): the read API's range queries search this
-- index instead of scanning every row.
CREATE INDEX IF NOT EXISTS readings_station_reading_time
    ON readings (station_id, COALESCE(device_time, received_at));
"""

# Payload fields stored as-is, in column order (device_time is converted).
_COLUMNS = [name for name in Reading.model_fields]


def utc_text(moment: datetime) -> str:
    """Format a timestamp as stored: UTC, millisecond precision, ``Z`` suffix."""
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def connect(path: str) -> sqlite3.Connection:
    return sqlite3.connect(path, timeout=5)


def init_db(path: str) -> None:
    """Create the file and schema if missing. Safe to run on every startup."""
    with closing(connect(path)) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"{path} has schema version {version}, newer than this server ({SCHEMA_VERSION})"
            )
        # Rollback journal, not WAL: WAL readers must write the -shm file, so
        # read-only users such as Grafana could not open the database. At one
        # write per five minutes, WAL's concurrency gain doesn't matter.
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.executescript(SCHEMA)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()


def check_db(path: str) -> None:
    """Raise if the database cannot be opened and read."""
    with closing(connect(path)) as conn:
        conn.execute("SELECT 1 FROM readings LIMIT 1").fetchall()


def store_reading(path: str, reading: Reading) -> ReadingReceipt:
    """Insert a reading, or return the existing row if it was already stored."""
    values = reading.model_dump()
    if reading.device_time is not None:
        values["device_time"] = utc_text(reading.device_time)
    received_at = utc_text(datetime.now(UTC))

    columns = ", ".join(["received_at", *_COLUMNS])
    placeholders = ", ".join("?" * (len(_COLUMNS) + 1))
    with closing(connect(path)) as conn, conn:
        cursor = conn.execute(
            f"INSERT INTO readings ({columns}) VALUES ({placeholders}) "
            "ON CONFLICT (station_id, reading_id) DO NOTHING",
            [received_at, *(values[name] for name in _COLUMNS)],
        )
        duplicate = cursor.rowcount == 0
        row_id, received_at = conn.execute(
            "SELECT id, received_at FROM readings WHERE station_id = ? AND reading_id = ?",
            (reading.station_id, reading.reading_id),
        ).fetchone()
    return ReadingReceipt(
        id=row_id,
        station_id=reading.station_id,
        reading_id=reading.reading_id,
        received_at=received_at,
        duplicate=duplicate,
    )
