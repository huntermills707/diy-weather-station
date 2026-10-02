# Scripts

Utility scripts for the project.

- `serial_capture.py` — capture station serial output with host UTC
  timestamps, optionally sending commands (`s` report, `c` calibration
  stream). Run with `uv run --with pyserial scripts/serial_capture.py --help`.
- `soak_report.py` — summarize a soak test (JAE-50) from the readings
  database: stored vs expected readings at the five-minute cadence, gaps,
  readings lost in transit, reboots, unsynced clocks, sensor errors, and
  station/server clock offset, each with a timestamp. Standard library only;
  on the Pi: `python3 scripts/soak_report.py /var/lib/weather-station/weather.db
  --since 2026-10-03T00:00:00Z --hours 24` (needs read access to the file:
  `sudo`, or membership in the `weather-station` group).

Planned contents:

- Raspberry Pi provisioning (SSH keys, fixed LAN addressing, time sync,
  security updates)
- Nightly SQLite backup
- Data export for analysis notebooks
