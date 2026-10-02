import hmac
import logging
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from weather_station_server import db
from weather_station_server.config import load_db_path, load_ingest_token
from weather_station_server.models import Reading, ReadingReceipt

# uvicorn configures its own loggers only; logging through its error logger
# puts these lines in the same stream (journald on the Pi).
log = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Fail fast at startup when required secrets are missing (issue #23).
    app.state.ingest_token = load_ingest_token()
    app.state.db_path = load_db_path()
    db.init_db(app.state.db_path)
    log.info("storing readings in %s", app.state.db_path)
    yield


app = FastAPI(title="weather-station-server", lifespan=lifespan)


def require_token(request: Request) -> None:
    """Reject requests without the station's bearer token (ADR 0001)."""
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    expected = request.app.state.ingest_token
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        token.strip().encode(), expected.encode()
    ):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )


@app.post(
    "/readings",
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": ReadingReceipt, "description": "Duplicate of a stored reading"}},
)
async def create_reading(request: Request, response: Response) -> ReadingReceipt:
    """Store one reading; a repeated reading_id returns the original row."""
    # The body is parsed by hand, after authentication: a declared body
    # parameter would be parsed (and could fail with 422) before the token
    # is checked, leaking validation details to unauthenticated clients.
    require_token(request)
    try:
        reading = Reading.model_validate_json(await request.body())
    except ValidationError as exc:
        raise RequestValidationError(exc.errors(include_url=False, include_input=False)) from exc

    try:
        receipt = await run_in_threadpool(db.store_reading, request.app.state.db_path, reading)
    except sqlite3.Error as exc:
        log.exception("failed to store reading %s", reading.reading_id)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Database unavailable") from exc

    if receipt.duplicate:
        response.status_code = status.HTTP_200_OK
        log.info("duplicate reading %s/%s", reading.station_id, reading.reading_id)
    return receipt


@app.get("/health", responses={503: {"description": "Database unavailable"}})
async def health(request: Request) -> JSONResponse:
    """Liveness probe: the service is up and its database is readable."""
    try:
        await run_in_threadpool(db.check_db, request.app.state.db_path)
    except sqlite3.Error:
        # Details go to the log, not to unauthenticated callers.
        log.exception("health check failed")
        return JSONResponse(
            {"status": "error", "detail": "Database unavailable"},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return JSONResponse({"status": "ok"})
