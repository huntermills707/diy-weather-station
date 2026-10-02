# Sensors, units, and calibration

The data contract for the station's serial `report` line, and how to calibrate
it once in the field. All tunable values live in
[`firmware/calibration.h`](../firmware/calibration.h); the defaults come from
SparkFun's
[Weather Meter Kit library](https://github.com/sparkfun/SparkFun_Weather_Meter_Kit_Arduino_Library)
(ESP32 on the Weather Carrier) and
[Weather Carrier examples](https://github.com/sparkfun/MicroMod_Weather_Carrier_Board).
Measurements are meant to be reasonable, not lab grade.

Lightning (AS3935) is out of scope (ADR 0001) and soil moisture has been
dropped from the project; neither is read.

## Report fields

One `report` line every five minutes (or on demand with `s`). `t` is device
uptime in ms; wall-clock time comes with NTP in M2. The serial capture script
(`scripts/serial_capture.py`) prefixes every line with host UTC time.

| Field | Unit | Sensor | How it is measured |
| ----- | ---- | ------ | ------------------ |
| `window_s` | s | — | Length of the window the rain/wind counts cover |
| `rain_tips` / `rain_mm` | count / mm | Rain gauge | Tips in the window × `RAIN_MM_PER_TIP` |
| `rain_total` | count | Rain gauge | Tips since boot (resets on reboot) |
| `wind_avg_kmh` | km/h | Anemometer | Closures in the window ÷ window seconds × `WIND_KMH_PER_HZ` |
| `wind_peak_kmh` | km/h | Anemometer | Shortest gap between two closures in the window; equals the average with fewer than two closures |
| `wind_dir_deg` | degrees | Wind vane | Closest `VANE_ADC` entry + `VANE_OFFSET_DEG`; `unknown` when the vane reads open circuit (unplugged) or shorted to ground |
| `temp_c` | °C | BME280 | Library read |
| `rh_pct` | % RH | BME280 | Library read |
| `press_hpa` | hPa | BME280 | Station pressure (not sea-level corrected) |
| `bme280` | — | BME280 | `ok`, `implausible` (out-of-range values suppressed), or `error` (no I2C response; retried each report) |

Invalid states print explicitly rather than as made-up numbers.

## Constants and defaults

| Constant | Default | Source |
| -------- | ------- | ------ |
| `RAIN_MM_PER_TIP` | 0.2794 mm (0.011 in) | SEN-08942 datasheet / SparkFun library |
| `WIND_KMH_PER_HZ` | 2.4 km/h per closure/s | SEN-08942 datasheet / SparkFun library |
| `VANE_ADC[16]` | Calibrated on this unit 2026-10-02 (2867, 1381, 1599, …) | Field sweep; SparkFun ESP32 values (3118, 1526, 1761, …) in `SparkFun_Weather_Meter_Kit_Constants.h` are the fallback for new hardware |
| `VANE_OFFSET_DEG` | 0 | — |

Fixed sampling behaviour (in `weather_meters.cpp`, not expected to change):
rain debounce 100 ms (bench-measured settle edges at 18-34 ms after a tip),
wind debounce 5 ms, vane averaged over 8 ADC reads.

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
3. **Rain and wind** need no calibration. To sanity-check: pour a known
   volume slowly through the gauge, or compare wind against a handheld
   anemometer, and adjust the constant only if clearly off.

## Quirks

- The vane's 67.5° and 90° values are close (~40 ADC counts), so readings
  near those headings can flip in noise.
- Opening the serial port resets the board, so `rain_total` restarts from 0
  on every new capture.
