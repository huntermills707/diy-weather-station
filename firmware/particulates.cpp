#include "particulates.h"

#include <Adafruit_PM25AQI.h>
#include <Wire.h>

// Each burst: wake, let the fan run WARMUP_MS (the datasheet asks for at least
// 30 s after waking before readings are stable, and the fan flushes the
// chamber with fresh air), then sample every SAMPLE_MS for READ_MS. The burst
// ends when the window closes, so the fan runs about 40 s of every 300 s.
constexpr uint32_t WARMUP_MS = 30000;
constexpr uint32_t READ_MS = 10000;
constexpr uint32_t BURST_MS = WARMUP_MS + READ_MS;
// The sensor refreshes its data every 0.2-2.3 s, so ~5 samples per burst.
constexpr uint32_t SAMPLE_MS = 2000;

// Rebuilt for every probe: the library's begin_I2C() fails on any call
// after the first, even when that first one failed.
static Adafruit_PM25AQI* pmsa003i = nullptr;
static bool sensorOk = false;
static bool awake = false;
static uint32_t nextSampleAt = 0;     // the first is WARMUP_MS after waking
static bool probeErrorShown = false;  // one "no response" line per burst
static ParticulateWindow window = {};

static void beginSensor() {
    delete pmsa003i;
    pmsa003i = new Adafruit_PM25AQI();
    sensorOk = pmsa003i->begin_I2C(&Wire);
    if (sensorOk) {
        Serial.println("pmsa003i: ready");
    } else if (!probeErrorShown) {
        Serial.println("pmsa003i: ERROR no response at 0x12");
        probeErrorShown = true;
    }
}

static void wake(uint32_t now) {
    digitalWrite(PIN_PM_SET, HIGH);
    awake = true;
    nextSampleAt = now + WARMUP_MS;
    probeErrorShown = false;
    Serial.println("pmsa003i: wake (fan on)");
}

void particulatesInit() {
    // The external pull-down has held SET low through reset and boot; from
    // here the pin drives it.
    pinMode(PIN_PM_SET, OUTPUT);
    digitalWrite(PIN_PM_SET, LOW);
}

void particulatesSleep() {
    digitalWrite(PIN_PM_SET, LOW);
    if (awake) {
        Serial.println("pmsa003i: sleep (fan off)");
    }
    awake = false;
}

void particulatesWakeNow() {
    if (awake) {
        Serial.println("pmsa003i: already awake");
        return;
    }
    wake(millis());
}

void particulatesPoll(uint32_t windowClosesAt) {
    uint32_t now = millis();
    if (!awake) {
        if ((int32_t)(now - (windowClosesAt - BURST_MS)) >= 0) {
            wake(now);
        }
        return;
    }
    if ((int32_t)(now - nextSampleAt) < 0) {
        return;
    }
    nextSampleAt = now + SAMPLE_MS;
    window.attempted = true;

    if (!sensorOk) {
        beginSensor();  // first burst since boot, or after a burst with no samples
        if (!sensorOk) {
            return;
        }
    }
    PM25_AQI_Data data;
    if (!pmsa003i->read(&data)) {
        return;  // no answer or a bad checksum: skip this sample
    }
    window.samples++;
    window.pm1Ugm3 += data.pm10_env;
    window.pm25Ugm3 += data.pm25_env;
    window.pm10Ugm3 += data.pm100_env;
    window.particles03um += data.particles_03um;
    window.particles05um += data.particles_05um;
    window.particles1um += data.particles_10um;
    window.particles25um += data.particles_25um;
    window.particles5um += data.particles_50um;
    window.particles10um += data.particles_100um;
}

ParticulateWindow particulatesTakeWindow() {
    particulatesSleep();
    ParticulateWindow w = window;
    window = {};
    if (w.samples == 0) {
        if (w.attempted) {
            // Awake for the read phase and still no reading: probe afresh in
            // the next burst (e.g. the auxiliary box's cable was reseated).
            sensorOk = false;
        }
        return w;
    }
    float n = (float)w.samples;
    w.pm1Ugm3 /= n;
    w.pm25Ugm3 /= n;
    w.pm10Ugm3 /= n;
    w.particles03um /= n;
    w.particles05um /= n;
    w.particles1um /= n;
    w.particles25um /= n;
    w.particles5um /= n;
    w.particles10um /= n;
    return w;
}
