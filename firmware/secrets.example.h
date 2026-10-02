// Local secrets template. Copy to secrets.h (same folder) and fill in real
// values. secrets.h is gitignored and must never be committed.
#pragma once

// WiFi network the station joins to reach the ingest service.
#define WIFI_SSID "your-wifi-ssid"
#define WIFI_PASSWORD "your-wifi-password"

// Per-station pre-shared token sent as `Authorization: Bearer` (ADR 0001).
// Must match WEATHER_STATION_INGEST_TOKEN on the server.
#define INGEST_TOKEN "generate-a-long-random-token"

// Ingest endpoint on the LAN, e.g. "http://192.168.1.50:8000/readings".
#define INGEST_URL "http://your-server-ip:8000/readings"
