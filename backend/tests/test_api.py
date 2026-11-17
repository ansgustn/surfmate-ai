from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import KST, app, get_now, get_tour, get_weather
from app.models import Conditions, Spot


# 혼잡도가 모두 '여유'인 시각 (11월 평일 새벽) — 정렬이 실행 시각에 따라 바뀌지 않도록
QUIET = datetime(2026, 11, 10, 3, 0, tzinfo=KST)
# 혼잡한 시각 (8월 토요일 오후 1시)
BUSY = datetime(2026, 8, 8, 13, 0, tzinfo=KST)


class FixedWeather:
    """해운대만 파도가 높은 고정 날씨."""

    def get_many(self, spots: list[Spot]) -> dict[str, Conditions]:
        return {s.id: Conditions(wave_height_m=1.8 if s.id == "haeundae" else 0.8, wave_period_s=8,
                                 wind_speed_ms=3, wind_dir_deg=0, tide_m=0.5, source="test")
                for s in spots}


@pytest.fixture
def client():
    app.dependency_overrides[get_weather] = FixedWeather
    app.dependency_overrides[get_now] = lambda: QUIET
    app.dependency_overrides[get_tour] = lambda: None  # 실제 관광공사 API 호출 안 함
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_list_spots(client):
    ids = {s["id"] for s in client.get("/spots").json()}
    assert {"songjeong", "jukdo"} <= ids


def test_spot_report(client):
    r = client.get("/spots/haeundae").json()
    assert r["grade"]["status"] == "avoid"
    assert r["conditions"]["wave_height_m"] == 1.8


def test_unknown_spot_404(client):
    assert client.get("/spots/nope").status_code == 404


def test_recommend_near_busan_prefers_safe_and_close(client):
    # 해운대 근처에서 요청
    r = client.get("/recommend", params={"lat": 35.16, "lon": 129.16, "limit": 3}).json()
    ids = [x["spot"]["id"] for x in r]
    assert "haeundae" not in ids  # 파고 1.8m → 입수 자제
    assert ids[:2] == ["gwangalli", "songjeong"]  # 입수 최적 중 가까운 순
    assert all(x["grade"]["status"] == "optimal" for x in r)


def test_recommend_max_km_filters(client):
    r = client.get("/recommend", params={"lat": 38.03, "lon": 128.72, "max_km": 20, "limit": 10}).json()
    assert {x["spot"]["region"] for x in r} == {"양양"}


def test_recommend_requires_both_coords(client):
    assert client.get("/recommend", params={"lat": 35}).status_code == 422


def test_report_includes_congestion(client):
    c = client.get("/spots/songjeong").json()["congestion"]
    assert c["level"] == "low" and len(c["slots"]) == 4


def test_busy_time_prefers_less_crowded(client):
    app.dependency_overrides[get_now] = lambda: BUSY
    r = client.get("/recommend", params={"lat": 35.16, "lon": 129.16, "limit": 3}).json()
    # 송정은 입수 최적이고 더 가깝지만 성수기 주말 오후라 '혼잡' → 덜 붐비는 광안리·일광·다대포가 먼저
    ids = [x["spot"]["id"] for x in r]
    assert ids == ["gwangalli", "ilgwang", "dadaepo"] and "songjeong" not in ids
    assert all(x["congestion"]["level"] != "high" for x in r)
