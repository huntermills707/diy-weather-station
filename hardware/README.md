# Hardware

Hardware documentation for the weather station.

Contents:

- Weather Carrier board assembly and verification notes
- Wiring and pin assignments for sensors (BME280, rain gauge, anemometer,
  wind vane, soil moisture)
- Weatherproof enclosure and radiation shield build
- Site survey and mounting notes
- Solar charging and battery performance test results

## Solar charger and battery (JAE-73)

**Parts.** A WatangTech "5V Solar Charge Controller JEITA" board, a rebrand
of the Seengreat Solar Energy Manager C (CN3166 charger,
[wiki](https://seengreat.com/wiki/185/),
[schematic](https://seengreat.com/upload/file/2024/185/Solar%20Energy%20Manager%20C%20V1.4.pdf)).
The battery is a Horbupa E26-1S2P pack: two 18650 cells in parallel,
3.7 V nominal, 5200 mAh. The panels are USB-C and plug into the board's
DC-044 solar jack through a USB-C to barrel adapter. The board's own USB-C
port also charges, but it cuts out the solar input while in use.

**Wiring.** The board's status header (unsoldered as shipped) goes to the
carrier's soil moisture terminal, unused since soil moisture was dropped,
and to the PWM0 header:

| Charger | Carrier | ESP32 GPIO | Signal |
| ------- | ------- | ---------- | ------ |
| V_BAT | A0, soil terminal SIG | 34 | Cell voltage through a 4.7k/10k divider (2.0-2.9 V at the pin) |
| DONE | G0, soil terminal PWR | 15 | Low = battery full |
| CHRG | PWM0, top PTH header | 13 | Low = charging |
| GND | Soil terminal GND | — | |

Leave 5V_EN and 3V3_EN unconnected: both default to on. Don't use PWM1
(GPIO12) for a status line: it is a strapping pin, and a line held high at
boot selects 1.8 V flash and the board won't start.

**Bench findings (2026-10-21).**

- **CHRG/DONE pull-ups are powered from the solar input.** The wiki says
  the lines have 10k pull-ups to 3.3 V, but that 3.3 V comes from the
  panel side. With no input (night, or a panel indoors), both lines read
  about 0 V, and even the ESP32's internal pull-ups only lift them to
  ~0.9 V. The CN3166 never pulls both low itself, so firmware reads "both
  low" as `idle`. With a USB-C charger on the solar jack: CHRG ~0 V, DONE
  ~3.15 V, reported as `charging`.
- **The ESP32 reads the battery low.** The pin sits at 2.6-2.9 V, above the
  ~2.45 V where the ESP32 ADC is accurate. With the nominal ratio of 1.47,
  the cell read 4.06 V while the charger held it at 4.2 V, so
  `BATT_DIVIDER_RATIO` is calibrated to 1.52 (`firmware/calibration.h`).
  Not yet checked against a multimeter.
- **The station runs from the charger's 5 V output.** It kept running with
  the PC's USB unplugged. The carrier's BATT_VIN/3 pin (GPIO39) read
  1.65 V, a 4.96 V supply. That is the carrier's input, not the battery, so
  firmware doesn't read it.
