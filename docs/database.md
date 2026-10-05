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
    boot_count    INTEGER,           -- NULL from firmware before M4
    reset_reason  TEXT,
    queue_dropped INTEGER,
    quality       TEXT    NOT NULL DEFAULT '',  -- data-quality flags, '' = clean
    UNIQUE (station_id, reading_id)
);
CREATE INDEX readings_station_time ON readings (station_id, received_at);
CREATE INDEX readings_station_reading_time
    ON readings (station_id, COALESCE(device_time, received_at));
```

Notes on the design:

- **Columns match the [ingest payload](ingest-api.md)** one-to-one, plus `id`,
  `received_at`, and `quality`. Each measurement has its own typed column, so charts and
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
- **Backfill.** Readings the station queued during an outage arrive late and
  out of order. They are stored with their own `device_time`, and every read
  query orders by reading time, so they land where they belong.
- **Quality flags.** `quality` holds the [data-quality](data-quality.md)
  flags set at ingest, space-separated. Raw values are never changed.
- **Rollback journal (SQLite's default), not WAL.** In WAL mode every reader
  must be able to write the `-shm` side file. Then Grafana, which only has
  read permission, could not open the database. A reader can briefly delay a
  write, but the 5 s busy timeout covers that at one write per five minutes.
- **Indexes are the time-ordered lookup.** Both are B-trees sorted by
  station and time, so a range ("rain in the last 24 hours") reads only the
  rows in that range. `readings_station_time` serves arrival-time queries
  such as the soak report. `readings_station_reading_time` serves the
  [read API](read-api.md), which places readings at their reading time.
  Measured on 10 years of synthetic readings (1 million rows): the rain
  totals query took 106 ms scanning every row and 0.3 ms with this index.
  No running total or daily summary table is kept. Either would need
  rewriting whenever a late reading arrives (backfill), and the index
  already makes sums over a range cheap.
- `PRAGMA user_version` records the schema version (currently 2). On
  startup the service migrates an older file in one transaction. Version 1
  to 2 (M4) adds `boot_count`, `reset_reason`, `queue_dropped`, and
  `quality`, then runs the quality rules over every stored reading. Adding an
  index does not change the version: `CREATE INDEX IF NOT EXISTS` runs on
  every startup, and older code still reads the file. A server older than
  the file refuses to start.

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

## Backups

A nightly backup (JAE-63) copies the database with SQLite's online backup
API, so a reading stored mid-copy cannot leave a torn file. Never back up
with `cp` while the service runs.

| | |
| - | - |
| When | 03:17 every night (`weather-station-backup.timer`); at the next boot if the Pi was off then |
| Where | `/var/backups/weather-station/weather-<UTC time>.db` on the Pi (`WEATHER_STATION_BACKUP_DIR`) |
| Kept | The newest 30; older ones are deleted after each backup |
| Checks | `PRAGMA integrity_check` on the copy before it gets its final name. A failed backup leaves no file |
| Failures | Logged to the journal (`journalctl -u weather-station-backup`), and the unit shows as failed. The [backup alert](alerts.md) fires when the newest backup is over 26 hours old |

Code: `server/src/weather_station_server/backup.py`. Each copy is a complete,
ordinary SQLite file, about the size of the database.

The backups live on the Pi's own drive, in a separate folder from the
database. They protect against a bad write, a mistaken delete, or a corrupt
file, but not against losing the Pi or its drive. Copying them off the Pi
is a later step.

Run a backup now:

```sh
sudo systemctl start weather-station-backup
journalctl -u weather-station-backup -n 5   # "backup: wrote ... (N readings, ...)"
```

### Restore

Test a backup without touching the live database:

```sh
cp /var/backups/weather-station/weather-<time>.db /tmp/restore-test.db
sqlite3 /tmp/restore-test.db 'PRAGMA integrity_check'   # ok
sqlite3 /tmp/restore-test.db \
  'SELECT count(*), max(COALESCE(device_time, received_at)) FROM readings'
```

Replace the live database:

```sh
sudo systemctl stop weather-station weather-station-alerts
sudo install -o weather-station -g weather-station -m 0640 \
  /var/backups/weather-station/weather-<time>.db /var/lib/weather-station/weather.db
sudo rm -f /var/lib/weather-station/weather.db-journal
sudo systemctl start weather-station weather-station-alerts
curl -s localhost:8000/api/current   # latest reading is the backup's newest
```

Readings since the backup are lost unless the station still has them
queued. `server/tests/test_backup.py` restores a backup into a clean file
and queries it.
