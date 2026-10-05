#pragma once

#include <Arduino.h>

#include "reading.h"

// Bounded upload queue (ADR 0001, JAE-60). Every reading goes through it:
// it is sent oldest first, and a reading that fails stays at the front and
// is retried with bounded backoff. The queue lives in RAM, so a reboot or
// power loss empties it.

// 24 hours of five-minute readings, about 37 KB of RAM.
constexpr size_t UPLOAD_QUEUE_CAPACITY = 288;

// Retry backoff after a failed send: doubles from MIN up to MAX, and resets
// after a success.
constexpr uint32_t UPLOAD_RETRY_MIN_MS = 10UL * 1000UL;
constexpr uint32_t UPLOAD_RETRY_MAX_MS = 5UL * 60UL * 1000UL;

// After this many sends in a row fail without reaching the server (no HTTP
// response at all) while WiFi claims to be up, the link is dropped and
// reconnected from scratch (JAE-62).
constexpr uint32_t UPLOAD_FAILURES_BEFORE_WIFI_RESET = 3;

// Sets the station ID sent with every reading.
void uploadQueueInit(const char* stationId);

// Adds a reading at the back. When the queue is full the oldest reading is
// dropped to make room, and counted in uploadQueueDropped().
void uploadQueuePush(const Reading& r);

// Call every loop(): sends at most one reading (the oldest) when it is due.
void uploadQueuePoll();

size_t uploadQueueDepth();

// Readings dropped because the queue was full, since boot.
uint32_t uploadQueueDropped();

// Prints depth, drops, rejections, failures, and the next retry on serial.
void uploadQueuePrintStatus();
