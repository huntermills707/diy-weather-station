# Read API

How the dashboard reads stored readings from the server on the Raspberry Pi.
The same service that runs the [ingest API](ingest-api.md) serves these
endpoints. They are read-only: they open the database read-only and never
change it.

No authentication, like `GET /health`. The API is reachable only on the LAN
([ADR 0001](adr/0001-local-architecture.md)). The same three endpoints are
also published on the internet, rate limited, by the separate
[public dashboard](public-dashboard.md) app.

The service also serves interactive docs with the exact response schemas at
`/docs`.

## Common parameters

| Parameter | Default | Rules |
| --------- | ------- | ----- |
| `station` | `station-1` | 1-64 chars, `[A-Za-z0-9_-]` |
| `start` | `end` minus 24 hours | ISO 8601 **with a UTC offset**, inclusive |
| `end` | now | ISO 8601 **with a UTC offset**, exclusive |

`start` and `end` apply to `/api/series` and `/api/wind`. A range is
rejected with `422` and a message in `detail` when:

- `start` is not before `end` (`"start must be before end"`)
- it is longer than 366 days (`"range is longer than the 366-day maximum"`)
- a time has no UTC offset, or isn't a date at all (FastAPI's standard
  error list naming the parameter)

A range with no readings is not an error: it returns empty results.

**Reading time.** Every endpoint places a reading at its `device_time` (when
the station closed the window), or at `received_at` if the station's clock
was not synced yet ([database.md](database.md)). So a reading that arrives
late still lands where it belongs in time.

All responses can also be `503 {"detail": "Database unavailable"}` when the
database cannot be read.

## `GET /api/current`

The latest reading, with derived metrics, rain totals, and station health.

```json
{
  "station_id": "station-1",
  "now": "2026-10-03T23:12:22.651Z",
  "timezone": "America/Los_Angeles",
  "reading": {
    "time": "2026-10-03T22:47:38.000Z",
    "received_at": "2026-10-03T22:47:38.936Z",
    "device_time": "2026-10-03T22:47:38.000Z",
    "reading_id": "46150aed-298",
    "uptime_ms": 88824814,
    "window_s": 300,
    "rain_tips": 0,
    "rain_mm": 0.0,
    "wind_avg_kmh": 0.0,
    "wind_peak_kmh": 0.0,
    "wind_dir_deg": 45.0,
    "wind_dir_label": "NE",
    "temp_c": 30.73,
    "rh_pct": 35.7,
    "press_hpa": 1005.1,
    "bme280": "ok",
    "rssi_dbm": -66,
    "boot_count": 12,
    "reset_reason": "power_on",
    "queue_dropped": 0,
    "quality": []
  },
  "derived": {
    "dew_point_c": 13.8,
    "heat_index_c": 30.0,
    "sea_level_hpa": 1010.8,
    "altitude_m": 50.0
  },
  "rain": { "last_hour_mm": 0.0, "last_24h_mm": 0.0, "today_mm": 0.0, "month_mm": 1.68 },
  "health": {
    "age_s": 1483.7,
    "stale": true,
    "stale_after_s": 660,
    "boot_id": "46150aed",
    "uptime_s": 88824,
    "readings_24h": 278,
    "expected_24h": 288,
    "boots_24h": 1,
    "flagged_24h": 0,
    "clock_synced": true,
    "clock_offset_s": 0.9,
    "rssi_dbm": -66,
    "bme280": "ok"
  }
}
```

- `reading` has the stored columns ([database.md](database.md)) plus `time`
  (the reading time above) and `wind_dir_label`, the 16-point compass name
  of the heading (`null` when the vane reads unknown). `quality` is a list
  of [data-quality flags](data-quality.md), empty for a clean reading.
  Flagged values are still returned as stored.
- `reading`, `derived`, and `health` are `null` when the station has no
  readings yet. `rain` is always present.
- `health.age_s` is the time since the server received the latest reading.
  `stale` is true once that passes `stale_after_s` (660 s: two five-minute
  cadences plus a minute of slack). One missed reading is not stale; a
  second late one is.
- `readings_24h` and `boots_24h` count readings and distinct boot IDs in the
  last 24 hours. More than one boot means the station rebooted.
  `flagged_24h` counts readings with any quality flag.
- `clock_offset_s` is `received_at` minus `device_time`: clock offset plus
  delivery delay. `null` while the clock is unsynced.

### Rain totals

| Total | Period |
| ----- | ------ |
| `last_hour_mm` | Readings in the last 60 minutes |
| `last_24h_mm` | Readings in the last 24 hours |
| `today_mm` | Readings since local midnight |
| `month_mm` | Readings since local midnight on the 1st |

Each reading's `rain_mm` covers only its own window, counted from zero
([sensors.md](sensors.md)). Summing the windows gives the cumulative total,
and it is reboot-safe: a reboot only starts a new window, so a total can
never go negative or count tips twice. The station's own since-boot counter
(`rain_total`) is not used. A retried reading is stored once (unique
`reading_id`), so it is never added twice. Tips during the reboot itself,
before the new window starts, are not counted.
Rain [flagged](data-quality.md) as implausible is not added.

**Time zone.** Days and months follow `timezone` in the response: the
`WEATHER_STATION_TIMEZONE` setting, else the server's own zone (the Pi's is
America/Los_Angeles), else UTC. A reading counts in the period its window
**ends** in; one ending exactly at midnight belongs to the day before. A
window that spans midnight counts entirely in the day it ends in, so up to
five minutes of rain can land on the wrong side of midnight.

### Derived metrics

Every derived value is `null` when any of its inputs is `null` (for example
`bme280` is `error`) or [flagged](data-quality.md), so a failed sensor never
produces a made-up number.
Code: `server/src/weather_station_server/derived.py`.

**Dew point:** the Magnus formula with the Alduchov and Eskridge (1996)
coefficients, accurate to about 0.4 °C between -40 and 50 °C:

```
γ  = ln(RH / 100) + a·T / (b + T)        a = 17.625, b = 243.04 °C
Td = b·γ / (a − γ)
```

**Heat index:** the US National Weather Service algorithm
([NWS](https://www.wpc.ncep.noaa.gov/html/heatindex_equation.shtml)),
computed in °F and returned in °C. Steadman's simple formula first. If that
averages 80 °F or more with the air temperature, the Rothfusz regression
with the NWS adjustments for low humidity (< 13 %) and high humidity
(> 85 %) instead. Tested against the NWS heat index chart. In mild weather
the result is close to the air temperature; the dashboard shows it only at
26.7 °C (80 °F) and above.

**Sea-level pressure:** station pressure reduced with the barometric
formula, assuming the standard lapse rate of 6.5 °C/km below the station:

```
P0 = P · (1 − 0.0065·h / (T + 0.0065·h + 273.15)) ^ −5.257
```

`h` is the station altitude in metres from `WEATHER_STATION_ALTITUDE_M`.
Without that setting `sea_level_hpa` is `null`; the altitude is echoed as
`altitude_m`. Indoors the measured temperature isn't the outdoor air's, so
expect a small error until the station is outside.

## `GET /api/series`

Readings over a range, downsampled on the server.

```json
{
  "station_id": "station-1",
  "start": "2026-10-02T22:00:00.000Z",
  "end": "2026-10-03T23:00:00.000Z",
  "bucket_s": 300,
  "points": [
    {
      "time": "2026-10-02T22:12:39.000Z",
      "n": 1,
      "flagged": 0,
      "temp_c": 30.58, "temp_min_c": 30.58, "temp_max_c": 30.58,
      "rh_pct": 30.9,
      "press_hpa": 1007.0,
      "wind_avg_kmh": 0.0,
      "wind_peak_kmh": 0.0,
      "rain_mm": 0.0
    }
  ]
}
```

**Downsampling.** Readings are grouped into buckets of `bucket_s` seconds.
The server picks the smallest size from 5 min, 10 min, 15 min, 30 min, 1 h,
2 h, 3 h, 6 h, 12 h, 1 day that keeps the range within 400 buckets:

| Range | Bucket | Points at most |
| ----- | ------ | -------------- |
| 24 hours | 5 min (one reading each) | 288 |
| 7 days | 30 min | 336 |
| 30 days | 2 h | 360 |
| 366 days (maximum) | 1 day | 366 |

Buckets are aligned to whole multiples of `bucket_s` since 1970 (UTC). Each
point has:

- `time`: the mean time of the readings in the bucket
- `n`: how many readings it holds
- the averages of `temp_c`, `rh_pct`, `press_hpa`, and `wind_avg_kmh`; the
  lowest and highest temperature (`temp_min_c`, `temp_max_c`); the highest
  gust (`wind_peak_kmh`); and the total `rain_mm`

Missing sensor values are left out of the averages, and so are
[flagged](data-quality.md) ones. If a bucket has no valid value for a field,
that field is `null`. `flagged` counts the bucket's readings with any flag.

**Gaps stay gaps.** Only buckets with readings are returned. Where no
reading arrived for longer than one bucket plus half a cadence, a **gap
marker** sits between the two points around it: `n` is `0` and every value
is `null`. Charts break the line there instead of drawing across the
missing data. The quiet time is measured between actual readings, not bucket
means. So at the 5-minute bucket, one missed reading is a gap. But a
reading that arrives a second early or late (two readings in one bucket,
none in the next) is not. At larger buckets a gap needs more than a bucket
of silence: a 10-minute outage is invisible at 2-hour resolution.

## `GET /api/wind`

A wind rose: readings counted by direction and average speed.

```json
{
  "station_id": "station-1",
  "start": "...", "end": "...",
  "total": 2016,
  "calm": 361,
  "unknown": 16,
  "flagged": 0,
  "calm_below_kmh": 2.0,
  "speed_classes_kmh": [2.0, 10.0, 20.0, 30.0],
  "sectors": [
    { "label": "N", "direction_deg": 0.0, "counts": [12, 4, 0, 0] },
    { "label": "NNE", "direction_deg": 22.5, "counts": [3, 1, 0, 0] }
  ]
}
```

Each reading in the range goes into exactly one of four places:

1. **`flagged`**: the average speed is [flagged](data-quality.md) as
   implausible.
2. **`unknown`**: the vane read open or shorted (`wind_dir_deg` is null).
   These are never put in a direction, whatever the speed.
3. **`calm`**: a heading but an average below 2 km/h (about 1 knot, the WMO
   calm limit). In still air the vane just keeps its last position, so its
   heading means nothing.
4. **A sector**: one of 16 sectors of 22.5°, centred on N, NNE, NE, … (the
   vane's own 16 headings). A heading exactly on a boundary goes to the
   clockwise sector. Inside the sector, `counts[i]` counts readings whose
   average speed is at least `speed_classes_kmh[i]` and below the next edge
   (2-10, 10-20, 20-30, 30+ km/h).

So `total = flagged + calm + unknown + the sum of every sector's counts`.
