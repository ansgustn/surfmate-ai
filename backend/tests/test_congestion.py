from datetime import datetime

from app.congestion import Level, day_info, estimate, level_of

from tests.test_api import BUSY, QUIET


def test_day_info():
    assert day_info(datetime(2026, 11, 10).date())[1] == "평일"
    assert day_info(datetime(2026, 11, 14).date())[1] == "주말"
    assert day_info(datetime(2026, 10, 3).date())[1].startswith("공휴일")  # 개천절(토요일이지만 공휴일 우선)


def test_levels():
    assert level_of(34) == Level.low and level_of(35) == Level.normal and level_of(65) == Level.high


def test_busy_vs_quiet():
    assert estimate(1.0, 0.8, BUSY).level == Level.high
    assert estimate(1.0, 0.8, QUIET).level == Level.low


def test_small_waves_reduce_crowd():
    assert estimate(1.0, 0.1, BUSY).score < estimate(1.0, 0.8, BUSY).score


def test_slots_and_factors():
    c = estimate(0.9, 0.8, BUSY)
    assert [s.label for s in c.slots] == ["오전 9~12시", "오후 12~3시", "오후 3~6시", "오후 6~9시"]
    assert c.slots[3].score < c.slots[1].score  # 저녁이 낮보다 한산
    assert "주말" in c.factors and "성수기(8월)" in c.factors
