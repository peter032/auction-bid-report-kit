"""상세페이지(ca_view.php) 수집. 네트워크는 여기에만 있다.

**반드시 `page.goto()` 로 가져온다.** 2026-08-27 실측: `context.request.get()`
(APIRequestContext)으로 상세를 치면 로그인 세션이 멀쩡해도 197바이트짜리
`alert('로그인 후 이용해 주세요~')` 페이지가 **200 OK** 로 돌아온다.
목록(ca_list.php)은 request 로 되는데 상세는 안 된다. 캐시된 storage_state
재사용 자체는 정상 동작한다(실측 12/12).

이용약관 대응(선행 설계 §9 승계): 단일 세션·동시요청 없음·요청 간 딜레이·회당 상한.
"""

import time
from collections.abc import Iterable, Iterator

__all__ = ["is_rejected", "DetailFetchError", "fetch_details", "VIEW_URL"]

VIEW_URL = "https://www.auction1.co.kr/auction/ca_view.php?product_id={product_id}"

REQUEST_DELAY_SEC = 1.5
MAX_PER_RUN = 30  # 회당 상한. 대량수집으로 보이지 않게 한다.
_MIN_DETAIL_BYTES = 200
# 마커는 `login_box.php` 하나뿐이다. 실측상 정상 상세페이지에는 0번 나오고,
# 거부 페이지는 이 주소로 리다이렉트한다.
#
# ⚠️ '로그인 후 이용' 은 **마커로 쓰면 안 된다.** 정상 상세페이지에도 다른 버튼
# 스크립트 안에 1번 들어 있어서, 이 문구로 판정하면 전 건이 거부로 찍힌다.
#
# 2026-10-08 추가: 세션이 죽으면 리다이렉트를 따라가 **로그인 화면 자체**(13KB)가 돌아온다.
# 그 HTML 에는 `login_box.php` 문자열이 없어서 로그인 폼(`#client_id`)도 마커로 잡는다.
# 정상 상세페이지에는 이 폼이 없다(픽스처·캐시 실측 0건).
_REJECT_MARKERS = ("login_box.php", 'id="client_id"')


class DetailFetchError(RuntimeError):
    """상세 수집이 신뢰할 수 없는 상태다. 부분 결과를 정상으로 취급하면 안 된다."""


def is_rejected(html: str) -> bool:
    """상세페이지가 아니라 로그인 요구/빈 응답인가.

    짧은 응답은 문구가 바뀌어도 거부로 본다. 사이트가 문구를 갈아도
    조용히 빈 결과를 만드는 것보다 실패로 드러나는 편이 낫다.
    """
    if len(html) < _MIN_DETAIL_BYTES:
        return True
    return any(marker in html for marker in _REJECT_MARKERS)


def fetch_details(
    context,
    product_ids: Iterable[str],
    *,
    delay: float = REQUEST_DELAY_SEC,
    limit: int = MAX_PER_RUN,
) -> Iterator[tuple[str, str]]:
    """`(product_id, html)` 를 하나씩 흘려보낸다.

    거부 응답을 만나면 **즉시 중단**한다. 세션이 끊긴 채로 계속 돌면
    나머지 전부가 빈 결과가 되고, 그건 조용한 데이터 유실이다.
    """
    ids = list(product_ids)[:limit]
    page = context.new_page()
    try:
        for index, product_id in enumerate(ids):
            page.goto(
                VIEW_URL.format(product_id=product_id),
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            page.wait_for_timeout(1_500)
            html = page.content()

            if is_rejected(html):
                raise DetailFetchError(
                    f"상세 접근이 거부됐다 (product_id={product_id}, "
                    f"{index}/{len(ids)}건 수집 후). 로그인 세션을 확인해라. "
                    "`clear_state()` 로 재로그인을 강제할 수 있다."
                )

            yield product_id, html
            if index < len(ids) - 1:
                time.sleep(delay)
    finally:
        page.close()
