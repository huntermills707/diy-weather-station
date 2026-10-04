import pytest

from weather_station_server.derived import dew_point_c, heat_index_c, sea_level_pressure_hpa


def to_f(temp_c: float) -> float:
    return temp_c * 9 / 5 + 32


def to_c(temp_f: float) -> float:
    return (temp_f - 32) * 5 / 9


@pytest.mark.parametrize(
    ("temp_c", "rh_pct", "expected_c"),
    [
        # Magnus with these coefficients; references agree within 0.1 °C.
        (25.0, 60.0, 16.7),
        (20.0, 50.0, 9.3),
        (0.0, 100.0, 0.0),
        (30.73, 35.7, 13.8),
    ],
)
def test_dew_point(temp_c: float, rh_pct: float, expected_c: float) -> None:
    assert dew_point_c(temp_c, rh_pct) == pytest.approx(expected_c, abs=0.1)


@pytest.mark.parametrize(
    ("temp_f", "rh_pct", "expected_f"),
    [
        # NWS heat index chart values (weather.gov/safety/heat-index).
        (80, 40, 80),
        (90, 70, 106),
        (96, 65, 121),
        (100, 40, 109),
        (86, 90, 105),
    ],
)
def test_heat_index_matches_nws_chart(temp_f: float, rh_pct: float, expected_f: float) -> None:
    result = heat_index_c(to_c(temp_f), rh_pct)
    assert result is not None
    assert to_f(result) == pytest.approx(expected_f, abs=1)


def test_heat_index_in_mild_weather_stays_near_air_temperature() -> None:
    result = heat_index_c(20.0, 50.0)
    assert result == pytest.approx(20.0, abs=1)


def test_sea_level_pressure() -> None:
    # 100 m in the standard atmosphere is about 12 hPa.
    assert sea_level_pressure_hpa(1000.0, 15.0, 100.0) == pytest.approx(1011.9, abs=0.1)
    assert sea_level_pressure_hpa(1013.25, 15.0, 0.0) == pytest.approx(1013.25)


@pytest.mark.parametrize(
    "call",
    [
        lambda: dew_point_c(None, 50.0),
        lambda: dew_point_c(20.0, None),
        lambda: dew_point_c(20.0, 0.0),
        lambda: heat_index_c(None, 50.0),
        lambda: heat_index_c(30.0, None),
        lambda: sea_level_pressure_hpa(None, 15.0, 100.0),
        lambda: sea_level_pressure_hpa(1000.0, None, 100.0),
        lambda: sea_level_pressure_hpa(1000.0, 15.0, None),
    ],
)
def test_unavailable_inputs_give_unavailable_outputs(call) -> None:
    assert call() is None
