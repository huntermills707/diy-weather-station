#include <Arduino.h>

const int LED_PIN = LED_BUILTIN;  // GPIO 2

/**
 * @brief Initialize the ESP32 hardware and serial communication.
 *
 * Sets up serial communication at 115200 baud, waits for USB-serial
 * to stabilize, prints startup message, and configures LED pin as output.
 */
void setup() {
    Serial.begin(115200);
    delay(1000);  // let USB-serial settle before first print
    Serial.println("MicroMod ESP32 up");

    pinMode(LED_PIN, OUTPUT);
}

/**
 * @brief Main program loop that blinks the LED on and off.
 *
 * Turns the LED on for 750ms while printing "on" to serial,
 * then turns it off for 750ms while printing "off" to serial.
 * This pattern repeats continuously.
 */
void loop() {
    digitalWrite(LED_PIN, HIGH);
    Serial.println("on");
    delay(750);

    digitalWrite(LED_PIN, LOW);
    Serial.println("off");
    delay(750);
}
