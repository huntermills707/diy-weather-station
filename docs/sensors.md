# Sensors, units, and calibration

The data contract for the station's serial `report` line, and how to calibrate
it once in the field. All tunable values live in
[`firmware/calibration.h`](../firmware/calibration.h); the defaults come from
SparkFun's
[Weather Meter Kit library](https://github.com/sparkfun/SparkFun_Weather_Meter_Kit_Arduino_Library)
(ESP32 on the Weather Carrier) and
[Weather Carrier examples](https://github.com/sparkfun/MicroMod_Weather_Carrier_Board).
Measurements are meant to be reasonable, not lab grade.

Temperature, humidity, pressure and air quality come from an auxiliary box
on the carrier's Qwiic cable (JAE-74): an Adafruit BME680 (#3660, address
pad soldered for 0x76) and an Adafruit PMSA003I (#4632, 0x12). The
carrier's own BME280 (0x77) is still on the bus but no longer read. The
`i` serial command lists what answers on the bus.

Lightning (AS3935) is out of scope (ADR 0001) and soil moisture has been
dropped from the project; neither is read.

## Report fields

One `report` line every five minutes (or on demand with `s`). The same
reading is POSTed to the ingest service ([ingest-api.md](ingest-api.md)) with
the same field names, except that `id`, `time`, and `t` become `reading_id`,
`device_time`, and `uptime_ms`, `charge` becomes `charge_state`, and
`rain_total` is serial-only. The serial capture
script (`scripts/serial_capture.py`) prefixes every line with host UTC time.

| Field | Unit | Sensor | How it is measured |
| ----- | ---- | ------ | ------------------ |
| `id` | — | — | `reading_id`: `<boot_id>-<seq>`, random per boot, counting per reading |
| `time` | UTC | — | `device_time` from NTP; `unsynced` until the first NTP sync after boot |
| `t` | ms | — | Device uptime (`uptime_ms`) |
| `window_s` | s | — | Length of the window the rain/wind counts cover |
| `rain_tips` / `rain_mm` | count / mm | Rain gauge | Tips in the window × `RAIN_MM_PER_TIP` |
| `rain_total` | count | Rain gauge | Tips since boot (resets on reboot) |
| `wind_avg_kmh` | km/h | Anemometer | Closures in the window ÷ window seconds × `WIND_KMH_PER_HZ` |
| `wind_peak_kmh` | km/h | Anemometer | Shortest gap between two closures in the window; equals the average with fewer than two closures |
| `wind_dir_deg` | degrees | Wind vane | Closest `VANE_ADC` entry + `VANE_OFFSET_DEG`; `unknown` when the vane reads open circuit (unplugged) or shorted to ground |
| `temp_c` | °C | BME680 | One forced measurement at report time (Adafruit library) |
| `rh_pct` | % RH | BME680 | Same measurement |
| `press_hpa` | hPa | BME680 | Station pressure (not sea-level corrected) |
| `gas_kohm` | kΩ | BME680 | Gas (VOC) sensor resistance, heater at 320 °C for 150 ms. Lower means more VOCs; a trend, not a calibrated value. `unknown` when the heater did not reach temperature |
| `bme680` | — | BME680 | `ok`, `implausible` (out-of-range values suppressed), or `error` (no I2C response; retried each report) |
| `pm1` / `pm25` / `pm10` | µg/m³ | PMSA003I | PM1.0, PM2.5 and PM10 mass ("environmental" values), averaged over the window. Sent as `pm1_ugm3`, `pm25_ugm3`, `pm10_ugm3` |
| `pm_samples` | count | PMSA003I | Samples averaged: one every 10 s, so ~30 per window. Serial only |
| — | per 0.1 L | PMSA003I | Particles above 0.3, 0.5, 1, 2.5, 5 and 10 µm, averaged over the window. Sent only, as `particles_03um` … `particles_10um` |
| `pmsa003i` | — | PMSA003I | `ok`, or `error` (not one good sample in the window; the sensor is probed again every 10 s) |
| `batt_v` | V | Charger V_BAT | 16 calibrated ADC reads × `BATT_DIVIDER_RATIO`; `unknown` outside 2.5-4.5 V (wire off) |
| `charge` | — | Charger CHRG/DONE | `charging` (only CHRG low), `full` (only DONE low), or `idle` (no solar input, e.g. night: the charger powers its status pull-ups from the panel, so both lines read low). Sent as `charge_state` |
| `rssi_dbm` | dBm | WiFi | Signal strength; omitted while WiFi is down |

Invalid states print explicitly rather than as made-up numbers.

## Constants and defaults

| Constant | Default | Source |
| -------- | ------- | ------ |
| `RAIN_MM_PER_TIP` | 0.2794 mm (0.011 in) | SEN-08942 datasheet / SparkFun library |
| `WIND_KMH_PER_HZ` | 2.4 km/h per closure/s | SEN-08942 datasheet / SparkFun library |
| `VANE_ADC[16]` | Calibrated on this unit 2026-10-02 (2867, 1381, 1599, …) | Field sweep; SparkFun ESP32 values (3118, 1526, 1761, …) in `SparkFun_Weather_Meter_Kit_Constants.h` are the fallback for new hardware |
| `VANE_OFFSET_DEG` | 0 | — |
| `BATT_DIVIDER_RATIO` | 1.52, calibrated on this unit 2026-10-21 (charger holding 4.2 V read 4.06 V with 1.47) | 1.47 nominal for the 4.7k/10k divider, [Seengreat Solar Energy Manager C wiki](https://seengreat.com/wiki/185/) |

Fixed sampling behaviour (in `weather_meters.cpp`, not expected to change):
rain debounce 100 ms (bench-measured settle edges at 18-34 ms after a tip),
wind debounce 5 ms, vane averaged over 8 ADC reads.

Air quality (in `particulates.cpp` and `firmware.ino`): the PMSA003I is
sampled every 10 s, starting 30 s after boot (its warm-up), and its fan
runs all the time (about 100 mA) because the SET sleep pin is not wired.
The BME680 gas heater runs only for each five-minute measurement, so its
self-heating of the temperature reading is negligible. No IAQ index is
computed (Bosch's BSEC library is closed source); an air quality index from
PM2.5 belongs on the server.

## Field calibration (once, after mounting)

Connect a laptop over USB and stream raw values:

```sh
uv run --with pyserial scripts/serial_capture.py --send c
```

This prints `cal vane_adc=<n> dir=<deg>` twice a second. Edit
`firmware/calibration.h`, re-upload, and check a few headings again.

1. **Wind vane table.** Hold the vane pointing at each heading (N, NE, E, …)
   and write the `vane_adc` value into that heading's `VANE_ADC` slot. The
   eight main headings are easy to hold; the in-between ones (NNE, ENE, …)
   snap past without settling — capture them if you can, otherwise keep the
   existing values (each must sit below both neighbouring main headings).
   This matters: SparkFun's defaults read ~8% high against this unit, which
   mislabelled 11 of 16 headings before calibration.
2. **Vane orientation.** If the station's "N" mark can't face true north,
   set `VANE_OFFSET_DEG` to the direction the "N" mark actually faces
   (e.g. it faces east → `90`).
3. **Battery.** Measure the cell with a multimeter and compare it with
   `batt_v` from an `s` report. If they differ by more than ~0.05 V, scale
   `BATT_DIVIDER_RATIO` by meter ÷ `batt_v`.
4. **Rain and wind** need no calibration. To sanity-check: pour a known
   volume slowly through the gauge, or compare wind against a handheld
   anemometer, and adjust the constant only if clearly off.

## Quirks

- The vane's 67.5° and 90° values are close (~40 ADC counts), so readings
  near those headings can flip in noise.
- Opening the serial port resets the board, so `rain_total` restarts from 0
  on every new capture, and the reading `id` gets a new boot ID.
