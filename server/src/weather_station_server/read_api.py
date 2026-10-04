"""Read API for the dashboard (docs/read-api.md).

No authentication, like ``/health``: the API is LAN-only (ADR 0001) and
read-only.
"""

import logging
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, TypeVar

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from pydantic import AwareDatetime, BaseModel

from weather_station_server import derived, history
from weather_station_server.db import utc_text

log = logging.getLogger("uvicorn.error")

# More than two cadences plus a minute of slack: one missed reading is not
# stale yet, but a second late one is.
STALE_AFTER_S = 2 * history.CADENCE_S + 60
EXPECTED_24H = 24 * 3600 // history.CADENCE_S

router = APIRouter(prefix="/api", responses={503: {"description": "Database unavailable"}})

Station = Annotated[str, Query(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]
RangeStart = Annotated[
    AwareDatetime | None, Query(description="Inclusive, with a UTC offset. Default: end - 24 h")
]
RangeEnd = Annotated[
    AwareDatetime | None, Query(description="Exclusive, with a UTC offset. Default: now")
]

T = TypeVar("T")


class StoredReading(BaseModel):
    """The latest reading as stored (docs/database.md), plus its time."""

    time: str
    received_at: str
    device_time: str | None
    reading_id: str
    uptime_ms: int
    window_s: int
    rain_tips: int
    rain_mm: float
    wind_avg_kmh: float
    wind_peak_kmh: float
    wind_dir_deg: float | None
    wind_dir_label: str | None
    temp_c: float | None
    rh_pct: float | None
    press_hpa: float | None
    bme280: Literal["ok", "implausible", "error"]
    rssi_dbm: int | None


class Derived(BaseModel):
    dew_point_c: float | None
    heat_index_c: float | None
    sea_level_hpa: float | None
    altitude_m: float | None


class RainTotals(BaseModel):
    last_hour_mm: float
    last_24h_mm: float
    today_mm: float
    month_mm: float


class Health(BaseModel):
    age_s: float
    stale: bool
    stale_after_s: int
    boot_id: str
    uptime_s: int
    readings_24h: int
    expected_24h: int
    boots_24h: int
    clock_synced: bool
    clock_offset_s: float | None
    rssi_dbm: int | None
    bme280: Literal["ok", "implausible", "error"]


class Current(BaseModel):
    station_id: str
    now: str
    timezone: str
    reading: StoredReading | None
    derived: Derived | None
    rain: RainTotals
    health: Health | None


class SeriesPoint(BaseModel):
    time: str
    n: int
    temp_c: float | None
    temp_min_c: float | None
    temp_max_c: float | None
    rh_pct: float | None
    press_hpa: float | None
    wind_avg_kmh: float | None
    wind_peak_kmh: float | None
    rain_mm: float | None


class Series(BaseModel):
    station_id: str
    start: str
    end: str
    bucket_s: int
    points: list[SeriesPoint]


class WindSector(BaseModel):
    label: str
    direction_deg: float
    counts: list[int]


class WindRose(BaseModel):
    station_id: str
    start: str
    end: str
    total: int
    calm: int
    unknown: int
    calm_below_kmh: float
    speed_classes_kmh: list[float]
    sectors: list[WindSector]


async def query(func: Callable[..., T], *args: Any) -> T:
    """Run a blocking query off the event loop; a database failure is a 503."""
    try:
        return await run_in_threadpool(func, *args)
    except sqlite3.Error as exc:
        log.exception("read query failed")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Database unavailable") from exc


def resolve_range(start: datetime | None, end: datetime | None) -> tuple[datetime, datetime]:
    """Apply defaults and reject empty, reversed, or overlong ranges with 422."""
    end = (end or datetime.now(UTC)).astimezone(UTC)
    start = (start or end - timedelta(hours=24)).astimezone(UTC)
    if start >= end:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "start must be before end")
    if end - start > history.MAX_RANGE:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"range is longer than the {history.MAX_RANGE.days}-day maximum",
        )
    return start, end


@router.get("/current")
async def current(request: Request, station: Station = "station-1") -> Current:
    """Latest reading, derived metrics, rain totals, and station health."""
    state = request.app.state
    now = datetime.now(UTC)
    row = await query(history.latest, state.db_path, station)
    rain = await query(history.rain_totals, state.db_path, station, now, state.timezone)
    reading = metrics = health = None
    if row is not None:
        direction = row["wind_dir_deg"]
        reading = StoredReading(
            **row,
            wind_dir_label=(
                None if direction is None else history.SECTOR_LABELS[history.sector_of(direction)]
            ),
        )
        metrics = Derived(
            dew_point_c=_round(derived.dew_point_c(row["temp_c"], row["rh_pct"])),
            heat_index_c=_round(derived.heat_index_c(row["temp_c"], row["rh_pct"])),
            sea_level_hpa=_round(
                derived.sea_level_pressure_hpa(row["press_hpa"], row["temp_c"], state.altitude_m)
            ),
            altitude_m=state.altitude_m,
        )
        activity = await query(history.recent_activity, state.db_path, station, now)
        received = history.parse_utc(row["received_at"])
        age = (now - received).total_seconds()
        offset = None
        if row["device_time"] is not None:
            offset = (received - history.parse_utc(row["device_time"])).total_seconds()
        health = Health(
            age_s=round(age, 1),
            stale=age > STALE_AFTER_S,
            stale_after_s=STALE_AFTER_S,
            boot_id=history.boot_id(row["reading_id"]),
            uptime_s=row["uptime_ms"] // 1000,
            expected_24h=EXPECTED_24H,
            clock_synced=row["device_time"] is not None,
            clock_offset_s=None if offset is None else round(offset, 1),
            rssi_dbm=row["rssi_dbm"],
            bme280=row["bme280"],
            **activity,
        )
    return Current(
        station_id=station,
        now=utc_text(now),
        timezone=state.timezone.key,
        reading=reading,
        derived=metrics,
        rain=RainTotals(**rain),
        health=health,
    )


@router.get("/series", responses={422: {"description": "Invalid range"}})
async def series(
    request: Request,
    station: Station = "station-1",
    start: RangeStart = None,
    end: RangeEnd = None,
) -> Series:
    """Readings over a range, downsampled to at most 400 buckets, with gaps marked."""
    start, end = resolve_range(start, end)
    bucket_s = history.bucket_for(end - start)
    points = await query(history.series, request.app.state.db_path, station, start, end, bucket_s)
    return Series(
        station_id=station,
        start=utc_text(start),
        end=utc_text(end),
        bucket_s=bucket_s,
        points=points,
    )


@router.get("/wind", responses={422: {"description": "Invalid range"}})
async def wind(
    request: Request,
    station: Station = "station-1",
    start: RangeStart = None,
    end: RangeEnd = None,
) -> WindRose:
    """Wind rose: readings counted by direction sector and average-speed class."""
    start, end = resolve_range(start, end)
    rose = await query(history.wind_rose, request.app.state.db_path, station, start, end)
    return WindRose(station_id=station, start=utc_text(start), end=utc_text(end), **rose)


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 1)
