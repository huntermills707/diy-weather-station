# Server

FastAPI ingest service running on a Raspberry Pi on the local network.

Responsibilities:

- Accept authenticated five-minute readings from the ESP32 over LAN-only HTTP
- Validate payloads and store device + server timestamps in SQLite
- Expose defined errors and a health endpoint
- Serve a read API and the local dashboard (`dashboard/`, at `/`)
- Flag implausible and stuck values ([docs/data-quality.md](../docs/data-quality.md))
- Back up the database nightly (`python -m weather_station_server.backup`,
  [docs/database.md](../docs/database.md#backups))
- Send local alerts through ntfy (`python -m weather_station_server.alerts`,
  [docs/alerts.md](../docs/alerts.md))
- Run under systemd as a non-root user with journald logging

The APIs are documented in [docs/ingest-api.md](../docs/ingest-api.md) and
[docs/read-api.md](../docs/read-api.md), and the SQLite schema in [docs/database.md](../docs/database.md). Interactive API docs
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
- `WEATHER_STATION_ALTITUDE_M` — station altitude in metres, for sea-level
  pressure. Unset, sea-level pressure is unavailable.
- `WEATHER_STATION_TIMEZONE` — IANA zone (e.g. `America/Los_Angeles`) for
  daily and monthly rain totals; defaults to the host's zone, else UTC.
- `WEATHER_STATION_DASHBOARD_DIR` — folder served at `/`; defaults to the
  repository's `dashboard/`.
- `WEATHER_STATION_BACKUP_DIR` — where backups go and where the backup alert
  looks; defaults to `backups` in the working directory.
- `WEATHER_STATION_NTFY_URL` — ntfy topic URL for alerts, e.g.
  `http://localhost/weather`. Unset, alerts only go to the log.
- `WEATHER_STATION_STATION_ID` — the station the alerts watch; defaults to
  `station-1`.
- `WEATHER_STATION_ALERT_STATE` — the alerts' state file; defaults to
  `alerts.json` beside the database.

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
