#pragma once

#include <Arduino.h>

#include "calibration.h"

// Pin mapping for the SparkFun MicroMod Weather Carrier Board + ESP32
// processor, per the esp32micromod variant pins_arduino.h (NOT the weather
// carrier hookup-guide sketch, which wrongly uses GPIO 23 for D0).
constexpr uint8_t PIN_RAIN = 27;    // carrier D1, RJ11 "RAIN" jack
constexpr uint8_t PIN_WSPEED = 14;  // carrier D0, RJ11 "WIND" jack
constexpr uint8_t PIN_WDIR = 35;    // carrier A1, RJ11 "WIND" jack (analog ladder)

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

// Averaged raw vane ADC count (0..4095); used for field calibration.
int windDirectionRawAdc();

// Heading in degrees (closest VANE_ADC entry plus VANE_OFFSET_DEG), or -1.0f
// when the vane reads open circuit (unplugged) or shorted to ground.
float windDirectionDeg(int rawAdc);
