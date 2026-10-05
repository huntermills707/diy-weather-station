#include "upload_queue.h"

#include "network.h"

static const char* station = "";

// Ring buffer: `head` is the oldest reading, `count` how many are queued.
static Reading queue[UPLOAD_QUEUE_CAPACITY];
static size_t head = 0;
static size_t count = 0;

static uint32_t dropped = 0;    // overflow, since boot
static uint32_t rejected = 0;   // refused by the server as invalid, since boot
static uint32_t failures = 0;   // failed attempts, since boot
static uint32_t unreached = 0;  // attempts in a row with no HTTP response
static uint32_t retryDelayMs = UPLOAD_RETRY_MIN_MS;
static uint32_t nextSendAt = 0;

static void popFront() {
    head = (head + 1) % UPLOAD_QUEUE_CAPACITY;
    count--;
}

void uploadQueueInit(const char* stationId) { station = stationId; }

void uploadQueuePush(const Reading& r) {
    if (count == UPLOAD_QUEUE_CAPACITY) {
        dropped++;
        Serial.printf("queue: FULL, dropped oldest id=%s (dropped=%lu)\n", queue[head].readingId,
                      (unsigned long)dropped);
        popFront();
    }
    queue[(head + count) % UPLOAD_QUEUE_CAPACITY] = r;
    count++;
}

void uploadQueuePoll() {
    uint32_t now = millis();
    // Without WiFi, networkPoll() owns the reconnect backoff; nothing to try.
    if (count == 0 || !networkConnected() || (int32_t)(now - nextSendAt) < 0) {
        return;
    }

    Reading& r = queue[head];
    // A reading taken before the first NTP sync gets its time once the
    // clock is set, counted back from its uptime, so a late delivery still
    // lands at the right time on the server (JAE-61).
    if (r.deviceTime[0] == '\0') {
        formatUtcAt(r.uptimeMs, r.deviceTime, sizeof(r.deviceTime));
    }

    char json[640];
    if (!readingToJson(r, station, json, sizeof(json))) {
        Serial.printf("upload: id=%s DROPPED payload too large\n", r.readingId);
        rejected++;
        popFront();
        return;
    }

    int code = postReading(json);
    if (code == 200 || code == 201) {
        // 200 means the server already had it (a retry after a lost response).
        Serial.printf("upload: id=%s ok (%d) queued=%u\n", r.readingId, code,
                      (unsigned)(count - 1));
        popFront();
        unreached = 0;
        retryDelayMs = UPLOAD_RETRY_MIN_MS;
        nextSendAt = now;  // send the next one on the following loop
        return;
    }
    if (code == 400 || code == 413 || code == 422) {
        // The server will never accept this payload: retrying would block the
        // queue forever. The server logs why.
        rejected++;
        Serial.printf("upload: id=%s REJECTED code=%d, dropped (rejected=%lu)\n", r.readingId, code,
                      (unsigned long)rejected);
        popFront();
        nextSendAt = now;
        return;
    }

    // Anything else (no response, 401, 5xx) may succeed later: keep it.
    failures++;
    Serial.printf("upload: id=%s FAILED code=%d, retry in %lu s (queued=%u failures=%lu)\n",
                  r.readingId, code, (unsigned long)(retryDelayMs / 1000), (unsigned)count,
                  (unsigned long)failures);
    nextSendAt = now + retryDelayMs;
    retryDelayMs = min(retryDelayMs * 2, UPLOAD_RETRY_MAX_MS);

    // Negative codes are HTTPClient errors: the server was never reached.
    if (code < 0 && ++unreached >= UPLOAD_FAILURES_BEFORE_WIFI_RESET) {
        Serial.printf("upload: %lu sends in a row got no response, resetting wifi\n",
                      (unsigned long)unreached);
        unreached = 0;
        networkReset();
    }
}

size_t uploadQueueDepth() { return count; }

uint32_t uploadQueueDropped() { return dropped; }

void uploadQueuePrintStatus() {
    int32_t wait = (int32_t)(nextSendAt - millis());
    Serial.printf(
        "queue: depth=%u/%u dropped=%lu rejected=%lu failures=%lu next_send_in_s=%ld oldest=%s\n",
        (unsigned)count, (unsigned)UPLOAD_QUEUE_CAPACITY, (unsigned long)dropped,
        (unsigned long)rejected, (unsigned long)failures, (long)(wait > 0 ? wait / 1000 : 0),
        count > 0 ? queue[head].readingId : "none");
}
