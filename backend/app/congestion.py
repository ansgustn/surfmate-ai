"""라인업 혼잡도 추정 (규칙 기반 대리지표).

서핑 라인업 인원을 직접 알려주는 공개 데이터가 없어서, 붐빔과 관련된 요인을 곱해
0~100 점수로 추정한다. 학습 모델이 아니며, 웹캠 인원 집계 등 정답 데이터가 모이면
각 계수를 학습값으로 바꾼다.

  점수 = 100 × 해변 인기도 × (그날의 붐빔) × 시간대 × 파도 매력도

그날의 붐빔:
  - 한국관광공사 관광지 집중률 예측(0~100)이 있으면 집중률/100  ← 실제 통신 데이터 기반
  - 없으면 요일(주말·공휴일) × 계절 규칙
"""

from datetime import date, datetime
from enum import Enum
from functools import lru_cache

import holidays
from pydantic import BaseModel

# 시간대 (사진 속 결과물과 같은 구간)
SLOTS = [(9, 12, "오전 9~12시"), (12, 15, "오후 12~3시"), (15, 18, "오후 3~6시"), (18, 21, "오후 6~9시")]

# 시각별 라인업 이용 비율 (서핑 강습이 몰리는 10~15시가 최대). 없는 시각은 0.05
HOUR_FACTOR = {6: 0.4, 7: 0.5, 8: 0.6, 9: 0.75, 10: 0.95, 11: 1.0, 12: 0.9, 13: 1.0, 14: 1.0,
               15: 0.9, 16: 0.8, 17: 0.65, 18: 0.45, 19: 0.3, 20: 0.15}

# 월별 계수 (여름 성수기 최대)
MONTH_FACTOR = {1: 0.2, 2: 0.2, 3: 0.25, 4: 0.35, 5: 0.55, 6: 0.75,
                7: 1.0, 8: 1.0, 9: 0.75, 10: 0.5, 11: 0.3, 12: 0.2}

WEEKDAY_FACTOR = 0.45  # 평일 / 주말·공휴일 = 1.0


class Level(str, Enum):
    low = "low"
    normal = "normal"
    high = "high"

    @property
    def label(self) -> str:
        return {"low": "여유", "normal": "보통", "high": "혼잡"}[self.value]

    @property
    def rank(self) -> int:
        return {"low": 0, "normal": 1, "high": 2}[self.value]


def level_of(score: int) -> Level:
    return Level.low if score < 35 else Level.normal if score < 65 else Level.high


class SlotEstimate(BaseModel):
    label: str
    score: int
    level: Level
    level_label: str


class Congestion(BaseModel):
    score: int  # 지금 시각 추정치 0~100
    level: Level
    level_label: str
    slots: list[SlotEstimate]  # 오늘 시간대별
    factors: list[str]  # 점수에 영향을 준 요인 (화면·챗봇 설명용)
    method: str = "규칙 기반 추정 (요일·공휴일·계절·시간대·파도·해변 인기도)"
    concentration: float | None = None  # 한국관광공사 관광지 집중률 (그날, 0~100)


@lru_cache(maxsize=8)
def _kr_holidays(year: int) -> holidays.HolidayBase:
    return holidays.KR(years=year)


def day_info(d: date) -> tuple[float, str]:
    name = _kr_holidays(d.year).get(d)
    if name:
        return 1.0, f"공휴일({name})"
    if d.weekday() >= 5:
        return 1.0, "주말"
    return WEEKDAY_FACTOR, "평일"


def wave_appeal(wave_m: float) -> tuple[float, str]:
    """서핑하기 좋은 파도일수록 사람이 몰린다."""
    if wave_m < 0.3:
        return 0.3, "파도가 거의 없어 서퍼가 적음"
    if wave_m < 0.5:
        return 0.6, "파도가 작아 서퍼가 다소 적음"
    if wave_m <= 1.5:
        return 1.0, "서핑하기 좋은 파도라 서퍼가 몰림"
    return 0.6, "파도가 높아 초보·강습 인원이 줄어듦"


def _score(popularity: float, day_f: float, month_f: float, hour_f: float, wave_f: float) -> int:
    return round(100 * popularity * day_f * month_f * hour_f * wave_f)


def estimate(popularity: float, wave_m: float, now: datetime,
             concentration: float | None = None) -> Congestion:
    """models 를 import 하지 않도록 필요한 값만 받는다 (SpotReport 가 Congestion 을 포함).
    concentration: 그날의 관광지 집중률(0~100). 있으면 요일·계절 규칙 대신 쓴다."""
    day_f, day_label = day_info(now.date())
    month_f = MONTH_FACTOR[now.month]
    wave_f, wave_label = wave_appeal(wave_m)
    if concentration is not None:
        base = (popularity, concentration / 100, 1.0)
    else:
        base = (popularity, day_f, month_f)

    score = _score(*base, HOUR_FACTOR.get(now.hour, 0.05), wave_f)
    slots = []
    for start, end, label in SLOTS:
        hour_f = sum(HOUR_FACTOR.get(h, 0.05) for h in range(start, end)) / (end - start)
        # 다른 시간대도 지금 파도가 유지된다고 가정 (시간별 파도 예보 연동 전까지)
        s = _score(*base, hour_f, wave_f)
        lv = level_of(s)
        slots.append(SlotEstimate(label=label, score=s, level=lv, level_label=lv.label))

    season = "성수기" if month_f >= 0.75 else "비수기" if month_f <= 0.35 else "준성수기"
    lv = level_of(score)
    if concentration is not None:
        factors = [f"관광지 집중률 {concentration:.0f} (한국관광공사 예측, {day_label})", wave_label,
                   f"해변 인기도 {popularity:.0%}"]
        method = "한국관광공사 관광지 집중률 × 시간대·파도·해변 인기도 규칙"
    else:
        factors = [day_label, f"{season}({now.month}월)", wave_label, f"해변 인기도 {popularity:.0%}"]
        method = "규칙 기반 추정 (요일·공휴일·계절·시간대·파도·해변 인기도)"
    return Congestion(score=score, level=lv, level_label=lv.label, slots=slots,
                      factors=factors, method=method, concentration=concentration)
