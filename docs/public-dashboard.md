# Public dashboard

The dashboard is also published read-only on the internet (JAE-72),
through a [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
from the Pi. The station still posts to the LAN-only ingest service. Nothing
on the internet can reach that service, Grafana, or ntfy. Install steps:
[server/deploy/README.md](../server/deploy/README.md#public-dashboard).

```text
visitor ──HTTPS──▶ Cloudflare ──tunnel──▶ cloudflared (Pi) ──▶ 127.0.0.1:8001  public app
                                                             (read-only)
station ──LAN HTTP──▶ 0.0.0.0:8000  ingest service (unchanged, not in the tunnel)
```

The tunnel is an outbound connection from the Pi, so no router port is
forwarded and the Pi's address stays private.

## What is published

A separate app, `weather_station_server.public`, runs as its own process
(`weather-station-public`) on `127.0.0.1:8001`. The tunnel points only at it.
It serves:

| Path | What |
| ---- | ---- |
| `GET /`, `/index.html` | The dashboard page, without its LAN-only footer links (API docs, Grafana) |
| `GET /app.js`, `/style.css` | The page's script and styles |
| `GET /api/current`, `/api/series`, `/api/wind` | The [read API](read-api.md), unchanged |

Everything else is closed:

- **Other methods** (`POST`, `PUT`, `DELETE`, ...) get `405` on any path.
  `POST /readings` doesn't exist in this app, so writes cannot reach the
  database: the app also runs with a read-only filesystem.
- **Other paths** get `404`, including `/readings`, `/health`, `/docs`,
  `/openapi.json`, and the rest of the `dashboard/` folder.
- **No secrets.** The process starts without the ingest token
  (`UnsetEnvironment=` in the unit). Errors return generic messages, like the
  LAN service, and uvicorn's `server` header is off.

The API responses include station health (uptime, reboots, WiFi signal).
That is part of the dashboard and reveals nothing about the network.

## Rate limits

Each visitor (by the `CF-Connecting-IP` address Cloudflare adds) gets a burst
of 60 requests, refilled at 60 a minute. Opening the page takes about seven
requests. After that it makes one a minute plus two every five minutes, so
normal use never comes near the limit. Past it, requests get
`429 {"detail": "Too many requests"}` with a `Retry-After` header in seconds.
The limits are `RATE_BURST` and `RATE_PER_MIN` in `public.py`.

The counts are kept in memory and reset when the service restarts. Cloudflare's
own DDoS protection sits in front of the tunnel.

## Logging

One line per request in the journal, for blocked requests as well:

```text
$ journalctl -u weather-station-public -f
... 203.0.113.7 GET /api/current 200 12ms
... 203.0.113.7 POST /readings 405 0ms
... 198.51.100.2 GET /api/series?start=... 429 0ms
```

The fields are the visitor's address, the method, the path with its query,
the status, and the time taken. The tunnel's own connection events are in
`journalctl -u weather-station-tunnel`.

## Checking it from outside

Run these from a machine off the home network (a phone hotspot works), with
your hostname:

```sh
H=https://weather.volundarhus.com
curl -s -o /dev/null -w '%{http_code}\n' $H/                 # 200
curl -s $H/api/current | head -c 200; echo                    # the latest reading
curl -s -o /dev/null -w '%{http_code}\n' -X POST $H/readings  # 405
curl -s -o /dev/null -w '%{http_code}\n' $H/docs              # 404
curl -s -o /dev/null -w '%{http_code}\n' $H/health            # 404
# Rate limit: the first 60 or so succeed, then 429
for i in $(seq 70); do curl -s -o /dev/null -w '%{http_code} ' $H/api/wind; done; echo
```
