#include "weather_meters.h"

// A vane reading this close to full scale means the ladder is open circuit
// (vane unplugged): only the 10k pull-up is left.
constexpr int VANE_OPEN_CIRCUIT_ADC = 4090;

static volatile uint32_t rainTotal = 0;
static volatile uint32_t rainLastEdgeMs = 0;
static volatile uint32_t rainWindow = 0;

static volatile uint32_t windTotal = 0;
static volatile uint32_t windLastEdgeMs = 0;
static volatile uint32_t windLastPulseMs = 0;
static volatile uint32_t windWindow = 0;
static volatile uint32_t windMinInterval = 0;

static uint32_t windowStartMs = 0;

static void IRAM_ATTR rainIsr() {
    uint32_t now = millis();
    if (now - rainLastEdgeMs < RAIN_DEBOUNCE_MS) {
        return;
    }
    rainLastEdgeMs = now;
    rainTotal++;
    rainWindow++;
}

static void IRAM_ATTR windIsr() {
    uint32_t now = millis();
    if (now - windLastEdgeMs < WIND_DEBOUNCE_MS) {
        return;
    }
    windLastEdgeMs = now;
    if (windLastPulseMs != 0) {
        uint32_t interval = now - windLastPulseMs;
        if (windMinInterval == 0 || interval < windMinInterval) {
            windMinInterval = interval;
        }
    }
    windLastPulseMs = now;
    windTotal++;
    windWindow++;
}

void weatherMetersInit() {
    // The carrier provides 43k pull-ups on both digital lines; the vane
    // ladder uses its 10k pull-up, so no internal pull-ups here.
    pinMode(PIN_RAIN, INPUT);
    pinMode(PIN_WSPEED, INPUT);
    pinMode(PIN_WDIR, INPUT);

    analogReadResolution(12);
    analogSetPinAttenuation(PIN_WDIR, ADC_11db);

    attachInterrupt(digitalPinToInterrupt(PIN_RAIN), rainIsr, FALLING);
    attachInterrupt(digitalPinToInterrupt(PIN_WSPEED), windIsr, FALLING);

    windowStartMs = millis();
}

uint32_t rainTipsTotal() { return rainTotal; }

uint32_t windClosuresTotal() { return windTotal; }

WindRainWindow windRainTakeWindow() {
    // On dual-core ESP32, noInterrupts() only masks interrupts on the calling
    // core. That suffices here only because the ISRs and this function both
    // run on the Arduino core (attached from setup(), called from loop()); a
    // future FreeRTOS task calling this from the other core would need a real
    // critical section instead.
    noInterrupts();
    WindRainWindow w;
    w.rainTips = rainWindow;
    w.rainTipsTotal = rainTotal;
    w.windClosures = windWindow;
    w.windMinIntervalMs = windMinInterval;
    rainWindow = 0;
    windWindow = 0;
    windMinInterval = 0;
    // Clear the last-pulse timestamp too: intervals must be measured only
    // between closures within this window, otherwise a lone closure would
    // inherit a minutes-long stale gap from the previous window and violate
    // the "windMinIntervalMs == 0 means fewer than two closures" contract.
    windLastPulseMs = 0;
    interrupts();

    uint32_t now = millis();
    w.durationMs = now - windowStartMs;
    windowStartMs = now;
    return w;
}

int windDirectionRawAdc() {
    // Average a few reads to smooth ESP32 ADC noise.
    constexpr int SAMPLES = 8;
    int sum = 0;
    for (int i = 0; i < SAMPLES; i++) {
        sum += analogRead(PIN_WDIR);
    }
    return sum / SAMPLES;
}

float windDirectionDeg(int rawAdc) {
    if (rawAdc >= VANE_OPEN_CIRCUIT_ADC) {
        return -1.0f;
    }
    // Closest calibrated value wins, like SparkFun's Weather Meter Kit library.
    int best = 0;
    for (int i = 1; i < 16; i++) {
        if (abs(rawAdc - VANE_ADC[i]) < abs(rawAdc - VANE_ADC[best])) {
            best = i;
        }
    }
    return fmodf(best * 22.5f + VANE_OFFSET_DEG + 360.0f, 360.0f);
}
