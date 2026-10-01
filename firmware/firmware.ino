#include <Arduino.h>
#include <SparkFunBME280.h>
#include <Wire.h>

#include "weather_meters.h"

// Collection cadence per ADR 0001: one reading every five minutes.
constexpr uint32_t SAMPLE_WINDOW_MS = 5UL * 60UL * 1000UL;
constexpr uint32_t LIVE_WIND_PRINT_MS = 1000;
constexpr uint32_t VANE_CAL_PRINT_MS = 500;

BME280 bme280;
bool bme280Ok = false;
bool vaneCalMode = false;

uint32_t nextWindowAt = 0;
uint32_t nextWindPrintAt = 0;
uint32_t nextCalPrintAt = 0;
uint32_t lastRainSeen = 0;
uint32_t lastWindSeen = 0;

static void beginBme280() {
    // Carrier BME280 sits at I2C address 0x77 (the library default).
    bme280Ok = bme280.beginI2C(Wire);
    Serial.println(bme280Ok ? "bme280: ready" : "bme280: ERROR no response at 0x77");
}

static bool plausible(float tempC, float pressPa, float rh) {
    return tempC > -40.0f && tempC < 85.0f && pressPa > 30000.0f && pressPa < 110000.0f &&
           rh >= 0.0f && rh <= 100.0f;
}

static void printReport() {
    WindRainWindow w = windRainTakeWindow();
    nextWindowAt = millis() + SAMPLE_WINDOW_MS;

    float windAvgKmh = 0.0f;
    if (w.durationMs > 0) {
        windAvgKmh = w.windClosures * WIND_KMH_PER_HZ * 1000.0f / w.durationMs;
    }
    // With fewer than two closures in the window there is no measurable
    // interval, so peak falls back to the (near-zero) average.
    float windPeakKmh =
        w.windMinIntervalMs > 0 ? WIND_KMH_PER_HZ * 1000.0f / w.windMinIntervalMs : windAvgKmh;

    float windDir = windDirectionDeg();

    Serial.printf("report t=%lu window_s=%lu rain_tips=%lu rain_mm=%.2f rain_total=%lu ",
                  (unsigned long)millis(), (unsigned long)(w.durationMs / 1000), w.rainTips,
                  w.rainTips * RAIN_MM_PER_TIP, w.rainTipsTotal);
    Serial.printf("wind_avg_kmh=%.1f wind_peak_kmh=%.1f ", windAvgKmh, windPeakKmh);
    if (windDir >= 0.0f) {
        Serial.printf("wind_dir_deg=%.1f ", windDir);
    } else {
        Serial.print("wind_dir_deg=unknown ");
    }

    if (!bme280Ok) {
        beginBme280();  // retry a sensor that failed at boot
    }
    if (bme280Ok) {
        float tempC = bme280.readTempC();
        float pressHpa = bme280.readFloatPressure() / 100.0f;
        float rh = bme280.readFloatHumidity();
        if (plausible(tempC, pressHpa * 100.0f, rh)) {
            Serial.printf("temp_c=%.2f rh_pct=%.1f press_hpa=%.1f bme280=ok", tempC, rh, pressHpa);
        } else {
            Serial.print("bme280=implausible");
        }
    } else {
        Serial.print("bme280=error");
    }
    Serial.println();
}

static void printHelp() {
    Serial.println("commands: s=sample report now, c=toggle vane calibration, h=help");
}

static void handleSerial() {
    while (Serial.available() > 0) {
        char c = (char)Serial.read();
        switch (c) {
            case 's':
                printReport();
                break;
            case 'c':
                vaneCalMode = !vaneCalMode;
                Serial.println(vaneCalMode ? "vane calibration on" : "vane calibration off");
                break;
            case 'h':
                printHelp();
                break;
            default:
                break;  // ignore newlines and anything else
        }
    }
}

void setup() {
    Serial.begin(115200);
    delay(1000);  // let USB-serial settle before first print
    Serial.println("weather station firmware up");
    printHelp();

    Wire.begin();
    beginBme280();
    weatherMetersInit();

    nextWindowAt = millis() + SAMPLE_WINDOW_MS;
}

void loop() {
    handleSerial();

    uint32_t rainNow = rainTipsTotal();
    if (rainNow != lastRainSeen) {
        lastRainSeen = rainNow;
        Serial.printf("event: rain tip #%lu t=%lu (%.2f mm since boot)\n", (unsigned long)rainNow,
                      (unsigned long)millis(), rainNow * RAIN_MM_PER_TIP);
    }

    uint32_t now = millis();

    if (now >= nextWindPrintAt) {
        nextWindPrintAt = now + LIVE_WIND_PRINT_MS;
        uint32_t windNow = windClosuresTotal();
        uint32_t delta = windNow - lastWindSeen;
        lastWindSeen = windNow;
        if (delta > 0) {
            Serial.printf("wind: %lu closures last second (~%.1f km/h)\n", (unsigned long)delta,
                          delta * WIND_KMH_PER_HZ);
        }
    }

    if (vaneCalMode && now >= nextCalPrintAt) {
        nextCalPrintAt = now + VANE_CAL_PRINT_MS;
        int adc = windDirectionRawAdc();
        float deg = windDirectionDeg();
        if (deg >= 0.0f) {
            Serial.printf("vane adc=%d dir=%.1f\n", adc, deg);
        } else {
            Serial.printf("vane adc=%d dir=unknown\n", adc);
        }
    }

    if (now >= nextWindowAt) {
        printReport();
    }
}
