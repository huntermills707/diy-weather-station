# Firmware

ESP32 (SparkFun MicroMod) firmware for the weather station, built with
PlatformIO and the Arduino framework.

Responsibilities:

- Read sensors (BME280, rain gauge, anemometer, wind vane)
- Connect to WiFi with bounded retry/backoff
- Timestamp readings in UTC via NTP
- POST readings to the FastAPI ingest service over the LAN every five minutes
  ([docs/ingest-api.md](../docs/ingest-api.md))
- Queue failed uploads to a bounded backlog and retry oldest-first (M4; for
  now a failed upload is logged and that reading is dropped)

`firmware.ino` takes and reports readings, `weather_meters.*` reads the
rain/wind/vane hardware, `network.*` handles WiFi, NTP and the HTTP POST, and
`reading.*` builds the JSON payload.

## Layout

`firmware.ino` is the main sketch (`setup()`/`loop()`). The Arduino IDE
requires the sketch folder name to match the `.ino` name, which is why the
file is named after this directory. Add new code as `.cpp`/`.h` files in this
folder — both build systems pick them up automatically. The `platformio.ini`
at the repository root points `src_dir` here, so both IDEs build the same
files.

## Secrets (required to build)

WiFi credentials and the ingest token live in `firmware/secrets.h`, which is
gitignored and must never be committed (issue #23). The sketch fails to
compile without it:

```sh
cp firmware/secrets.example.h firmware/secrets.h
# then edit firmware/secrets.h with real values
```

`INGEST_TOKEN` must match `WEATHER_STATION_INGEST_TOKEN` on the server
(see `server/README.md`). `INGEST_URL` points at the Pi, e.g.
`http://192.168.1.50:8000/readings`. Optionally define `NTP_SERVER` (default
`pool.ntp.org`). `STATION_ID` at the top of `firmware.ino` names the station. CI builds with the placeholder values from
`secrets.example.h`.

## Setup: CLion + PlatformIO

1. Install the PlatformIO plugin in CLion (or use the `pio` CLI).
2. Open the **repository root** (where `platformio.ini` lives) — not this folder.
3. Build: `pio run`
4. Upload: `pio run -t upload`
5. Serial monitor: `pio device monitor` (115200 baud, already configured)

## Setup: Arduino IDE (Windows)

1. Install Arduino IDE 2.x from arduino.cc (the direct installer, not the
   Microsoft Store build).
2. File → Preferences → "Additional boards manager URLs": add
   `https://espressif.github.io/arduino-esp32/package_esp32_index.json`
3. Tools → Board → Boards Manager → install **esp32** by Espressif.
4. Tools → Board → select **SparkFun ESP32 MicroMod**.
5. Install the Silicon Labs CP210x USB-to-UART driver (the "CP210x Windows
   Drivers" zip on SiLabs' "USB to UART Bridge VCP Drivers" page; SparkFun's
   "How to Install CP2104 Drivers" tutorial walks through it). Install it even
   if a COM port already appears — the driver Windows auto-installs breaks the
   board's auto-reset circuit and uploads will fail. Then select the port
   under Tools → Port.
6. File → Open → `firmware/firmware.ino`, then Sketch → Upload.
   Serial Monitor: 115200 baud.

## Hardware pin map (MicroMod Weather Carrier + ESP32)

| Sensor        | Carrier signal | ESP32 GPIO | Interface |
| ------------- | -------------- | ---------- | --------- |
| Rain gauge    | D1 (RJ11)      | 27         | digital, falling-edge interrupt |
| Anemometer    | D0 (RJ11)      | 14         | digital, falling-edge interrupt |
| Wind vane     | A1 (RJ11)      | 35         | 12-bit ADC, 10k pull-up to 3.3V |
| BME280        | Qwiic I2C      | 21/22      | I2C address 0x77 |

The carrier puts 43k pull-ups and 0.1uF RC filters on the rain and wind-speed
lines, so firmware uses plain `INPUT` and only a short software debounce
(rain 100 ms — bench-measured phantom edges arrive 18-34 ms after a real tip;
wind 5 ms) to reject reed-switch bounce and mechanical settling. The soil
moisture terminal (A0/G0) is not used: soil moisture is out of scope.

## Units and calibration

Report fields, units, defaults, and the one-time field calibration procedure
are in [docs/sensors.md](../docs/sensors.md). Every tunable value lives in
`calibration.h`. Rain and wind use SparkFun's published Weather Meter Kit
values; the `VANE_ADC` table is field-calibrated for this unit, with SparkFun's
table as the fallback for new hardware.

## Serial output and commands (115200 baud)

- `report ...` every five minutes (ADR 0001 cadence): reading ID, UTC time,
  rain, wind, vane direction, BME280 fields, and RSSI (see docs/sensors.md).
  Invalid sensor states print explicitly (`bme280=error`,
  `wind_dir_deg=unknown`, `time=unsynced`) instead of fabricated values.
- `upload: id=... ok (201)` after each report, or `FAILED no wifi` /
  `FAILED code=N` with a running failure count. `200` means the server already
  had that reading. Negative codes are HTTPClient errors (`-1` connection
  refused, `-11` read timeout).
- `wifi: ...` on every connect attempt, connection (with IP and RSSI), and
  link loss. Retries back off 10 s, 20 s, 40 s … up to 5 minutes; sensors and
  reports keep running throughout. `ntp: started` follows the first
  connection.
- `event: rain tip #N` prints immediately on each debounced tip; wind closures
  print once per second while the anemometer is turning.
- Commands: `s` = print a sample report now (resets the window),
  `c` = toggle the calibration stream (raw vane ADC and heading),
  `h` = help.
- `scripts/serial_capture.py` captures this output with host UTC timestamps.

## CI and static analysis

The `Firmware` GitHub Actions workflow runs on every pull request and on
pushes to `main` that touch `firmware/` or `platformio.ini`:

- **Compile**: `pio run` — compilation errors fail the workflow
- **Static analysis**: `pio check --fail-on-defect medium` (cppcheck, medium+ severity)
- **Formatting**: `clang-format --dry-run --Werror` against `.clang-format`

Local equivalents:

```sh
pio run
pio check --fail-on-defect medium
find firmware -type f \( -name '*.ino' -o -name '*.cpp' -o -name '*.h' \) \
  -exec clang-format -i --assume-filename=sketch.cpp {} +
```

`.ino` files are C++, so C++ tooling applies; `--assume-filename` is needed
because clang-format does not recognize the `.ino` extension.

## Working together

- **Libraries**: install each dependency in the Arduino IDE environment and list it in `lib_deps` in `platformio.ini` for PlatformIO. `lib_deps` is not read by Arduino IDE, so keep the library names and compatible versions aligned across both builds.
- **Flash/partition layout differs between the two builds**: `platformio.ini`
  overrides the board to 16MB flash with `default_16MB.csv` partitions, while
  the Arduino IDE's board definition is fixed at 4MB (there is no Flash Size
  menu for this board). Both run fine, but data stored in a flash filesystem
  (SPIFFS/LittleFS) is not portable between the two layouts, and an IDE build
  is limited to ~1.2MB app size by default (pick a larger Partition Scheme in
  the IDE if that ever bites).
