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

void powerInit();

// Battery voltage, or -1.0f when the reading is outside a plausible Li-ion
// range (e.g. the V_BAT wire is off).
float batteryVolts();

// "charging" (CHRG low), "full" (DONE low), "idle" (neither: no solar input),
// or "unknown" (both low, which the charger never does on its own).
const char* chargeState();
