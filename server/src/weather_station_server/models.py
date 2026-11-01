"""Request and response bodies for the ingest API (docs/ingest-api.md)."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]
# 500 km/h sits above the firmware ceiling (5 ms wind debounce = 480 km/h): a
# glitchy gust must not cost the whole reading. Plausibility is flagged after
# storage instead (quality.py).
WindKmh = Annotated[float, Field(ge=0, le=500)]
SensorStatus = Literal["ok", "implausible", "error"]
# Particulate limits sit far above the PMSA003I's 500 ug/m3 effective range and
# its 16-bit counters: a dusty spike must not cost the whole reading.
Pm = Annotated[float, Field(ge=0, le=10000)] | None
ParticleCount = Annotated[float, Field(ge=0, le=65535)] | None


class Reading(BaseModel):
    """One five-minute reading as the station submits it."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    station_id: Identifier
    reading_id: Identifier
    device_time: AwareDatetime | None
    uptime_ms: Annotated[int, Field(ge=0)]
    window_s: Annotated[int, Field(ge=1, le=3600)]
    rain_tips: Annotated[int, Field(ge=0)]
    rain_mm: Annotated[float, Field(ge=0)]
    wind_avg_kmh: WindKmh
    wind_peak_kmh: WindKmh
    wind_dir_deg: Annotated[float, Field(ge=0, lt=360)] | None
    temp_c: Annotated[float, Field(ge=-40, le=85)] | None
    rh_pct: Annotated[float, Field(ge=0, le=100)] | None
    press_hpa: Annotated[float, Field(ge=300, le=1100)] | None
    # Status of the temperature, humidity and pressure sensor. Firmware sends
    # exactly one: bme280 before JAE-74, bme680 since.
    bme280: SensorStatus | None = None
    bme680: SensorStatus | None = None
    rssi_dbm: Annotated[int, Field(ge=-127, le=0)] | None
    # Reboot and upload-queue telemetry (JAE-60, JAE-62). Optional, so firmware
    # from before M4 still validates.
    boot_count: Annotated[int, Field(ge=0)] | None = None
    reset_reason: Annotated[str, Field(pattern=r"^[a-z_]{1,32}$")] | None = None
    queue_dropped: Annotated[int, Field(ge=0)] | None = None
    # Solar charger telemetry (JAE-73). Optional, so older firmware still
    # validates. The firmware sends null for a battery reading outside 2.5-4.5 V.
    batt_v: Annotated[float, Field(ge=0, le=5)] | None = None
    charge_state: Literal["charging", "full", "idle", "unknown"] | None = None
    # Air quality sensors (JAE-74). Optional, so older firmware still validates.
    gas_kohm: Annotated[float, Field(ge=0, le=100000)] | None = None
    pmsa003i: SensorStatus | None = None
    pm1_ugm3: Pm = None
    pm25_ugm3: Pm = None
    pm10_ugm3: Pm = None
    particles_03um: ParticleCount = None
    particles_05um: ParticleCount = None
    particles_1um: ParticleCount = None
    particles_25um: ParticleCount = None
    particles_5um: ParticleCount = None
    particles_10um: ParticleCount = None

    @model_validator(mode="after")
    def sensor_values_match_status(self) -> "Reading":
        if (self.bme280 is None) == (self.bme680 is None):
            raise ValueError("exactly one of bme280 or bme680 is required")
        climate = {name: getattr(self, name) for name in ("temp_c", "rh_pct", "press_hpa")}
        if self.bme680 is None:
            _check_status("bme280", self.bme280, climate)
        else:
            _check_status("bme680", self.bme680, climate)
        # Gas may be null with bme680 'ok': the heater can miss its temperature
        # on one measurement without spoiling the rest of it.
        if self.bme680 != "ok" and self.gas_kohm is not None:
            raise ValueError("gas_kohm must be null unless bme680 is 'ok'")
        particulates = {
            name: getattr(self, name)
            for name in type(self).model_fields
            if name.startswith(("pm", "particles_")) and name != "pmsa003i"
        }
        _check_status("pmsa003i", self.pmsa003i, particulates)
        return self


def _check_status(sensor: str, status: str | None, values: dict[str, float | None]) -> None:
    """A sensor's numbers must be present exactly when its status is ``ok``."""
    names = ", ".join(values)
    if status == "ok" and None in values.values():
        raise ValueError(f"{names} are required when {sensor} is 'ok'")
    if status != "ok" and any(v is not None for v in values.values()):
        raise ValueError(f"{names} must be null unless {sensor} is 'ok'")


class ReadingReceipt(BaseModel):
    """What the server stored for a submitted reading."""

    id: int
    station_id: str
    reading_id: str
    received_at: str
    duplicate: bool
