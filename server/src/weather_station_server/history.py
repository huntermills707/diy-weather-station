"""Read-side queries for the dashboard (docs/read-api.md).

A reading's time is ``device_time``, or ``received_at`` while the station's
clock was unsynced (docs/database.md). Connections are read-only, so these
queries can never change stored data.
"""

import math
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from weather_station_server.db import utc_text

CADENCE_S = 300
READING_TIME = "COALESCE(device_time, received_at)"
# Bucket sizes for downsampling, smallest first; the series uses the smallest
# one that keeps the range within MAX_POINTS.
BUCKETS_S = (300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400)
MAX_POINTS = 400
MAX_RANGE = timedelta(days=366)

# Wind rose: 16 compass sectors, matching the vane's 16 headings.
SECTOR_LABELS = tuple("N NNE NE ENE E ESE SE SSE S SSW SW WSW W WNW NW NNW".split())
# Average speed below 2 km/h (about 1 knot, the WMO calm limit) counts as
# calm: the vane holds its last heading when the air is still.
CALM_KMH = 2.0
# Lower edges of the speed classes above calm, km/h.
SPEED_CLASSES_KMH = (CALM_KMH, 10.0, 20.0, 30.0)


def connect_ro(path: str) -> sqlite3.Connection:
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def parse_utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def boot_id(reading_id: str) -> str:
    """The boot part of a ``<boot_id>-<seq>`` reading ID (docs/ingest-api.md)."""
    return reading_id.partition("-")[0]


def bucket_for(span: timedelta) -> int:
    """Smallest bucket that keeps ``span`` within MAX_POINTS buckets."""
    for size in BUCKETS_S:
        if span.total_seconds() / size <= MAX_POINTS:
            return size
    return BUCKETS_S[-1]


def latest(path: str, station: str) -> dict[str, Any] | None:
    """The station's most recent reading, as stored."""
    with closing(connect_ro(path)) as conn:
        row = conn.execute(
            f"SELECT *, {READING_TIME} AS time FROM readings WHERE station_id = ? "
            "ORDER BY time DESC LIMIT 1",
            (station,),
        ).fetchone()
    return dict(row) if row else None


def rain_totals(path: str, station: str, now: datetime, tz: ZoneInfo) -> dict[str, float]:
    """Rain in the last hour, since local midnight, and since the 1st of the month.

    Each reading carries the tips of its own window, counted from zero, so
    summing windows is the cumulative total. A reboot only starts a new
    window: it cannot make rain negative or count tips twice, and the unique
    reading ID keeps a retried reading from being added again.
    """
    local = now.astimezone(tz)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    starts = {
        "last_hour_mm": now - timedelta(hours=1),
        "today_mm": midnight,
        "month_mm": midnight.replace(day=1),
    }
    # One query; each total sums the readings after its own start.
    columns = ", ".join(
        f"COALESCE(sum(CASE WHEN time > :{name} THEN rain_mm END), 0) AS {name}" for name in starts
    )
    params = {name: utc_text(start) for name, start in starts.items()}
    with closing(connect_ro(path)) as conn:
        row = conn.execute(
            f"SELECT {columns} FROM (SELECT {READING_TIME} AS time, rain_mm FROM readings "
            "WHERE station_id = :station) WHERE time > :earliest",
            {**params, "station": station, "earliest": min(params.values())},
        ).fetchone()
    return {name: round(row[name], 2) for name in starts}


def recent_activity(path: str, station: str, now: datetime) -> dict[str, int]:
    """Readings stored and boots seen in the last 24 hours."""
    with closing(connect_ro(path)) as conn:
        ids = [
            row[0]
            for row in conn.execute(
                f"SELECT reading_id FROM readings WHERE station_id = ? AND {READING_TIME} > ?",
                (station, utc_text(now - timedelta(hours=24))),
            )
        ]
    return {"readings_24h": len(ids), "boots_24h": len({boot_id(i) for i in ids})}


def series(
    path: str, station: str, start: datetime, end: datetime, bucket_s: int
) -> list[dict[str, Any]]:
    """Readings in [start, end) averaged into ``bucket_s`` buckets.

    Only buckets with readings are returned, each at the mean time of its
    readings. Where no reading arrived for longer than one bucket plus half a
    cadence, a point with every value null marks the gap, so charts break
    the line instead of drawing across missing data. The quiet time is
    measured between actual readings, not bucket means, so timing jitter
    that puts two readings in one bucket never looks like a gap.
    """
    epoch = "CAST(strftime('%s', time) AS INTEGER)"
    with closing(connect_ro(path)) as conn:
        rows = conn.execute(
            f"""
            SELECT {epoch} / :bucket AS bucket,
                   count(*) AS n,
                   avg({epoch}) AS epoch, min({epoch}) AS first, max({epoch}) AS last,
                   avg(temp_c) AS temp_c, min(temp_c) AS temp_min_c, max(temp_c) AS temp_max_c,
                   avg(rh_pct) AS rh_pct,
                   avg(press_hpa) AS press_hpa,
                   avg(wind_avg_kmh) AS wind_avg_kmh,
                   max(wind_peak_kmh) AS wind_peak_kmh,
                   sum(rain_mm) AS rain_mm
            FROM (SELECT {READING_TIME} AS time, * FROM readings WHERE station_id = :station)
            WHERE time >= :start AND time < :end
            GROUP BY bucket ORDER BY bucket
            """,
            {
                "bucket": bucket_s,
                "station": station,
                "start": utc_text(start),
                "end": utc_text(end),
            },
        ).fetchall()

    points: list[dict[str, Any]] = []
    previous = None
    for row in rows:
        if previous is not None and row["first"] - previous > bucket_s + CADENCE_S / 2:
            points.append(_gap((previous + row["first"]) / 2))
        previous = row["last"]
        internal = ("bucket", "epoch", "first", "last")
        point = {name: row[name] for name in row.keys() if name not in internal}
        for name, value in point.items():
            if isinstance(value, float):
                point[name] = round(value, 2)
        points.append({"time": _epoch_text(row["epoch"]), **point})
    return points


def _epoch_text(epoch: float) -> str:
    return utc_text(datetime.fromtimestamp(round(epoch), UTC))


def _gap(epoch: float) -> dict[str, Any]:
    names = (
        "temp_c temp_min_c temp_max_c rh_pct press_hpa wind_avg_kmh wind_peak_kmh rain_mm".split()
    )
    return {"time": _epoch_text(epoch), "n": 0, **dict.fromkeys(names)}


def sector_of(direction_deg: float) -> int:
    """Index of the 22.5° compass sector centred nearest to a heading.

    A heading on a boundary goes clockwise (11.25° is NNE), consistently;
    ``round`` would alternate because it rounds halves to even.
    """
    return math.floor(direction_deg / 22.5 + 0.5) % 16


def speed_class(speed_kmh: float) -> int:
    """Index into SPEED_CLASSES_KMH for a speed at or above calm."""
    return max(i for i, low in enumerate(SPEED_CLASSES_KMH) if speed_kmh >= low)


def wind_rose(path: str, station: str, start: datetime, end: datetime) -> dict[str, Any]:
    """Count readings in [start, end) by direction sector and average-speed class.

    A reading without a vane heading is ``unknown``, never put in a sector.
    A reading with a heading but an average below CALM_KMH is ``calm``.
    """
    counts = [[0] * len(SPEED_CLASSES_KMH) for _ in SECTOR_LABELS]
    calm = unknown = 0
    with closing(connect_ro(path)) as conn:
        rows = conn.execute(
            f"SELECT wind_dir_deg, wind_avg_kmh FROM readings WHERE station_id = ? "
            f"AND {READING_TIME} >= ? AND {READING_TIME} < ?",
            (station, utc_text(start), utc_text(end)),
        ).fetchall()
    for direction, speed in rows:
        if direction is None:
            unknown += 1
        elif speed < CALM_KMH:
            calm += 1
        else:
            counts[sector_of(direction)][speed_class(speed)] += 1
    return {
        "total": len(rows),
        "calm": calm,
        "unknown": unknown,
        "calm_below_kmh": CALM_KMH,
        "speed_classes_kmh": list(SPEED_CLASSES_KMH),
        "sectors": [
            {"label": label, "direction_deg": i * 22.5, "counts": counts[i]}
            for i, label in enumerate(SECTOR_LABELS)
        ],
    }
