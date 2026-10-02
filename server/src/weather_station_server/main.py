from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from weather_station_server.config import load_ingest_token


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Fail fast at startup when required secrets are missing (issue #23).
    app.state.ingest_token = load_ingest_token()
    yield


app = FastAPI(title="weather-station-server", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe for the ingest service."""
    return {"status": "ok"}
