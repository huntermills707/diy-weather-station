#pragma once

#include <Arduino.h>

// Pin mapping for the SparkFun MicroMod Weather Carrier Board + ESP32
// processor, per the esp32micromod variant pins_arduino.h (NOT the weather
// carrier hookup-guide sketch, which wrongly uses GPIO 23 for D0).
constexpr uint8_t PIN_RAIN = 27;    // carrier D1, RJ11 "RAIN" jack
constexpr uint8_t PIN_WSPEED = 14;  // carrier D0, RJ11 "WIND" jack
constexpr uint8_t PIN_WDIR = 35;    // carrier A1, RJ11 "WIND" jack (analog ladder)

// Conversion constants for the SparkFun Weather Meter Kit (SEN-08942
// datasheet): one bucket tip is 0.011" of rain, and one anemometer closure
// per second corresponds to 2.4 km/h (1.492 mph).
constexpr float RAIN_MM_PER_TIP = 0.2794f;
constexpr float WIND_KMH_PER_HZ = 2.4f;

// Software debounce windows. Both digital lines already have hardware RC
// filtering on the carrier (43k pull-up + 0.1uF to ground), but bench testing
// showed the rain bucket's reed produces a second edge 18-34 ms after each
// real tip as the mechanism settles. 100 ms rejects that phantom edge with
// ~3x margin, while still accepting tips 10x faster than the bucket can
// physically tip. The anemometer needs a much shorter window: at 2.4 km/h per
// Hz, 5 ms still resolves gusts beyond 200 km/h.
constexpr uint32_t RAIN_DEBOUNCE_MS = 100;
constexpr uint32_t WIND_DEBOUNCE_MS = 5;

struct WindRainWindow {
    uint32_t durationMs;         // actual length of the window
    uint32_t rainTips;           // bucket tips during the window
    uint32_t rainTipsTotal;      // cumulative tips since boot
    uint32_t windClosures;       // anemometer closures during the window
    uint32_t windMinIntervalMs;  // shortest gap between closures; 0 if fewer than 2
};

void weatherMetersInit();

// Cumulative counters since boot, for live event prints.
uint32_t rainTipsTotal();
uint32_t windClosuresTotal();

// Atomically snapshots the per-window counters and resets them. The returned
// duration is measured from the previous call (or from init).
WindRainWindow windRainTakeWindow();

// Median-filtered wind vane heading in degrees (0/22.5/.../337.5), or -1.0f
// when the ADC reading falls outside every reference band.
float windDirectionDeg();

// Raw ADC count (0..4095) for vane calibration.
int windDirectionRawAdc();
