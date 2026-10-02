import pytest
from fastapi.testclient import TestClient

from weather_station_server.config import (
    INGEST_TOKEN_ENV_VAR,
    MissingConfigError,
    load_ingest_token,
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
