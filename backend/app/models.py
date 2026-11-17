from enum import Enum

from pydantic import BaseModel

from .congestion import Congestion
from .tour import TourRef


class BottomType(str, Enum):
    sand = "sand"
    reef = "reef"
    mixed = "mixed"
    rock = "rock"
    unknown = "unknown"  # 공공데이터에서 자동으로 가져온 해변 (현장 확인 전)


class Status(str, Enum):
    """초보자 기준 입수 상태. 값이 클수록 위험."""

    optimal = "optimal"  # 입수 최적
    caution = "caution"  # 주의 요망
    avoid = "avoid"  # 입수 자제

    @property
    def label(self) -> str:
        return {"optimal": "입수 최적", "caution": "주의 요망", "avoid": "입수 자제"}[self.value]

    @property
    def rank(self) -> int:
        return {"optimal": 0, "caution": 1, "avoid": 2}[self.value]


class Spot(BaseModel):
    id: str
    name: str
    region: str
    lat: float
    lon: float
    bottom_type: BottomType
    beginner_friendly: bool
    board_fit: list[str]
    popularity: float = 0.5  # 0~1, 서핑 인기도 (혼잡도 추정용 초기값, 검증 필요)
    tour: TourRef | None = None  # 한국관광공사 관광지 집중률 데이터의 관광지
    note: str | None = None


class Conditions(BaseModel):
    wave_height_m: float
    wave_period_s: float
    wind_speed_ms: float
    wind_dir_deg: float
    tide_m: float
    source: str  # "kma" | "open-meteo" | "mock"
    station: str | None = None  # 기상청 관측 지점·거리 (source 가 kma 일 때)


class Grade(BaseModel):
    status: Status
    label: str
    reasons: list[str]


class SpotReport(BaseModel):
    spot: Spot
    conditions: Conditions
    grade: Grade
    distance_km: float | None = None
    congestion: Congestion | None = None
