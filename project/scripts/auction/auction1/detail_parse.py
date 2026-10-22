"""상세페이지(ca_view.php) HTML → dict. 순수 함수, 네트워크를 모른다.

목록 파서(`parse.py`)와 같은 계약을 따른다. 옥션원은 클래스명·함수명을 난독화해
내려주므로 **셀렉터에 의존하지 않고** 표 헤더 텍스트와 값 표기 패턴에만 기댄다.

수집은 `detail_fetch.py` 가 한다. 여기서는 HTML 문자열만 받는다.
"""

import html as html_module
import re

from bs4 import BeautifulSoup

__all__ = [
    "parse_detail",
    "flatten_detail",
    "tenant_summary",
    "DETAIL_COLUMNS",
    "TENANT_COLUMNS",
]

# 네이버 부동산 버튼의 onclick 에 좌표가 박혀 있다.
# 이 값 덕분에 지오코딩 API 없이 P3 시세 조회를 바로 걸 수 있다.
_NAVER_MAP = re.compile(
    r"https://new\.land\.naver\.com/offices\?ms=([\d.]+),([\d.]+)[^'\"]*"
)
# `임차인현황 ( 말소기준권리 : 2024.09.26 / 배당요구종기일 : 2025.07.07 )`
_BASIS = re.compile(r"말소기준권리\s*:\s*([\d.]+)")
_DEADLINE = re.compile(r"배당요구종기일\s*:\s*([\d.]+)")

# 임차인 표. 헤더 텍스트로 앵커링한다 — 클래스명은 배포마다 바뀐다.
_TENANT_HEADER = ["임차인", "점유부분", "전입/확정/배당", "보증금/차임"]
_TENANT_COLUMNS = 7
_NO_TENANT = "조사된 임차내역 없음"

_DEPOSIT = re.compile(r"보\s?([\d,]+)\s?원")
_RENT = re.compile(r"월\s?([\d,]+)\s?원")
_CONVERTED = re.compile(r"환산\s?([\d,]+)\s?만원")  # 만원 단위로 표기된다
_SITE_DEPOSIT_SUM = re.compile(r"임차보증금합계\s*:\s*([\d,]+)\s*원")
_SITE_RENT_SUM = re.compile(r"월세합계\s*:\s*([\d,]+)\s*원")
_REGISTERED = re.compile(r"사업등록\s*:\s*(\S+)")
_CONFIRMED = re.compile(r"확정일자\s*:\s*(\S+)")
_CLAIMED = re.compile(r"배당요구\s*:\s*(\S+)")
# 대항력 있는 임차인의 보증금을 낙찰자가 떠안는다는 신호.
_ASSUMPTION = "전액매수인인수"

# 등기부 권리 표. 사이트가 소멸/인수를 이미 판정해 준다.
_RIGHTS_HEADER = ["No", "접수", "권리종류", "권리자", "채권금액"]
_RIGHTS_COLUMNS = 7
_BASIS_MARK = "말소기준등기"
_AMOUNT = re.compile(r"([\d,]{4,})\s?원")

# 특수물건은 **전문가멘트의 선언 문장에서만** 읽는다.
# 전체 텍스트 키워드 매칭을 하면 안내문구("유치권/법정지상권 버튼을 눌러 참고하시고")가
# 그대로 오탐이 된다. 실측 픽스처에 이 함정이 들어 있다.
_EXPERT_PREFIX = "전문가멘트"
_DECLARED = re.compile(r"본 건은\s*(\S+?)신고가 된 경매물건입니다")

# `▶본건매각 2024.07.30 / 매각가 240,000,000원 / 1명 입찰 / 대금미납`
# 앞사람이 잔금을 못 냈다 = 대출이 안 나왔을 가능성.
_RESALE = re.compile(r"본건매각\s*[\d.]+\s*/\s*매각가\s*([\d,]+)\s*원[^*▶]{0,160}?대금미납")


def _text(soup: BeautifulSoup) -> str:
    """NBSP 를 보통 공백으로 눕힌 전체 텍스트.

    상세페이지 값에는 `\xa0` 가 섞여 있어 정규식이 조용히 빗나간다.
    """
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True).replace("\xa0", " "))


def _cells(row) -> list[str]:
    return [
        re.sub(r"\s+", " ", cell.get_text(" ", strip=True).replace("\xa0", " "))
        for cell in row.find_all(["th", "td"])
    ]


def _won(pattern: re.Pattern, text: str, *, unit: int = 1) -> int | None:
    matched = pattern.search(text)
    if not matched:
        return None
    return int(matched.group(1).replace(",", "")) * unit


def _field(pattern: re.Pattern, text: str) -> str | None:
    matched = pattern.search(text)
    return matched.group(1) if matched else None


def _find_tenant_table(soup: BeautifulSoup):
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header = _cells(rows[0])
        if header[: len(_TENANT_HEADER)] == _TENANT_HEADER:
            return table
    return None


def _parse_tenants(soup: BeautifulSoup) -> tuple[list[dict], int | None, int | None]:
    """임차인 표 → (임차인 목록, 사이트 보증금합계, 사이트 월세합계)."""
    table = _find_tenant_table(soup)
    if table is None:
        return [], None, None

    tenants: list[dict] = []
    deposit_sum = rent_sum = None

    for row in table.find_all("tr")[1:]:
        cells = _cells(row)
        # 표 끝의 `임차인분석` 행은 셀 수가 다르다. 사이트가 계산한 합계가 여기 있다.
        if len(cells) != _TENANT_COLUMNS:
            joined = " ".join(cells)
            deposit_sum = deposit_sum or _won(_SITE_DEPOSIT_SUM, joined)
            rent_sum = rent_sum or _won(_SITE_RENT_SUM, joined)
            continue

        name, occupancy, dates, money, standing, distribution = cells[:6]
        # 대항력 칸이 빈 물건이 실제로 있다. '없음' 으로 읽으면 인수 리스크를 놓친다.
        standing = standing.strip() or None
        tenants.append(
            {
                "이름": name,
                "점유부분": occupancy,
                "사업등록": _field(_REGISTERED, dates),
                "확정일자": _field(_CONFIRMED, dates),
                "배당요구": _field(_CLAIMED, dates),
                "보증금": _won(_DEPOSIT, money),
                "월세": _won(_RENT, money),
                "환산보증금": _won(_CONVERTED, money, unit=10_000),
                "대항력": standing,
                "배당예상": distribution or None,
                "인수": standing == "있음" and _ASSUMPTION in distribution,
            }
        )

    return tenants, deposit_sum, rent_sum


def _parse_rights(soup: BeautifulSoup) -> list[dict]:
    """등기부 권리 표 → 행 목록. 소멸/인수 판정은 사이트 값을 그대로 옮긴다."""
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows or _cells(rows[0])[: len(_RIGHTS_HEADER)] != _RIGHTS_HEADER:
            continue

        rights = []
        for row in rows[1:]:
            cells = _cells(row)
            if len(cells) != _RIGHTS_COLUMNS:
                continue
            order, received, kind, holder, amount, note, status = cells
            rights.append(
                {
                    "순번": order,
                    "접수일": received or None,
                    "권리종류": kind,
                    "권리자": holder,
                    "채권금액": _won(_AMOUNT, amount),
                    "채권금액원문": amount or None,
                    "비고": note or None,
                    "소멸여부": status.strip() or None,
                }
            )
        return rights
    return []


def _parse_expert_comments(soup: BeautifulSoup) -> list[str]:
    comments = []
    for table in soup.find_all("table"):
        text = re.sub(r"\s+", " ", table.get_text(" ", strip=True).replace("\xa0", " "))
        if text.startswith(_EXPERT_PREFIX):
            comments.append(text[len(_EXPERT_PREFIX) :].strip())
    return comments


def parse_detail(raw_html: str) -> dict:
    soup = BeautifulSoup(raw_html, "html.parser")
    text = _text(soup)

    tenants, site_deposit_sum, site_rent_sum = _parse_tenants(soup)
    rights = _parse_rights(soup)
    comments = _parse_expert_comments(soup)
    resale = _RESALE.search(text)

    result: dict = {
        "위도": None,
        "경도": None,
        "네이버지도URL": None,
        "말소기준일": None,
        "배당요구종기일": None,
        "임차인": tenants,
        "임차조사없음": not tenants and _NO_TENANT in text,
        "인수보증금": sum(t["보증금"] or 0 for t in tenants if t["인수"]),
        "사이트보증금합계": site_deposit_sum,
        "사이트월세합계": site_rent_sum,
        "등기권리": rights,
        "말소기준권리종류": next(
            (r["권리종류"] for r in rights if r["비고"] and _BASIS_MARK in r["비고"]),
            None,
        ),
        "인수권리": [r for r in rights if r["소멸여부"] == "인수"],
        "전문가멘트": comments,
        "특수물건": [
            matched.group(1)
            for comment in comments
            if (matched := _DECLARED.search(comment))
        ],
        "재매각": resale is not None,
        "직전매각가": int(resale.group(1).replace(",", "")) if resale else None,
    }

    # onclick 속성 안의 URL 은 `&amp;` 로 이스케이프되어 있다.
    matched = _NAVER_MAP.search(html_module.unescape(raw_html))
    if matched:
        result["위도"] = float(matched.group(1))
        result["경도"] = float(matched.group(2))
        result["네이버지도URL"] = matched.group(0)

    basis = _BASIS.search(text)
    if basis:
        result["말소기준일"] = basis.group(1)
    deadline = _DEADLINE.search(text)
    if deadline:
        result["배당요구종기일"] = deadline.group(1)

    return result


# 엑셀 한 행에 붙일 스칼라 컬럼. `auction1_deepen` 이 이 순서로 쓴다.
DETAIL_COLUMNS = [
    "보증금",
    "월세",
    "환산보증금",
    "임차인수",
    "임차범위",
    "제외임차인수",
    "대항력",
    "인수보증금",
    "임차조사없음",
    "말소기준일",
    "말소기준권리종류",
    "배당요구종기일",
    "인수권리수",
    "특수물건",
    "재매각",
    "직전매각가",
    "전문가멘트수",
    "사이트보증금합계",
    "사이트월세합계",
    "위도",
    "경도",
    "네이버지도URL",
]


# `106,107,111,112호` `107호` `비-121호` 에서 호수 번호를 뽑는다.
_UNIT_LIST = re.compile(r"((?:\d+\s*,\s*)*\d+)\s*호")
# 점유부분에 호수가 없어도 이 물건 전체를 쓴다는 표기.
_WHOLE = ("전부", "전체")


def _unit_numbers(text: str) -> set[str]:
    numbers: set[str] = set()
    for matched in _UNIT_LIST.finditer(text or ""):
        numbers.update(part.strip() for part in matched.group(1).split(","))
    return numbers


def _belongs_to_unit(occupancy: str, target: set[str]) -> bool:
    """이 임차인의 보증금·월세를 이 물건 하나에 귀속시켜도 되는가.

    실측 함정: `점포 106,107,111,112호 168㎡` 처럼 여러 호실을 통으로 임차한
    임차인이 있다. 그 금액을 107호 하나에 귀속시키면 수익률이 8배로 부푼다.
    """
    units = _unit_numbers(occupancy)
    if not units:
        return any(word in occupancy for word in _WHOLE)
    return units == target


def _sum_or_none(values) -> int | None:
    """전부 비어 있으면 0 이 아니라 None.

    0 으로 두면 '월세 0원짜리 물건'이 되어 수익률 계산이 조용히 오염된다.
    """
    present = [v for v in values if v is not None]
    return sum(present) if present else None


def flatten_detail(parsed: dict, unit: str | None = None) -> dict:
    """중첩 파싱 결과 → 엑셀 한 행에 붙일 스칼라 dict.

    `unit` 은 이 물건의 호수(`107호`). 임차인 금액을 이 물건에 귀속시킬지
    판정하는 데 쓴다. 넘기지 않으면 판정할 수 없으므로 전부 더하고 `불명` 으로 표시한다.

    ⚠️ 사이트가 준 `임차보증금합계` 는 **사건 전체** 합계다. 물번이 여러 개인 사건에서
    그 값을 물건 하나의 금액으로 쓰면 수익률이 몇 배로 부풀려진다(실측 확인).
    검산용으로만 남기고 금액은 임차인 행에서 직접 더한다.
    """
    all_tenants = parsed["임차인"]
    target = _unit_numbers(unit) if unit else set()

    if not all_tenants:
        tenants, scope = [], "해당없음"
    elif not target:
        tenants, scope = all_tenants, "불명"
    else:
        tenants = [t for t in all_tenants if _belongs_to_unit(t["점유부분"], target)]
        scope = "물건확정" if tenants else "해당없음"

    standings = [t["대항력"] for t in tenants]

    if "있음" in standings:
        standing = "있음"          # 한 명이라도 있으면 물건 단위로는 있음으로 본다
    elif tenants and all(s == "없음" for s in standings):
        standing = "없음"
    else:
        standing = None            # 임차인이 없거나, 미상이 섞여 있다

    return {
        "보증금": _sum_or_none(t["보증금"] for t in tenants),
        "월세": _sum_or_none(t["월세"] for t in tenants),
        "환산보증금": _sum_or_none(t["환산보증금"] for t in tenants),
        "임차인수": len(tenants),
        "임차범위": scope,
        "제외임차인수": len(all_tenants) - len(tenants),
        "사이트보증금합계": parsed["사이트보증금합계"],
        "사이트월세합계": parsed["사이트월세합계"],
        "대항력": standing,
        "인수보증금": sum(t["보증금"] or 0 for t in tenants if t["인수"]),
        "임차조사없음": parsed["임차조사없음"],
        "말소기준일": parsed["말소기준일"],
        "말소기준권리종류": parsed["말소기준권리종류"],
        "배당요구종기일": parsed["배당요구종기일"],
        "인수권리수": len(parsed["인수권리"]),
        "특수물건": " / ".join(parsed["특수물건"]),
        "재매각": parsed["재매각"],
        "직전매각가": parsed["직전매각가"],
        "전문가멘트수": len(parsed["전문가멘트"]),
        "위도": parsed["위도"],
        "경도": parsed["경도"],
        "네이버지도URL": parsed["네이버지도URL"],
    }


# 랭킹 표에 붙이는 임차 요약 컬럼.
TENANT_COLUMNS = ["임차인유무", "보증금합계", "월세합계"]


def tenant_summary(flat: dict | None) -> dict:
    """`flatten_detail` 결과 → 랭킹 표용 임차 3컬럼.

    `flat` 이 None 이면 상세를 안 본 물건이다. '없음' 이 아니라 '미조회' 로 남긴다 —
    둘을 섞으면 안 본 물건이 공실로 읽힌다.
    """
    if flat is None:
        return {"임차인유무": "미조회", "보증금합계": None, "월세합계": None}

    if flat["임차인수"]:
        # 호수를 몰라 전부 더한 금액은 사건 전체 합계일 수 있다.
        label = "있음(범위불명)" if flat["임차범위"] == "불명" else "있음"
        return {"임차인유무": label, "보증금합계": flat["보증금"], "월세합계": flat["월세"]}

    if flat["제외임차인수"]:
        # 통임차·타호실 임차인뿐이다. 이 물건 몫을 알 수 없어 금액은 비운다.
        return {"임차인유무": "있음(귀속불가)", "보증금합계": None, "월세합계": None}

    label = "없음" if flat["임차조사없음"] else "미상"
    return {"임차인유무": label, "보증금합계": None, "월세합계": None}
