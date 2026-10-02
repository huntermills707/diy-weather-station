"""Request and response bodies for the ingest API (docs/ingest-api.md)."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]
WindKmh = Annotated[float, Field(ge=0, le=300)]


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
    bme280: Literal["ok", "implausible", "error"]
    rssi_dbm: Annotated[int, Field(ge=-127, le=0)] | None

    @model_validator(mode="after")
    def bme280_values_match_status(self) -> "Reading":
        values = (self.temp_c, self.rh_pct, self.press_hpa)
        if self.bme280 == "ok" and None in values:
            raise ValueError("temp_c, rh_pct and press_hpa are required when bme280 is 'ok'")
        if self.bme280 != "ok" and any(v is not None for v in values):
            raise ValueError("temp_c, rh_pct and press_hpa must be null unless bme280 is 'ok'")
        return self


class ReadingReceipt(BaseModel):
    """What the server stored for a submitted reading."""

    id: int
    station_id: str
    reading_id: str
    received_at: str
    duplicate: bool
