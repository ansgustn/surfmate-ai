"""기상청 API허브(apihub.kma.go.kr) 해양기상종합관측 (sea_obs.php).

해양기상부이·파고부이(해수욕장 앞바다)·등표·조위관측소 등의 관측값을
지점 좌표와 함께 한 번에 돌려준다. 쉼표 구분 텍스트, '#' 줄은 설명.

열: TP, TM, STN_ID, STN_KO, LON, LAT, WH, WD, WS, WS_GST, TW, TA, PA, HM
  TP: B 해양기상부이, C 파고부이, D 표류부이, L 등표, N 조위관측소, F 연안방재, G 파랑계, J 기상1호
결측값은 -99 계열. 파주기는 제공하지 않는다.
"""

from dataclasses import dataclass
from datetime import datetime

import httpx

SEA_OBS_URL = "https://apihub.kma.go.kr/api/typ01/url/sea_obs.php"

OBS_TYPE = {"B": "해양기상부이", "C": "파고부이", "D": "표류부이", "L": "등표",
            "N": "조위관측소", "F": "연안방재", "G": "파랑계", "J": "기상1호"}


@dataclass(frozen=True)
class SeaObs:
    tp: str
    tm: datetime
    stn: str
    name: str
    lat: float
    lon: float
    wave_m: float | None  # 유의파고
    wind_dir_deg: float | None
    wind_speed_ms: float | None
    water_temp_c: float | None

    @property
    def label(self) -> str:
        return f"{self.name} {OBS_TYPE.get(self.tp, '관측소')}"


def _val(s: str) -> float | None:
    try:
        v = float(s)
    except ValueError:
        return None
    return None if v <= -99 else v


def parse_sea_obs(text: str) -> list[SeaObs]:
    """지점별 가장 최근 관측 1건씩 돌려준다. (표류부이는 위치가 계속 바뀌므로 제외)"""
    latest: dict[tuple[str, str], SeaObs] = {}
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        p = [x.strip() for x in line.split(",")]
        if len(p) < 11 or p[0] == "D":
            continue
        try:
            o = SeaObs(
                tp=p[0], tm=datetime.strptime(p[1], "%Y%m%d%H%M"), stn=p[2], name=p[3],
                lon=float(p[4]), lat=float(p[5]), wave_m=_val(p[6]),
                wind_dir_deg=_val(p[7]), wind_speed_ms=_val(p[8]), water_temp_c=_val(p[10]),
            )
        except ValueError:
            continue
        key = (o.tp, o.stn)
        if key not in latest or o.tm > latest[key].tm:
            latest[key] = o
    return list(latest.values())


def fetch_sea_obs(client: httpx.Client, auth_key: str, at: datetime) -> list[SeaObs]:
    """at 기준 직전 1시간(-59분~00분) 전 지점 관측."""
    r = client.get(SEA_OBS_URL, params={"tm": at.strftime("%Y%m%d%H%M"), "stn": 0, "authKey": auth_key})
    r.raise_for_status()
    raw = r.content
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("euc-kr", errors="replace")
    if text.lstrip().startswith("{"):  # 오류는 JSON 으로 온다 (인증·활용신청 등)
        raise httpx.HTTPStatusError(f"KMA 오류 응답: {text[:200]}", request=r.request, response=r)
    return parse_sea_obs(text)
