from datetime import date

import httpx

from app.congestion import Level, estimate
from app.tour import TourConcentrationProvider, TourRef
from tests.test_api import BUSY, QUIET

REF = TourRef(area="26", signgu="26350", name="송정해수욕장")


def body(items, total=None):
    return {"response": {"header": {"resultCode": "0000", "resultMsg": "OK"},
                         "body": {"items": {"item": items}, "numOfRows": 1000, "pageNo": 1,
                                  "totalCount": total if total is not None else len(items)}}}


ITEMS = [
    {"baseYmd": "20261116", "tAtsNm": "송정해수욕장", "cnctrRate": "57.25"},
    {"baseYmd": "20261117", "tAtsNm": "송정해수욕장", "cnctrRate": "56.37"},
    {"baseYmd": "20261116", "tAtsNm": "해운대해수욕장", "cnctrRate": "64.85"},
]


def provider(handler):
    calls = []

    def h(req):
        calls.append(req)
        return handler(req)

    return TourConcentrationProvider("k", client=httpx.Client(transport=httpx.MockTransport(h))), calls


def test_rate_lookup_and_cache():
    p, calls = provider(lambda req: httpx.Response(200, json=body(ITEMS)))
    assert p.rate(REF, date(2026, 11, 16)) == 57.25
    assert p.rate(REF, date(2026, 11, 17)) == 56.37
    assert p.rate(REF, date(2026, 12, 31)) is None  # 30일 예측 범위 밖
    assert len(calls) == 1 and calls[0].url.params["signguCd"] == "26350"


def test_failure_returns_none_and_backs_off():
    p, calls = provider(lambda req: httpx.Response(503))
    assert p.rate(REF, date(2026, 11, 16)) is None
    assert p.rate(REF, date(2026, 11, 16)) is None
    assert len(calls) == 1  # 실패 후 바로 다시 호출하지 않음


def test_single_item_object():
    p, _ = provider(lambda req: httpx.Response(200, json=body(ITEMS[0])))
    assert p.rate(REF, date(2026, 11, 16)) == 57.25


def test_concentration_replaces_day_and_season_rules():
    # 11월 평일 새벽이라도 집중률이 높으면 낮 시간대는 붐빈다고 본다
    c = estimate(1.0, 0.8, QUIET.replace(hour=13), concentration=90)
    assert c.level == Level.high and c.concentration == 90
    assert c.factors[0].startswith("관광지 집중률 90")
    # 8월 토요일이라도 집중률이 낮으면 한산
    assert estimate(1.0, 0.8, BUSY, concentration=20).level == Level.low
