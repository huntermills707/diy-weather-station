# Deploying the ingest service on the Pi

The service runs under systemd as the unprivileged `weather-station` user and
logs to journald ([ADR 0001](../../docs/adr/0001-local-architecture.md)).
These steps assume a provisioned Raspberry Pi OS (Debian) host with SSH
access, a fixed LAN address, and time sync. Run them as your normal admin
user.

| What | Where | Owner |
| ---- | ----- | ----- |
| Code and virtualenv | `/opt/weather-station` (git checkout) | admin user, world-readable |
| Secrets | `/etc/weather-station/env` | root, mode 0600 |
| Database | `/var/lib/weather-station/weather.db` | `weather-station`, created by systemd |
| Unit | `/etc/systemd/system/weather-station.service` | root |

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

Then point the station at the Pi: in `firmware/secrets.h`, set
`INGEST_URL` to `http://<pi-address>:8000/readings` and `INGEST_TOKEN` to the
token from step 4. Then re-upload the firmware.

## Update

```sh
cd /opt/weather-station && git pull
cd server && uv sync --locked --no-dev --python /usr/bin/python3
sudo systemctl restart weather-station
```

## Check it

```sh
systemctl status weather-station          # active (running), enabled
curl -s localhost:8000/health             # {"status":"ok"}
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

## Changing the token

Edit `/etc/weather-station/env` (`sudo nano /etc/weather-station/env`), then
`sudo systemctl restart weather-station`. Update `INGEST_TOKEN` on the station
to match.
