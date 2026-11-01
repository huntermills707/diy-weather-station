"""Derived weather metrics (docs/read-api.md, "Derived metrics").

Each function returns None when any input is unavailable, so a failed sensor
never turns into a made-up number.
"""

import math

# Magnus coefficients from Alduchov & Eskridge (1996), over water.
MAGNUS_A = 17.625
MAGNUS_B_C = 243.04


def dew_point_c(temp_c: float | None, rh_pct: float | None) -> float | None:
    """Dew point by the Magnus formula; within 0.4 °C for -40 to 50 °C."""
    if temp_c is None or rh_pct is None or rh_pct <= 0:
        return None
    gamma = math.log(rh_pct / 100) + MAGNUS_A * temp_c / (MAGNUS_B_C + temp_c)
    return MAGNUS_B_C * gamma / (MAGNUS_A - gamma)


def heat_index_c(temp_c: float | None, rh_pct: float | None) -> float | None:
    """US National Weather Service heat index (the NWS algorithm, in °F).

    Steadman's simple formula first; if that averages 80 °F or more with the
    air temperature, the Rothfusz regression with the NWS low- and
    high-humidity adjustments. In mild weather the result stays close to
    the air temperature.
    """
    if temp_c is None or rh_pct is None:
        return None
    t = temp_c * 9 / 5 + 32
    rh = rh_pct
    hi = 0.5 * (t + 61 + (t - 68) * 1.2 + rh * 0.094)
    if (hi + t) / 2 >= 80:
        hi = (
            -42.379
            + 2.04901523 * t
            + 10.14333127 * rh
            - 0.22475541 * t * rh
            - 0.00683783 * t * t
            - 0.05481717 * rh * rh
            + 0.00122874 * t * t * rh
            + 0.00085282 * t * rh * rh
            - 0.00000199 * t * t * rh * rh
        )
        if rh < 13 and 80 <= t <= 112:
            hi -= (13 - rh) / 4 * math.sqrt((17 - abs(t - 95)) / 17)
        elif rh > 85 and 80 <= t <= 87:
            hi += (rh - 85) / 10 * (87 - t) / 5
    return (hi - 32) * 5 / 9


def sea_level_pressure_hpa(
    press_hpa: float | None, temp_c: float | None, altitude_m: float | None
) -> float | None:
    """Station pressure reduced to sea level (barometric formula).

    Assumes the standard lapse rate of 6.5 °C/km below the station, starting
    from the measured temperature.
    """
    if press_hpa is None or temp_c is None or altitude_m is None:
        return None
    lapse = 0.0065 * altitude_m
    return press_hpa * (1 - lapse / (temp_c + lapse + 273.15)) ** -5.257


# US EPA AQI breakpoints for PM2.5 (2024 revision): concentration range in
# ug/m3 (truncated to 0.1), index range, and category.
AQI_PM25 = (
    (0.0, 9.0, 0, 50, "Good"),
    (9.1, 35.4, 51, 100, "Moderate"),
    (35.5, 55.4, 101, 150, "Unhealthy for sensitive groups"),
    (55.5, 125.4, 151, 200, "Unhealthy"),
    (125.5, 225.4, 201, 300, "Very unhealthy"),
    (225.5, 325.4, 301, 500, "Hazardous"),
)


def aqi_pm25(pm25_ugm3: float | None) -> tuple[int, str] | None:
    """US EPA air quality index and category for a PM2.5 concentration.

    The EPA computes the index from a 24-hour (or NowCast) average; this
    applies the same scale to whatever average it is given. Above the top
    of the scale the index stays at 500.
    """
    if pm25_ugm3 is None:
        return None
    # Truncate as the EPA does; round first so 35.4 isn't stored as 35.39999.
    c = math.floor(round(pm25_ugm3 * 10, 6)) / 10
    for c_lo, c_hi, i_lo, i_hi, category in AQI_PM25:
        if c <= c_hi:
            return round(i_lo + (i_hi - i_lo) * (c - c_lo) / (c_hi - c_lo)), category
    return 500, AQI_PM25[-1][4]
