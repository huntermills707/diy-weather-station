#include "particulates.h"

#include <Adafruit_PM25AQI.h>
#include <Wire.h>

// The sensor updates about once a second; a sample every 10 s gives ~30 per
// five-minute window, plenty to smooth its noise.
constexpr uint32_t SAMPLE_MS = 10000;
// The datasheet asks for 30 s after power-up before readings are stable.
constexpr uint32_t WARMUP_MS = 30000;

// Rebuilt for every probe: the library's begin_I2C() fails on any call
// after the first, even when that first one failed.
static Adafruit_PM25AQI* pmsa003i = nullptr;
static bool sensorOk = false;
static uint32_t nextSampleAt = 0;
static ParticulateWindow window = {};

static void beginSensor() {
    delete pmsa003i;
    pmsa003i = new Adafruit_PM25AQI();
    sensorOk = pmsa003i->begin_I2C(&Wire);
    Serial.println(sensorOk ? "pmsa003i: ready" : "pmsa003i: ERROR no response at 0x12");
}

void particulatesInit() {
    beginSensor();
    nextSampleAt = millis() + WARMUP_MS;
}

void particulatesPoll() {
    uint32_t now = millis();
    if ((int32_t)(now - nextSampleAt) < 0) {
        return;
    }
    nextSampleAt = now + SAMPLE_MS;

    if (!sensorOk) {
        beginSensor();  // e.g. the auxiliary box's cable was reseated
        return;
    }
    PM25_AQI_Data data;
    if (!pmsa003i->read(&data)) {
        return;  // no fresh frame or a bad checksum: skip this sample
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
    ParticulateWindow w = window;
    window = {};
    if (w.samples == 0) {
        // Not even a single read in a whole window: probe the sensor afresh.
        sensorOk = false;
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
