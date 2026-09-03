# ADR 0001: Local architecture — ESP32 HTTP over LAN, FastAPI, SQLite

- Status: Accepted
- Date: 2026-09-02

## Context

The DIY weather station collects environmental readings (temperature,
humidity, pressure via BME280; rainfall via tipping bucket; wind speed and
direction; soil moisture) on a SparkFun MicroMod ESP32. Readings must be
stored durably, queryable for current and historical conditions, and
visualizable on a local dashboard. The system runs entirely on the home
network: the station and a Raspberry Pi server sit on the same LAN.

We needed to decide the three core architectural choices before building:

1. How readings get from the ESP32 to the server.
2. What the ingest service is built with.
3. Where readings are stored.

## Decision

### 1. ESP32 pushes readings via HTTP POST over LAN/WiFi

The ESP32 connects to the LAN over WiFi (with bounded reconnect backoff) and
POSTs a reading to the ingest service every **five minutes**. Delivery
failures queue on-device in a bounded backlog, retried oldest-first with
bounded backoff; overflow policy is observable. Each reading receives a
device-generated `reading_id` when it is sampled. The ID is stored with the
queued payload and reused unchanged for every retry. SQLite enforces a unique
constraint on `(station_id, reading_id)`; the server treats a conflict as a
successful duplicate submission and returns the existing reading, so a lost
response cannot create another row and the device can remove the queued item.

### 2. FastAPI ingest service on a Raspberry Pi

A LAN-only FastAPI application receives readings, validates payloads with
Pydantic, stores them, and exposes defined error responses and a health
endpoint. It runs under systemd as a non-root user with journald logging.
Reading submissions use a per-station pre-shared token in the HTTP
`Authorization: Bearer` header. The token is provisioned into the ESP32 during
device setup and into a root-readable environment file used by the systemd
service; it is never stored in source control. The service rejects missing or
invalid credentials with `401 Unauthorized` before validating or storing the
payload. Python tooling is `uv` + `ruff` + `pytest`.

### 3. SQLite for storage

Readings are stored in SQLite on the Pi, recording both device and server
timestamps so clock drift and duplicates can be detected. Before production
deployment, a nightly SQLite backup and regularly tested restore procedure are
required controls; they are not yet implemented.

### Cadence and scope exclusions

- **Five-minute collection cadence**: one reading per station every five
  minutes, validated by a 24-hour soak test.
- **Excluded from scope**: deep-sleep power optimization and lightning
  detection. No cloud services or internet exposure — everything is LAN-only.

## Alternatives considered

### Transport

- **MQTT**: the standard IoT choice and planned later for Home Assistant
  integration. Rejected as the primary path for now because it adds a broker
  to deploy and operate before any data flows; plain HTTP POST to a service
  we control is simpler to build, validate, and debug. MQTT publishing is
  deferred to a follow-up feature, layered on top of stored data.
- **Serial/USB tether to the Pi**: eliminates WiFi failure modes but fixes
  the station's location to the Pi's, which rules out proper outdoor siting.
- **Cloud IoT service**: contradicts the LAN-only goal and adds accounts,
  credentials, and recurring cost for no benefit at this scale.

### Ingest framework

- **Flask**: viable, but FastAPI gives request validation (Pydantic), an
  async ASGI server, and generated API docs out of the box.
- **Node/Express or similar**: the project's Python tooling decision
  (`uv`/`ruff`/`pytest`) and the data-analysis direction (notebooks, pandas)
  favor keeping the whole server side in one Python ecosystem.

### Storage

- **PostgreSQL**: more than we need — one row per station every five minutes
  is ~288 rows/day, trivial for SQLite. A separate database server adds
  operational burden on a single Pi.
- **Time-series database (InfluxDB)**: attractive query model, but another
  service to run; SQLite plus plain SQL covers current/historical queries at
  this volume.
- **Flat files/CSV**: no concurrent read/write handling, no constraints, and
  painful queries; SQLite is strictly better at the same simplicity.

## Consequences

- The ESP32 firmware owns WiFi retry and the bounded upload queue; brief LAN
  outages do not lose data.
- FastAPI validation rejects malformed payloads at the edge; invalid readings
  fail visibly rather than corrupting storage.
- Dual timestamps (device + server) support later gap/duplicate analysis.
- SQLite keeps backups trivial (copy one file) but caps concurrent write
  scaling — acceptable at one write per five minutes.
- Staying LAN-only means remote access, if ever wanted, requires an explicit
  future decision (e.g., VPN); it is deliberately out of scope now.
