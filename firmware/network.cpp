#include "network.h"

#include <HTTPClient.h>
#include <WiFi.h>
#include <esp_sntp.h>
#include <time.h>

// WiFi credentials and ingest token live in the gitignored secrets.h
// (issue #23); copy secrets.example.h and fill in real values.
#if __has_include("secrets.h")
#include "secrets.h"
#else
#error "firmware/secrets.h missing: copy secrets.example.h to secrets.h and fill in your values"
#endif

// NTP server; define NTP_SERVER in secrets.h to use e.g. the Pi instead.
#ifndef NTP_SERVER
#define NTP_SERVER "pool.ntp.org"
#endif

static bool linkUp = false;
static bool ntpStarted = false;
static volatile bool synced = false;
static uint32_t nextAttemptAt = 0;
static uint32_t retryDelayMs = WIFI_RETRY_MIN_MS;

static void onTimeSync(struct timeval*) { synced = true; }

static void startAttempt(uint32_t now) {
    Serial.printf("wifi: connecting to \"%s\" (next retry in %lu s)\n", WIFI_SSID,
                  (unsigned long)(retryDelayMs / 1000));
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    nextAttemptAt = now + retryDelayMs;
    retryDelayMs = min(retryDelayMs * 2, WIFI_RETRY_MAX_MS);
}

void networkInit() {
    WiFi.persistent(false);  // don't rewrite credentials to flash on every begin
    WiFi.mode(WIFI_STA);
    // Reconnects are driven from networkPoll() so the backoff is ours.
    WiFi.setAutoReconnect(false);
    startAttempt(millis());
}

void networkPoll() {
    uint32_t now = millis();
    if (WiFi.status() == WL_CONNECTED) {
        if (!linkUp) {
            linkUp = true;
            retryDelayMs = WIFI_RETRY_MIN_MS;
            Serial.printf("wifi: connected ip=%s rssi=%d\n", WiFi.localIP().toString().c_str(),
                          WiFi.RSSI());
            if (!ntpStarted) {
                // SNTP keeps running in the background and re-syncs hourly.
                ntpStarted = true;
                sntp_set_time_sync_notification_cb(onTimeSync);
                configTime(0, 0, NTP_SERVER);
                Serial.printf("ntp: started (%s)\n", NTP_SERVER);
            }
        }
        return;
    }

    if (linkUp) {
        linkUp = false;
        Serial.println("wifi: link lost");
        nextAttemptAt = now;  // first retry right away, then back off
    }
    if ((int32_t)(now - nextAttemptAt) >= 0) {
        startAttempt(now);
    }
}

bool networkConnected() { return WiFi.status() == WL_CONNECTED; }

void networkReset() {
    // networkPoll() sees the link go down, logs it, and reconnects at once.
    WiFi.disconnect();
}

int networkRssi() { return WiFi.RSSI(); }

bool clockSynced() { return synced; }

bool formatUtcAt(uint32_t uptimeMs, char* buf, size_t len) {
    if (!synced) {
        buf[0] = '\0';
        return false;
    }
    time_t at = time(nullptr) - (time_t)((millis() - uptimeMs) / 1000);
    struct tm utc;
    gmtime_r(&at, &utc);
    strftime(buf, len, "%Y-%m-%dT%H:%M:%SZ", &utc);
    return true;
}

int postReading(const char* json) {
    if (!networkConnected()) {
        return POST_NOT_CONNECTED;
    }
    HTTPClient http;
    http.setConnectTimeout(HTTP_TIMEOUT_MS);
    http.setTimeout(HTTP_TIMEOUT_MS);
    if (!http.begin(INGEST_URL)) {
        return HTTPC_ERROR_CONNECTION_REFUSED;
    }
    http.addHeader("Content-Type", "application/json");
    http.addHeader("Authorization", "Bearer " INGEST_TOKEN);
    int code = http.POST((uint8_t*)json, strlen(json));
    http.end();
    return code;
}
