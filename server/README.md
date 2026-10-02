# Server

FastAPI ingest service running on a Raspberry Pi on the local network.

Responsibilities:

- Accept authenticated five-minute readings from the ESP32 over LAN-only HTTP
- Validate payloads and store device + server timestamps in SQLite
- Expose defined errors and a health endpoint
- Run under systemd as a non-root user with journald logging

The API is documented in [docs/ingest-api.md](../docs/ingest-api.md) and the
SQLite schema in [docs/database.md](../docs/database.md). Interactive API docs
are served at `/docs` while the service runs.

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
exact environment. On the Raspberry Pi the service runs under systemd as a
non-root user with journald logging: see [deploy/README.md](deploy/README.md).

## Configuration

Secrets are read from the environment and never committed (issue #23). The
service refuses to start without them:

- `WEATHER_STATION_INGEST_TOKEN` — per-station pre-shared token that
  stations send as `Authorization: Bearer` (ADR 0001). Must match
  `INGEST_TOKEN` in the station's `firmware/secrets.h`.

Optional:

- `WEATHER_STATION_DB_PATH` — SQLite file for readings; defaults to
  `weather.db` in the working directory. Created on startup if missing.

For local development, copy `.env.example` to `.env` (gitignored), fill in a
token, and load it before starting the service:

```sh
cp .env.example .env   # then edit .env
set -a; . ./.env; set +a
```

On the Pi, the same variables live in a root-readable `EnvironmentFile`
referenced by the systemd unit (ADR 0001) instead of `.env`.

## CI

The `Python` GitHub Actions workflow runs on every pull request and on
pushes to `main` that touch `server/`: `uv sync --locked`, `ruff check`,
`ruff format --check`, and `pytest`.
