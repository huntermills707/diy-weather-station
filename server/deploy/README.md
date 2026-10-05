# Deploying the ingest service on the Pi

The service runs under systemd as the unprivileged `weather-station` user and
logs to journald ([ADR 0001](../../docs/adr/0001-local-architecture.md)).
These steps assume a provisioned Raspberry Pi OS (Debian) host with SSH
access, a fixed LAN address, and time sync: see the
[Raspberry Pi setup record](../../docs/raspberry-pi.md). Run them as your normal admin
user.

| What | Where | Owner |
| ---- | ----- | ----- |
| Code and virtualenv | `/opt/weather-station` (git checkout) | admin user, world-readable |
| Secrets | `/etc/weather-station/env` | root, mode 0600 |
| Database | `/var/lib/weather-station/weather.db` | `weather-station`, created by systemd |
| Backups | `/var/backups/weather-station/` | `weather-station`, mode 0750 |
| Alert state | `/var/lib/weather-station/alerts.json` | `weather-station` |
| Units | `/etc/systemd/system/weather-station*.{service,timer}` | root |

The service can read its code but not change it, and it can write only its
state directory.

## Install

```sh
# 1. Tools: git, sqlite3 CLI (for inspecting data), uv
sudo apt install -y git sqlite3
curl -LsSf https://astral.sh/uv/install.sh | sh   # then open a new shell

# 2. Service user (no login, no home directory)
sudo adduser --system --group --no-create-home weather-station

# 3. Code, with a virtualenv built on the system Python. Do not use a
#    uv-managed Python: it would live in your home directory, which the
#    service cannot read (ProtectHome).
sudo install -d -o "$USER" -g "$USER" /opt/weather-station
git clone https://github.com/huntermills707/diy-weather-station.git /opt/weather-station
cd /opt/weather-station/server
uv sync --locked --no-dev --python /usr/bin/python3

# 4. Secrets: generate the station token and keep a copy for firmware/secrets.h
sudo install -d -m 0755 /etc/weather-station
echo "WEATHER_STATION_INGEST_TOKEN=$(openssl rand -hex 32)" \
  | sudo install -m 0600 /dev/stdin /etc/weather-station/env
sudo cat /etc/weather-station/env   # copy the token into INGEST_TOKEN

# 5. Unit
sudo cp deploy/weather-station.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now weather-station
```

The service listens on port 8000 on all interfaces. It stays LAN-only
because the router does not forward the port. If the Pi runs a firewall, allow
only the LAN, for example
`sudo ufw allow from 192.168.68.0/22 to any port 8000 proto tcp` (use your
subnet).

Optionally set the station's altitude, so the dashboard can show sea-level
pressure ([docs/read-api.md](../../docs/read-api.md#derived-metrics)):

```sh
echo "WEATHER_STATION_ALTITUDE_M=50" | sudo tee -a /etc/weather-station/env   # your altitude
sudo systemctl restart weather-station
```

Rain totals use the Pi's time zone for days and months
(`timedatectl` shows it); set `WEATHER_STATION_TIMEZONE` the same way to
override it.

Then point the station at the Pi: in `firmware/secrets.h`, set
`INGEST_URL` to `http://<pi-address>:8000/readings` and `INGEST_TOKEN` to the
token from step 4. Then re-upload the firmware.

## Update

```sh
cd /opt/weather-station && git pull
cd server && uv sync --locked --no-dev --python /usr/bin/python3
sudo systemctl restart weather-station weather-station-alerts
```

If a unit file in `deploy/` changed, copy it to `/etc/systemd/system/` and run
`sudo systemctl daemon-reload` before restarting.

### Upgrading to M4 (reliability)

Order matters: **server first, then firmware.** The new firmware sends
`boot_count`, `reset_reason`, and `queue_dropped`, which an older server
rejects with `422`, and the station drops a reading the server rejects. The
new server accepts readings with or without them.

1. Take a backup by hand before the schema migration:
   `sudo sqlite3 /var/lib/weather-station/weather.db ".backup /var/lib/weather-station/pre-m4.db"`
2. Update as above. On startup the service migrates the database to schema
   version 2 and flags existing readings. `journalctl -u weather-station -b`
   should show a normal startup.
3. Install the backup timer and alerts (below).
4. Flash the new firmware ([firmware/README.md](../../firmware/README.md)).
   The dashboard's health section then shows "Last reboot" and "Upload
   queue".

## Check it

```sh
systemctl status weather-station          # active (running), enabled
curl -s localhost:8000/health             # {"status":"ok"}
curl -s localhost:8000/api/current        # latest reading, rain totals, health
journalctl -u weather-station -f          # startup line and one POST per reading
sqlite3 /var/lib/weather-station/weather.db \
  'SELECT received_at, reading_id, temp_c FROM readings ORDER BY id DESC LIMIT 5'
```

`sqlite3` needs read access to the file, so run it with `sudo`, or add
yourself to the `weather-station` group
(`sudo adduser "$USER" weather-station`, then log in again).

Restart behaviour (JAE-49 verification):

```sh
sudo systemctl kill -s KILL weather-station   # simulate a crash
sleep 6; systemctl status weather-station     # restarted ~5 s later
sudo reboot                                   # then, after it comes back:
curl -s <pi-address>:8000/health              # from another machine on the LAN
journalctl -u weather-station -b              # this boot's logs
```

## Backups

Nightly SQLite backups to `/var/backups/weather-station`, keeping 30
([docs/database.md](../../docs/database.md#backups), which also has the
restore procedure).

```sh
sudo install -d -o weather-station -g weather-station -m 0750 /var/backups/weather-station
sudo cp deploy/weather-station-backup.service deploy/weather-station-backup.timer \
  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now weather-station-backup.timer
sudo systemctl start weather-station-backup     # one now, to check it
journalctl -u weather-station-backup -n 5       # backup: wrote ... (N readings, ...)
systemctl list-timers weather-station-backup    # next run 03:17
```

## Alerts

Notifications for an offline station, freeze risk, and a missing backup
([docs/alerts.md](../../docs/alerts.md)), delivered by a self-hosted
[ntfy](https://docs.ntfy.sh) server on the Pi.

```sh
# 1. ntfy server from ntfy's apt repository
sudo mkdir -p /etc/apt/keyrings
sudo curl -L -o /etc/apt/keyrings/ntfy.gpg https://archive.ntfy.sh/apt/keyring.gpg
echo "deb [arch=arm64 signed-by=/etc/apt/keyrings/ntfy.gpg] https://archive.ntfy.sh/apt stable main" \
  | sudo tee /etc/apt/sources.list.d/ntfy.list
sudo apt update && sudo apt install -y ntfy

# 2. Tell ntfy its LAN address, then start it (it listens on port 80)
echo 'base-url: "http://192.168.68.53"' | sudo tee -a /etc/ntfy/server.yml   # your Pi
sudo systemctl enable --now ntfy

# 3. Point the alerts at a topic, and start them
echo "WEATHER_STATION_NTFY_URL=http://localhost/weather" | sudo tee -a /etc/weather-station/env
sudo cp deploy/weather-station-alerts.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now weather-station-alerts
journalctl -u weather-station-alerts -n 5   # alerts: watching station-1 ...
```

On the phone, install the ntfy app, add the server `http://<pi-address>`,
and subscribe to the topic `weather`. Then send a test:

```sh
sudo sh -c 'set -a; . /etc/weather-station/env; \
  /opt/weather-station/server/.venv/bin/python -m weather_station_server.alerts --test'
```

The Android app keeps its own connection to the Pi, so notifications arrive
while the phone is on the home WiFi. The iOS app wakes up through Apple's
push service, which a LAN-only server can't use without forwarding to
ntfy.sh (`upstream-base-url`); without it, iOS shows notifications when the
app is opened. Like ports 8000 and 3000, port 80 must stay LAN-only.

## Dashboard

The service serves the dashboard ([docs/dashboard.md](../../docs/dashboard.md))
from the checkout's `dashboard/` folder. Open `http://<pi-address>:8000/` on
any device on the LAN. Nothing else to install: `git pull` and a restart
update it like the rest of the service.

## Grafana charts

Grafana reads the SQLite file directly, read-only, through the
[frser-sqlite-datasource](https://grafana.com/grafana/plugins/frser-sqlite-datasource/)
plugin. Its datasource and dashboard are provisioned from
[`server/grafana/`](../grafana), so they are versioned and `git pull` picks up
dashboard changes.

```sh
# 1. Grafana OSS from Grafana's apt repository (arm64 and armhf builds)
sudo apt install -y apt-transport-https gnupg wget
sudo mkdir -p /etc/apt/keyrings
wget -qO - https://apt.grafana.com/gpg.key | gpg --dearmor | sudo tee /etc/apt/keyrings/grafana.gpg >/dev/null
echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" \
  | sudo tee /etc/apt/sources.list.d/grafana.list
sudo apt update && sudo apt install -y grafana

# 2. SQLite plugin, and read access to the database through the group
sudo grafana cli --homepath /usr/share/grafana --pluginsDir /var/lib/grafana/plugins \
  plugins install frser-sqlite-datasource
sudo chown -R grafana:grafana /var/lib/grafana/plugins
sudo adduser grafana weather-station

# 3. Provisioning (copies; re-copy if these two files change)
sudo cp /opt/weather-station/server/grafana/provisioning/datasources/weather-station.yaml \
  /etc/grafana/provisioning/datasources/
sudo cp /opt/weather-station/server/grafana/provisioning/dashboards/weather-station.yaml \
  /etc/grafana/provisioning/dashboards/
sudo systemctl enable --now grafana-server
```

Open `http://<pi-address>:3000`. The first login is `admin` / `admin`, and
Grafana asks for a new password. Open the **Weather station** dashboard. Like
port 8000, port 3000 must stay LAN-only.

The dashboard shows temperature, humidity, pressure, wind, rain, the minutes
between readings, and a table of the latest rows. Missing readings break the
lines. A sensor error stored as NULL also leaves a gap. The interval panel
shows a gap as a spike above 5 minutes. To check a point against the
database, compare it with the table, or query the row with `sqlite3`.
Chart times use the station's NTP time (`device_time`), falling back to the
server's `received_at`, and display in the browser's time zone.

The database uses SQLite's rollback journal rather than WAL so this
read-only access works (see [docs/database.md](../../docs/database.md)).

## Changing the token

Edit `/etc/weather-station/env` (`sudo nano /etc/weather-station/env`), then
`sudo systemctl restart weather-station`. Update `INGEST_TOKEN` on the station
to match.
