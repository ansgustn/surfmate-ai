"""AI 에이전트 챗봇 (Ollama 로컬 LLM).

LLM 이 수치를 지어내지 않도록:
- 현재 모든 스팟의 기상·안전 등급을 시스템 프롬프트에 그대로 넣고
- 질문에 나온 스팟과 대안 스팟은 코드가 정해서 프롬프트와 응답 카드에 함께 쓴다.
"""

import os

import httpx
from pydantic import BaseModel, Field

from .congestion import Level
from .models import SpotReport, Status
from .repository import haversine_km



def ollama_url() -> str:
    return os.getenv("OLLAMA_URL", "http://localhost:11434")


def ollama_model() -> str:
    """backend/.env 를 읽은 뒤의 값을 쓰도록 호출 시점에 읽는다."""
    return os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

OFF_TOPIC = "저는 서핑과 해양 안전 질문만 도와드릴 수 있어요."

SYSTEM_PROMPT = f"""너는 초보 서퍼를 돕는 해양 안전 가이드 'SurfMate AI'야.
규칙:
1. 반드시 자연스러운 한국어로만 답해. 한자·중국어·영어 문장을 섞지 마.
2. 3~4문장으로 짧게 답해.
3. 해변의 등급(입수 최적/주의 요망/입수 자제)과 파고·바람 수치는 아래 해변 상태 목록에 적힌 그대로 전달해. 등급을 바꾸거나 수치를 지어내지 마.
4. '입수 자제'인 해변은 들어가지 말라고 분명히 말해. '주의 요망'이면 그 이유를 설명해.
5. 다른 해변을 추천할 때는 '추천 대안' 목록에 있는 해변만 추천해. 목록이 비어 있으면 추천하지 마.
6. 답변에 대괄호([ ])나 목록 제목을 그대로 쓰지 마.
7. 혼잡도(여유/보통/혼잡)는 요일·계절·시간대로 계산한 '추정치'야. 전할 때는 추정이라고 밝혀. 해변이 '혼잡'이면 충돌 위험을 알리고 추천 대안을 권해.
8. 지형이 '미확인'인 해변은 서핑 가능 여부와 바닥 지형이 확인되지 않은 곳이라고 밝히고, 초보자에게는 지형이 확인된 해변을 먼저 권해.
9. 서핑·바다·해변 날씨와 관계없는 질문(음식, 숙제 등)에는 답하지 말고 "{OFF_TOPIC}"라고만 답해."""

def wind_word(ms: float) -> str:
    """LLM 이 풍속 숫자를 잘못 해석하지 않도록 말로 함께 준다."""
    return "약함" if ms < 4 else "보통" if ms < 8 else "강함" if ms < 12 else "매우 강함"


def wave_word(m: float) -> str:
    return "초보자에게 작음" if m < 0.5 else "초보자 적정" if m <= 1.0 else "초보자에게 높음" if m <= 1.5 else "위험하게 높음"


BOTTOM_KO = {"sand": "모래", "reef": "암초", "mixed": "모래·암반 혼재", "rock": "암반", "unknown": "미확인"}


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=2000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)
    lat: float | None = None
    lon: float | None = None


class ChatResponse(BaseModel):
    reply: str
    spot: SpotReport | None  # 질문에서 언급된 해변
    alternatives: list[SpotReport]
    model: str


def find_mentioned(message: str, reports: list[SpotReport]) -> SpotReport | None:
    """'해운대', '송정 해변' 처럼 해변 이름이 들어 있으면 그 스팟.
    이름이 겹치면 (부산 송정 / 강릉 송정) 질문에 나온 지역 → 긴 이름 → 직접 정리한 해변 순으로 고른다.
    '속초 해변'처럼 지역 이름과 같은 해변 이름은 지역 질문으로 본다."""
    regions = {r.spot.region for r in reports}
    asked_regions = {g for g in regions if g in message}
    best, best_key = None, None
    for r in reports:
        short = r.spot.name.removesuffix(" 해변")
        if len(short) < 2 or short in regions or short not in message:
            continue
        k = (r.spot.region in asked_regions, len(short), r.spot.bottom_type.value != "unknown")
        if best_key is None or k > best_key:
            best, best_key = r, k
    return best


def find_region(message: str, reports: list[SpotReport]) -> str | None:
    """'양양 쪽은 어때?' 처럼 지역 이름만 나온 경우."""
    return next((r.spot.region for r in reports if r.spot.region in message), None)


NEARBY_WORDS = ("근처", "주변", "가까운", "가까이")


def resolve_focus(req: "ChatRequest", reports: list[SpotReport]) -> tuple[SpotReport | None, str | None]:
    """질문이 가리키는 (해변, 지역).
    '덜 붐비는 곳은?' 처럼 해변·지역이 없는 후속 질문은 직전 대화의 지역을 이어받는다.
    단 '근처'처럼 사용자 위치를 묻는 말이 있으면 이어받지 않는다."""
    mentioned = find_mentioned(req.message, reports)
    if mentioned:
        return mentioned, None
    region = find_region(req.message, reports)
    if region or any(w in req.message for w in NEARBY_WORDS):
        return None, region
    for m in reversed(req.history):
        if m.role != "user":
            continue
        prev = find_mentioned(m.content, reports)
        region = prev.spot.region if prev else find_region(m.content, reports)
        if region or any(w in m.content for w in NEARBY_WORDS):
            return None, region
    return None, None


def _crowd_rank(r: SpotReport) -> int:
    return r.congestion.level.rank if r.congestion else 0


def pick_alternatives(reports: list[SpotReport], mentioned: SpotReport | None,
                      lat: float | None, lon: float | None, limit: int = 2,
                      region: str | None = None) -> list[SpotReport]:
    """언급한 해변이 위험하거나 혼잡하면, 같은 지역에서 더 안전하거나 덜 붐비는 해변 → 가까운 순.
    언급이 없으면 (지역을 말했으면 그 지역 안에서) 사용자 위치(없으면 등급)를 기준으로
    '입수 최적'·'주의 요망' 해변을 등급 → 혼잡도 순으로."""
    if mentioned is not None:
        crowded = mentioned.congestion is not None and mentioned.congestion.level == Level.high
        if mentioned.grade.status == Status.optimal and not crowded:
            return []
        m, m_rank, m_crowd = mentioned.spot, mentioned.grade.status.rank, _crowd_rank(mentioned)

        def better(r: SpotReport) -> bool:
            g = r.grade.status.rank
            return g < m_rank or (g == m_rank and _crowd_rank(r) < m_crowd)

        cands = [r for r in reports if r.spot.id != m.id and r.spot.region == m.region and better(r)]
        cands.sort(key=lambda r: (r.grade.status.rank, _crowd_rank(r),
                                  haversine_km(m.lat, m.lon, r.spot.lat, r.spot.lon)))
        return cands[:limit]

    cands = [r for r in reports if r.grade.status != Status.avoid
             and (region is None or r.spot.region == region)]
    if lat is not None and lon is not None:
        cands.sort(key=lambda r: (r.grade.status.rank, _crowd_rank(r),
                                  haversine_km(lat, lon, r.spot.lat, r.spot.lon)))
    else:
        cands.sort(key=lambda r: (r.grade.status.rank, _crowd_rank(r)))
    return cands[:limit]


def describe(r: SpotReport, origin: tuple[float, float] | None = None) -> str:
    c = r.conditions
    src = "기상청 실측" if c.source == "kma" else "예보 모델" if c.source == "open-meteo" else "가짜 데이터"
    dist = ""
    if origin:
        dist = f", 사용자로부터 {haversine_km(origin[0], origin[1], r.spot.lat, r.spot.lon):.0f}km"
    crowd = ""
    if r.congestion:
        slots = ", ".join(f"{x.label} {x.level_label}" for x in r.congestion.slots)
        crowd = f" | 혼잡도(추정) 지금 {r.congestion.level_label}, 오늘 {slots}"
    return (f"- {r.spot.region} {r.spot.name}: {r.grade.label}{crowd} | 파고 {c.wave_height_m}m({wave_word(c.wave_height_m)}), "
            f"파주기 {c.wave_period_s}s, 풍속 {c.wind_speed_ms}m/s(바람 {wind_word(c.wind_speed_ms)}) | 지형 {BOTTOM_KO[r.spot.bottom_type.value]} | 이유: {'; '.join(r.grade.reasons)} "
            f"({src}{dist})")


CONTEXT_LIMIT = 15  # 프롬프트에 넣는 해변 수 (7b 모델 문맥 길이 고려)


def relevant_reports(reports: list[SpotReport], mentioned: SpotReport | None, region: str | None,
                     alternatives: list[SpotReport], origin: tuple[float, float] | None,
                     limit: int = CONTEXT_LIMIT) -> list[SpotReport]:
    """해변이 수백 곳이라 전부 넣지 않고, 질문과 관련된 해변만 골라 넣는다:
    물어본 해변·추천 대안 → 같은 지역 → 사용자 근처(또는 등급 좋은 순)."""
    picked: dict[str, SpotReport] = {}
    focus_region = mentioned.spot.region if mentioned else region
    for r in ([mentioned] if mentioned else []) + alternatives:
        picked[r.spot.id] = r

    def rank(r: SpotReport):
        dist = haversine_km(origin[0], origin[1], r.spot.lat, r.spot.lon) if origin else 0.0
        return (r.spot.region != focus_region, r.grade.status.rank, dist)

    for r in sorted(reports, key=rank):
        if len(picked) >= limit:
            break
        if focus_region is None and origin is None and r.grade.status == Status.avoid:
            continue
        picked.setdefault(r.spot.id, r)
    return list(picked.values())


def build_messages(req: ChatRequest, reports: list[SpotReport], mentioned: SpotReport | None,
                   alternatives: list[SpotReport], region: str | None = None) -> list[dict]:
    origin = (req.lat, req.lon) if req.lat is not None and req.lon is not None else None
    shown = relevant_reports(reports, mentioned, region, alternatives, origin)
    context = [SYSTEM_PROMPT, "", "## 현재 해변 상태 (질문과 관련된 해변만)"] + [describe(r, origin) for r in shown]
    if mentioned:
        context += ["", f"## 사용자가 물어본 해변: {mentioned.spot.name} — 등급은 '{mentioned.grade.label}'이다. "
                        f"이 등급을 그대로 전달할 것."]
    elif region:
        context += ["", f"## 사용자가 물어본 지역: {region} — {region} 해변만 이야기할 것."]
    context += ["", "## 추천 대안"] + ([describe(r) for r in alternatives] or ["- 없음"])
    if alternatives and all(r.grade.status != Status.optimal for r in alternatives):
        context += ["※ 추천 대안 중 '입수 최적' 해변이 없다. 초보자가 지금 안심하고 들어갈 해변은 없다고 먼저 말하고, "
                    "그나마 나은 해변은 '주의 요망' 이유(위 '이유' 항목 그대로)와 함께만 알려줄 것."]
    msgs = [{"role": "system", "content": "\n".join(context)}]
    msgs += [m.model_dump() for m in req.history]
    msgs.append({"role": "user", "content": req.message})
    return msgs


class OllamaError(RuntimeError):
    pass


def ask_ollama(messages: list[dict], client: httpx.Client | None = None) -> str:
    client = client or httpx.Client(timeout=120.0)
    url, model = ollama_url(), ollama_model()
    try:
        r = client.post(f"{url}/api/chat", json={
            "model": model, "messages": messages, "stream": False,
            "options": {"temperature": 0.3},
        })
        r.raise_for_status()
        return r.json()["message"]["content"].strip()
    except httpx.ConnectError as e:
        raise OllamaError(f"Ollama 서버({url})에 연결할 수 없습니다. 'ollama serve' 로 실행해 주세요.") from e
    except httpx.HTTPStatusError as e:
        raise OllamaError(f"Ollama 오류 ({e.response.status_code}): {e.response.text[:200]}"
                          f" — 모델 '{model}' 이 설치되어 있는지 확인해 주세요 (ollama pull {model}).") from e
    except httpx.HTTPError as e:
        raise OllamaError(f"Ollama 호출 실패: {e}") from e
