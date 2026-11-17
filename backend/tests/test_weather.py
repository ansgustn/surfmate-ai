import httpx

from app.models import Spot
from app.weather import OpenMeteoProvider


def spot(i, lat=35.0):
    return Spot(id=f"s{i}", name="t", region="t", lat=lat, lon=129.0, bottom_type="sand",
                beginner_friendly=True, board_fit=[])


def marine(h):
    return {"current": {"wave_height": h, "wave_period": 6.2, "sea_level_height_msl": -0.31}}


WIND = {"current": {"wind_speed_10m": 4.26, "wind_direction_10m": 45.4}}


def provider(handler):
    calls = []

    def wrapped(req: httpx.Request):
        calls.append(req)
        return handler(req)

    p = OpenMeteoProvider(client=httpx.Client(transport=httpx.MockTransport(wrapped)))
    return p, calls


def test_parses_batched_response_and_caches():
    def handler(req):
        if "marine" in req.url.host:
            return httpx.Response(200, json=[marine(0.84), marine(1.26)])
        return httpx.Response(200, json=[WIND, WIND])

    p, calls = provider(handler)
    spots = [spot(1), spot(2)]
    out = p.get_many(spots)
    assert out["s1"].wave_height_m == 0.8 and out["s2"].wave_height_m == 1.3
    assert out["s1"].wind_speed_ms == 4.3 and out["s1"].wind_dir_deg == 45
    assert out["s1"].tide_m == -0.31 and out["s1"].source == "open-meteo"
    assert calls[0].url.params["latitude"] == "35.0,35.0"

    p.get_many(spots)
    assert len(calls) == 2  # 두 번째는 캐시


def test_single_spot_object_response():
    def handler(req):
        return httpx.Response(200, json=marine(0.5) if "marine" in req.url.host else WIND)

    p, _ = provider(handler)
    assert p.get_many([spot(1)])["s1"].wave_height_m == 0.5


def test_falls_back_to_mock_on_error():
    p, _ = provider(lambda req: httpx.Response(503))
    assert p.get_many([spot(1)])["s1"].source == "mock"


def test_missing_wave_height_falls_back():
    def handler(req):
        return httpx.Response(200, json=marine(None) if "marine" in req.url.host else WIND)

    p, _ = provider(handler)
    assert p.get_many([spot(1)])["s1"].source == "mock"


def test_spot_outside_marine_grid_borrows_nearest():
    # 만 안쪽 해변(s2)만 파고가 없으면 전체를 가짜 데이터로 바꾸지 않고 가장 가까운 해변 값을 쓴다
    def handler(req):
        if "marine" in req.url.host:
            return httpx.Response(200, json=[marine(0.84), marine(None), marine(1.5)])
        return httpx.Response(200, json=[WIND, WIND, WIND])

    p, _ = provider(handler)
    out = p.get_many([spot(1, lat=35.0), spot(2, lat=35.01), spot(3, lat=36.0)])
    assert out["s2"].wave_height_m == 0.8 and out["s2"].source == "open-meteo"
