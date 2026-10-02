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
// 0, 22.5, 45, ... 337.5 degrees. Field procedure: stream raw counts with the
// `c` serial command, point the vane at each heading, and write the count
// here. The heading reported is the closest entry.
constexpr int VANE_ADC[16] = {
    3118,  // 0.0   N
    1526,  // 22.5  NNE
    1761,  // 45.0  NE
    199,   // 67.5  ENE
    237,   // 90.0  E
    123,   // 112.5 ESE
    613,   // 135.0 SE
    371,   // 157.5 SSE
    1040,  // 180.0 S
    859,   // 202.5 SSW
    2451,  // 225.0 SW
    2329,  // 247.5 WSW
    3984,  // 270.0 W
    3290,  // 292.5 WNW
    3616,  // 315.0 NW
    2755,  // 337.5 NNW
};

// Added to the vane heading, for a station mounted with its "N" mark not
// facing true north (e.g. N mark faces east -> 90).
constexpr float VANE_OFFSET_DEG = 0.0f;
