import pytest
from fastapi.testclient import TestClient

from app.chat import OllamaError
from app.main import app, get_llm, get_now, get_tour, get_weather
from tests.test_api import BUSY, QUIET, FixedWeather  # 해운대만 파고 1.8m(입수 자제), 나머지 0.8m


@pytest.fixture
def captured():
    calls = []

    def fake_llm(messages):
        calls.append(messages)
        return "테스트 답변"

    app.dependency_overrides[get_weather] = FixedWeather
    app.dependency_overrides[get_llm] = lambda: fake_llm
    app.dependency_overrides[get_now] = lambda: QUIET
    app.dependency_overrides[get_tour] = lambda: None  # 실제 관광공사 API 호출 안 함
    yield calls
    app.dependency_overrides.clear()


def test_mentioned_risky_spot_gets_safer_nearby_alternatives(captured):
    r = TestClient(app).post("/chat", json={"message": "지금 해운대 어때?"}).json()
    assert r["reply"] == "테스트 답변"
    assert r["spot"]["spot"]["id"] == "haeundae"
    alt = [a["spot"]["id"] for a in r["alternatives"]]
    assert alt == ["gwangalli", "songjeong"]  # 같은 부산, 해운대에서 가까운 순
    system = captured[0][0]["content"]
    assert "사용자가 물어본 해변: 해운대 해변" in system
    assert "입수 자제" in system and "파고 1.8m" in system


def test_optimal_spot_has_no_alternatives(captured):
    r = TestClient(app).post("/chat", json={"message": "송정 해변 괜찮아?"}).json()
    assert r["spot"]["spot"]["id"] == "songjeong" and r["alternatives"] == []


def test_no_mention_uses_location(captured):
    r = TestClient(app).post("/chat", json={"message": "어디 가면 좋아?", "lat": 38.03, "lon": 128.72}).json()
    assert r["spot"] is None
    assert r["alternatives"][0]["spot"]["region"] == "양양"


def test_history_is_forwarded(captured):
    TestClient(app).post("/chat", json={
        "message": "그럼 다른 곳은?",
        "history": [{"role": "user", "content": "해운대 어때?"}, {"role": "assistant", "content": "파도가 높아요"}],
    })
    roles = [m["role"] for m in captured[0]]
    assert roles == ["system", "user", "assistant", "user"]


def test_ollama_down_returns_503():
    def down(_):
        raise OllamaError("Ollama 서버에 연결할 수 없습니다")

    app.dependency_overrides[get_weather] = FixedWeather
    app.dependency_overrides[get_llm] = lambda: down
    app.dependency_overrides[get_tour] = lambda: None
    try:
        r = TestClient(app).post("/chat", json={"message": "해운대?"})
        assert r.status_code == 503 and "Ollama" in r.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_region_mention_limits_alternatives(captured):
    r = TestClient(app).post("/chat", json={"message": "양양 쪽은 어때?", "lat": 35.16, "lon": 129.16}).json()
    assert {a["spot"]["region"] for a in r["alternatives"]} == {"양양"}


def test_follow_up_keeps_previous_region(captured):
    # '제주 어때?' 다음의 '덜 붐비는 곳은?' → 부산(사용자 위치)이 아니라 제주 해변 카드
    history = [{"role": "user", "content": "제주 쪽은 지금 어때?"}, {"role": "assistant", "content": "..."}]
    r = TestClient(app).post("/chat", json={"message": "오늘 덜 붐비는 곳은 어디야?", "history": history,
                                            "lat": 35.16, "lon": 129.16}).json()
    assert {a["spot"]["region"] for a in r["alternatives"]} == {"제주"}
    assert "사용자가 물어본 지역: 제주" in captured[0][0]["content"]


def test_nearby_question_uses_location_not_history(captured):
    history = [{"role": "user", "content": "제주 쪽은 지금 어때?"}, {"role": "assistant", "content": "..."}]
    r = TestClient(app).post("/chat", json={"message": "근처에 초보자가 가기 좋은 해변 있어?", "history": history,
                                            "lat": 35.16, "lon": 129.16}).json()
    assert {a["spot"]["region"] for a in r["alternatives"]} == {"부산"}


def test_no_optimal_alternative_is_flagged():
    from datetime import datetime

    from app.chat import ChatRequest, build_messages
    from app.main import KST, _report, get_repo
    from app.models import Grade, Status
    from tests.test_api import FixedWeather

    req = ChatRequest(message="제주 어때?")
    spots = get_repo().all()
    conds = FixedWeather().get_many(spots)
    reports = [_report(s, conds[s.id], datetime(2026, 11, 10, 3, tzinfo=KST)) for s in spots]
    caution = [r.model_copy(update={"grade": Grade(status=Status.caution, label="주의 요망", reasons=["테스트"])})
               for r in reports if r.spot.region == "제주"]
    text = build_messages(req, reports, None, caution, "제주")[0]["content"]
    assert "'입수 최적' 해변이 없다" in text
    optimal_text = build_messages(req, reports, None, [r for r in reports if r.grade.status == Status.optimal][:2], "제주")[0]["content"]
    assert "'입수 최적' 해변이 없다" not in optimal_text


def test_crowded_optimal_spot_gets_quieter_alternatives(captured):
    app.dependency_overrides[get_now] = lambda: BUSY
    r = TestClient(app).post("/chat", json={"message": "송정 어때?"}).json()
    assert r["spot"]["congestion"]["level"] == "high"
    assert [a["spot"]["id"] for a in r["alternatives"]] == ["gwangalli", "ilgwang"]
    assert "혼잡도(추정) 지금 혼잡" in captured[0][0]["content"]


def test_same_name_prefers_asked_region_then_curated():
    from app.chat import find_mentioned
    from app.main import KST, _report, get_repo
    from tests.test_api import FixedWeather
    from datetime import datetime

    spots = get_repo().all()
    conds = FixedWeather().get_many(spots)
    reports = [_report(s, conds[s.id], datetime(2026, 11, 10, 3, tzinfo=KST)) for s in spots]
    assert find_mentioned("송정 어때?", reports).spot.id == "songjeong"  # 직접 정리한 부산 송정
    gangneung = find_mentioned("강릉 송정 어때?", reports)
    assert gangneung.spot.region == "강릉" and gangneung.spot.name == "송정 해변"


def test_prompt_only_has_relevant_spots(captured):
    TestClient(app).post("/chat", json={"message": "양양 쪽은 어때?", "lat": 35.16, "lon": 129.16})
    system = captured[0][0]["content"]
    from app.chat import CONTEXT_LIMIT
    assert system.count("\n- ") <= CONTEXT_LIMIT + 3  # 해변 목록 + 추천 대안
    assert "- 양양 죽도 해변" in system
