"""옥션원 종합검색 실행 + 페이지네이션 순회.

검색 1회는 `POST /auction/ca_list.php`, 이후 페이지는 같은 파라미터에
`start=` 만 바꾼 GET 이다 (사이트의 페이지 링크가 그렇게 생겼다).

사이트 이용약관이 프로그램을 이용한 대량 수집을 제한하므로,
단일 세션 · 순차 요청 · 요청 간 지연을 지킨다. 동시 요청은 하지 않는다.
"""

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

from . import codes
from .parse import parse_list_page, parse_total_count

__all__ = ["SearchQuery", "SearchResult", "FetchError", "run_search"]

BASE_URL = "https://www.auction1.co.kr"
LIST_URL = f"{BASE_URL}/auction/ca_list.php"
SEARCH_FORM_URL = f"{BASE_URL}/auction/ca_title.php"

REQUEST_DELAY_SEC = 1.5
PAGE_TIMEOUT_MS = 45_000
DEBUG_DIR = Path(__file__).resolve().parents[1] / "_debug"

# 옥션원은 EUC-KR(cp949) 로 응답한다. Playwright 의 response.text() 는
# UTF-8 을 가정하므로 바이트를 직접 디코딩해야 한다.
SITE_ENCODING = "cp949"


class FetchError(RuntimeError):
    """수집 중 복구 불가능한 문제. 부분 결과를 저장하지 않고 중단한다."""


@dataclass(frozen=True)
class SearchQuery:
    """사람이 읽는 검색 조건. 사이트 코드 변환은 이 클래스가 책임진다."""

    sido: str = "서울"
    property_types: tuple[str, ...] = ("근린상가", "근린시설", "사무실")
    state: str = "진행물건"
    page_size: int = codes.SAFE_PAGE_SIZE

    def to_params(self) -> list[tuple[str, str]]:
        """폼 파라미터 목록. clg_* 는 같은 키가 반복되므로 dict 가 아닌 list."""
        type_codes = codes.property_type_codes(list(self.property_types))

        params: list[tuple[str, str]] = [
            ("state", codes.state_code(self.state)),
            ("power_flag", "1"),
        ]
        for code, group in type_codes:
            params.append((group, code))
        params.append(("s_class2", ",".join(code for code, _ in type_codes)))
        params += [
            ("sido", codes.sido_code(self.sido)),
            ("gugun", "0"),
            ("dong", "0"),
            ("am_cnt", "0"),
            ("special", "0"),
            ("scale", str(self.page_size)),
            ("page_code", "101010"),
            ("ck_photo", "1"),
            ("favor_edit", "0"),
            ("search_mode", "1"),
        ]
        return params

    def describe(self) -> str:
        return (
            f"{self.sido} · {'/'.join(self.property_types)} · {self.state}"
        )


@dataclass
class SearchResult:
    rows: list[dict[str, Any]]
    total_reported: int | None
    warnings: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return (
            self.total_reported is not None
            and len(self.rows) == self.total_reported
            and not self.warnings
        )


def run_search(
    context,
    query: SearchQuery,
    *,
    log: Callable[[str], None] = print,
    delay_sec: float = REQUEST_DELAY_SEC,
) -> SearchResult:
    """로그인된 컨텍스트로 검색을 실행하고 전 페이지를 수집한다."""
    params = query.to_params()
    warnings: list[str] = []

    log(f"검색 조건: {query.describe()}")
    first_html = _post_search(context, params)

    total = parse_total_count(first_html)
    if total is None:
        _dump_debug(first_html, "no_total_count.html")
        raise FetchError(
            "결과 건수('물건수 : N건')를 찾지 못했다. 사이트 구조가 바뀌었을 수 있다. "
            f"응답을 {DEBUG_DIR} 에 저장했다."
        )

    log(f"사이트 표시 건수: {total}건")
    if total == 0:
        return SearchResult(rows=[], total_reported=0)

    rows = parse_list_page(first_html)
    if not rows:
        _dump_debug(first_html, "no_rows.html")
        raise FetchError(
            f"{total}건이라는데 결과 행을 하나도 파싱하지 못했다. "
            f"응답을 {DEBUG_DIR} 에 저장했다."
        )

    # 페이지 링크는 '요청한 scale' 만큼 start 를 건너뛴다.
    # 실제 렌더된 행 수로 스텝을 잡으면 오프셋이 어긋나 구간이 통째로 빈다.
    page_size = query.page_size
    log(f"1페이지 {len(rows)}건 수집")
    warnings += _page_size_warning(1, len(rows), page_size, total)

    for start in range(page_size, total, page_size):
        time.sleep(delay_sec)
        page_no = start // page_size + 1
        html = _get_page(context, params, total=total, start=start)
        if html is None:
            warnings.append(f"{page_no}페이지(start={start}) 요청 실패 — 해당 구간 누락")
            log(f"  {page_no}페이지 실패 — 건너뜀")
            continue
        page_rows = parse_list_page(html)
        if not page_rows:
            warnings.append(f"{page_no}페이지(start={start}) 파싱 결과 0건 — 구간 누락 가능")
        rows.extend(page_rows)
        warnings += _page_size_warning(page_no, len(page_rows), page_size, total - start)
        log(f"  {page_no}페이지 {len(page_rows)}건 (누적 {len(rows)})")

    rows = _dedupe(rows, warnings)

    if len(rows) != total:
        warnings.append(
            f"수집 {len(rows)}건 ≠ 사이트 표시 {total}건 — 누락 가능성 있음"
        )

    return SearchResult(rows=rows, total_reported=total, warnings=warnings)


def _page_size_warning(page_no: int, got: int, requested: int, remaining: int) -> list[str]:
    """요청한 만큼 행이 안 왔으면 경고.

    사이트가 scale 을 무시하고 일부만 렌더하는 경우를 잡는다(80·100에서 발생).
    마지막 페이지는 원래 적게 오므로 제외한다.
    """
    expected = min(requested, remaining)
    if got < expected:
        return [
            f"{page_no}페이지: {requested}건 요청했는데 {got}건만 렌더됨 "
            f"(기대 {expected}건) — {expected - got}건 유실 가능"
        ]
    return []


def _dedupe(rows: list[dict[str, Any]], warnings: list[str]) -> list[dict[str, Any]]:
    """product_id 중복 제거. 중복이 나오면 페이지 오프셋이 어긋난 신호다."""
    seen: set[str] = set()
    unique = []
    for row in rows:
        key = row.get("product_id", "")
        if key and key in seen:
            continue
        seen.add(key)
        unique.append(row)
    if len(unique) != len(rows):
        warnings.append(
            f"중복 {len(rows) - len(unique)}건 제거 — 페이지 오프셋이 겹쳤을 수 있음"
        )
    return unique


def _post_search(context, params: list[tuple[str, str]]) -> str:
    response = context.request.post(
        LIST_URL,
        data=urlencode(params, encoding=SITE_ENCODING),
        headers={
            "Content-Type": f"application/x-www-form-urlencoded; charset={SITE_ENCODING}",
            "Referer": SEARCH_FORM_URL,
        },
        timeout=PAGE_TIMEOUT_MS,
    )
    if not response.ok:
        raise FetchError(f"검색 요청 실패: HTTP {response.status}")
    return _decode(response)


def _get_page(context, params, *, total: int, start: int) -> str | None:
    """페이지 GET. 1회 재시도 후에도 실패하면 None."""
    query = [("total_record", str(total)), ("search_fm_off", "1")]
    query += params
    query.append(("start", str(start)))
    url = f"{LIST_URL}?{urlencode(query, encoding='utf-8')}"

    for attempt in (1, 2):
        try:
            response = context.request.get(
                url, headers={"Referer": LIST_URL}, timeout=PAGE_TIMEOUT_MS
            )
            if response.ok:
                return _decode(response)
        except Exception:
            pass
        if attempt == 1:
            time.sleep(REQUEST_DELAY_SEC)
    return None


def _decode(response) -> str:
    """응답 바이트를 사이트 인코딩으로 디코딩.

    Content-Type 에 charset 이 있으면 그걸 쓰고, 없으면 cp949 로 본다.
    깨진 바이트가 있어도 수집을 중단시키지 않도록 replace 로 넘긴다.
    """
    charset = SITE_ENCODING
    content_type = response.headers.get("content-type", "")
    matched = re.search(r"charset=([\w-]+)", content_type, re.I)
    if matched:
        charset = matched.group(1)
    try:
        return response.body().decode(charset, errors="replace")
    except LookupError:
        return response.body().decode(SITE_ENCODING, errors="replace")


def _dump_debug(html: str, filename: str) -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    (DEBUG_DIR / filename).write_text(html, encoding="utf-8")
