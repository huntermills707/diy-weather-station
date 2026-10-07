import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from conftest import TOKEN, make_reading
from fastapi.testclient import TestClient

from weather_station_server import public
from weather_station_server.config import INGEST_TOKEN_ENV_VAR
from weather_station_server.db import init_db


@pytest.fixture
def public_client(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """The public app, started without the ingest token, over an empty database."""
    init_db(str(db_path))
    monkeypatch.delenv(INGEST_TOKEN_ENV_VAR)
    monkeypatch.setattr(public.app.state, "limiter", public.RateLimiter(1000, 60))
    with TestClient(public.app) as test_client:
        yield test_client


def test_serves_dashboard_without_lan_links(public_client: TestClient) -> None:
    for path in ("/", "/index.html"):
        response = public_client.get(path)
        assert response.status_code == 200
        assert "<title>Weather station</title>" in response.text
        assert "/docs" not in response.text
        assert "grafana" not in response.text.lower()
    assert public_client.get("/app.js").status_code == 200
    assert public_client.get("/style.css").status_code == 200


def test_serves_read_api(public_client: TestClient) -> None:
    assert public_client.get("/api/series").status_code == 200
    assert public_client.get("/api/wind").status_code == 200


@pytest.mark.parametrize(
    "path", ["/health", "/docs", "/redoc", "/openapi.json", "/README.md", "/readings", "/../x"]
)
def test_other_paths_are_not_published(public_client: TestClient, path: str) -> None:
    assert public_client.get(path).status_code == 404


@pytest.mark.parametrize("path", ["/readings", "/api/current", "/"])
@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
def test_writes_are_refused(public_client: TestClient, method: str, path: str) -> None:
    response = public_client.request(
        method, path, json=make_reading(), headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert response.status_code == 405
    assert response.headers["Allow"] == "GET, HEAD"


def test_rate_limits_each_client(
    public_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(public.app.state, "limiter", public.RateLimiter(3, 60))
    alice = {"CF-Connecting-IP": "203.0.113.7"}
    for _ in range(3):
        assert public_client.get("/api/wind", headers=alice).status_code == 200
    response = public_client.get("/api/wind", headers=alice)
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "1"
    # Another visitor has their own allowance.
    bob = {"CF-Connecting-IP": "198.51.100.2"}
    assert public_client.get("/api/wind", headers=bob).status_code == 200


def test_logs_each_request(public_client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        public_client.get("/api/wind?station=x", headers={"CF-Connecting-IP": "203.0.113.7"})
    assert any(
        r.getMessage().startswith("203.0.113.7 GET /api/wind?station=x 200 ")
        for r in caplog.records
    )


def test_bucket_refills_over_time() -> None:
    limiter = public.RateLimiter(burst=2, per_minute=60)
    assert limiter.take("a", 0.0) == 0
    assert limiter.take("a", 0.0) == 0
    assert limiter.take("a", 0.0) == pytest.approx(1.0)
    assert limiter.take("a", 0.5) == pytest.approx(0.5)
    assert limiter.take("a", 1.0) == 0


def test_client_table_is_bounded() -> None:
    limiter = public.RateLimiter(burst=1, per_minute=60, max_clients=2)
    for client in ("a", "b", "c"):
        limiter.take(client, 0.0)
    assert len(limiter.buckets) <= 2
