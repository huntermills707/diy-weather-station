#pragma once

#include <Arduino.h>

// One five-minute reading, as printed on serial and POSTed to the ingest
// service. Field meanings and units: docs/ingest-api.md and docs/sensors.md.
struct Reading {
    char readingId[24];   // "<boot_id>-<seq>", fixed when the reading is taken
    char deviceTime[24];  // UTC "YYYY-MM-DDTHH:MM:SSZ"; empty when not NTP-synced
    uint32_t uptimeMs;
    uint32_t windowS;
    uint32_t rainTips;
    uint32_t rainTipsTotal;  // serial only; resets on reboot
    float rainMm;
    float windAvgKmh;
    float windPeakKmh;
    float windDirDeg;    // < 0 when the vane is open or shorted
    const char* bme280;  // "ok", "implausible", or "error"
    float tempC;         // these three are valid only when bme280 is "ok"
    float rhPct;
    float pressHpa;
    bool rssiValid;
    int rssiDbm;
    // Reboot and queue telemetry (JAE-60, JAE-62), fixed when the reading is
    // taken.
    uint32_t bootCount;       // boots since flashing, from NVS
    const char* resetReason;  // why the last boot happened, e.g. "task_watchdog"
    uint32_t queueDropped;    // readings dropped by queue overflow since boot
};

// Writes the ingest JSON body for `r`, sent as station `stationId`.
// Returns false if it did not fit in `len`.
bool readingToJson(const Reading& r, const char* stationId, char* buf, size_t len);
