"""한국관광공사 지역별 방문자수(일별, 통신 데이터 기반)를 모아 CSV 로 저장한다.

혼잡도 예측 모델을 학습할 때 쓸 실측 이력 데이터. 스팟이 있는 시군구만 남긴다.
API 는 지역을 골라 조회할 수 없어 전국이 한꺼번에 온다.

사용 (backend 폴더에서, data.go.kr 이 열리는 네트워크에서):
  python scripts/collect_visitors.py 20260701 20260831
결과: ../data/visitors.csv  (이미 있는 날짜·지역·구분은 덮어씀)
"""

import csv
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "visitors.csv"
URL = "https://apis.data.go.kr/B551011/DataLabService/locgoRegnVisitrDDList"
# 스팟이 있는 시군구: 해운대구(해운대·송정), 사하구(다대포), 기장군(일광), 양양군(죽도·기사문)
TARGETS = {"26350", "26380", "26710", "51830"}
FIELDS = ["baseYmd", "signguCode", "signguNm", "daywkDivNm", "touDivNm", "touNum"]


def load_key() -> str:
    if key := os.getenv("DATA_GO_KR_KEY"):
        return key
    for line in (ROOT / "backend" / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("DATA_GO_KR_KEY="):
            return line.split("=", 1)[1].strip()
    sys.exit("DATA_GO_KR_KEY 가 없습니다 (backend/.env)")


def fetch(client: httpx.Client, key: str, start: str, end: str) -> list[dict]:
    rows, page = [], 1
    while True:
        r = client.get(URL, params={"serviceKey": key, "MobileOS": "ETC", "MobileApp": "SurfMateAI",
                                    "_type": "json", "numOfRows": 1000, "pageNo": page,
                                    "startYmd": start, "endYmd": end})
        r.raise_for_status()
        resp = r.json()["response"]
        if resp["header"]["resultCode"] != "0000":
            raise RuntimeError(resp["header"])
        items = (resp["body"].get("items") or {}).get("item") or []
        items = [items] if isinstance(items, dict) else items
        rows += [{k: it.get(k) for k in FIELDS} for it in items if it.get("signguCode") in TARGETS]
        if page * 1000 >= int(resp["body"].get("totalCount") or 0):
            return rows
        page += 1


def main(start: str, end: str) -> None:
    key, client = load_key(), httpx.Client(timeout=60)
    existing: dict[tuple, dict] = {}
    if OUT.exists():
        with OUT.open(encoding="utf-8") as f:
            existing = {(r["baseYmd"], r["signguCode"], r["touDivNm"]): r for r in csv.DictReader(f)}

    d, last = datetime.strptime(start, "%Y%m%d"), datetime.strptime(end, "%Y%m%d")
    added = 0
    while d <= last:  # 한 번에 7일씩 (응답이 너무 커지지 않게)
        chunk_end = min(d + timedelta(days=6), last)
        for r in fetch(client, key, d.strftime("%Y%m%d"), chunk_end.strftime("%Y%m%d")):
            existing[(r["baseYmd"], r["signguCode"], r["touDivNm"])] = r
            added += 1
        print(f"{d:%Y-%m-%d} ~ {chunk_end:%Y-%m-%d} 완료")
        d = chunk_end + timedelta(days=1)

    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(sorted(existing.values(), key=lambda r: (r["baseYmd"], r["signguCode"], r["touDivNm"])))
    print(f"{added}행 수집, 총 {len(existing)}행 → {OUT}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
