"""SQLite storage for readings (docs/database.md).

Plain ``sqlite3`` with one short-lived connection per request: at one write
every five minutes there is nothing to pool.
"""

import sqlite3
from collections import deque
from contextlib import closing
from datetime import UTC, datetime

from weather_station_server import quality
from weather_station_server.models import Reading, ReadingReceipt

SCHEMA_VERSION = 2

# A reading's time: the station's clock, or the server's while the station
# was unsynced (docs/database.md). Written exactly as in the index below, so
# SQLite can use the index for it.
READING_TIME = "COALESCE(device_time, received_at)"

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
    boot_count    INTEGER,
    reset_reason  TEXT,
    queue_dropped INTEGER,
    quality       TEXT    NOT NULL DEFAULT '',
    UNIQUE (station_id, reading_id)
);
CREATE INDEX IF NOT EXISTS readings_station_time ON readings (station_id, received_at);
-- Reading time (docs/database.md): the read API's range queries search this
-- index instead of scanning every row.
CREATE INDEX IF NOT EXISTS readings_station_reading_time
    ON readings (station_id, COALESCE(device_time, received_at));
"""

# Version 1 to 2 (M4): reboot and queue telemetry, and data-quality flags.
MIGRATE_V1 = (
    "ALTER TABLE readings ADD COLUMN boot_count INTEGER",
    "ALTER TABLE readings ADD COLUMN reset_reason TEXT",
    "ALTER TABLE readings ADD COLUMN queue_dropped INTEGER",
    "ALTER TABLE readings ADD COLUMN quality TEXT NOT NULL DEFAULT ''",
)

# Payload fields stored as-is, in column order (device_time is converted).
_COLUMNS = [name for name in Reading.model_fields]


def utc_text(moment: datetime) -> str:
    """Format a timestamp as stored: UTC, millisecond precision, ``Z`` suffix."""
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def connect(path: str) -> sqlite3.Connection:
    return sqlite3.connect(path, timeout=5)


def init_db(path: str) -> None:
    """Create the file and schema if missing, or migrate an older schema.

    Safe to run on every startup.
    """
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
        if version == 1:
            conn.execute("BEGIN")
            for statement in MIGRATE_V1:
                conn.execute(statement)
            reflag(conn)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.commit()
        conn.executescript(SCHEMA)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()


def reflag(conn: sqlite3.Connection) -> int:
    """Re-run the quality rules over every stored reading; returns how many are flagged."""
    conn.row_factory = sqlite3.Row
    fields = ", ".join(["window_s", "rain_mm", *quality.RANGES])
    rows = conn.execute(
        f"SELECT id, station_id, {fields} FROM readings ORDER BY station_id, {READING_TIME}"
    ).fetchall()
    conn.row_factory = None
    updates = []
    previous: deque[sqlite3.Row] = deque(maxlen=quality.STUCK_READINGS - 1)
    station = None
    for row in rows:
        if row["station_id"] != station:
            station = row["station_id"]
            previous.clear()
        flags = quality.evaluate(row, list(reversed(previous)))
        updates.append((" ".join(flags), row["id"]))
        previous.append(row)
    conn.executemany("UPDATE readings SET quality = ? WHERE id = ?", updates)
    return sum(1 for text, _ in updates if text)


def check_db(path: str) -> None:
    """Raise if the database cannot be opened and read."""
    with closing(connect(path)) as conn:
        conn.execute("SELECT 1 FROM readings LIMIT 1").fetchall()


def store_reading(path: str, reading: Reading) -> ReadingReceipt:
    """Insert a reading, or return the existing row if it was already stored.

    The reading is checked against the readings before it in time, so a late
    (backfilled) reading is judged by its neighbours, not by arrival order.
    """
    values = reading.model_dump()
    if reading.device_time is not None:
        values["device_time"] = utc_text(reading.device_time)
    received_at = utc_text(datetime.now(UTC))

    columns = ", ".join(["received_at", "quality", *_COLUMNS])
    placeholders = ", ".join("?" * (len(_COLUMNS) + 2))
    with closing(connect(path)) as conn, conn:
        conn.row_factory = sqlite3.Row
        previous = conn.execute(
            f"SELECT {', '.join(quality.STUCK_FIELDS)} FROM readings "
            f"WHERE station_id = ? AND {READING_TIME} < ? ORDER BY {READING_TIME} DESC LIMIT ?",
            (
                reading.station_id,
                values["device_time"] or received_at,
                quality.STUCK_READINGS - 1,
            ),
        ).fetchall()
        flags = " ".join(quality.evaluate(values, previous))
        cursor = conn.execute(
            f"INSERT INTO readings ({columns}) VALUES ({placeholders}) "
            "ON CONFLICT (station_id, reading_id) DO NOTHING",
            [received_at, flags, *(values[name] for name in _COLUMNS)],
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
