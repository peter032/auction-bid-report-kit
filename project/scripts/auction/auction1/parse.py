"""옥션원 검색결과 HTML → 구조화된 행 목록.

주의: 옥션원은 CSS 클래스명과 JS 함수명을 난독화해서 내려준다
(`wxwZlLbE`, `UTRYaLSz`, `BmEsrYye` 등 — 배포마다 바뀔 수 있다).
따라서 파서는 난독화된 이름에 절대 의존하지 않는다. 기대는 다음 세 가지뿐이다.

  1. 각 결과 행은 `<input name="ck_pid">` (product_id) 를 품은 `<tr>` 이다
  2. 소재지는 `div.addr`, 물건종류는 `.auct_class_name` (사람이 붙인 의미 있는 클래스)
  3. 나머지 필드는 셀 텍스트의 패턴으로 찾는다 (금액·날짜·유찰 표기 등)
"""

import re
from typing import Any

from bs4 import BeautifulSoup, Tag

from .floors import parse_floor

__all__ = ["parse_list_page", "parse_total_count", "COLUMNS"]

BASE_URL = "https://www.auction1.co.kr"

# 출력 컬럼 순서. report.py 가 이 순서를 그대로 쓴다.
COLUMNS = [
    "사건번호",
    "물건번호",
    "물건종류",
    "시군구",
    "소재지",
    "층",
    "층번호",
    "호수",
    "건물면적㎡",
    "건물면적평",
    "대지권㎡",
    "대지권평",
    "감정가",
    "최저가",
    "최저가율",
    "평당가만원",
    "유찰횟수",
    "매각기일",
    "매각시각",
    "특이사항",
    "규제",
    "조회수",
    "상세링크",
    "product_id",
]

_TOTAL = re.compile(r"물건수\s*:\s*([\d,]+)\s*건")
_CASE_NO = re.compile(r"(\d{2}-\d+)")
_ITEM_NO = re.compile(r"\((\d+)\)")
_MONEY = re.compile(r"\d{1,3}(?:,\d{3})+|\d+")
_PER_PYEONG = re.compile(r"평당\s*([\d,]+)\s*만원")
_FAIL = re.compile(r"유찰\s*(\d+)\s*회")
_RATE = re.compile(r"\((\d+)%\)")
_DATE = re.compile(r"(\d{4})\.(\d{2})\.(\d{2})")
_TIME = re.compile(r"\((\d{2}:\d{2})\)")
_AREA_LAND = re.compile(r"대지권\s*([\d.]+)\s*㎡\s*\(\s*([\d.]+)\s*평\s*\)")
_AREA_BLDG = re.compile(r"건물\s*([\d.]+)\s*㎡\s*\(\s*([\d.]+)\s*평\s*\)")
_BRACKET = re.compile(r"\[([^\[\]]*)\]")
_SGG = re.compile(r"^\S+\s+(\S*[구군시])\s")

# 규제지역 표기. 물건 자체의 특이사항이 아니라 지역 속성이라 따로 담는다.
_ZONE_WORDS = {
    "투기지역",
    "투기과열지구",
    "조정대상지역",
    "토지거래허가구역",
    "토지거래계약허가구역",
}


def parse_total_count(html: str) -> int | None:
    """'(물건수 : 422건)' → 422. 표기를 못 찾으면 None."""
    matched = _TOTAL.search(html)
    return int(matched.group(1).replace(",", "")) if matched else None


def parse_list_page(html: str) -> list[dict[str, Any]]:
    """검색결과 HTML → 행 dict 목록. 결과가 없으면 빈 리스트."""
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for checkbox in soup.find_all("input", {"name": "ck_pid"}):
        tr = checkbox.find_parent("tr")
        if tr is None:
            continue
        rows.append(_parse_row(tr, checkbox.get("value", "")))
    return rows


def _parse_row(tr: Tag, product_id: str) -> dict[str, Any]:
    cells = [_text(td) for td in tr.find_all("td")]

    address = _select_text(tr, "div.addr")
    floor = parse_floor(address)

    case_cell = _cell_of(tr, ".auct_class_name") or ""
    addr_cell = _cell_of(tr, "div.addr") or ""
    price_cell = _first_cell(cells, lambda t: "평당" in t)
    fail_cell = _first_cell(cells, lambda t: "유찰" in t or "신건" in t)
    date_cell = _first_cell(cells, _DATE.search)
    views_cell = _views_cell(cells, exclude={price_cell, fail_cell, date_cell})

    appraisal, min_price = _two_prices(price_cell)
    land_m2, land_py = _area(_AREA_LAND, addr_cell)
    bldg_m2, bldg_py = _area(_AREA_BLDG, addr_cell)
    notes, zones = _tags(addr_cell)

    return {
        "사건번호": _group(_CASE_NO, case_cell),
        "물건번호": _group(_ITEM_NO, case_cell),
        "물건종류": _select_text(tr, ".auct_class_name"),
        "시군구": _group(_SGG, address),
        "소재지": address,
        "층": floor.floor_label,
        "층번호": floor.floor_number,
        "호수": floor.unit,
        "지하여부": floor.is_basement,
        "지하판정근거": floor.reason,
        "건물면적㎡": bldg_m2,
        "건물면적평": bldg_py,
        "대지권㎡": land_m2,
        "대지권평": land_py,
        "감정가": appraisal,
        "최저가": min_price,
        "최저가율": _int(_group(_RATE, fail_cell)),
        "평당가만원": _int(_group(_PER_PYEONG, price_cell)),
        "유찰횟수": _fail_count(fail_cell),
        "매각기일": _date(date_cell),
        "매각시각": _group(_TIME, date_cell),
        "특이사항": notes,
        "규제": zones,
        "조회수": _int(views_cell),
        "상세링크": f"{BASE_URL}/auction/ca_view.php?product_id={product_id}",
        "product_id": product_id,
    }


# --- 셀 선택 ------------------------------------------------------------------


def _text(node: Tag) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True))


def _select_text(tr: Tag, selector: str) -> str:
    found = tr.select_one(selector)
    return _text(found) if found else ""


def _cell_of(tr: Tag, selector: str) -> str:
    """주어진 셀렉터를 품은 td 의 텍스트."""
    found = tr.select_one(selector)
    if found is None:
        return ""
    td = found.find_parent("td")
    return _text(td) if td else _text(found)


def _first_cell(cells: list[str], predicate) -> str:
    for cell in cells:
        if cell and predicate(cell):
            return cell
    return ""


def _views_cell(cells: list[str], exclude: set[str]) -> str:
    """조회수 = 숫자로 시작하는 마지막 셀의 선두 숫자 (금액·유찰·기일 셀 제외).

    셀 텍스트는 '641 (8일전)' 처럼 뒤에 부가 표기가 붙으므로 선두 숫자만 취한다.
    """
    for cell in reversed(cells):
        if not cell or cell in exclude:
            continue
        matched = re.match(r"^([\d,]+)\b", cell)
        if matched:
            return matched.group(1)
    return ""


# --- 값 변환 ------------------------------------------------------------------


def _group(pattern: re.Pattern, text: str, index: int = 1) -> str:
    matched = pattern.search(text or "")
    return matched.group(index) if matched else ""


def _int(text: str) -> int | None:
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def _two_prices(cell: str) -> tuple[int | None, int | None]:
    """'216,000,000 70,779,000 평당 477만원' → (감정가, 최저가).

    '평당 N만원' 의 N 이 섞이지 않도록 평당 표기를 먼저 제거한다.
    """
    stripped = _PER_PYEONG.sub("", cell or "")
    amounts = [int(m.group().replace(",", "")) for m in _MONEY.finditer(stripped)]
    appraisal = amounts[0] if len(amounts) > 0 else None
    min_price = amounts[1] if len(amounts) > 1 else None
    return appraisal, min_price


def _area(pattern: re.Pattern, cell: str) -> tuple[float | None, float | None]:
    matched = pattern.search(cell or "")
    if not matched:
        return None, None
    return float(matched.group(1)), float(matched.group(2))


def _fail_count(cell: str) -> int | None:
    """'유찰 5회' → 5, '신건' → 0."""
    matched = _FAIL.search(cell or "")
    if matched:
        return int(matched.group(1))
    if "신건" in (cell or ""):
        return 0
    return None


def _date(cell: str) -> str:
    matched = _DATE.search(cell or "")
    return "-".join(matched.groups()) if matched else ""


def _tags(addr_cell: str) -> tuple[str, str]:
    """소재지 셀의 대괄호 표기 → (특이사항, 규제).

    대괄호 안에는 면적('[건물 49.06㎡(14.84평)]'), 물건 특이사항('[재매각 / 위반건축물]'),
    규제지역('[투기지역/투기과열지구/조정대상지역]')이 섞여 있다.
    면적은 별도 컬럼으로 이미 뽑았으므로 여기서는 제거하고 나머지를 분류한다.
    """
    notes: list[str] = []
    zones: list[str] = []

    for bracket in _BRACKET.findall(addr_cell or ""):
        remainder = _AREA_LAND.sub("", bracket)
        remainder = _AREA_BLDG.sub("", remainder)
        for token in re.split(r"[/,]", remainder):
            token = token.strip()
            if not token:
                continue
            (zones if token in _ZONE_WORDS else notes).append(token)

    return " / ".join(notes), " / ".join(zones)
