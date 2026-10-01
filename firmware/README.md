# Firmware

ESP32 (SparkFun MicroMod) firmware for the weather station, built with
PlatformIO and the Arduino framework.

Responsibilities:

- Read sensors (BME280, rain gauge, anemometer, wind vane, soil moisture)
- Connect to WiFi with bounded retry/backoff
- POST readings to the FastAPI ingest service over the LAN every five minutes
- Queue failed uploads to a bounded backlog and retry oldest-first

## Layout

`firmware.ino` is the main sketch (`setup()`/`loop()`). The Arduino IDE
requires the sketch folder name to match the `.ino` name, which is why the
file is named after this directory. Add new code as `.cpp`/`.h` files in this
folder — both build systems pick them up automatically. The `platformio.ini`
at the repository root points `src_dir` here, so both IDEs build the same
files.

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
moisture terminal (A0/G0) is not used.

## Units and conversion constants (SparkFun Weather Meter Kit, SEN-08942)

- Rain: **0.2794 mm per bucket tip** (0.011 in)
- Wind speed: **2.4 km/h per closure per second** (1.492 mph/Hz). Average uses
  the closure count over the sample window; peak uses the shortest interval
  between two closures in the window (reported as the average when there are
  fewer than two closures).
- Wind direction: the vane is a resistor ladder read against the 10k pull-up.
  The 16 reference ADC values in `weather_meters.cpp` were calibrated on the
  assembled unit by sweeping the vane through a full revolution (even headings
  measured directly, odd headings measured or modelled as parallel-resistor
  combinations of their neighbours), and agree within 5-8% with SparkFun's
  experimental ESP32 constants in the Weather Meter Kit library. Re-calibrate
  with the `c` serial command if the hardware changes. Readings that fall in
  the dead zone between reference bands report `unknown`; 67.5 and 90 degrees
  are only 26 ADC counts apart and can flip in noise — a hardware limitation.

## Serial output and commands (115200 baud)

- `report ...` every five minutes (ADR 0001 cadence): rain tips/mm for the
  window, cumulative tips, wind average/peak km/h, direction, BME280
  temperature/pressure/humidity. Invalid sensor states print explicitly
  (`bme280=error`, `wind_dir_deg=unknown`) instead of fabricated values.
- `event: rain tip #N` prints immediately on each debounced tip; wind closures
  print once per second while the anemometer is turning.
- Commands: `s` = print a sample report now (resets the window),
  `c` = toggle vane calibration stream, `h` = help.

## CI and static analysis

The `Firmware` GitHub Actions workflow runs on pushes to `main` and on pull
requests that touch `firmware/` or `platformio.ini`:

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
