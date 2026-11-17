from datetime import datetime

import httpx

from app.kma import parse_sea_obs
from app.models import Conditions, Spot
from app.weather import KmaSeaObsProvider

# 실제 sea_obs.php 응답 형식 (일부 발췌)
SAMPLE = """#START7777
#            TM       STN                   STN           LON           LAT     WH   WD     WS     WS     TW     TA      PA     HM
C, 202611091330,    22454,                 장안, 129.25000000,  35.31000000,   0.6, -99,  -99.0,  -99.0,  18.0,  -99.0, -99.0, -99.0, ,=
C, 202611091400,    22454,                 장안, 129.25000000,  35.31000000,   0.7, -99,  -99.0,  -99.0,  18.1,  -99.0, -99.0, -99.0, ,=
L, 202611091400,      984,               오륙도, 129.12000000,  35.09000000,  -99.0,  30,    2.2,    3.1,  19.0,  15.0, 1022.0,  70.0, ,=
B, 202611091400,    22104,               거제도, 128.90000000,  34.76670000,   1.1, 354,  10.4,  12.7,  19.8,  13.2, 1023.8,  84.0, ,=
D, 202611091400,    99999,               표류, 129.20000000,  35.20000000,   0.3,  10,    1.0,    1.0,  19.0,  15.0, 1022.0,  70.0, ,=
#7777END
"""


def test_parse_keeps_latest_and_skips_drifting():
    obs = {o.stn: o for o in parse_sea_obs(SAMPLE)}
    assert set(obs) == {"22454", "984", "22104"}
    jangan = obs["22454"]
    assert jangan.tm == datetime(2026, 11, 9, 14, 0)
    assert jangan.wave_m == 0.7 and jangan.wind_speed_ms is None
    assert jangan.label == "장안 파고부이"
    assert obs["984"].wave_m is None and obs["984"].wind_speed_ms == 2.2


class Base:
    def get_many(self, spots):
        return {s.id: Conditions(wave_height_m=0.4, wave_period_s=6.0, wind_speed_ms=5.0,
                                 wind_dir_deg=90, tide_m=-0.3, source="open-meteo") for s in spots}


def provider(body: str):
    def handler(req):
        return httpx.Response(200, content=body.encode("utf-8"))

    return KmaSeaObsProvider("k", base=Base(), client=httpx.Client(transport=httpx.MockTransport(handler)))


def spot(id, lat, lon):
    return Spot(id=id, name=id, region="t", lat=lat, lon=lon, bottom_type="sand",
                beginner_friendly=True, board_fit=[])


def test_wave_and_wind_from_different_nearby_stations():
    # 일광: 장안 파고부이 ~6.5km, 오륙도 등표 ~21km(바람, 15km 초과)
    c = provider(SAMPLE).get_many([spot("ilgwang", 35.2603, 129.2336)])["ilgwang"]
    assert c.source == "kma"
    assert c.wave_height_m == 0.7
    assert c.wind_speed_ms == 5.0  # 15km 안에 바람 관측 없음 → base
    assert c.wave_period_s == 6.0 and c.tide_m == -0.3  # 항상 base
    assert c.station.startswith("파고 장안 파고부이")


def test_wind_from_nearby_light_beacon():
    # 해운대: 오륙도 등표 ~8km → 바람 실측
    c = provider(SAMPLE).get_many([spot("haeundae", 35.1587, 129.1604)])["haeundae"]
    assert c.wind_speed_ms == 2.2 and c.wind_dir_deg == 30
    assert "바람 오륙도 등표" in c.station


def test_far_spot_uses_base():
    c = provider(SAMPLE).get_many([spot("jukdo", 38.0283, 128.7158)])["jukdo"]
    assert c.source == "open-meteo"


def test_api_error_falls_back_to_base():
    body = '{"result":{"status":403,"message":"활용신청이 필요한 API 입니다."}}'
    c = provider(body).get_many([spot("ilgwang", 35.2603, 129.2336)])["ilgwang"]
    assert c.source == "open-meteo"
