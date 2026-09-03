# Server

FastAPI ingest service running on a Raspberry Pi on the local network.

Responsibilities:

- Accept authenticated five-minute readings from the ESP32 over LAN-only HTTP
- Validate payloads and store device + server timestamps in SQLite
- Expose defined errors and a health endpoint
- Run under systemd as a non-root user with journald logging

Tooling: `uv` for environment/dependencies, `ruff` for lint, `pytest` for tests.
