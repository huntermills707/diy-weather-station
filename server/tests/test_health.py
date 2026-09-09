from fastapi.testclient import TestClient

from weather_station_server.main import app

client = TestClient(app)


def test_health() -> None:
    """The health endpoint returns 200 with an ok status payload."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
