#include <Arduino.h>
#include <Preferences.h>
#include <SparkFunBME280.h>
#include <Wire.h>
#include <esp_random.h>
#include <esp_task_wdt.h>

#include "network.h"
#include "reading.h"
#include "upload_queue.h"
#include "weather_meters.h"

// Identifies this station's readings on the server (docs/ingest-api.md).
constexpr char STATION_ID[] = "station-1";

// Collection cadence per ADR 0001: one reading every five minutes.
constexpr uint32_t SAMPLE_WINDOW_MS = 5UL * 60UL * 1000UL;
constexpr uint32_t LIVE_WIND_PRINT_MS = 1000;
constexpr uint32_t CAL_PRINT_MS = 500;

// Task watchdog (JAE-62): if loop() stops running for this long, the ESP32
// panics and reboots. The slowest legitimate step is one POST, bounded at
// about 2 x HTTP_TIMEOUT_MS.
constexpr uint32_t WATCHDOG_TIMEOUT_S = 30;

BME280 bme280;
bool bme280Ok = false;
bool calMode = false;

// reading_id = "<bootId>-<readingSeq>": random per boot, counting per reading,
// so retries reuse it and gaps or reboots show up on the server.
uint32_t bootId = 0;
uint32_t readingSeq = 0;

// Reboot telemetry sent with every reading, so resets are diagnosable on the
// server: a lifetime boot counter kept in flash, and why this boot happened.
uint32_t bootCount = 0;
const char* resetReason = "unknown";

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

static const char* resetReasonText(esp_reset_reason_t reason) {
    switch (reason) {
        case ESP_RST_POWERON:
            return "power_on";
        case ESP_RST_EXT:
            return "external";
        case ESP_RST_SW:
            return "software";
        case ESP_RST_PANIC:
            return "panic";
        case ESP_RST_INT_WDT:
            return "int_watchdog";
        case ESP_RST_TASK_WDT:
            return "task_watchdog";
        case ESP_RST_WDT:
            return "watchdog";
        case ESP_RST_DEEPSLEEP:
            return "deep_sleep";
        case ESP_RST_BROWNOUT:
            return "brownout";
        default:
            return "unknown";
    }
}

// Counts this boot in NVS. One small write per boot is no flash-wear concern.
static uint32_t countBoot() {
    Preferences prefs;
    prefs.begin("station", false);
    uint32_t count = prefs.getUInt("boots", 0) + 1;
    prefs.putUInt("boots", count);
    prefs.end();
    return count;
}

static bool plausible(float tempC, float pressPa, float rh) {
    return tempC > -40.0f && tempC < 85.0f && pressPa > 30000.0f && pressPa < 110000.0f &&
           rh >= 0.0f && rh <= 100.0f;
}

// Closes the current rain/wind window and samples every sensor.
static Reading takeReading() {
    WindRainWindow w = windRainTakeWindow();
    nextWindowAt = millis() + SAMPLE_WINDOW_MS;

    Reading r = {};
    snprintf(r.readingId, sizeof(r.readingId), "%08lx-%lu", (unsigned long)bootId,
             (unsigned long)++readingSeq);
    r.uptimeMs = millis();
    formatUtcAt(r.uptimeMs, r.deviceTime, sizeof(r.deviceTime));
    // Rounded, and at least 1 s so an immediate `s` still sends a valid window.
    r.windowS = max<uint32_t>(1, (w.durationMs + 500) / 1000);
    r.rainTips = w.rainTips;
    r.rainTipsTotal = w.rainTipsTotal;
    r.rainMm = w.rainTips * RAIN_MM_PER_TIP;

    if (w.durationMs > 0) {
        r.windAvgKmh = w.windClosures * WIND_KMH_PER_HZ * 1000.0f / w.durationMs;
    }
    // With fewer than two closures in the window there is no measurable
    // interval, so peak falls back to the (near-zero) average.
    r.windPeakKmh =
        w.windMinIntervalMs > 0 ? WIND_KMH_PER_HZ * 1000.0f / w.windMinIntervalMs : r.windAvgKmh;
    r.windDirDeg = windDirectionDeg(windDirectionRawAdc());

    if (!bme280Ok) {
        beginBme280();  // retry a sensor that failed at boot
    }
    r.bme280 = "error";
    if (bme280Ok) {
        r.tempC = bme280.readTempC();
        r.pressHpa = bme280.readFloatPressure() / 100.0f;
        r.rhPct = bme280.readFloatHumidity();
        r.bme280 = plausible(r.tempC, r.pressHpa * 100.0f, r.rhPct) ? "ok" : "implausible";
    }

    r.rssiValid = networkConnected();
    r.rssiDbm = r.rssiValid ? networkRssi() : 0;
    r.bootCount = bootCount;
    r.resetReason = resetReason;
    r.queueDropped = uploadQueueDropped();
    return r;
}

static void printReading(const Reading& r) {
    Serial.printf(
        "report id=%s time=%s t=%lu window_s=%lu rain_tips=%lu rain_mm=%.2f "
        "rain_total=%lu ",
        r.readingId, r.deviceTime[0] != '\0' ? r.deviceTime : "unsynced", (unsigned long)r.uptimeMs,
        (unsigned long)r.windowS, (unsigned long)r.rainTips, r.rainMm,
        (unsigned long)r.rainTipsTotal);
    Serial.printf("wind_avg_kmh=%.1f wind_peak_kmh=%.1f ", r.windAvgKmh, r.windPeakKmh);
    if (r.windDirDeg >= 0.0f) {
        Serial.printf("wind_dir_deg=%.1f ", r.windDirDeg);
    } else {
        Serial.print("wind_dir_deg=unknown ");
    }
    if (strcmp(r.bme280, "ok") == 0) {
        Serial.printf("temp_c=%.2f rh_pct=%.1f press_hpa=%.1f ", r.tempC, r.rhPct, r.pressHpa);
    }
    Serial.printf("bme280=%s", r.bme280);
    if (r.rssiValid) {
        Serial.printf(" rssi_dbm=%d", r.rssiDbm);
    }
    Serial.println();
}

static void report() {
    Reading r = takeReading();
    printReading(r);
    // Sent by uploadQueuePoll(), right away unless older readings are waiting.
    uploadQueuePush(r);
}

static void printHelp() {
    Serial.println(
        "commands: s=sample report now, q=upload queue status, c=toggle calibration stream, "
        "x=hang (watchdog test), h=help");
}

static void handleSerial() {
    while (Serial.available() > 0) {
        char c = (char)Serial.read();
        switch (c) {
            case 's':
                report();
                break;
            case 'c':
                calMode = !calMode;
                if (calMode) {
                    // Refresh the schedule so the stream starts promptly even
                    // after long uptime (stale 0 goes negative past 24.8 days
                    // under the wrap-safe comparison).
                    nextCalPrintAt = millis();
                }
                Serial.println(calMode ? "calibration stream on" : "calibration stream off");
                break;
            case 'q':
                uploadQueuePrintStatus();
                break;
            case 'x':
                // Stops loop() so the watchdog fires; the next boot reports
                // reset_reason=task_watchdog.
                Serial.printf("hanging: the watchdog should reboot in %lu s\n",
                              (unsigned long)WATCHDOG_TIMEOUT_S);
                for (;;) {
                }
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
    bootCount = countBoot();
    resetReason = resetReasonText(esp_reset_reason());
    Serial.printf("boot #%lu, reset reason %s\n", (unsigned long)bootCount, resetReason);
    printHelp();

    Wire.begin();
    beginBme280();
    weatherMetersInit();

    networkInit();
    // After networkInit: with the radio on, esp_random() is a true RNG.
    bootId = esp_random();
    Serial.printf("boot id %08lx\n", (unsigned long)bootId);
    uploadQueueInit(STATION_ID);

    nextWindowAt = millis() + SAMPLE_WINDOW_MS;

    // The core already runs the task watchdog for its idle tasks; this
    // lengthens the timeout, makes it reboot, and adds loop() to it.
    esp_task_wdt_init(WATCHDOG_TIMEOUT_S, true);
    esp_task_wdt_add(nullptr);
}

void loop() {
    esp_task_wdt_reset();
    handleSerial();
    networkPoll();
    uploadQueuePoll();

    uint32_t rainNow = rainTipsTotal();
    if (rainNow != lastRainSeen) {
        lastRainSeen = rainNow;
        Serial.printf("event: rain tip #%lu t=%lu (%.2f mm since boot)\n", (unsigned long)rainNow,
                      (unsigned long)millis(), rainNow * RAIN_MM_PER_TIP);
    }

    uint32_t now = millis();

    // All three schedulers use signed-difference comparisons so millis()
    // rollover (~49.7 days) doesn't stall reporting — same wrap-safe pattern
    // the ISRs already use for debounce.
    if ((int32_t)(now - nextWindPrintAt) >= 0) {
        nextWindPrintAt = now + LIVE_WIND_PRINT_MS;
        uint32_t windNow = windClosuresTotal();
        uint32_t delta = windNow - lastWindSeen;
        lastWindSeen = windNow;
        if (delta > 0) {
            Serial.printf("wind: %lu closures last second (~%.1f km/h)\n", (unsigned long)delta,
                          delta * WIND_KMH_PER_HZ);
        }
    }

    if (calMode && (int32_t)(now - nextCalPrintAt) >= 0) {
        nextCalPrintAt = now + CAL_PRINT_MS;
        int vaneAdc = windDirectionRawAdc();
        float deg = windDirectionDeg(vaneAdc);
        if (deg >= 0.0f) {
            Serial.printf("cal vane_adc=%d dir=%.1f\n", vaneAdc, deg);
        } else {
            Serial.printf("cal vane_adc=%d dir=unknown\n", vaneAdc);
        }
    }

    if ((int32_t)(now - nextWindowAt) >= 0) {
        report();
    }
}
