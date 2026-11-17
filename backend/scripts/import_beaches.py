"""서핑 해안의 해변을 관광공사 TourAPI 에서 가져와 db/seed/spots_auto.json 을 만든다.

- 출처: 한국관광공사 국문 관광정보 서비스 areaBasedList2 (분류 NA020900 해수욕장, 좌표 포함)
- 대상: 파도가 들어오는 해안 시군구만 (SURF_COAST). 서해 갯벌·남해 만 안쪽은 제외
- 혼잡도: 관광지 집중률 API 의 관광지명과 이름이 정확히 맞으면 tour 참조를 붙인다
- 직접 정리한 db/seed/spots.json 과 1km 안에 있거나 이름이 같으면 건너뛴다

자동으로 가져온 해변은 해저 지형을 모르므로 bottom_type='unknown'(안전 등급 최소 '주의 요망'),
초보 적합 여부 false, 인기도 0.3 으로 둔다. 현장 확인 후 spots.json 으로 옮겨 정리한다.

사용: python scripts/import_beaches.py   (backend/.env 의 DATA_GO_KR_KEY 사용, 학교망에서는 접속 안 됨)
"""

import json
import re
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.repository import haversine_km  # noqa: E402
from app.tour import URL as CNCTR_URL, parse  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CURATED = ROOT / "db" / "seed" / "spots.json"
OUT = ROOT / "db" / "seed" / "spots_auto.json"
TOUR_URL = "https://apis.data.go.kr/B551011/KorService2/areaBasedList2"

# 서핑 해안 시군구 (법정동 시도+시군구 코드) → 앱에서 쓰는 지역 이름
SURF_COAST = {
    "26140": "부산", "26200": "부산", "26350": "부산", "26380": "부산", "26500": "부산", "26710": "부산",
    "31170": "울산", "31200": "울산", "31710": "울산",
    "47111": "포항", "47113": "포항", "47130": "경주", "47770": "영덕", "47930": "울진",
    "48310": "거제",
    "44825": "태안",
    "50110": "제주", "50130": "제주",
    "51150": "강릉", "51170": "동해", "51210": "속초", "51230": "삼척", "51820": "고성", "51830": "양양",
}
DEFAULT_POPULARITY = 0.3
NOTE = "공공데이터에서 자동으로 가져온 해변 — 해저 지형·이안류·서핑 가능 여부 미확인"


def key() -> str:
    for line in (ROOT / "backend" / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("DATA_GO_KR_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("backend/.env 에 DATA_GO_KR_KEY 가 없습니다")


def core(name: str, region: str = "") -> str:
    """'강릉 경포해수욕장' → '경포', '남애해변(남애1, 3리)' → '남애'"""
    n = re.sub(r"\(.*?\)|\[.*?\]", "", name)
    n = re.sub(r"(간이)?(해수욕장|해변|해안)\s*$", "", n.strip()).strip()
    head = re.split(r"해수욕장|해변", n)[0].strip(" ·")  # '장호해변·장호항' → '장호'
    if len(head) >= 2:
        n = head
    words = n.split()
    if len(words) > 1 and (words[0] == region or words[0] in SURF_COAST.values()):
        n = " ".join(words[1:])
    return n.strip()


def match_key(name: str) -> str:
    return re.sub(r"\s|·|,", "", core(name))


def fetch_beaches(c: httpx.Client, k: str) -> list[dict]:
    items, page = [], 1
    while True:
        j = c.get(TOUR_URL, params={
            "serviceKey": k, "MobileOS": "ETC", "MobileApp": "SurfMateAI", "_type": "json",
            "contentTypeId": 12, "lclsSystm1": "NA", "lclsSystm2": "NA02", "lclsSystm3": "NA020900",
            "numOfRows": 1000, "pageNo": page, "arrange": "A"}).json()
        body = j["response"]["body"]
        it = (body.get("items") or {}).get("item") or []
        items += [it] if isinstance(it, dict) else it
        if page * 1000 >= int(body.get("totalCount") or 0):
            return items
        page += 1


def fetch_tour_names(c: httpx.Client, k: str, sg: str) -> set[str]:
    """그 시군구에서 집중률 데이터가 있는 관광지 이름들."""
    for attempt in range(3):
        try:
            names, page = set(), 1
            while True:  # 30일 × 관광지 수라 1000행을 넘으면 여러 페이지
                r = c.get(CNCTR_URL, params={
                    "serviceKey": k, "MobileOS": "ETC", "MobileApp": "SurfMateAI", "_type": "json",
                    "numOfRows": 1000, "pageNo": page, "areaCd": sg[:2], "signguCd": sg})
                body = r.json()["response"]["body"]
                names |= {name for name, _ in parse(body)}
                if page * 1000 >= int(body.get("totalCount") or 0):
                    return names
                page += 1
        except (httpx.HTTPError, KeyError, ValueError):
            time.sleep(2 * (attempt + 1))
    print(f"  ! {sg} 집중률 이름 조회 실패")
    return set()


def main() -> None:
    k = key()
    c = httpx.Client(timeout=httpx.Timeout(60, connect=5))
    curated = json.loads(CURATED.read_text(encoding="utf-8"))
    beaches = fetch_beaches(c, k)
    print(f"TourAPI 해수욕장 {len(beaches)}곳")

    tour_names = {}
    for sg in sorted(SURF_COAST):
        tour_names[sg] = {match_key(n): n for n in fetch_tour_names(c, k, sg) if match_key(n)}
        time.sleep(0.3)

    out, seen, skipped_dup, with_tour = [], set(), 0, 0
    for b in sorted(beaches, key=lambda b: b["contentid"]):
        sg = f"{b['lDongRegnCd']}{b['lDongSignguCd']}"
        region = SURF_COAST.get(sg)
        if not region or not b.get("mapx"):
            continue
        lat, lon = float(b["mapy"]), float(b["mapx"])
        name_core = core(b["title"], region)
        if len(name_core) < 2:
            name_core = re.sub(r"\(.*?\)", "", b["title"]).strip()
        if (region, name_core) in seen or any(
                haversine_km(lat, lon, s["lat"], s["lon"]) < 1.0 or
                (s["region"] == region and core(s["name"], region) == name_core) for s in curated):
            skipped_dup += 1
            continue
        seen.add((region, name_core))
        tour_name = tour_names[sg].get(match_key(b["title"]))
        with_tour += bool(tour_name)
        out.append({
            "id": f"t{b['contentid']}",
            "name": f"{name_core} 해변",
            "region": region,
            "lat": round(lat, 5),
            "lon": round(lon, 5),
            "bottom_type": "unknown",
            "beginner_friendly": False,
            "board_fit": [],
            "popularity": DEFAULT_POPULARITY,
            "tour": {"area": sg[:2], "signgu": sg, "name": tour_name} if tour_name else None,
            "note": NOTE,
        })

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"저장 {len(out)}곳 → {OUT.relative_to(ROOT)} (집중률 연결 {with_tour}곳, 기존 해변과 겹쳐 제외 {skipped_dup}곳)")


if __name__ == "__main__":
    main()
