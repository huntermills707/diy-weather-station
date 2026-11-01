#pragma once

#include <Arduino.h>

// PMSA003I particulate sensor (JAE-74), on I2C at 0x12 in the auxiliary box.
// Its fan runs all the time: the SET (sleep) pin is not wired.

// One window of particulate readings, averaged over every sample taken.
struct ParticulateWindow {
    uint32_t samples;  // 0 when the sensor never answered: the values are unset
    float pm1Ugm3;     // PM1.0, PM2.5, PM10 mass, "environmental" (atmospheric)
    float pm25Ugm3;
    float pm10Ugm3;
    float particles03um;  // particles above each size per 0.1 L of air
    float particles05um;
    float particles1um;
    float particles25um;
    float particles5um;
    float particles10um;
};

void particulatesInit();

// Call every loop(): samples the sensor every few seconds, and retries a
// sensor that is not answering.
void particulatesPoll();

// Averages since the last call, and starts a new window.
ParticulateWindow particulatesTakeWindow();
