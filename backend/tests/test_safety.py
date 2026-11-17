import pytest

from app.models import BottomType, Conditions, Spot, Status
from app.safety import grade


def spot(bottom=BottomType.sand):
    return Spot(id="t", name="t", region="t", lat=35, lon=129, bottom_type=bottom,
                beginner_friendly=True, board_fit=[])


def cond(h=0.8, period=8, wind=3):
    return Conditions(wave_height_m=h, wave_period_s=period, wind_speed_ms=wind,
                      wind_dir_deg=0, tide_m=0.5, source="test")


@pytest.mark.parametrize("h,expected", [
    (0.1, Status.caution),
    (0.4, Status.caution),
    (0.5, Status.optimal),
    (0.8, Status.optimal),
    (1.0, Status.optimal),
    (1.2, Status.caution),
    (1.5, Status.caution),
    (1.6, Status.avoid),
])
def test_wave_height(h, expected):
    assert grade(spot(), cond(h=h)).status == expected


def test_strong_wind_overrides_good_waves():
    g = grade(spot(), cond(wind=13))
    assert g.status == Status.avoid
    assert "강풍" in g.reasons[0]


def test_short_period_is_caution():
    assert grade(spot(), cond(period=4)).status == Status.caution


def test_reef_is_avoid_for_beginners():
    assert grade(spot(BottomType.reef), cond()).status == Status.avoid


def test_mixed_bottom_is_caution():
    assert grade(spot(BottomType.mixed), cond()).status == Status.caution


def test_label_is_korean():
    assert grade(spot(), cond()).label == "입수 최적"


def test_unknown_bottom_is_never_optimal():
    g = grade(spot(BottomType.unknown), cond())
    assert g.status == Status.caution and any("미확인" in r for r in g.reasons)
