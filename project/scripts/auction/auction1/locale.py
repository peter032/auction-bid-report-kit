"""입지 스코어링 — 부가남 수공주(배후세대 ÷ 상가필지).

목적은 하나다: **이 상권의 배후세대가 탄탄한가.** 업종 구성·유동인구는 보지 않는다.
(2026-09-10 실측에서 업종 지표는 전부 기각됐다 — 업소 총수는 신도시 공급과잉 지역을
상위로 올렸고, 의료 비중은 9개 지점에서 2.8~5.1%로 변별력이 없었다.
`output/finance/상가투자/A급지_스크리닝_조건정의서.md` §4.8~4.10)

공식:

    실효배후세대(반경 800m, 임대 × 0.5)  ÷  상가필지수(반경 220m)

**두 반경이 다르다는 것이 이 모듈의 핵심이다.** 같은 값을 쓰면 지표가 무너진다 —
호매실 실측에서 필지 반경을 800m로 늘리면 34→63개가 되어 값이 절반이 되고,
세대 반경을 220m로 줄이면 6,272→2,192로 3분의 1이 된다.

반경 근거(§4.11~4.12, 앵커 = 호매실 중앙파크뷰):
  - 800m → 배후세대 6,272. 부가남 실측 6,533의 **96%**.
    임대 구성까지 일치했다 — 국민임대 1,592(능실22 712 + 휴먼시아16 880),
    민간임대 800(힐스테이트호매실). 우연히 맞을 숫자가 아니다.
  - 220m → 상가필지 34개. 부가남 실측 34와 일치.

⚠️ 두 반경 모두 **앵커 1건**에서 나왔다. 앵커가 늘면 재조정 대상이다.

⚠️ K-apt는 의무관리 대상(300세대 이상)만 담는다. 소규모 단지·빌라·오피스텔은 빠진다.
호매실에서 261세대(4%)가 이 차이로 설명된다. 빌라 밀집지는 배후가 과소평가된다.

점수는 판단을 대신하지 않는다. 부가남 본인이 "C급에도 진주가 있다"고 했고, 실제로
과거 낙찰 실적이 상층부였다. 이 값은 **볼 순서**를 정할 뿐이다.
"""

from dataclasses import dataclass
from typing import Any, Iterable

__all__ = [
    "BACKING_RADIUS_M",
    "PARCEL_RADIUS_M",
    "LEASE_DISCOUNT",
    "GRADE_CUTS",
    "MIN_PARCELS",
    "Complex",
    "count_parcels",
    "effective_households",
    "grade",
    "sugongju",
    "summarize",
    "LOCALE_COLUMNS",
]

BACKING_RADIUS_M = 800   # 배후세대 — §4.12 검증
PARCEL_RADIUS_M = 220    # 상가필지 — §4.10 검증
LEASE_DISCOUNT = 0.5     # 부가남 규칙: 임대 = 소비력 1/2

# 부가남 스케일. 출처 = `부가남_수공주판정_필지당세대수192.md` §1.
#   판교 삼평동 1,112 / 김포 구래동·세종 다정동 978~1,000+ (A+ 명시) /
#   용인 수지 헤르메스 700~800 / 수원 금곡동 540 / **우량 기준선 500** /
#   화성 봉담 347 / 호매실 192.1 (C 명시)
#
# A+(900)와 A(500)는 부가남이 명시한 값이다.
# B/C 경계 300은 **추정치** — 부가남이 등급을 명시한 건 A+·기준선 500·호매실 C 뿐이고,
# 봉담 347에는 등급이 없다. 봉담 1층 실측 15.2만원이 금곡(540) 16.6만원에 근접하므로
# 봉담을 B로 두는 선에서 잡았다. 앵커가 늘면 재조정할 것.
GRADE_CUTS = ((900, "A+"), (500, "A"), (300, "B"), (0, "C"))

LOCALE_COLUMNS = [
    "배후세대_원본",
    "배후세대_실효",
    "배후단지수",
    "상가필지",
    "세대당필지",
    "입지등급",
    "기준선대비",
    "표본경고",
]

# 분모가 이보다 적으면 필지 하나 차이로 등급이 뒤집힌다. 값을 버리진 않되 표시한다.
MIN_PARCELS = 10


@dataclass(frozen=True)
class Complex:
    """K-apt 공동주택 단지 1건.

    sale_type 은 `codeSaleNm` 원문(분양/임대/혼합)을 그대로 담는다.
    """

    name: str
    households: int
    sale_type: str
    distance_m: float


def effective_households(
    complexes: Iterable[Complex],
    radius_m: float = BACKING_RADIUS_M,
    discount_lease: bool = True,
) -> float:
    """반경 내 세대수 합. 임대는 소비력 1/2로 깎는다.

    '혼합'은 깎지 않는다. 부가남 문서의 국민임대 1,592 / 민간임대 800 은
    `codeSaleNm == "임대"` 인 단지만 더했을 때 정확히 재현된다. 혼합까지 깎으면 어긋난다.
    """
    total = 0.0
    for c in complexes:
        if c.distance_m > radius_m:
            continue
        rate = LEASE_DISCOUNT if (discount_lease and c.sale_type == "임대") else 1.0
        total += c.households * rate
    return total


def _parcel_key(store: dict[str, Any]) -> tuple[str, str, str, str] | None:
    """법정동 + 대지구분 + 본번 + 부번으로 필지를 식별한다.

    상권 API 응답의 `pnuCd` 는 헤더 columns 에만 있고 **실 데이터는 비어 있다.**
    (2026-09-10 실측: 528건 전부 공란) 그래서 조합해서 쓴다.
    본번의 선행 0 표기가 섞여 있어 정수로 정규화한다 — '0082'와 '82'는 같은 필지다.
    """
    mnno = store.get("lnoMnno")
    if mnno in (None, ""):
        return None
    try:
        main = str(int(str(mnno)))
        sub = str(int(str(store.get("lnoSlno") or 0)))
    except (TypeError, ValueError):
        return None
    return (
        str(store.get("ldongCd") or ""),
        str(store.get("plotSctCd") or ""),
        main,
        sub,
    )


def count_parcels(stores: Iterable[dict[str, Any]]) -> int:
    """상가필지 수 = 반경 내 업소들이 올라앉은 고유 필지 개수.

    반경 필터는 상권 API(`storeListInRadius`)가 이미 적용한 상태로 들어온다.
    본번이 없는 업소는 세지 않는다 — 필지를 특정할 수 없으면 분모에 넣을 수 없다.
    """
    keys = {k for k in (_parcel_key(s) for s in stores) if k is not None}
    return len(keys)


def sugongju(households: float, parcels: int) -> float | None:
    """세대/필지. 필지가 0이면 값을 지어내지 않는다.

    업소가 하나도 안 잡히는 곳은 '무한대로 좋은 상권'이 아니라 판정 불가다.
    """
    if not parcels:
        return None
    return round(households / parcels, 1)


def grade(ratio: float | None) -> str | None:
    """부가남 스케일 대조. 판정 불가는 등급을 지어내지 않는다."""
    if ratio is None:
        return None
    for cut, label in GRADE_CUTS:
        if ratio >= cut:
            return label
    return "C"


def summarize(
    complexes: Iterable[Complex],
    stores: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """물건 1건의 입지 판정 결과."""
    items = list(complexes)
    raw = effective_households(items, discount_lease=False)
    eff = effective_households(items)
    parcels = count_parcels(stores)
    ratio = sugongju(eff, parcels)
    return {
        "배후세대_원본": int(raw),
        "배후세대_실효": int(eff),
        "배후단지수": sum(1 for c in items if c.distance_m <= BACKING_RADIUS_M),
        "상가필지": parcels,
        "세대당필지": ratio,
        "입지등급": grade(ratio),
        "기준선대비": round(ratio / 500 * 100, 1) if ratio is not None else None,
        "표본경고": f"필지{parcels}" if 0 < parcels < MIN_PARCELS else "",
    }
