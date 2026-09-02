#include <Arduino.h>

const int LED_PIN = LED_BUILTIN;  // GPIO 2

void setup() {
    Serial.begin(115200);
    delay(1000);              // let USB-serial settle before first print
    Serial.println("MicroMod ESP32 up");

    pinMode(LED_PIN, OUTPUT);
}

void loop() {
    digitalWrite(LED_PIN, HIGH);
    Serial.println("on");
    delay(750);

    digitalWrite(LED_PIN, LOW);
    Serial.println("off");
    delay(750);
}