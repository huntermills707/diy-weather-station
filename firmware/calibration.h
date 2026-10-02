#pragma once

// Field calibration: every value you may need to adjust after mounting the
// station lives in this file. Defaults are SparkFun's published values
// (SparkFun_Weather_Meter_Kit_Arduino_Library, ESP32 on the Weather Carrier).
// See docs/sensors.md for the one-time field procedure.

// Rain gauge: one bucket tip = 0.011" of rain (SEN-08942 datasheet).
constexpr float RAIN_MM_PER_TIP = 0.2794f;

// Anemometer: one switch closure per second = 2.4 km/h (1.492 mph).
constexpr float WIND_KMH_PER_HZ = 2.4f;

// Wind vane: raw 12-bit ADC count for each heading, in heading order
// 0, 22.5, 45, ... 337.5 degrees. The heading reported is the closest entry.
// Field procedure: stream raw counts with the `c` serial command, point the
// vane at each heading, and write the count here.
//
// Calibrated on this unit 2026-10-02: the eight main headings were measured
// in a sweep; the in-between headings won't hold still, so they are this
// unit's earlier bench values (each sits below both neighbours, as the
// resistor ladder requires). SparkFun's ESP32 defaults read ~8% high here.
constexpr int VANE_ADC[16] = {
    2867,  // 0.0   N
    1381,  // 22.5  NNE
    1599,  // 45.0  NE
    150,   // 67.5  ENE
    176,   // 90.0  E
    74,    // 112.5 ESE
    529,   // 135.0 SE
    303,   // 157.5 SSE
    915,   // 180.0 S
    774,   // 202.5 SSW
    2249,  // 225.0 SW
    2154,  // 247.5 WSW
    3794,  // 270.0 W
    3181,  // 292.5 WNW
    3393,  // 315.0 NW
    2525,  // 337.5 NNW
};

// Added to the vane heading, for a station mounted with its "N" mark not
// facing true north (e.g. N mark faces east -> 90).
constexpr float VANE_OFFSET_DEG = 0.0f;
