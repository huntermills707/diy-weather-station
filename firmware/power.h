#pragma once

#include <Arduino.h>

#include "calibration.h"

// Charger status header (WatangTech 5V solar charger, a rebrand of the
// Seengreat Solar Energy Manager C), wired to the carrier's unused soil
// moisture terminal and PWM0 header. Pin numbers per the esp32micromod
// variant pins_arduino.h. Avoid PWM1 (GPIO12): it is a strapping pin, and
// a status line pulled high at boot would select 1.8 V flash.
constexpr uint8_t PIN_BATT = 34;      // carrier A0, soil terminal SIG <- charger V_BAT
constexpr uint8_t PIN_CHG_DONE = 15;  // carrier G0, soil terminal PWR <- charger DONE
constexpr uint8_t PIN_CHG_CHRG = 13;  // carrier PWM0, top PTH header <- charger CHRG

// Low-battery shutoff (JAE-81). On 2026-11-04 the battery ran flat and the
// ESP32 hung, powered, until someone pressed reset, even after the panel had
// recharged the battery. So the station stops before the battery runs flat:
// below BATT_SLEEP_V it deep-sleeps (fan off, no readings), waking every
// LOW_BATT_WAKE_MIN minutes to check, and resumes at BATT_RESUME_V. The gap
// between the two stops it cycling on and off around one voltage. Both are
// approximate: BATT_DIVIDER_RATIO was calibrated against the charger, not a
// multimeter.
constexpr float BATT_SLEEP_V = 3.3f;
constexpr float BATT_RESUME_V = 3.6f;
// Readings in a row below BATT_SLEEP_V before sleeping, so one noisy read
// (e.g. during a WiFi transmit) doesn't put the station to sleep.
constexpr uint32_t LOW_BATT_READINGS = 2;
constexpr uint32_t LOW_BATT_WAKE_MIN = 20;
// Before sleeping, how long to keep trying to upload queued readings (the
// queue lives in RAM and deep sleep empties it).
constexpr uint32_t LOW_BATT_FLUSH_MS = 20000;

void powerInit();

// Battery voltage, or -1.0f when the reading is outside a plausible Li-ion
// range (e.g. the V_BAT wire is off).
float batteryVolts();

// "charging" (only CHRG low), "full" (only DONE low), or "idle" (anything
// else: no solar input, or input too weak to charge).
const char* chargeState();
