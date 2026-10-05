"""Data-quality rules (docs/data-quality.md, JAE-64).

A rule only flags a reading. The raw values stay stored exactly as the station
sent them. Flags are words in the ``quality`` column, ``''`` for a clean
reading. Every flag starts with the prefix of the field it questions
(FIELD_PREFIXES), so read queries can leave just that field out of averages
and totals.
"""

from collections.abc import Mapping, Sequence
from typing import Any

# Plausible limits, wider than any weather the station should see. Pressure is
# station pressure, so the lower limit suits a station below about 1,000 m.
RANGES = {
    "temp_c": ("temp_range", -30.0, 50.0),
    "rh_pct": ("rh_range", 1.0, 100.0),
    "press_hpa": ("press_range", 850.0, 1090.0),
    "wind_avg_kmh": ("wind_range", 0.0, 150.0),
    "wind_peak_kmh": ("gust_range", 0.0, 250.0),
}
# Rain above this rate is flagged. The floor keeps a tip or two in a short
# window (an `s` report right after another) from looking like a cloudburst.
RAIN_MAX_MM_PER_H = 200.0
RAIN_MIN_LIMIT_MM = 2.0

# A value identical in this many consecutive readings (two hours) is stuck.
STUCK_READINGS = 24
STUCK_FIELDS = {"temp_c": "temp_stuck", "rh_pct": "rh_stuck", "press_hpa": "press_stuck"}

FIELD_PREFIXES = {
    "temp_c": "temp_",
    "rh_pct": "rh_",
    "press_hpa": "press_",
    "wind_avg_kmh": "wind_",
    "wind_peak_kmh": "gust_",
    "rain_mm": "rain_",
}


def evaluate(reading: Mapping[str, Any], previous: Sequence[Mapping[str, Any]]) -> list[str]:
    """Flags for one reading.

    ``previous`` holds the station's readings just before this one in time,
    newest first; only the first STUCK_READINGS - 1 are used.
    """
    flags = []
    for name, (flag, low, high) in RANGES.items():
        value = reading[name]
        if value is not None and not low <= value <= high:
            flags.append(flag)

    rain_limit = max(RAIN_MIN_LIMIT_MM, RAIN_MAX_MM_PER_H * reading["window_s"] / 3600)
    if reading["rain_mm"] > rain_limit:
        flags.append("rain_range")

    window = previous[: STUCK_READINGS - 1]
    if len(window) == STUCK_READINGS - 1:
        for name, flag in STUCK_FIELDS.items():
            value = reading[name]
            # Humidity legitimately sits at 100 % in fog or rain.
            if value is None or (name == "rh_pct" and value >= 100):
                continue
            if all(row[name] == value for row in window):
                flags.append(flag)
    return flags


def is_flagged(quality: str, field: str) -> bool:
    """True when any flag in a ``quality`` string questions ``field``."""
    prefix = FIELD_PREFIXES[field]
    return any(flag.startswith(prefix) for flag in quality.split())


def usable_sql(field: str) -> str:
    """SQL for a column's value, or NULL when the reading flags that field."""
    return f"CASE WHEN instr(quality, '{FIELD_PREFIXES[field]}') = 0 THEN {field} END"
