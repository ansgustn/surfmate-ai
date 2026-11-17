import logging
import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from .chat import OFF_TOPIC, ChatRequest, ChatResponse, OllamaError, ask_ollama, build_messages, ollama_model, pick_alternatives, resolve_focus
from .congestion import estimate as estimate_congestion
from .models import Conditions, Spot, SpotReport
from .repository import JsonSpotRepository, PostgisSpotRepository, SpotRepository
from .safety import grade
from .tour import TourConcentrationProvider
from .weather import KmaSeaObsProvider, MockWeatherProvider, OpenMeteoProvider, WeatherProvider


def _load_dotenv(path: Path = Path(__file__).resolve().parents[1] / ".env") -> None:
    """backend/.env 의 KEY=VALUE 를 환경변수로 (이미 설정된 값은 유지)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    if os.getenv("WARM_UP", "1") != "0":
        threading.Thread(target=_warm_up, daemon=True).start()
    yield


app = FastAPI(title="SurfMate AI API", version="0.1.0", lifespan=_lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_repo: SpotRepository | None = None
_weather: WeatherProvider | None = None


def get_repo() -> SpotRepository:
    global _repo
    if _repo is None:
        dsn = os.getenv("DATABASE_URL")
        _repo = PostgisSpotRepository(dsn) if dsn else JsonSpotRepository()
    return _repo


def get_weather() -> WeatherProvider:
    """WEATHER_PROVIDER=mock → 가짜 데이터.
    그 외: Open-Meteo 예보, KMA_AUTH_KEY 가 있으면 가까운 기상청 부이 실측값을 우선 사용."""
    global _weather
    if _weather is None:
        if os.getenv("WEATHER_PROVIDER") == "mock":
            _weather = MockWeatherProvider()
        elif key := os.getenv("KMA_AUTH_KEY"):
            _weather = KmaSeaObsProvider(key, base=OpenMeteoProvider())
        else:
            _weather = OpenMeteoProvider()
    return _weather


_tour: TourConcentrationProvider | None = None


def get_tour() -> TourConcentrationProvider | None:
    """DATA_GO_KR_KEY 가 있으면 한국관광공사 관광지 집중률을 혼잡도에 반영."""
    global _tour
    if _tour is None and (key := os.getenv("DATA_GO_KR_KEY")):
        _tour = TourConcentrationProvider(key)
    return _tour


KST = ZoneInfo("Asia/Seoul")


def _warm_up() -> None:
    """해변이 수백 곳이라 첫 요청이 오래 걸리지 않도록 서버 시작 때 날씨·집중률을 미리 받아 둔다."""
    try:
        spots = get_repo().all()
        get_weather().get_many(spots)
        if tour := get_tour():
            today = datetime.now(KST).date()
            for ref in {(s.tour.area, s.tour.signgu): s.tour for s in spots if s.tour}.values():
                tour.rate(ref, today)
        logging.getLogger(__name__).info("미리 받기 완료: 해변 %d곳", len(spots))
    except Exception as e:  # 실패해도 요청 때 다시 받으므로 서버는 계속 뜬다
        logging.getLogger(__name__).warning("미리 받기 실패: %s", e)


def get_now() -> datetime:
    """혼잡도 추정 기준 시각 (테스트에서 고정할 수 있도록 의존성으로 둔다)."""
    return datetime.now(KST)


def _report(spot: Spot, cond: Conditions, now: datetime, dist: float | None = None,
            tour: TourConcentrationProvider | None = None) -> SpotReport:
    rate = tour.rate(spot.tour, now.date()) if tour else None
    return SpotReport(spot=spot, conditions=cond, grade=grade(spot, cond),
                      distance_km=None if dist is None else round(dist, 1),
                      congestion=estimate_congestion(spot.popularity, cond.wave_height_m, now, rate))


@app.get("/", include_in_schema=False)
def root():
    """루트로 들어오면 API 문서로 보낸다."""
    return RedirectResponse("/docs")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/spots", response_model=list[Spot])
def list_spots(repo: SpotRepository = Depends(get_repo)):
    return repo.all()


@app.get("/spots/{spot_id}", response_model=SpotReport)
def spot_report(spot_id: str, repo: SpotRepository = Depends(get_repo),
                weather: WeatherProvider = Depends(get_weather), now: datetime = Depends(get_now),
                tour: TourConcentrationProvider | None = Depends(get_tour)):
    spot = repo.get(spot_id)
    if spot is None:
        raise HTTPException(404, f"스팟을 찾을 수 없습니다: {spot_id}")
    return _report(spot, weather.get_many([spot])[spot.id], now, tour=tour)


@app.get("/recommend", response_model=list[SpotReport])
def recommend(
    lat: float | None = Query(None, ge=-90, le=90),
    lon: float | None = Query(None, ge=-180, le=180),
    max_km: float = Query(50, gt=0, description="위치를 준 경우 이 거리(km) 안의 스팟만"),
    limit: int = Query(3, ge=1, le=500),
    repo: SpotRepository = Depends(get_repo),
    weather: WeatherProvider = Depends(get_weather),
    now: datetime = Depends(get_now),
    tour: TourConcentrationProvider | None = Depends(get_tour),
):
    """초보자 추천 스팟. 안전 등급 → 혼잡도 → 거리 → 적정 파고(0.75m)와의 차이 순으로 정렬."""
    if (lat is None) != (lon is None):
        raise HTTPException(422, "lat 과 lon 은 함께 지정해야 합니다")
    spots = repo.all()
    if lat is not None:
        dists = repo.distances_km(lat, lon)
        spots = [s for s in spots if dists[s.id] <= max_km]
    else:
        dists = {}
    conds = weather.get_many(spots)
    reports = [_report(s, conds[s.id], now, dists.get(s.id), tour) for s in spots]
    reports.sort(key=lambda r: (
        r.grade.status.rank,
        r.congestion.level.rank,
        r.distance_km if r.distance_km is not None else 0,
        abs(r.conditions.wave_height_m - 0.75),
    ))
    return reports[:limit]


def get_llm():
    return ask_ollama


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, repo: SpotRepository = Depends(get_repo),
         weather: WeatherProvider = Depends(get_weather), llm=Depends(get_llm),
         now: datetime = Depends(get_now), tour: TourConcentrationProvider | None = Depends(get_tour)):
    """AI 에이전트 챗봇. 현재 전체 스팟 상태를 근거로 답하고, 대안 스팟 카드를 함께 돌려준다."""
    if (req.lat is None) != (req.lon is None):
        raise HTTPException(422, "lat 과 lon 은 함께 지정해야 합니다")
    spots = repo.all()
    conds = weather.get_many(spots)
    reports = sorted((_report(s, conds[s.id], now, tour=tour) for s in spots), key=lambda r: r.grade.status.rank)
    mentioned, region = resolve_focus(req, reports)
    alternatives = pick_alternatives(reports, mentioned, req.lat, req.lon, region=region)
    try:
        reply = llm(build_messages(req, reports, mentioned, alternatives, region))
    except OllamaError as e:
        raise HTTPException(503, str(e)) from e
    if OFF_TOPIC in reply:  # 서핑과 무관한 질문이면 스팟 카드를 붙이지 않는다
        mentioned, alternatives = None, []
    return ChatResponse(reply=reply, spot=mentioned, alternatives=alternatives, model=ollama_model())
