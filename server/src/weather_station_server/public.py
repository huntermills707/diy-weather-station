"""The public, read-only face of the server (JAE-72, docs/public-dashboard.md).

A separate app from ``main``, run as its own process on localhost and
published through a Cloudflare Tunnel. It has only the read API and the
dashboard: no ``POST /readings``, no ``/health``, no ``/docs``, and it never
loads the ingest token. Every request is rate limited per client and logged.
"""

import logging
import math
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from weather_station_server import read_api
from weather_station_server.config import (
    load_altitude,
    load_dashboard_dir,
    load_db_path,
    load_timezone,
)

log = logging.getLogger("uvicorn.error")

# Per client: a burst of RATE_BURST requests, refilled at RATE_PER_MIN. One
# page load is about seven requests, then one a minute while it stays open.
RATE_BURST = 60
RATE_PER_MIN = 60
# Forget clients beyond this many, so the table can't grow without bound.
MAX_CLIENTS = 10_000

# Parts of the dashboard page that only make sense on the LAN (the API docs
# and Grafana links), between these markers in index.html.
LAN_ONLY = re.compile(r"<!-- lan-only -->.*?<!-- /lan-only -->", re.DOTALL)


class RateLimiter:
    """A token bucket per client address."""

    def __init__(self, burst: int, per_minute: float, max_clients: int = MAX_CLIENTS) -> None:
        self.burst = burst
        self.rate = per_minute / 60
        self.max_clients = max_clients
        self.buckets: dict[str, tuple[float, float]] = {}  # client -> (tokens, updated)

    def take(self, client: str, now: float) -> float:
        """Spend a token; return 0 if allowed, else seconds until the next one."""
        tokens, updated = self.buckets.get(client, (self.burst, now))
        tokens = min(self.burst, tokens + (now - updated) * self.rate)
        if tokens < 1:
            self.buckets[client] = (tokens, now)
            return (1 - tokens) / self.rate
        if client not in self.buckets and len(self.buckets) >= self.max_clients:
            self.buckets.clear()
        self.buckets[client] = (tokens - 1, now)
        return 0.0


def client_address(request: Request) -> str:
    """The visitor's address: cloudflared passes it in CF-Connecting-IP.

    The app listens on localhost only, so the header comes from the tunnel.
    """
    return request.headers.get("CF-Connecting-IP") or (
        request.client.host if request.client else "unknown"
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Read-only: the ingest service creates and migrates the database.
    app.state.db_path = load_db_path()
    app.state.timezone = load_timezone()
    app.state.altitude_m = load_altitude()
    log.info("public read-only app reading %s", app.state.db_path)
    yield


app = FastAPI(
    title="weather-station-public",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.state.limiter = RateLimiter(RATE_BURST, RATE_PER_MIN)
app.include_router(read_api.router)


@app.middleware("http")
async def guard(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """Allow only GET and HEAD, rate limit, and log one line per request."""
    started = time.monotonic()
    client = client_address(request)
    if request.method not in ("GET", "HEAD"):
        response: Response = JSONResponse(
            {"detail": "Method Not Allowed"},
            status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
            headers={"Allow": "GET, HEAD"},
        )
    elif wait := request.app.state.limiter.take(client, started):
        response = JSONResponse(
            {"detail": "Too many requests"},
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(math.ceil(wait))},
        )
    else:
        response = await call_next(request)
    path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    log.info(
        "%s %s %s %d %.0fms",
        client,
        request.method,
        path,
        response.status_code,
        (time.monotonic() - started) * 1000,
    )
    return response


def public_index() -> str:
    """The dashboard page without its LAN-only parts."""
    return LAN_ONLY.sub("", (load_dashboard_dir() / "index.html").read_text())


@app.get("/", include_in_schema=False)
@app.get("/index.html", include_in_schema=False)
async def index() -> HTMLResponse:
    return HTMLResponse(public_index())


# Only the page's own files: nothing else in dashboard/ (its README) is published.
ASSETS = {"app.js": "text/javascript", "style.css": "text/css"}


@app.get("/{name}", include_in_schema=False, responses={404: {}})
async def asset(name: str) -> Response:
    if name not in ASSETS:
        return JSONResponse({"detail": "Not Found"}, status_code=status.HTTP_404_NOT_FOUND)
    return FileResponse(load_dashboard_dir() / name, media_type=ASSETS[name])
