# Alerts

The Pi sends local notifications when the station stops reporting, when
there is a risk of frost, and when the nightly backup is missing (JAE-65).
They go to a self-hosted [ntfy](https://ntfy.sh) server on the Pi and on to
the ntfy phone app, all on the LAN. Code:
`server/src/weather_station_server/alerts.py`. Install:
[server/deploy/README.md](../server/deploy/README.md#alerts).

## How it runs

`weather-station-alerts.service` is its own small daemon, separate from the
ingest service, so it still notices if that service dies. Once a minute it
reads the database (read-only) and checks each condition. Every
notification is also written to the journal:

```sh
journalctl -u weather-station-alerts
```

Without `WEATHER_STATION_NTFY_URL`, alerts go only to the journal.

## Conditions

| Alert | Fires when | Clears when |
| ----- | ---------- | ----------- |
| **Weather station offline** | No reading has arrived for **15 minutes** (three missed readings). Measured by the server's receive time, so a dead ingest service, a down WiFi, or a dead station all trigger it | A reading arrives |
| **Freeze risk** | The latest reading is at or below **2 °C (35.6 °F)**. Frost can form on the ground with the air slightly above freezing | It reaches **3 °C (37.4 °F)**. The one-degree gap keeps a temperature hovering at the threshold from flapping |
| **Backup missing** | The newest file in the backup folder is more than **26 hours** old, or there are none ([database.md](database.md#backups)) | A new backup is written |

The freeze check only uses a fresh reading (no older than 15 minutes) with a
temperature that is present and not flagged ([data-quality.md](data-quality.md)).
Otherwise it leaves the alert as it is: the offline alert already covers
missing data. Before the first reading ever arrives, the offline alert stays
quiet.

## Rate limits

- **Start:** one high-priority notification.
- **While it lasts:** one reminder ("Still: …") every **6 hours**.
- **End:** one normal-priority "back online", "freeze risk over", or "backups
  current" notification.
- **Flapping:** if an alert comes back within **1 hour** of clearing, it is not
  announced again until that hour is up. A station that drops out every 20
  minutes for two hours sends four messages, not twelve. The journal still
  records each change.
- If ntfy can't be reached, the alert's state doesn't change, so the next
  check, a minute later, sends it again.

State (active, last sent, last cleared) is kept in
`/var/lib/weather-station/alerts.json`, so restarting the daemon does not
repeat notifications.

The thresholds are constants at the top of `alerts.py`.

## Testing

```sh
# Send a test notification through the configured ntfy URL (root, to read
# the env file).
sudo sh -c 'set -a; . /etc/weather-station/env; \
  /opt/weather-station/server/.venv/bin/python -m weather_station_server.alerts --test'
```

To see a real alert, unplug the station for 15 minutes, then plug it back
in. `server/tests/test_alerts.py` simulates stale data, freezing values,
repetition, flapping, failed delivery, and recovery against a stand-in ntfy
server.
