"""입찰보고서 수집 헬퍼(사진 URL·로그인 판정)와 입력 게이트 테스트.

고정하는 함정 (2026-09-14 실측):
1. 옥션원 사진 원본 URL은 상세 HTML에 base64로 박혀 있다. CDN 직접 요청은 403 —
   로그인 브라우저 컨텍스트에서 사진 페이지를 열어야 서명 URL이 발급된다.
2. 세션 캐시가 만료되면 상세 요청이 12KB짜리 '옥션원 로그인' 페이지로 온다.
   `login_box.php` 마커가 없어서 기존 is_rejected() 를 통과했다 → 캐시 오염.
3. 필수 입력(사건·네이버 지도)이 비면 보고서를 시작하지 않는다.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bid_report.fetch_case import extract_photos, is_login_page
from bid_report.gate import check_case

FIX = Path(__file__).parent / "fixtures"


def test_extract_photos_decodes_all_labels():
    html = (FIX / "detail_photos_2735879.html").read_text(encoding="utf-8")
    photos = extract_photos(html)
    assert len(photos) == 17
    labels = {p["label"] for p in photos}
    assert {"개황도", "위치도", "사진", "집합사진"} <= labels
    assert all(p["url"].startswith("https://cdn-file.auction1.co.kr/Photo/") for p in photos)


def test_extract_photos_unique_by_number():
    html = (FIX / "detail_photos_2735879.html").read_text(encoding="utf-8")
    numbers = [p["num"] for p in extract_photos(html)]
    assert len(numbers) == len(set(numbers))


def test_login_page_detected():
    assert is_login_page((FIX / "login_page.html").read_text(encoding="utf-8"))


def test_real_detail_is_not_login_page():
    assert not is_login_page((FIX / "detail_photos_2735879.html").read_text(encoding="utf-8"))


FULL = {
    "case": {"사건번호": "2024타경78261", "product_id": "2735879"},
    "naver_map_url": "https://fin.land.naver.com/map?center=x&zoom=17",
    "buyer": {"명의": "법인", "법인설립연수": 0},
    "field": {"중개사청취": "평당 5만", "임차인사업자번호": "582-81-01515"},
    "finance": {"금리": 0.055},
    "assumptions": {"요구수익률": 0.075},
}


def test_complete_case_passes():
    result = check_case(FULL)
    assert result["blocking"] == []
    assert result["ok"]


def test_missing_required_blocks():
    case = {**FULL, "naver_map_url": "", "buyer": {}}
    result = check_case(case)
    assert not result["ok"]
    assert {q["key"] for q in result["blocking"]} == {"naver_map_url"}


def test_missing_buyer_defaults_to_corporation():
    """명의는 별도 언급 없으면 법인 — 막지 않고 가정으로 표기 ."""
    result = check_case({**FULL, "buyer": {}})
    assert result["ok"]
    assumed = {q["key"]: q["default"] for q in result["assumed"]}
    assert assumed["buyer.명의"] == "법인"


def test_case_number_or_product_id_is_enough():
    case = {**FULL, "case": {"사건번호": "", "product_id": "2735879"}}
    assert check_case(case)["ok"]


def test_case_number_alone_needs_court():
    """사건번호는 법원마다 겹친다 — 법원도 product_id 도 없으면 물건 특정 불가."""
    case = {**FULL, "case": {"사건번호": "2025타경31107"}}
    result = check_case(case)
    assert not result["ok"]
    assert [q["key"] for q in result["blocking"]] == ["case.사건번호"]


def test_case_number_with_court_is_enough():
    case = {**FULL, "case": {"사건번호": "2025타경31107", "법원": "수원지방법원"}}
    assert check_case(case)["ok"]


def test_missing_recommended_becomes_assumption_not_block():
    case = {**FULL, "field": {}, "assumptions": {}}
    result = check_case(case)
    assert result["ok"]
    keys = {q["key"] for q in result["assumed"]}
    assert "field.중개사청취" in keys
    assert "assumptions.요구수익률" in keys


def test_every_question_has_prompt_and_why():
    result = check_case({})
    for q in result["blocking"] + result["assumed"]:
        assert q["question"] and q["why"]
