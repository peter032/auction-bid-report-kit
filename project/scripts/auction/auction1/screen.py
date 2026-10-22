"""단타(단기 전매) 적합도 스코어링.

목록 데이터에는 인근 실거래 시세가 없다. 그래서 '싸게 샀는가'를 직접 잴 수 없다.
대신 **같은 법정동·같은 층대 물건들의 '감정' 평당가 중앙값**을 동네 시세의 대용물로 두고,
거기에 이 물건의 **'최저' 평당가**를 견줘 할인율을 낸다.

비교군을 최저가가 아니라 감정가로 잡는 이유: 최저가에는 유찰 진행도가 섞여 있다.
같은 단지에서 5회 유찰된 물건과 1회 유찰된 물건을 최저가끼리 비교하면
'저평가'가 아니라 '더 많이 유찰됨'을 측정하게 되고, 저감률 점수와 이중계산된다.
(실측: 거여동 1층 10건이 단지 4개에서 나왔고 평당가 차이가 사실상 유찰 횟수 차이였다.)

동 표본이 3건 미만이면 구 단위로 물러서되 그 사실을 컬럼에 남기고,
구로도 모자라면 값을 지어내지 않고 비워 둔다.

⚠️ 한계: 감정가도 시세가 아니다. 신축 단지내 상가는 분양가 기반으로 감정이 높게 잡힌다.
비교군이 소수 단지에 쏠리면 `단지편중` 으로 표시한다. 확정하려면 실거래 대조가 필요하다.

점수는 판단을 대신하지 않는다. 300건을 눈으로 볼 수 없으니 **볼 순서를 정해주는 것**이
전부다. 최종 판단에 필요한 세 가지(인근 실거래 마진 · 명도 난이도 · 인수 권리)는
목록에 없고, 상세 페이지와 현장에서만 확인된다.
"""

import re
from dataclasses import dataclass
from statistics import median
from typing import Any

__all__ = ["score_rows", "SCORE_COLUMNS", "WEIGHTS"]

# 가중치. 근거는 부가남 KB(분석체크리스트 10·11·12, persona 원칙 '100원 넣고 100원 먹기').
WEIGHTS = {
    "저평가": 45,  # 동네 감정 시세 대비 최저가 할인. 싸게 사는 것이 단타의 거의 전부
    "저감률": 15,  # 경락대출 LTV 확보용(저감 24~34% → 90%). 저평가와 일부 겹쳐 낮게 둔다
    "환금성": 20,  # 층. 되팔 수 있어야 단타다
    "경쟁도": 12,  # 조회수 = 입찰 경쟁 프록시. 경쟁 붙으면 마진이 증발
    "규모": 8,  # 매수자층 두꺼운 크기
}
RISK_PENALTY_MAX = 25  # 명도·권리 리스크 감점 상한

# 명도가 늦어지면 이자로 마진이 녹는다. 단타에서 가장 치명적인 축.
_HEAVY_RISK = {
    "대항력": 12,
    "임차권등기": 8,
    "선순위전세권": 10,
    "유치권": 12,
    "토지및건물 지분 매각": 15,
    "지분매각": 15,
    "법정지상권": 10,
    "재매각": 6,  # 앞사람이 잔금을 못 냈다 = 대출이 안 나왔을 가능성
}
# 가격에는 불리하나 해소 가능한 축. 저가 매입 기회이기도 하다.
_MEDIUM_RISK = {
    "대지권미등기": 5,
    "위반건축물": 5,
    "토지별도등기인수": 5,
    "임금채권": 3,
    "맹지": 6,
}

# 환금 불능 의심 — 싸 보이는 이유가 '저평가'가 아니라 '아무도 안 사서'인 경우.
# 동대문·중구 의류상가의 초소형 고층 호실이 전형이다. 유찰 10회, 평당가 붕괴,
# 그래도 안 팔린다. 저감률·저평가율만 보면 최상위로 튀어오르므로 반드시 눌러야 한다.
_DEAD_ASSET_RULES = [
    ("유찰5회이상", 12),  # 시장이 다섯 번 거절한 물건
    ("초소형5평미만", 12),  # 매수자층이 사실상 없음
    ("평당가붕괴", 12),  # 동네 감정 평당가의 10% 미만 = 저평가가 아니라 하자 신호
]
DEAD_ASSET_PENALTY_MAX = 30

SCORE_COLUMNS = [
    "단타점수",
    "저평가율",
    "동네감정평당가",
    "비교단위",
    "표본수",
    "비교단지수",
    "비교신뢰도",
    "저감률",
    "리스크감점",
    "리스크사유",
    "환금경고",
]


@dataclass(frozen=True)
class _Peer:
    """비교군 — 같은 지역·같은 층대 물건들의 '감정' 평당가 중앙값."""

    median_price: float | None
    sample: int
    level: str  # '동' | '구' | '없음'
    buildings: int = 0  # 비교군을 구성한 서로 다른 건물 수

    @property
    def concentrated(self) -> bool:
        """소수 단지가 비교군을 지배하면 중앙값이 그 단지의 분양가를 반영할 뿐이다."""
        return self.median_price is not None and self.buildings < 3


MIN_SAMPLE = 3
MIN_BUILDINGS = 3
_ADMIN = re.compile(r"[시군구]$")  # 안산시 · 가평군 · 단원구 (일산동구도 '구'로 끝난다)
_LEGAL = re.compile(r"[동가읍면]$")  # 화곡동 · 종로2가 · 청평읍 · 청평면
_BUILDING = re.compile(r",\s*([^,]+?)\s+(?:제?[지비B]?하?\d*층|\d+동)")


def _appraisal_per_pyeong(row: dict[str, Any]) -> float | None:
    """감정가 기준 평당가(만원). 유찰 진행도가 섞이지 않은 가격 지표."""
    appraisal, pyeong = row.get("감정가"), row.get("건물면적평")
    if not appraisal or not pyeong:
        return None
    return float(appraisal) / float(pyeong) / 10_000


def _building(row: dict[str, Any]) -> str:
    """소재지에서 건물명. 비교군이 몇 개 단지로 이뤄졌는지 세는 데 쓴다."""
    matched = _BUILDING.search(str(row.get("소재지") or ""))
    return matched.group(1).strip() if matched else str(row.get("소재지") or "")[:30]


def _floor_band(row: dict[str, Any]) -> str:
    """층을 비교 가능한 묶음으로. 1층은 가격대가 완전히 달라 따로 둔다."""
    number = row.get("층번호")
    if number is None:
        label = str(row.get("층") or "")
        if not label:
            return "미상"
        number = None
    if number == 1:
        return "1층"
    if number == 2:
        return "2층"
    if number is not None and number >= 3:
        return "3층이상"
    return "미상"


def _dong_key(row: dict[str, Any]) -> tuple[str, str]:
    """(법정동, 층대). 같은 구 안에서도 동에 따라 평당가가 10배 벌어진다.

    실측: 강서구 1층 — 화곡동 평당 424~1,304 vs 마곡동 1,948~9,334.
    구 단위로 묶으면 화곡동 물건이 마곡동과 비교돼 저평가로 잘못 뜬다.

    주소 형식은 지역마다 다르다 — 서울 '강서구 화곡동'(2단), 경기 '평택시 죽백동'(2단),
    '안산시 단원구 선부동'(3단), '가평군 청평면'(군·읍면). 시도 다음부터
    시/군/구 토큰을 삼키다가 동/가/읍/면 토큰에서 멈추는 방식으로 전부 수용한다.
    실측 사고: 구 전용 정규식이 경기 1,433건 전체를 '?' 비교군 하나로 묶었다.
    """
    tokens = str(row.get("소재지") or "").split()
    parts: list[str] = []
    for token in tokens[1:5]:  # 상한 4토큰: 지번·건물명의 '○○상가'가 동으로 오인되지 않게
        if _LEGAL.search(token):
            parts.append(token)
            return (" ".join(parts), _floor_band(row))
        if _ADMIN.search(token):
            parts.append(token)
            continue
        break
    return ("?", _floor_band(row))


def _gu_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("시군구") or "?"), _floor_band(row))


def _medians(rows, key_fn) -> dict[tuple[str, str], tuple[float, int, int]]:
    """버킷별 (감정평당가 중앙값, 표본수, 서로 다른 건물 수)."""
    prices: dict[tuple[str, str], list[float]] = {}
    buildings: dict[tuple[str, str], set[str]] = {}
    for row in rows:
        price = _appraisal_per_pyeong(row)
        if price:
            key = key_fn(row)
            prices.setdefault(key, []).append(price)
            buildings.setdefault(key, set()).add(_building(row))
    return {
        key: (median(values), len(values), len(buildings[key]))
        for key, values in prices.items()
    }


class _PeerIndex:
    """동 우선 → 구 폴백. 어느 단위로 비교했는지 함께 돌려준다.

    동 단위가 정확하지만 표본이 얇다(서울 330건 기준 53%만 3건 이상).
    표본이 모자라면 구로 물러서되, 그 사실을 숨기지 않는다.
    """

    def __init__(self, rows: list[dict[str, Any]]):
        self._dong = _medians(rows, _dong_key)
        self._gu = _medians(rows, _gu_key)

    def lookup(self, row: dict[str, Any]) -> _Peer:
        for level, table, key in (
            ("동", self._dong, _dong_key(row)),
            ("구", self._gu, _gu_key(row)),
        ):
            entry = table.get(key)
            if entry and entry[1] >= MIN_SAMPLE:
                return _Peer(
                    median_price=entry[0], sample=entry[1], level=level, buildings=entry[2]
                )

        fallback = self._dong.get(_dong_key(row))
        return _Peer(median_price=None, sample=fallback[1] if fallback else 0, level="없음")


def _discount(row: dict[str, Any], peer: _Peer) -> float | None:
    """동네 감정 평당가 중앙값 대비, 이 물건 '최저가' 평당가의 할인율(%).

    양수면 동네 감정 시세보다 싸게 살 수 있다는 뜻이다.
    """
    price = row.get("평당가만원")
    if not price or not peer.median_price:
        return None
    return round((1 - float(price) / peer.median_price) * 100, 1)


def _risk(row: dict[str, Any]) -> tuple[int, str]:
    """특이사항 → (감점, 사유). 배제가 아니라 감점이다."""
    notes = str(row.get("특이사항") or "")
    penalty, reasons = 0, []
    for keyword, points in {**_HEAVY_RISK, **_MEDIUM_RISK}.items():
        if keyword in notes:
            penalty += points
            reasons.append(keyword)
    return min(penalty, RISK_PENALTY_MAX), " / ".join(reasons)


def _dead_asset(row: dict[str, Any], discount: float | None) -> tuple[int, str]:
    """'싸다'가 아니라 '안 팔린다'의 신호 → (감점, 사유).

    단타는 되파는 게 전제라, 환금성이 죽은 물건은 아무리 싸도 후보가 아니다.
    """
    hits = []
    fails = row.get("유찰횟수")
    if fails is not None and fails >= 5:
        hits.append("유찰5회이상")

    pyeong = row.get("건물면적평")
    if pyeong is not None and float(pyeong) < 5:
        hits.append("초소형5평미만")

    if discount is not None and discount >= 90:
        hits.append("평당가붕괴")

    penalty = sum(points for name, points in _DEAD_ASSET_RULES if name in hits)
    return min(penalty, DEAD_ASSET_PENALTY_MAX), " / ".join(hits)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _liquidity(row: dict[str, Any]) -> float:
    """환금성 0~1. 1층이 압도적이고 위로 갈수록 매수자가 준다."""
    band = _floor_band(row)
    return {"1층": 1.0, "2층": 0.55, "3층이상": 0.3, "미상": 0.5}[band]


def _size_fit(row: dict[str, Any]) -> float:
    """규모 적합도 0~1. 10~40평이 매수자층이 가장 두껍다."""
    pyeong = row.get("건물면적평")
    if not pyeong:
        return 0.5
    pyeong = float(pyeong)
    if 10 <= pyeong <= 40:
        return 1.0
    if pyeong < 10:
        return _clamp(pyeong / 10)
    return _clamp(1 - (pyeong - 40) / 160)


def _competition(row: dict[str, Any], max_views: int) -> float:
    """경쟁도 0~1. 조회수가 낮을수록 높은 점수."""
    views = row.get("조회수")
    if not views or max_views <= 0:
        return 0.5
    return _clamp(1 - float(views) / max_views)


def score_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """각 행에 단타 점수와 근거 컬럼을 붙여 반환 (원본은 건드리지 않는다)."""
    peers = _PeerIndex(rows)
    view_values = [float(r["조회수"]) for r in rows if r.get("조회수")]
    max_views = max(view_values) if view_values else 0.0

    scored = []
    for row in rows:
        peer = peers.lookup(row)
        discount = _discount(row, peer)

        # 저평가: -10%(동네 감정가보다 비쌈) ~ +70%(크게 쌈) 구간을 0~1 로 편다.
        # 비교군이 없으면 중립(0.5)으로 두고 '표본부족'을 표기해 사람이 알게 한다.
        undervalue = 0.5 if discount is None else _clamp((discount + 10) / 80)

        rate = row.get("최저가율")
        cut = (100 - float(rate)) if rate else 0.0
        # 저감률: 0~60% 를 0~1 로. 그 이상 떨어진 물건은 대개 물건 자체에 이유가 있다.
        cut_score = _clamp(cut / 60)

        raw = (
            WEIGHTS["저평가"] * undervalue
            + WEIGHTS["저감률"] * cut_score
            + WEIGHTS["환금성"] * _liquidity(row)
            + WEIGHTS["경쟁도"] * _competition(row, max_views)
            + WEIGHTS["규모"] * _size_fit(row)
        )
        penalty, reasons = _risk(row)
        dead_penalty, dead_reasons = _dead_asset(row, discount)

        enriched = dict(row)
        enriched.update(
            {
                "단타점수": round(max(0.0, raw - penalty - dead_penalty), 1),
                "환금경고": dead_reasons,
                "저평가율": discount,
                "동네감정평당가": round(peer.median_price) if peer.median_price else None,
                "비교단위": peer.level,
                "표본수": peer.sample,
                "비교단지수": peer.buildings,
                "비교신뢰도": "단지편중" if peer.concentrated else "",
                "저감률": round(cut),
                "리스크감점": penalty or None,
                "리스크사유": reasons,
            }
        )
        scored.append(enriched)

    scored.sort(key=lambda r: r["단타점수"], reverse=True)
    return scored
