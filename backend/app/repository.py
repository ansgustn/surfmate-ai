"""스팟 저장소.

DATABASE_URL 이 있으면 PostGIS, 없으면 db/seed/spots.json 을 읽는다.
DB 없이도 바로 개발·테스트할 수 있게 하기 위함.
"""

import json
import math
from pathlib import Path
from typing import Protocol

from .models import Spot
from .tour import TourRef

SEED_PATH = Path(__file__).resolve().parents[2] / "db" / "seed" / "spots.json"
# 관광공사 TourAPI 에서 자동으로 가져온 서핑 해안 해변 (scripts/import_beaches.py 로 생성)
AUTO_SEED_PATH = SEED_PATH.with_name("spots_auto.json")


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


class SpotRepository(Protocol):
    def all(self) -> list[Spot]: ...
    def get(self, spot_id: str) -> Spot | None: ...
    def distances_km(self, lat: float, lon: float) -> dict[str, float]: ...


class JsonSpotRepository:
    def __init__(self, path: Path = SEED_PATH, auto_path: Path | None = AUTO_SEED_PATH):
        """직접 정리한 해변을 먼저, 자동 수집 해변은 그 뒤에 (id 가 겹치면 직접 정리한 쪽)."""
        rows = json.loads(path.read_text(encoding="utf-8"))
        if auto_path and auto_path.exists():
            ids = {r["id"] for r in rows}
            rows += [r for r in json.loads(auto_path.read_text(encoding="utf-8")) if r["id"] not in ids]
        self._spots = [Spot(**s) for s in rows]

    def all(self) -> list[Spot]:
        return list(self._spots)

    def get(self, spot_id: str) -> Spot | None:
        return next((s for s in self._spots if s.id == spot_id), None)

    def distances_km(self, lat: float, lon: float) -> dict[str, float]:
        return {s.id: haversine_km(lat, lon, s.lat, s.lon) for s in self._spots}


class PostgisSpotRepository:
    _SELECT = """
        SELECT id, name, region, ST_Y(geom::geometry), ST_X(geom::geometry),
               bottom_type, beginner_friendly, board_fit, popularity, note,
               tour_area, tour_signgu, tour_name
        FROM spots
    """

    def __init__(self, dsn: str):
        import psycopg

        self._conn = psycopg.connect(dsn, autocommit=True)

    @staticmethod
    def _row(r) -> Spot:
        return Spot(
            id=r[0], name=r[1], region=r[2], lat=r[3], lon=r[4],
            bottom_type=r[5], beginner_friendly=r[6], board_fit=r[7], popularity=r[8], note=r[9],
            tour=TourRef(area=r[10], signgu=r[11], name=r[12]) if r[10] else None,
        )

    def all(self) -> list[Spot]:
        return [self._row(r) for r in self._conn.execute(self._SELECT + " ORDER BY id")]

    def get(self, spot_id: str) -> Spot | None:
        r = self._conn.execute(self._SELECT + " WHERE id = %s", (spot_id,)).fetchone()
        return self._row(r) if r else None

    def distances_km(self, lat: float, lon: float) -> dict[str, float]:
        rows = self._conn.execute(
            "SELECT id, ST_Distance(geom, ST_MakePoint(%s, %s)::geography) / 1000 FROM spots",
            (lon, lat),
        )
        return {r[0]: r[1] for r in rows}
