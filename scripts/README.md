# Scripts

Utility scripts for the project.

- `serial_capture.py` — capture station serial output with host UTC
  timestamps, optionally sending commands (`s` report, `c` calibration
  stream). Run with `uv run --with pyserial scripts/serial_capture.py --help`.

Planned contents:

- Raspberry Pi provisioning (SSH keys, fixed LAN addressing, time sync,
  security updates)
- Nightly SQLite backup
- Data export for analysis notebooks
