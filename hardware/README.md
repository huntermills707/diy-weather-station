# Hardware

Hardware documentation for the weather station.

Contents:

- Weather Carrier board assembly and verification notes
- Wiring and pin assignments for sensors (BME680, PMSA003I, rain gauge, anemometer,
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

**Power.** The station runs from the charger's 3.3 V output, wired to the
carrier's 3.3V pin with a GND wire alongside. This feeds the carrier's 3.3 V
rail directly and bypasses its own regulator, so the carrier's USB-C and
battery inputs are unused in the field. The charger's 5 V output is not
used.

| Charger | Carrier | Purpose |
| ------- | ------- | ------- |
| 3.3V | 3.3V | Station supply |
| GND | GND | Supply return |

When the carrier is also plugged into USB for flashing or serial capture,
both its regulator and the charger drive the 3.3 V rail. Unplug one of
them first.

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
- **The bench setup ran from the charger's 5 V output** into the carrier's
  input. The carrier's BATT_VIN/3 pin (GPIO39) read 1.65 V, a 4.96 V
  supply. The field station now uses the 3.3 V output instead (see
  **Power**), which leaves the carrier's input, and GPIO39, unpowered.
  Firmware doesn't read GPIO39 either way.

## PMSA003I fan control (JAE-81)

The PMSA003I's fan draws about 100 mA all the time, and the battery lasted
only about a day once the auxiliary box went in. Firmware now runs the fan
only for about 40 s of each five-minute window (see
[firmware/README.md](../firmware/README.md#power)). That needs one extra
wire from the auxiliary box to the carrier, alongside the Qwiic cable, and a
pull-down resistor. The Qwiic cable already carries GND.

| PMSA003I breakout | Carrier | ESP32 GPIO | Purpose |
| ----------------- | ------- | ---------- | ------- |
| SET | RX1, middle pin of the 3-pin bottom header (TX1 · RX1 · GND) | 16 | High = run, low = sleep |
| SET to GND | — | — | 330 Ω pull-down, soldered at the breakout |
| RST | — | — | Leave unconnected |

- **The breakout circuit** (Adafruit #4632; checked against the Eagle
  schematic and board files). Header SET reaches the sensor through a
  1N4148 diode. The sensor side has a 100k pull-up to the breakout's
  3.3 V. It feeds the sensor's SET pin and the shutdown input of the 5 V
  boost that powers the sensor (AP3602 or RT9361). The sensor reads SET as
  sleep below 0.8 V.
- **Why a pull-down, and why 330 Ω.** Without one, SET floats high whenever
  the ESP32 isn't driving it (reset, boot, deep sleep), and the fan runs.
  The pull-down has to sink the 100k plus the sensor's internal pull-up
  (the datasheet doesn't give its value) through the diode, while keeping
  the sensor side under 0.8 V. That takes a few hundred ohms. 1k is
  marginal if the internal pull-up is about 20k, and 10k fails outright.
  330 Ω reaches 0.8 V only in the worst case (a 10k internal pull-up, a
  worst-case diode, about 0 °C). It costs 10 mA only while the ESP32 drives
  SET high, about 1.3 mA on average. 220 Ω also works, at 15 mA.
- **The boost probably turns off too.** SET low leaves the sensor side one
  diode drop up (about 0.5 V). That isn't guaranteed to shut down either
  boost chip (AP3602 below 0.3 V, RT9361 below 0.4 V), but the RT9361's
  typical threshold is 0.9-1.2 V. Either way the fan stops. If the boost is
  off, the sensor is unpowered and doesn't answer I2C, which firmware
  expects.
- **Where the resistor goes.** On the breakout header the order is VIN,
  3Vo, GND, SCL, SDA, RST, SET. SET and GND are 0.4" (10.16 mm) apart,
  the standard bend for a 1/4 W resistor. Keep its leads clear of the SCL,
  SDA and RST pads, or fit it on the back. At the breakout, the fan still
  defaults to off if the wire between the boxes breaks. Fitting it across
  RX1 and GND on the carrier header also works, but a broken wire would
  then leave the fan running all the time.
- **Pins to avoid:** PWM1 (GPIO12) is a strapping pin. TX1 (GPIO17) shares
  GPIO17 with G3, the lightning detector's IRQ. The SPI pins are shared
  with the lightning detector and the SD slot. The backup is G2 (GPIO26),
  pin 4 of the 5-pin top SPI header, next to its GND. Change `PIN_PM_SET`
  in `firmware/particulates.h` if you use it.

**Checks:**

1. Before soldering, check with a meter that RX1 beeps to GPIO16.
2. With the pin undriven (old firmware, or the board held in reset), header
   SET reads under 0.1 V and the fan stops. If it reads higher, use 220 Ω.
3. With SET low, send `i`. The BME680 (0x76) must still answer: an
   unpowered PMSA003I must not hold the shared Qwiic bus. 0x12 may be
   missing while it sleeps.
4. After flashing, send `p`. The fan starts, and about 30 s later
   `pmsa003i: ready` prints. Send `s`. The report shows `pm_samples`, and
   the fan stops (`pmsa003i: sleep (fan off)`).
5. Measure battery life before and after, ideally with a current meter on
   the 3.3 V feed.
