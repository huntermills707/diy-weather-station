#include "power.h"

// A 1S Li-ion cell reads 3.0-4.2 V in normal use (the charger cuts off at
// 3.0 V and 4.2 V). Anything well outside that is a wiring fault, not a
// battery level.
constexpr float BATT_MIN_V = 2.5f;
constexpr float BATT_MAX_V = 4.5f;
constexpr int BATT_SAMPLES = 16;

void powerInit() {
    // CHRG and DONE are open-drain with 10k pull-ups on the charger. The
    // pull-ups' 3.3 V comes from the solar input, so with no input both
    // lines sit low (bench, 2026-10-21).
    pinMode(PIN_CHG_CHRG, INPUT);
    pinMode(PIN_CHG_DONE, INPUT);
    pinMode(PIN_BATT, INPUT);
    // 11 dB covers the 2.0-2.9 V the divided battery line swings over.
    analogSetPinAttenuation(PIN_BATT, ADC_11db);
}

float batteryVolts() {
    // analogReadMilliVolts applies the chip's factory ADC calibration.
    uint32_t sumMv = 0;
    for (int i = 0; i < BATT_SAMPLES; i++) {
        sumMv += analogReadMilliVolts(PIN_BATT);
    }
    float volts = sumMv / (float)BATT_SAMPLES / 1000.0f * BATT_DIVIDER_RATIO;
    return volts >= BATT_MIN_V && volts <= BATT_MAX_V ? volts : -1.0f;
}

const char* chargeState() {
    // The charger never pulls both low itself: both low means the pull-ups
    // are unpowered, i.e. no solar input.
    bool chrgLow = digitalRead(PIN_CHG_CHRG) == LOW;
    bool doneLow = digitalRead(PIN_CHG_DONE) == LOW;
    if (chrgLow != doneLow) {
        return chrgLow ? "charging" : "full";
    }
    return "idle";
}
