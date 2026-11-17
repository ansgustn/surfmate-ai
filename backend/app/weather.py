"""해양 기상 데이터 제공자.

- OpenMeteoProvider (기본): Open-Meteo Marine + Forecast API. 인증키 없이 실제 예보값을 받는다.
  파고·파주기·해수면 높이(조위 포함)는 Marine API, 풍속·풍향은 Forecast API.
- MockWeatherProvider: 네트워크 없이 개발·테스트할 때.

기상청 / 국립해양조사원 API는 공공데이터포털 인증키를 받은 뒤
같은 `get_many(spots)` 인터페이스로 추가한다.
"""

import hashlib
import logging
import math
import time
from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo

import httpx

from .models import Conditions, Spot

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")


class WeatherProvider(Protocol):
    def get_many(self, spots: list[Spot]) -> dict[str, Conditions]: ...


class MockWeatherProvider:
    """스팟·시각별로 항상 같은 값을 돌려주는 가짜 데이터."""

    def get(self, spot: Spot, at: datetime) -> Conditions:
        key = f"{spot.id}:{at:%Y%m%d%H}".encode()
        r = [b / 255 for b in hashlib.sha256(key).digest()[:5]]
        # 조위는 약 12.4시간 주기의 사인파로 흉내
        tide_phase = (at.timestamp() / 3600) / 12.42 * 2 * math.pi
        return Conditions(
            wave_height_m=round(0.2 + r[0] * 1.6, 1),
            wave_period_s=round(4 + r[1] * 8, 0),
            wind_speed_ms=round(r[2] * 14, 1),
            wind_dir_deg=round(r[3] * 360),
            tide_m=round(0.5 * math.sin(tide_phase), 2),
            source="mock",
        )

    def get_many(self, spots: list[Spot]) -> dict[str, Conditions]:
        now = datetime.now(KST)
        return {s.id: self.get(s, now) for s in spots}


class OpenMeteoProvider:
    MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
    FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

    def __init__(self, ttl_s: int = 900, timeout_s: float = 10.0,
                 client: httpx.Client | None = None, fallback: WeatherProvider | None = None):
        self._ttl = ttl_s
        self._client = client or httpx.Client(timeout=timeout_s)
        self._fallback = fallback or MockWeatherProvider()
        self._cache: dict[str, tuple[float, Conditions]] = {}

    def get_many(self, spots: list[Spot]) -> dict[str, Conditions]:
        now = time.monotonic()
        fresh = {s.id: c for s in spots if (hit := self._cache.get(s.id)) and now - hit[0] < self._ttl
                 for c in [hit[1]]}
        missing = [s for s in spots if s.id not in fresh]
        if missing:
            try:
                fetched = self._fetch(missing)
            except (httpx.HTTPError, KeyError, ValueError, TypeError) as e:
                log.warning("Open-Meteo 호출 실패, mock 데이터로 대체: %s", e)
                return {**fresh, **self._fallback.get_many(missing)}
            for sid, c in fetched.items():
                self._cache[sid] = (now, c)
            fresh.update(fetched)
        return fresh

    BATCH = 100  # 한 요청에 넣는 좌표 수 (URL 길이 제한)

    def _fetch(self, spots: list[Spot]) -> dict[str, Conditions]:
        out: dict[str, Conditions] = {}
        for i in range(0, len(spots), self.BATCH):
            out.update(self._fetch_batch(spots[i:i + self.BATCH]))
        # 만 안쪽 등 해상 격자 밖이라 파고가 없는 해변은 가장 가까운 해변 값을 빌려 쓴다
        from .repository import haversine_km
        missing = [s for s in spots if s.id not in out]
        have = [s for s in spots if s.id in out]
        if missing and not have:
            raise ValueError("모든 해변의 파고 값이 없음")
        for s in missing:
            near = min(have, key=lambda h: haversine_km(s.lat, s.lon, h.lat, h.lon))
            out[s.id] = out[near.id]
        return out

    def _fetch_batch(self, spots: list[Spot]) -> dict[str, Conditions]:
        # 여러 좌표를 쉼표로 묶어 한 번에 요청 (스팟이 1개면 객체, 여러 개면 리스트로 응답)
        coords = {
            "latitude": ",".join(str(s.lat) for s in spots),
            "longitude": ",".join(str(s.lon) for s in spots),
            "timezone": "Asia/Seoul",
        }
        marine = self._get(self.MARINE_URL, {**coords, "current": "wave_height,wave_period,sea_level_height_msl"})
        wind = self._get(self.FORECAST_URL, {**coords, "current": "wind_speed_10m,wind_direction_10m",
                                             "wind_speed_unit": "ms"})
        out: dict[str, Conditions] = {}
        for spot, m, w in zip(spots, marine, wind, strict=True):
            mc, wc = m["current"], w["current"]
            if mc.get("wave_height") is None:  # 해상 격자 밖 → _fetch 에서 이웃 값으로 채움
                log.info("%s: Open-Meteo 파고 값 없음, 가까운 해변 값 사용", spot.id)
                continue
            out[spot.id] = Conditions(
                wave_height_m=round(mc["wave_height"], 1),
                wave_period_s=round(mc["wave_period"] or 0, 1),
                wind_speed_ms=round(wc["wind_speed_10m"], 1),
                wind_dir_deg=round(wc["wind_direction_10m"]),
                tide_m=round(mc["sea_level_height_msl"] or 0, 2),
                source="open-meteo",
            )
        return out

    def _get(self, url: str, params: dict) -> list[dict]:
        r = self._client.get(url, params=params)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else [data]


class KmaSeaObsProvider:
    """기상청 해양기상종합관측 실측값을 우선 쓰고, 없는 값은 base(Open-Meteo)로 채운다.

    - 파고: 스팟에서 max_km 안의 가장 가까운 파고 관측 지점 (해수욕장 파고부이 등)
    - 풍향·풍속: max_km 안의 가장 가까운 바람 관측 지점 (파고부이는 바람을 재지 않음)
    - 파주기·조위: 이 API에 없으므로 항상 base 값
    """

    def __init__(self, auth_key: str, base: WeatherProvider, max_km: float = 15.0,
                 ttl_s: int = 600, client: httpx.Client | None = None):
        self._key = auth_key
        self._base = base
        self._max_km = max_km
        self._ttl = ttl_s
        self._client = client or httpx.Client(timeout=15.0)
        self._cache: tuple[float, list] | None = None

    def _observations(self) -> list:
        from .kma import fetch_sea_obs

        if self._cache is None or time.monotonic() - self._cache[0] > self._ttl:
            now = datetime.now(KST).replace(tzinfo=None)
            self._cache = (time.monotonic(), fetch_sea_obs(self._client, self._key, now))
        return self._cache[1]

    def _nearest(self, spot: Spot, obs: list, has) -> tuple[float, object] | None:
        from .repository import haversine_km

        best = min(((haversine_km(spot.lat, spot.lon, o.lat, o.lon), o) for o in obs if has(o)),
                   key=lambda x: x[0], default=None)
        return best if best and best[0] <= self._max_km else None

    def get_many(self, spots: list[Spot]) -> dict[str, Conditions]:
        base = self._base.get_many(spots)
        try:
            obs = self._observations()
        except (httpx.HTTPError, ValueError) as e:
            log.warning("기상청 해양관측 조회 실패, %s 값만 사용: %s", type(self._base).__name__, e)
            return base

        out: dict[str, Conditions] = {}
        for spot in spots:
            b = base[spot.id]
            wave = self._nearest(spot, obs, lambda o: o.wave_m is not None)
            wind = self._nearest(spot, obs, lambda o: o.wind_speed_ms is not None and o.wind_dir_deg is not None)
            if wave is None and wind is None:
                out[spot.id] = b
                continue
            notes = []
            if wave:
                notes.append(f"파고 {wave[1].label} {wave[0]:.1f}km")
            if wind:
                notes.append(f"바람 {wind[1].label} {wind[0]:.1f}km")
            tm = max(x[1].tm for x in (wave, wind) if x)
            out[spot.id] = Conditions(
                wave_height_m=round(wave[1].wave_m, 1) if wave else b.wave_height_m,
                wave_period_s=b.wave_period_s,
                wind_speed_ms=wind[1].wind_speed_ms if wind else b.wind_speed_ms,
                wind_dir_deg=wind[1].wind_dir_deg if wind else b.wind_dir_deg,
                tide_m=b.tide_m,
                source="kma",
                station=f"{', '.join(notes)} · {tm:%H:%M} 관측",
            )
        return out
