# Firmware

ESP32 (SparkFun MicroMod) firmware for the weather station, built with
PlatformIO and the Arduino framework.

Responsibilities:

- Read sensors (BME280, rain gauge, anemometer, wind vane, soil moisture)
- Connect to WiFi with bounded retry/backoff
- POST readings to the FastAPI ingest service over the LAN every five minutes
- Queue failed uploads to a bounded backlog and retry oldest-first

> Note: the current PlatformIO project (`platformio.ini`, `src/`) still lives
> at the repository root and will be relocated here in a later change.
