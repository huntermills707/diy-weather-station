"""Runtime configuration loaded from the environment (issue #23).

Secrets live outside version control: locally in the gitignored
``server/.env``, and on the Pi in a root-readable EnvironmentFile consumed
by systemd (ADR 0001).
"""

import os
from collections.abc import Mapping
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

INGEST_TOKEN_ENV_VAR = "WEATHER_STATION_INGEST_TOKEN"
DB_PATH_ENV_VAR = "WEATHER_STATION_DB_PATH"
DEFAULT_DB_PATH = "weather.db"
TIMEZONE_ENV_VAR = "WEATHER_STATION_TIMEZONE"
ALTITUDE_ENV_VAR = "WEATHER_STATION_ALTITUDE_M"
DASHBOARD_DIR_ENV_VAR = "WEATHER_STATION_DASHBOARD_DIR"
# The repository's dashboard/ folder: this file is server/src/weather_station_server/config.py.
DEFAULT_DASHBOARD_DIR = Path(__file__).resolve().parents[3] / "dashboard"


class ConfigError(RuntimeError):
    """Raised when configuration in the environment is unusable."""


class MissingConfigError(ConfigError):
    """Raised when required configuration is absent from the environment."""


def load_ingest_token(env: Mapping[str, str] | None = None) -> str:
    """Return the per-station ingest token, failing clearly when unset."""
    env = os.environ if env is None else env
    token = env.get(INGEST_TOKEN_ENV_VAR, "").strip()
    if not token:
        raise MissingConfigError(
            f"{INGEST_TOKEN_ENV_VAR} is not set. Copy server/.env.example to "
            "server/.env, fill in a token, and load it into the environment "
            "(or set the variable directly, or via the systemd EnvironmentFile)."
        )
    return token


def load_db_path(env: Mapping[str, str] | None = None) -> str:
    """Return the SQLite file path, defaulting to ``weather.db`` in the cwd."""
    env = os.environ if env is None else env
    return env.get(DB_PATH_ENV_VAR, "").strip() or DEFAULT_DB_PATH


def load_timezone(
    env: Mapping[str, str] | None = None, localtime: Path = Path("/etc/localtime")
) -> ZoneInfo:
    """Return the zone that daily and monthly rain totals use.

    ``WEATHER_STATION_TIMEZONE`` (an IANA name) if set, else the host's zone
    (the ``/etc/localtime`` symlink, as on Debian), else UTC.
    """
    env = os.environ if env is None else env
    name = env.get(TIMEZONE_ENV_VAR, "").strip()
    if name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ConfigError(f"{TIMEZONE_ENV_VAR}={name!r} is not a known time zone") from exc
    target = str(localtime.resolve()) if localtime.is_symlink() else ""
    _, found, host_name = target.partition("/zoneinfo/")
    if found:
        try:
            return ZoneInfo(host_name)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return ZoneInfo("UTC")


def load_altitude(env: Mapping[str, str] | None = None) -> float | None:
    """Return the station altitude in metres, or None when it is not configured."""
    env = os.environ if env is None else env
    text = env.get(ALTITUDE_ENV_VAR, "").strip()
    if not text:
        return None
    try:
        altitude = float(text)
    except ValueError:
        altitude = float("nan")
    if not -500 <= altitude <= 9000:
        raise ConfigError(f"{ALTITUDE_ENV_VAR}={text!r} must be metres above sea level")
    return altitude


def load_dashboard_dir(env: Mapping[str, str] | None = None) -> Path:
    """Return the folder of static dashboard files served at ``/``."""
    env = os.environ if env is None else env
    text = env.get(DASHBOARD_DIR_ENV_VAR, "").strip()
    return Path(text) if text else DEFAULT_DASHBOARD_DIR


BACKUP_DIR_ENV_VAR = "WEATHER_STATION_BACKUP_DIR"
DEFAULT_BACKUP_DIR = "backups"
NTFY_URL_ENV_VAR = "WEATHER_STATION_NTFY_URL"
STATION_ENV_VAR = "WEATHER_STATION_STATION_ID"
DEFAULT_STATION = "station-1"
ALERT_STATE_ENV_VAR = "WEATHER_STATION_ALERT_STATE"


def load_backup_dir(env: Mapping[str, str] | None = None) -> Path:
    """Return the folder nightly backups go to (docs/database.md, "Backups")."""
    env = os.environ if env is None else env
    return Path(env.get(BACKUP_DIR_ENV_VAR, "").strip() or DEFAULT_BACKUP_DIR)


def load_ntfy_url(env: Mapping[str, str] | None = None) -> str | None:
    """Return the ntfy topic URL alerts are posted to, or None to only log them."""
    env = os.environ if env is None else env
    url = env.get(NTFY_URL_ENV_VAR, "").strip()
    if url and not url.startswith(("http://", "https://")):
        raise ConfigError(f"{NTFY_URL_ENV_VAR}={url!r} must be an http:// or https:// URL")
    return url or None


def load_station(env: Mapping[str, str] | None = None) -> str:
    """Return the station the alert checker watches."""
    env = os.environ if env is None else env
    return env.get(STATION_ENV_VAR, "").strip() or DEFAULT_STATION


def load_alert_state_path(env: Mapping[str, str] | None = None) -> Path:
    """Return the alert checker's state file; defaults to beside the database."""
    env = os.environ if env is None else env
    text = env.get(ALERT_STATE_ENV_VAR, "").strip()
    return Path(text) if text else Path(load_db_path(env)).parent / "alerts.json"
