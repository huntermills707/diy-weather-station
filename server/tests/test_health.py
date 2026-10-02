from pathlib import Path

from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    """The health endpoint returns 200 with an ok status payload."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_reports_unreadable_database(client: TestClient, db_path: Path) -> None:
    """A missing readings table (or broken file) turns health into a 503."""
    db_path.unlink()
    response = client.get("/health")
    assert response.status_code == 503
    # Generic message only: SQLite's error text stays in the server log.
    assert response.json() == {"status": "error", "detail": "Database unavailable"}


def test_startup_creates_database(client: TestClient, db_path: Path) -> None:
    assert db_path.exists()
