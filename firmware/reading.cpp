#include "reading.h"

#include <math.h>
#include <string.h>

bool readingToJson(const Reading& r, const char* stationId, char* buf, size_t len) {
    bool bmeOk = strcmp(r.bme280, "ok") == 0;

    // Optional values are formatted first so the main printf stays readable.
    // Invalid states become JSON null, never a placeholder number.
    char deviceTime[28] = "null";
    char windDir[12] = "null";
    char tempC[12] = "null";
    char rhPct[12] = "null";
    char pressHpa[12] = "null";
    char rssi[8] = "null";
    if (r.deviceTime[0] != '\0') {
        snprintf(deviceTime, sizeof(deviceTime), "\"%s\"", r.deviceTime);
    }
    if (r.windDirDeg >= 0.0f) {
        // Round before printing so e.g. 359.97 is sent as 0.0, not 360.0
        // (the server accepts 0 <= heading < 360).
        float deg = roundf(r.windDirDeg * 10.0f) / 10.0f;
        snprintf(windDir, sizeof(windDir), "%.1f", deg >= 360.0f ? deg - 360.0f : deg);
    }
    if (bmeOk) {
        snprintf(tempC, sizeof(tempC), "%.2f", r.tempC);
        snprintf(rhPct, sizeof(rhPct), "%.1f", r.rhPct);
        snprintf(pressHpa, sizeof(pressHpa), "%.1f", r.pressHpa);
    }
    if (r.rssiValid) {
        snprintf(rssi, sizeof(rssi), "%d", r.rssiDbm);
    }

    int n = snprintf(buf, len,
                     "{\"station_id\":\"%s\",\"reading_id\":\"%s\",\"device_time\":%s,"
                     "\"uptime_ms\":%lu,\"window_s\":%lu,\"rain_tips\":%lu,\"rain_mm\":%.2f,"
                     "\"wind_avg_kmh\":%.1f,\"wind_peak_kmh\":%.1f,\"wind_dir_deg\":%s,"
                     "\"temp_c\":%s,\"rh_pct\":%s,\"press_hpa\":%s,\"bme280\":\"%s\","
                     "\"rssi_dbm\":%s,\"boot_count\":%lu,\"reset_reason\":\"%s\","
                     "\"queue_dropped\":%lu}",
                     stationId, r.readingId, deviceTime, (unsigned long)r.uptimeMs,
                     (unsigned long)r.windowS, (unsigned long)r.rainTips, r.rainMm, r.windAvgKmh,
                     r.windPeakKmh, windDir, tempC, rhPct, pressHpa, r.bme280, rssi,
                     (unsigned long)r.bootCount, r.resetReason, (unsigned long)r.queueDropped);
    return n > 0 && (size_t)n < len;
}
