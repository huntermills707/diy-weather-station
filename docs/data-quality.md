# Data quality

The server checks every reading against simple rules and **flags** suspect
values (JAE-64). It never deletes or changes them: the raw values stay stored
exactly as the station sent them. Code:
`server/src/weather_station_server/quality.py`.

## Flags

Flags are space-separated words in the reading's `quality` column
([database.md](database.md)). `''` means a clean reading. Each flag names the
field it questions:

| Flag | Field | Rule |
| ---- | ----- | ---- |
| `temp_range` | `temp_c` | Outside -30 to 50 °C (-22 to 122 °F) |
| `rh_range` | `rh_pct` | Below 1 % |
| `press_range` | `press_hpa` | Station pressure outside 850 to 1090 hPa |
| `wind_range` | `wind_avg_kmh` | Average above 150 km/h (93 mph) |
| `gust_range` | `wind_peak_kmh` | Gust above 250 km/h (155 mph) |
| `rain_range` | `rain_mm` | Faster than 200 mm/h over the window (16.7 mm in five minutes). Never flagged at 2 mm or less, so a tip or two in a short `s` window passes |
| `temp_stuck` | `temp_c` | Same value in 24 readings in a row (two hours) |
| `rh_stuck` | `rh_pct` | Same, except at 100 %: humidity really does sit at saturation in fog or rain |
| `press_stuck` | `press_hpa` | Same |

The limits are wider than any weather the station should see. They catch
sensor and wiring faults, not unusual weather. The ingest API already
rejects values outside the sensors' physical range ([ingest-api.md](ingest-api.md)),
so a flag means "possible, but not believable here". The pressure limits fit
a station below about 1,000 m; a higher station needs a lower minimum.

A stuck value is compared at full stored precision (0.01 °C, 0.1 %,
0.1 hPa). Real air never holds that still for two hours. A frozen sensor or
a firmware bug that repeats an old value does.

## When the rules run

- **At ingest.** The server flags each reading as it stores it. The stuck
  rule compares it with the 23 readings **before it in time**, not the last
  ones to arrive, so a backfilled reading is judged by its neighbours.
  Readings already stored after it are not re-checked.
- **On upgrade.** The schema migration to version 2 runs the rules over
  every reading already stored.

## How flags are used

| Where | Effect |
| ----- | ------ |
| `GET /api/current` | `reading.quality` lists the latest reading's flags; the raw values are still returned. A derived value (dew point, heat index, sea-level pressure) is `null` if any of its inputs is flagged. `health.flagged_24h` counts flagged readings in the last 24 hours |
| `GET /api/series` | A flagged field is left out of its bucket's average, min, max, or total, the same as a missing value. Each point's `flagged` counts the readings in it with any flag |
| Rain totals | Flagged rain is not added |
| `GET /api/wind` | A reading with a flagged average speed counts in `flagged`, not a sector |
| Freeze alert | Ignores a flagged temperature ([alerts.md](alerts.md)) |
| Dashboard | The card shows the value with "Suspect: outside plausible range" or "Suspect: unchanged for 2 h" in amber. Health shows readings flagged in 24 h. Chart tooltips say how many flagged readings were left out |

## Finding flagged readings

```sql
SELECT COALESCE(device_time, received_at) AS time, reading_id, quality,
       temp_c, rh_pct, press_hpa, wind_avg_kmh, wind_peak_kmh, rain_mm
FROM readings WHERE quality != '' ORDER BY time DESC LIMIT 50;
```

## Testing

`server/tests/test_quality.py` injects implausible and constant fixtures and
checks the flags end to end: storage (raw values kept), the read API, the
series, rain totals, and the wind rose.
