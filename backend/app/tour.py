"""한국관광공사 관광지 집중률 방문자 추이 예측 (공공데이터포털 TatsCnctrRateService).

통신 데이터 기반으로 관광지(해수욕장 포함)별 '오늘부터 30일간' 일별 집중률을 예측한 값.
집중률은 관광지마다 가장 붐비는 시기를 100으로 둔 상대값이라 해변끼리 직접 비교할 수 없다.
→ 혼잡도 추정에서 해변 인기도와 곱해 쓴다.

주의: 학교(동서대) 네트워크에서는 data.go.kr 접속이 막혀 있다. 그때는 None 을 돌려주고
혼잡도는 요일·계절 규칙으로 대신 계산된다.
"""

import logging
import threading
import time
from datetime import date

import httpx
from pydantic import BaseModel

log = logging.getLogger(__name__)

URL = "https://apis.data.go.kr/B551011/TatsCnctrRateService/tatsCnctrRatedList"


class TourRef(BaseModel):
    """스팟이 관광공사 데이터에서 어떤 이름·시군구로 잡혀 있는지."""

    area: str  # 시도 코드 (부산 26, 강원 51)
    signgu: str  # 시군구 코드 (해운대구 26350 ...)
    name: str  # 관광지명 (예: 송정해수욕장)


def parse(body: dict) -> dict[tuple[str, str], float]:
    """{(관광지명, YYYYMMDD): 집중률}"""
    items = (body.get("items") or {}).get("item") or []
    if isinstance(items, dict):  # 한 건이면 객체로 온다
        items = [items]
    out = {}
    for it in items:
        try:
            out[(it["tAtsNm"], it["baseYmd"])] = float(it["cnctrRate"])
        except (KeyError, ValueError, TypeError):
            continue
    return out


class TourConcentrationProvider:
    def __init__(self, service_key: str, ttl_s: int = 6 * 3600, retry_after_s: int = 600,
                 client: httpx.Client | None = None):
        self._key = service_key
        self._ttl = ttl_s
        self._retry_after = retry_after_s
        # 접속이 막힌 네트워크에서 요청마다 오래 기다리지 않도록 연결 대기는 짧게
        self._client = client or httpx.Client(timeout=httpx.Timeout(15.0, connect=4.0))
        self._cache: dict[tuple[str, str], tuple[float, dict]] = {}
        self._down_until = 0.0  # 실패 후 이 시각까지는 호출하지 않음
        self._lock = threading.Lock()  # 동시 요청이 같은 시군구를 중복 호출하지 않도록

    def _district(self, area: str, signgu: str) -> dict[tuple[str, str], float]:
        with self._lock:
            return self._district_locked(area, signgu)

    def _district_locked(self, area: str, signgu: str) -> dict[tuple[str, str], float]:
        hit = self._cache.get((area, signgu))
        if hit and time.monotonic() - hit[0] < self._ttl:
            return hit[1]
        data: dict[tuple[str, str], float] = {}
        page = 1
        while True:
            r = self._client.get(URL, params={
                "serviceKey": self._key, "MobileOS": "ETC", "MobileApp": "SurfMateAI", "_type": "json",
                "numOfRows": 1000, "pageNo": page, "areaCd": area, "signguCd": signgu})
            r.raise_for_status()
            resp = r.json()["response"]
            if resp["header"]["resultCode"] != "0000":
                raise ValueError(f"관광공사 API 오류: {resp['header']}")
            data.update(parse(resp["body"]))
            if page * 1000 >= int(resp["body"].get("totalCount") or 0):
                break
            page += 1
        self._cache[(area, signgu)] = (time.monotonic(), data)
        return data

    def rate(self, ref: TourRef | None, day: date) -> float | None:
        """해당 날짜 집중률(0~100). 데이터가 없거나 호출이 실패하면 None."""
        if ref is None:
            return None
        cached = self._cache.get((ref.area, ref.signgu))
        if time.monotonic() < self._down_until:  # 최근 실패 → 호출하지 않고 오래된 값(있으면)만 사용
            return cached[1].get((ref.name, day.strftime("%Y%m%d"))) if cached else None
        try:
            data = self._district(ref.area, ref.signgu)
        except (httpx.HTTPError, ValueError, KeyError) as e:
            log.warning("관광지 집중률 조회 실패 (%s), %d초 동안 재시도 안 함: %s", ref.name, self._retry_after, e)
            self._down_until = time.monotonic() + self._retry_after
            if cached:  # 오래된 값이라도 있으면 사용
                return cached[1].get((ref.name, day.strftime("%Y%m%d")))
            return None
        return data.get((ref.name, day.strftime("%Y%m%d")))
