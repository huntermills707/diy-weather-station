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
