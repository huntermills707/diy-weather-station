#include "reading.h"

#include <math.h>
#include <string.h>

bool readingToJson(const Reading& r, const char* stationId, char* buf, size_t len) {
    bool bmeOk = strcmp(r.bme680, "ok") == 0;
    bool pmOk = strcmp(r.pmsa003i, "ok") == 0;

    // Optional values are formatted first so the main printf stays readable.
    // Invalid states become JSON null, never a placeholder number.
    char deviceTime[28] = "null";
    char windDir[12] = "null";
    char tempC[12] = "null";
    char rhPct[12] = "null";
    char pressHpa[12] = "null";
    char gasKohm[16] = "null";
    // The particulate fields, from "pm1_ugm3" on, or all null.
    char pm[320];
    char rssi[8] = "null";
    char battV[8] = "null";
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
        if (r.gasKohm >= 0.0f) {
            snprintf(gasKohm, sizeof(gasKohm), "%.1f", r.gasKohm);
        }
    }
    if (pmOk) {
        snprintf(pm, sizeof(pm),
                 "\"pm1_ugm3\":%.1f,\"pm25_ugm3\":%.1f,\"pm10_ugm3\":%.1f,"
                 "\"particles_03um\":%.1f,\"particles_05um\":%.1f,\"particles_1um\":%.1f,"
                 "\"particles_25um\":%.1f,\"particles_5um\":%.1f,\"particles_10um\":%.1f",
                 r.pm.pm1Ugm3, r.pm.pm25Ugm3, r.pm.pm10Ugm3, r.pm.particles03um, r.pm.particles05um,
                 r.pm.particles1um, r.pm.particles25um, r.pm.particles5um, r.pm.particles10um);
    } else {
        snprintf(pm, sizeof(pm),
                 "\"pm1_ugm3\":null,\"pm25_ugm3\":null,\"pm10_ugm3\":null,"
                 "\"particles_03um\":null,\"particles_05um\":null,\"particles_1um\":null,"
                 "\"particles_25um\":null,\"particles_5um\":null,\"particles_10um\":null");
    }
    if (r.rssiValid) {
        snprintf(rssi, sizeof(rssi), "%d", r.rssiDbm);
    }
    if (r.battV >= 0.0f) {
        snprintf(battV, sizeof(battV), "%.2f", r.battV);
    }

    int n = snprintf(buf, len,
                     "{\"station_id\":\"%s\",\"reading_id\":\"%s\",\"device_time\":%s,"
                     "\"uptime_ms\":%lu,\"window_s\":%lu,\"rain_tips\":%lu,\"rain_mm\":%.2f,"
                     "\"wind_avg_kmh\":%.1f,\"wind_peak_kmh\":%.1f,\"wind_dir_deg\":%s,"
                     "\"temp_c\":%s,\"rh_pct\":%s,\"press_hpa\":%s,\"bme680\":\"%s\","
                     "\"gas_kohm\":%s,\"pmsa003i\":\"%s\",%s,"
                     "\"rssi_dbm\":%s,\"boot_count\":%lu,\"reset_reason\":\"%s\","
                     "\"queue_dropped\":%lu,\"batt_v\":%s,\"charge_state\":\"%s\"}",
                     stationId, r.readingId, deviceTime, (unsigned long)r.uptimeMs,
                     (unsigned long)r.windowS, (unsigned long)r.rainTips, r.rainMm, r.windAvgKmh,
                     r.windPeakKmh, windDir, tempC, rhPct, pressHpa, r.bme680, gasKohm, r.pmsa003i,
                     pm, rssi, (unsigned long)r.bootCount, r.resetReason,
                     (unsigned long)r.queueDropped, battV, r.chargeState);
    return n > 0 && (size_t)n < len;
}
