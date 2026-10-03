# Docs

Project documentation.

- `adr/` — architecture decision records, starting with
  [ADR 0001: local architecture](adr/0001-local-architecture.md)
- [Ingest API](ingest-api.md) — how the station submits readings
- [Read API](read-api.md) — current conditions, history, wind rose, rain
  totals, and derived metrics for the dashboard
- [Dashboard design](dashboard.md) — layout, timestamps, and how stale or
  unavailable data is shown
- [Database](database.md) — SQLite schema, timestamps, and retention
- [Raspberry Pi setup record](raspberry-pi.md) — how the server Pi is built
- [Sensors, units, and calibration](sensors.md) — report fields and the
  one-time field calibration procedure
