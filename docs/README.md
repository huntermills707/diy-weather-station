# Docs

Project documentation.

- `adr/` — architecture decision records, starting with
  [ADR 0001: local architecture](adr/0001-local-architecture.md)
- [Ingest API](ingest-api.md) — how the station submits readings
- [Read API](read-api.md) — current conditions, history, wind rose, rain
  totals, and derived metrics for the dashboard
- [Dashboard design](dashboard.md) — layout, timestamps, and how stale or
  unavailable data is shown
- [Public dashboard](public-dashboard.md) — the read-only internet copy
  through a Cloudflare Tunnel: what is published, rate limits, logging
- [Database](database.md) — SQLite schema, timestamps, retention, and
  nightly backups with the restore procedure
- [Data quality](data-quality.md) — range and stuck-sensor flags, and how
  flagged values are treated
- [Alerts](alerts.md) — offline, freeze, and backup notifications through
  ntfy on the Pi
- [Raspberry Pi setup record](raspberry-pi.md) — how the server Pi is built
- [Sensors, units, and calibration](sensors.md) — report fields and the
  one-time field calibration procedure
