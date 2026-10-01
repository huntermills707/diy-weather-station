#include "weather_meters.h"

// Wind vane reference table: 12-bit ADC counts for each of the 16 headings,
// measured on this unit by sweeping the vane through a full revolution. The
// eight even headings are direct plateau measurements; the odd headings are
// parallel-resistor combinations, measured where the sweep caught them and
// otherwise modelled from the measured neighbours (validated by the rule that
// each odd value must read below both adjacent even values). Cross-checked
// against SparkFun's experimental ESP32 values in the Weather Meter Kit
// library (SparkFun_Weather_Meter_Kit_Constants.h): agreement within 5-8% on
// every heading. Note: 67.5 and 90 are only 26 counts apart, so those two can
// flip or read unknown in noise — inherent to the ladder's low end (GH #37).
struct VaneRef {
    int adc;
    float deg;
};

static const VaneRef VANE_REFS[] = {
    {74, 112.5f},  {150, 67.5f},   {176, 90.0f},   {303, 157.5f},  {528, 135.0f},  {774, 202.5f},
    {914, 180.0f}, {1381, 22.5f},  {1598, 45.0f},  {2154, 247.5f}, {2249, 225.0f}, {2525, 337.5f},
    {2865, 0.0f},  {3181, 292.5f}, {3393, 315.0f}, {3790, 270.0f},
};
constexpr size_t VANE_REF_COUNT = sizeof(VANE_REFS) / sizeof(VANE_REFS[0]);

// A reading is accepted only within this fraction of the gap to the nearest
// neighbouring reference; anything in the dead zone between bands is unknown.
constexpr float VANE_TOLERANCE_OF_GAP = 0.25f;

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

static int vaneMedianAdc() {
    constexpr int SAMPLES = 7;
    int readings[SAMPLES];
    for (int i = 0; i < SAMPLES; i++) {
        readings[i] = analogRead(PIN_WDIR);
        delay(2);
    }
    for (int i = 1; i < SAMPLES; i++) {
        int v = readings[i];
        int j = i - 1;
        while (j >= 0 && readings[j] > v) {
            readings[j + 1] = readings[j];
            j--;
        }
        readings[j + 1] = v;
    }
    return readings[SAMPLES / 2];
}

static float vaneDegForAdc(int adc) {
    size_t best = 0;
    int bestDist = INT_MAX;
    for (size_t i = 0; i < VANE_REF_COUNT; i++) {
        int dist = abs(adc - VANE_REFS[i].adc);
        if (dist < bestDist) {
            bestDist = dist;
            best = i;
        }
    }
    int gap = INT_MAX;
    if (best > 0) {
        gap = VANE_REFS[best].adc - VANE_REFS[best - 1].adc;
    }
    if (best + 1 < VANE_REF_COUNT) {
        gap = min(gap, VANE_REFS[best + 1].adc - VANE_REFS[best].adc);
    }
    if (bestDist > static_cast<int>(gap * VANE_TOLERANCE_OF_GAP)) {
        return -1.0f;
    }
    return VANE_REFS[best].deg;
}

float windDirectionDeg() { return vaneDegForAdc(vaneMedianAdc()); }

int windDirectionRawAdc() { return vaneMedianAdc(); }
