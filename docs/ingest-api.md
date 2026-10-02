# Ingest API

How the station submits readings to the server on the Raspberry Pi
([ADR 0001](adr/0001-local-architecture.md)). The station sends one reading
every five minutes. The API is reachable only on the LAN: nothing forwards it
to the internet.

## `POST /readings`

### Authentication

Every request needs the station's pre-shared token:

```
Authorization: Bearer <token>
```

The token is `INGEST_TOKEN` in `firmware/secrets.h` on the station and
`WEATHER_STATION_INGEST_TOKEN` on the server. A missing, malformed, or wrong
token gets `401` **before** the body is parsed or stored, so an
unauthenticated client cannot learn anything from validation errors.

### Request body

`Content-Type: application/json`. Field units match the serial `report` line
([sensors.md](sensors.md)). Fields marked "or null" describe a sensor state
that has no valid number. The station sends `null` and never a fake value.

| Field | Type | Rules | Meaning |
| ----- | ---- | ----- | ------- |
| `station_id` | string | 1-64 chars, `[A-Za-z0-9_-]` | Which station sent it |
| `reading_id` | string | 1-64 chars, `[A-Za-z0-9_-]` | Device-generated ID, the same on every retry (see below) |
| `device_time` | string or null | ISO 8601 with a UTC offset | When the window closed, by the station's NTP clock. `null` = clock not synced yet |
| `uptime_ms` | integer | ≥ 0 | Station uptime when the window closed. Detects reboots |
| `window_s` | integer | 1-3600 | Length of the window that the rain and wind counts cover |
| `rain_tips` | integer | ≥ 0 | Bucket tips in the window |
| `rain_mm` | number | ≥ 0 | `rain_tips × RAIN_MM_PER_TIP` |
| `wind_avg_kmh` | number | 0-300 | Average wind speed over the window |
| `wind_peak_kmh` | number | 0-300 | Gust: the shortest gap between two closures |
| `wind_dir_deg` | number or null | 0 ≤ x < 360 | Vane heading. `null` = vane open or shorted |
| `temp_c` | number or null | -40 to 85 | BME280 temperature |
| `rh_pct` | number or null | 0-100 | BME280 relative humidity |
| `press_hpa` | number or null | 300-1100 | BME280 station pressure |
| `bme280` | string | `ok`, `implausible`, `error` | Sensor status. The three BME280 numbers must be present exactly when this is `ok` |
| `rssi_dbm` | integer or null | -127 to 0 | WiFi signal strength when the reading was sent |

Unknown fields are rejected, so a typo cannot silently drop data.

Example:

```json
{
  "station_id": "station-1",
  "reading_id": "3f9a1c07-42",
  "device_time": "2026-10-02T18:35:00Z",
  "uptime_ms": 12600417,
  "window_s": 300,
  "rain_tips": 3,
  "rain_mm": 0.84,
  "wind_avg_kmh": 7.2,
  "wind_peak_kmh": 19.2,
  "wind_dir_deg": 225.0,
  "temp_c": 18.42,
  "rh_pct": 61.5,
  "press_hpa": 1004.2,
  "bme280": "ok",
  "rssi_dbm": -63
}
```

### Reading IDs and duplicates

The station creates `reading_id` once, when it takes the reading, as
`<boot_id>-<seq>`:

- `boot_id` is 8 hex digits, random on each boot.
- `seq` counts readings since boot, starting at 1.

Every retry of that reading sends the same ID. The server enforces uniqueness
on `(station_id, reading_id)`. If a reading arrives a second time, the server
answers `200` with the stored row and stores nothing new. This happens when a
response is lost and the station retries. The station treats `200` and `201`
the same: the reading is delivered.

Because IDs are sequential, a gap in `seq` within one `boot_id` means a lost
reading, and a new `boot_id` means the station rebooted.

### Responses

| Status | When | Body |
| ------ | ---- | ---- |
| `201 Created` | New reading stored | `{"id": 123, "station_id": "...", "reading_id": "...", "received_at": "...", "duplicate": false}` |
| `200 OK` | `(station_id, reading_id)` already stored | Same shape with the **original** `id` and `received_at`, and `"duplicate": true` |
| `401 Unauthorized` | Token missing or wrong | `{"detail": "..."}` with a `WWW-Authenticate: Bearer` header |
| `422 Unprocessable Entity` | Body is not valid JSON, or fails the rules above | `{"detail": [...]}`, FastAPI's standard error list naming each bad field |
| `503 Service Unavailable` | The database could not be written | `{"detail": "..."}`. The station should retry later with the same `reading_id` |

`received_at` is the server's UTC clock when the reading was first stored.
The server keeps it alongside `device_time` (see [database.md](database.md)).

## `GET /health`

No authentication. Returns `200 {"status": "ok"}` when the service is running
and can read its database. Returns `503 {"status": "error", "detail": "..."}`
when it cannot.
