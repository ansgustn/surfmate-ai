"""db/seed/spots.json (+ spots_auto.json) 을 PostGIS spots 테이블에 넣는다 (있으면 갱신).

사용: DATABASE_URL=postgresql://surf:surf@localhost:5432/surf python scripts/load_spots.py
"""

import json
import os
from pathlib import Path

import psycopg

SEED = Path(__file__).resolve().parents[2] / "db" / "seed" / "spots.json"
AUTO_SEED = SEED.with_name("spots_auto.json")

UPSERT = """
INSERT INTO spots (id, name, region, geom, bottom_type, beginner_friendly, board_fit, popularity, note,
                   tour_area, tour_signgu, tour_name)
VALUES (%(id)s, %(name)s, %(region)s, ST_MakePoint(%(lon)s, %(lat)s)::geography,
        %(bottom_type)s, %(beginner_friendly)s, %(board_fit)s, %(popularity)s, %(note)s,
        %(tour_area)s, %(tour_signgu)s, %(tour_name)s)
ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name, region = EXCLUDED.region, geom = EXCLUDED.geom,
    bottom_type = EXCLUDED.bottom_type, beginner_friendly = EXCLUDED.beginner_friendly,
    board_fit = EXCLUDED.board_fit, popularity = EXCLUDED.popularity, note = EXCLUDED.note,
    tour_area = EXCLUDED.tour_area, tour_signgu = EXCLUDED.tour_signgu, tour_name = EXCLUDED.tour_name
"""


def main() -> None:
    spots = json.loads(SEED.read_text(encoding="utf-8"))
    if AUTO_SEED.exists():
        ids = {s["id"] for s in spots}
        spots += [s for s in json.loads(AUTO_SEED.read_text(encoding="utf-8")) if s["id"] not in ids]
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        for s in spots:
            t = s.get("tour") or {}
            conn.execute(UPSERT, {**s, "tour_area": t.get("area"), "tour_signgu": t.get("signgu"),
                                  "tour_name": t.get("name")})
    print(f"{len(spots)}개 스팟 적재 완료")


if __name__ == "__main__":
    main()
