#pragma once

#include <Arduino.h>

// PMSA003I particulate sensor (JAE-74), on I2C at 0x12 in the auxiliary box.
//
// Its fan draws about 100 mA, so it runs only in a short burst at the end of
// each five-minute window (JAE-81): the breakout's SET pin is wired to
// GPIO16 (carrier RX1), with an external 330 ohm pull-down. SET high wakes
// the sensor, low puts it to sleep. The pull-down keeps the fan off whenever
// the ESP32 is not driving the pin: during reset, boot, and deep sleep.
//
// While asleep the sensor may not answer I2C at all (SET low probably also
// shuts off the breakout's 5 V boost), so it is only probed and read inside
// a burst.
constexpr uint8_t PIN_PM_SET = 16;  // carrier RX1 -> PMSA003I breakout SET

// One window of particulate readings, averaged over every sample taken.
struct ParticulateWindow {
    // True when the burst reached its read phase this window. False when the
    // window was cut short before that (e.g. an early `s` report): the sensor
    // was never asked, which is not an error.
    bool attempted;
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

// Drives SET low (fan off). Call early in setup().
void particulatesInit();

// Call every loop() with the time the current window closes: wakes the
// sensor in time for the burst to end at the close, and samples it during
// the burst's read phase.
void particulatesPoll(uint32_t windowClosesAt);

// Starts a burst now, whatever the window (the `p` serial command), to check
// the fan and the I2C link without waiting. It ends when the window closes.
void particulatesWakeNow();

// Puts the sensor to sleep (fan off), e.g. before deep sleep.
void particulatesSleep();

// Averages since the last call, puts the sensor to sleep, and starts a new
// window.
ParticulateWindow particulatesTakeWindow();
