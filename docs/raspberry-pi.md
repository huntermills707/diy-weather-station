# Raspberry Pi setup record

This records how the server Pi is built (JAE-44). Use it to rebuild the Pi
from scratch or to check the current one. Application deployment (ingest
service and Grafana) is covered separately in
[server/deploy/README.md](../server/deploy/README.md).

State as of 2026-10-02. Secrets (account password, WiFi key, ingest token) are
deliberately left out.

## Summary

| Item | Value |
| ---- | ----- |
| Hardware | Raspberry Pi 5 Model B Rev 1.1, 8 GB RAM |
| Storage | 256 GB NVMe SSD: `nvme0n1p1` 512 MB `/boot/firmware`, `nvme0n1p2` 238 GB `/`. Swap is 2 GB zram (no swap file) |
| OS | Raspberry Pi OS (64-bit) with desktop and recommended software (pi-gen stage4), image 2026-09-15, based on Debian 13 trixie, kernel 6.18 (`rpt-rpi-2712`) |
| Hostname | `weatherhub` |
| Admin user | `weather` (uid 1000, in `sudo`; sudo asks for the password) |
| Network | WiFi (`wlan0`, NetworkManager via netplan); Ethernet unused |
| Address | 192.168.68.53/22, a DHCP reservation in the home router |
| Time | `systemd-timesyncd` (Debian NTP pool), time zone America/Los_Angeles |
| Locale | `en_GB.UTF-8` (Raspberry Pi OS default), US keyboard layout |
| SSH | Port 22. Key login for `weather`; password login also allowed (see below) |
| Updates | `unattended-upgrades`: daily security and stable updates, no automatic reboot |
| Logs | journald, persistent (`/var/log/journal`), overriding the Raspberry Pi OS volatile default |

## 1. Image the NVMe drive

Use Raspberry Pi Imager to write **Raspberry Pi OS (64-bit)** to the NVMe
drive. The current Pi runs the full desktop image; Lite also works (see
leftovers below). In OS customisation, set:

- Hostname `weatherhub`
- User `weather` with a password
- WiFi SSID and key, with the wireless LAN country set
- Time zone America/Los_Angeles, keyboard `us`
- SSH enabled

Imager stores these choices in `/boot/firmware/user-data` and
`network-config`, and cloud-init applies them on first boot. WiFi then
appears in NetworkManager as `netplan-wlan0-<SSID>`. Both files contain
secrets: don't copy them into the repo.

The Pi boots from NVMe with the stock bootloader settings. `config.txt` is
the image's own file, unchanged for this project.

## 2. After first boot

The OS was patched right after first boot with `sudo apt update && sudo apt
upgrade` (the apt history shows `apt-get upgrade`). `sudo apt full-upgrade`
also pulls in updates that add or remove packages, such as new kernels; use
it on a rebuild. Then:

```sh
# SSH key login from the dev laptop (run on the laptop)
ssh-copy-id -i ~/.ssh/id_ed25519.pub weather@192.168.68.53

# Fixed address: reserve 192.168.68.53 for the Pi's WiFi MAC
# (2c:cf:67:c1:1c:59) in the router's DHCP settings.

# Automatic security updates
sudo apt install -y unattended-upgrades apt-listchanges
echo "unattended-upgrades unattended-upgrades/enable_auto_updates boolean true" \
  | sudo debconf-set-selections
sudo dpkg-reconfigure -f noninteractive unattended-upgrades
```

`unattended-upgrades` keeps Debian's defaults:

- Package lists refresh daily (`/etc/apt/apt.conf.d/20auto-upgrades`).
- Upgrades come from the Debian and Debian-Security origins.
- `Automatic-Reboot` stays off, so data collection is never interrupted
  without warning.

Packages from the Raspberry Pi archive (kernel, firmware) and Grafana's
repository are not upgraded automatically. Run `sudo apt full-upgrade`
occasionally, and reboot after kernel updates.

Time sync needs no setup: `systemd-timesyncd` is enabled by default. Check it
with `timedatectl`, which should show `System clock synchronized: yes`.

Keep the journal across reboots, so logs from before a power cut survive.
Raspberry Pi OS forces volatile storage in
`/usr/lib/systemd/journald.conf.d/40-rpi-volatile-storage.conf`; a later
drop-in in `/etc` overrides it. journald's default size cap (10% of the file
system, at most 4 GB) is fine on the NVMe drive.

```sh
sudo mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nStorage=persistent\n' \
  | sudo tee /etc/systemd/journald.conf.d/50-persistent.conf
sudo systemctl restart systemd-journald
sudo journalctl --flush
```

## 3. Application

Follow [server/deploy/README.md](../server/deploy/README.md). It installs
`git`, `sqlite3`, and `uv`, plus the ingest service with its
`weather-station` service user, and Grafana from Grafana's apt repository
(`/etc/apt/sources.list.d/grafana.list`) with the `frser-sqlite-datasource`
plugin.

Installed versions on 2026-10-02:

| Software | Version |
| -------- | ------- |
| Python (system) | 3.13.5 |
| uv (`~weather/.local/bin/uv`) | 0.12.22 |
| git | 2.47.3 |
| sqlite3 | 3.46.1 |
| Grafana OSS | 13.2.3 |
| frser-sqlite-datasource | 4.0.6 |
| unattended-upgrades | 2.12 |

## Listening ports

| Port | Service | Notes |
| ---- | ------- | ----- |
| 22 | sshd | |
| 8000 | weather-station (uvicorn) | Ingest API, LAN only |
| 3000 | grafana-server | Charts, LAN only |
| 111 | rpcbind | Comes with the desktop image; unused |

There is no host firewall. The Pi relies on the home router not forwarding
any ports, which matches ADR 0001's LAN-only scope.

## Deliberate choices and known leftovers

- **Password SSH login stays enabled**, and the Grafana `admin` login stays
  at its default. This is accepted for a home network that only the owner
  uses. Revisit both before anything is exposed beyond the LAN.
- **Desktop image.** The full desktop image includes a desktop session
  (lightdm), CUPS, Bluetooth, and rpcbind, none of which the station needs.
  They are harmless at this scale. The Lite image would be leaner for a
  rebuild.
- **Bootloader EEPROM update pending.** On 2026-10-02, `rpi-eeprom-update`
  reported the installed bootloader from 2025-12-08 and the latest from
  2026-09-25. To apply it, run `sudo rpi-eeprom-update -a` and reboot. Pick a
  moment when a missed reading doesn't matter: until the upload queue lands
  in M4, readings sent while the Pi is down are lost.

## Checks

```sh
cat /proc/device-tree/model; echo        # Raspberry Pi 5 Model B Rev 1.1
grep PRETTY /etc/os-release              # Debian GNU/Linux 13 (trixie)
timedatectl                               # synchronized: yes
journalctl --list-boots                   # lists earlier boots too
systemctl is-enabled unattended-upgrades apt-daily-upgrade.timer
sudo unattended-upgrade --dry-run        # no errors
ss -tln                                   # 22, 111, 3000, 8000
```
