from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from weather_station_server.config import (
    ALTITUDE_ENV_VAR,
    DASHBOARD_DIR_ENV_VAR,
    DEFAULT_DASHBOARD_DIR,
    INGEST_TOKEN_ENV_VAR,
    TIMEZONE_ENV_VAR,
    ConfigError,
    MissingConfigError,
    load_altitude,
    load_dashboard_dir,
    load_ingest_token,
    load_timezone,
)
from weather_station_server.main import app


def test_load_ingest_token_returns_configured_value() -> None:
    """A configured token is returned unchanged."""
    assert load_ingest_token({INGEST_TOKEN_ENV_VAR: "abc123"}) == "abc123"


def test_load_ingest_token_missing_fails_clearly() -> None:
    """A missing token raises an error naming the env var to set."""
    with pytest.raises(MissingConfigError, match=INGEST_TOKEN_ENV_VAR):
        load_ingest_token({})


def test_load_ingest_token_blank_fails_clearly() -> None:
    """A whitespace-only token is treated as missing."""
    with pytest.raises(MissingConfigError, match=INGEST_TOKEN_ENV_VAR):
        load_ingest_token({INGEST_TOKEN_ENV_VAR: "   "})


def test_app_startup_fails_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """The service refuses to start when the ingest token is not configured."""
    monkeypatch.delenv(INGEST_TOKEN_ENV_VAR, raising=False)
    with pytest.raises(MissingConfigError, match=INGEST_TOKEN_ENV_VAR), TestClient(app):
        pass


# --- Time zone, altitude, dashboard ------------------------------------------


def test_load_timezone_from_variable(tmp_path: Path) -> None:
    zone = load_timezone({TIMEZONE_ENV_VAR: "America/Denver"}, localtime=tmp_path / "none")
    assert zone.key == "America/Denver"


def test_load_timezone_unknown_name_fails_clearly() -> None:
    with pytest.raises(ConfigError, match=TIMEZONE_ENV_VAR):
        load_timezone({TIMEZONE_ENV_VAR: "Mars/Olympus_Mons"})


def test_load_timezone_follows_host_localtime_symlink(tmp_path: Path) -> None:
    target = tmp_path / "usr/share/zoneinfo/America/Los_Angeles"
    target.parent.mkdir(parents=True)
    target.touch()
    link = tmp_path / "localtime"
    link.symlink_to(target)
    assert load_timezone({}, localtime=link).key == "America/Los_Angeles"


def test_load_timezone_defaults_to_utc(tmp_path: Path) -> None:
    assert load_timezone({}, localtime=tmp_path / "missing").key == "UTC"


def test_load_altitude() -> None:
    assert load_altitude({}) is None
    assert load_altitude({ALTITUDE_ENV_VAR: " "}) is None
    assert load_altitude({ALTITUDE_ENV_VAR: "152.5"}) == 152.5
    assert load_altitude({ALTITUDE_ENV_VAR: "-20"}) == -20


@pytest.mark.parametrize("text", ["high", "nan", "12000", "-600"])
def test_load_altitude_rejects_nonsense(text: str) -> None:
    with pytest.raises(ConfigError, match=ALTITUDE_ENV_VAR):
        load_altitude({ALTITUDE_ENV_VAR: text})


def test_load_dashboard_dir() -> None:
    assert load_dashboard_dir({}) == DEFAULT_DASHBOARD_DIR
    assert (DEFAULT_DASHBOARD_DIR / "index.html").is_file()
    assert load_dashboard_dir({DASHBOARD_DIR_ENV_VAR: "/srv/dash"}) == Path("/srv/dash")
