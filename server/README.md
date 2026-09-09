# Server

FastAPI ingest service running on a Raspberry Pi on the local network.

Responsibilities:

- Accept authenticated five-minute readings from the ESP32 over LAN-only HTTP
- Validate payloads and store device + server timestamps in SQLite
- Expose defined errors and a health endpoint
- Run under systemd as a non-root user with journald logging

Tooling: `uv` for environment/dependencies, `ruff` for lint, `pytest` for tests.

## Setup

Requires [uv](https://docs.astral.sh/uv/). From this directory:

```sh
uv sync                      # create the venv and install locked dependencies
uv run ruff check .          # lint
uv run ruff format .         # format
uv run pytest                # tests
uv run uvicorn weather_station_server.main:app --reload  # dev server
```

`uv.lock` is committed — use `uv sync --locked` (as CI does) to reproduce the
exact environment. On the Raspberry Pi, run the service under systemd as a
non-root user with journald logging.

## CI

The `Python` GitHub Actions workflow runs on pushes to `main` and on pull
requests that touch `server/`: `uv sync --locked`, `ruff check`,
`ruff format --check`, and `pytest`.
