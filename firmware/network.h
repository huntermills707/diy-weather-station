#pragma once

#include <Arduino.h>

// WiFi, NTP, and the HTTP upload to the ingest service (ADR 0001).
// Everything here is non-blocking except postReading(), so sensor counting
// and serial reports carry on while the network is down.

// Reconnect backoff: the first retry comes WIFI_RETRY_MIN_MS after a failed
// attempt or a dropped link, doubling up to WIFI_RETRY_MAX_MS.
constexpr uint32_t WIFI_RETRY_MIN_MS = 10UL * 1000UL;
constexpr uint32_t WIFI_RETRY_MAX_MS = 5UL * 60UL * 1000UL;

// Upper bound on each phase of a POST; a dead server stalls loop() for at
// most about twice this.
constexpr uint32_t HTTP_TIMEOUT_MS = 5000;

// postReading() result when there is no WiFi link to try with.
constexpr int POST_NOT_CONNECTED = -100;

// Starts WiFi in station mode with the credentials from secrets.h.
void networkInit();

// Call every loop(): logs link changes, reconnects with bounded backoff, and
// starts NTP after the first successful connection.
void networkPoll();

bool networkConnected();

// Signal strength of the current link in dBm; only meaningful when connected.
int networkRssi();

// True once NTP has set the clock at least once since boot.
bool clockSynced();

// Writes the current UTC time as "YYYY-MM-DDTHH:MM:SSZ". Returns false (and
// writes an empty string) when the clock has never been synced.
bool formatUtcNow(char* buf, size_t len);

// POSTs a JSON body to INGEST_URL with the bearer token. Returns the HTTP
// status code, a negative HTTPClient error, or POST_NOT_CONNECTED.
int postReading(const char* json);
