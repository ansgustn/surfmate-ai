"""초보 서퍼 기준 안전 등급 엔진.

각 규칙이 (상태, 이유)를 내고, 가장 위험한 상태를 최종 등급으로 삼는다.
기준값은 개요서의 '파고 0.5~1m 내외, 모래 지형'을 출발점으로 잡은 초안이며
멘토링·현장 의견을 받아 조정한다.
"""

from .models import BottomType, Conditions, Grade, Spot, Status

# 파고 (m)
WAVE_OPTIMAL = (0.5, 1.0)
WAVE_TOO_SMALL = 0.3
WAVE_AVOID = 1.5
# 파주기 (s) — 짧으면 파도가 거칠고 연속적
PERIOD_CHOPPY = 5.0
# 풍속 (m/s)
WIND_CAUTION = 8.0
WIND_AVOID = 12.0


def grade(spot: Spot, c: Conditions) -> Grade:
    findings: list[tuple[Status, str]] = []

    h = c.wave_height_m
    if h > WAVE_AVOID:
        findings.append((Status.avoid, f"파고 {h:.1f}m — 초보자에게 위험한 높이"))
    elif h > WAVE_OPTIMAL[1]:
        findings.append((Status.caution, f"파고 {h:.1f}m — 초보자에게 다소 높음"))
    elif h < WAVE_TOO_SMALL:
        findings.append((Status.caution, f"파고 {h:.1f}m — 파도가 너무 작아 연습이 어려움"))
    elif h < WAVE_OPTIMAL[0]:
        findings.append((Status.caution, f"파고 {h:.1f}m — 다소 작지만 롱보드로 연습 가능"))
    else:
        findings.append((Status.optimal, f"파고 {h:.1f}m — 초보자 적정"))

    if c.wave_period_s < PERIOD_CHOPPY:
        findings.append((Status.caution, f"파주기 {c.wave_period_s:.0f}s — 파도가 짧고 거침"))

    w = c.wind_speed_ms
    if w >= WIND_AVOID:
        findings.append((Status.avoid, f"풍속 {w:.0f}m/s — 강풍"))
    elif w >= WIND_CAUTION:
        findings.append((Status.caution, f"풍속 {w:.0f}m/s — 바람이 강함"))

    if spot.bottom_type in (BottomType.reef, BottomType.rock):
        findings.append((Status.avoid, "해저 지형이 암반 — 초보자 부상 위험"))
    elif spot.bottom_type == BottomType.mixed:
        findings.append((Status.caution, "모래·암반 혼재 지형 — 입수 위치 주의"))
    elif spot.bottom_type == BottomType.unknown:
        findings.append((Status.caution, "해저 지형·이안류 미확인 — 현지 서핑숍·안전요원에게 확인 필요"))

    worst = max((s for s, _ in findings), key=lambda s: s.rank)
    reasons = [r for s, r in findings if s == worst] + [r for s, r in findings if s != worst]
    return Grade(status=worst, label=worst.label, reasons=reasons)
