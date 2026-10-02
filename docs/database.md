# Database

Readings are stored in one SQLite file on the Raspberry Pi
([ADR 0001](adr/0001-local-architecture.md)). The ingest service creates the
file on startup, applying the schema in
`server/src/weather_station_server/db.py`.

- Default path: `weather.db` in the working directory.
- Override it with `WEATHER_STATION_DB_PATH`.
- On the Pi, systemd sets the path to `/var/lib/weather-station/weather.db`.

## Schema

One table, one row per five-minute reading:

```sql
CREATE TABLE readings (
    id            INTEGER PRIMARY KEY,
    station_id    TEXT    NOT NULL,
    reading_id    TEXT    NOT NULL,
    received_at   TEXT    NOT NULL,  -- server UTC, e.g. 2026-10-02T18:35:01.207Z
    device_time   TEXT,              -- station UTC (NTP); NULL = clock not synced
    uptime_ms     INTEGER NOT NULL,
    window_s      INTEGER NOT NULL,
    rain_tips     INTEGER NOT NULL,
    rain_mm       REAL    NOT NULL,
    wind_avg_kmh  REAL    NOT NULL,
    wind_peak_kmh REAL    NOT NULL,
    wind_dir_deg  REAL,              -- NULL = vane open/shorted
    temp_c        REAL,              -- NULL unless bme280 = 'ok'
    rh_pct        REAL,
    press_hpa     REAL,
    bme280        TEXT    NOT NULL,  -- ok | implausible | error
    rssi_dbm      INTEGER,
    UNIQUE (station_id, reading_id)
);
CREATE INDEX readings_station_time ON readings (station_id, received_at);
```

Notes on the design:

- **Columns match the [ingest payload](ingest-api.md)** one-to-one, plus `id`
  and `received_at`. Each measurement has its own typed column, so charts and
  queries are plain SQL.
- **Dual timestamps.** `device_time` is when the station closed the window.
  `received_at` is when the server stored it. Their difference shows clock
  drift or delivery delay. When `device_time` is NULL (the station had no NTP
  sync yet), use `received_at` as the reading's time.
- **Timestamps are ISO 8601 UTC text** with a `Z` suffix and millisecond
  precision. They are readable as stored, sort correctly as strings, and work
  with SQLite's date functions (`unixepoch(received_at)`, `date(...)`).
- **Deduplication.** `UNIQUE (station_id, reading_id)` stores a retried
  reading only once.
- **Rollback journal (SQLite's default), not WAL.** In WAL mode every reader
  must be able to write the `-shm` side file. Then Grafana, which only has
  read permission, could not open the database. A reader can briefly delay a
  write, but the 5 s busy timeout covers that at one write per five minutes.
- `PRAGMA user_version` records the schema version (currently 1). A future
  schema change updates the version and migrates from it.

## Useful queries

Latest reading:

```sql
SELECT * FROM readings ORDER BY received_at DESC LIMIT 1;
```

Hourly averages and rain for the last day:

```sql
SELECT strftime('%Y-%m-%dT%H:00Z', COALESCE(device_time, received_at)) AS hour,
       round(avg(temp_c), 1) AS temp_c,
       round(avg(rh_pct), 0) AS rh_pct,
       round(sum(rain_mm), 2) AS rain_mm,
       max(wind_peak_kmh) AS gust_kmh
FROM readings
WHERE received_at >= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-1 day')
GROUP BY hour ORDER BY hour;
```

Gaps longer than ten minutes, for the soak test:

```sql
SELECT prev, received_at,
       round((unixepoch(received_at) - unixepoch(prev)) / 60.0, 1) AS gap_min
FROM (SELECT received_at,
             lag(received_at) OVER (ORDER BY received_at) AS prev
      FROM readings)
WHERE unixepoch(received_at) - unixepoch(prev) > 600;
```

## Retention

Keep everything; nothing is deleted. One station produces 288 rows a day,
about 105,000 rows and roughly 20 MB a year, which is small for SQLite and
the Pi's storage. Revisit this only if the file grows past a few hundred
megabytes. Downsampling old rows into hourly summaries would be the first
step.

Backups are a separate, required control before outdoor deployment (M4,
nightly SQLite backup). Copy with `sqlite3 weather.db ".backup ..."`, not
`cp`, so a write in progress does not leave a torn copy.
