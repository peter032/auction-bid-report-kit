"""네이버부동산 매물 카드 → 입찰보고서 시세 비교군 테스트.

앵커: 2026-09-14 수원 권선동 파크앤시티Ⅱ 인근 (월세·매매 × 사무실·상가 × 중층) 74카드.

고정하는 함정:
1. 같은 물건을 중개사 여러 곳이 올린다 → 층·보증금·월세 동일 + 전용 ±0.15평을 1건으로.
2. 매매 0건일 수 있다 → 매매 통계는 비어 있어야지 0으로 채우면 안 된다.
3. 마커 수집 실패(err)는 조용히 버리지 않고 미매핑으로 남긴다.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bid_report.comps import (
    dedupe,
    floor_stats,
    group_comps,
    large_comps,
    marker_summary,
    parse_cards,
    size_bands,
    trade_counts,
)

FIX = Path(__file__).parent / "fixtures"
RAW = json.loads((FIX / "naver_raw_gwonseon.json").read_text(encoding="utf-8"))
MARKERS = json.loads((FIX / "naver_markers_gwonseon.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rows():
    return parse_cards(RAW)


def test_parses_every_card(rows):
    assert len(rows) == 74


def test_trade_counts_keep_zero_sale(rows):
    assert trade_counts(rows) == {"월세": 74, "매매": 0, "전세": 0}


def test_dedupe_merges_multi_broker_listings(rows):
    assert len(dedupe(rows)) == 45


def test_floor_stats_second_floor(rows):
    stats = floor_stats(dedupe(rows))
    second = stats["2층"]
    assert second["n"] == 26
    assert second["median"] == pytest.approx(3.9, abs=0.05)
    assert second["min"] == pytest.approx(1.5, abs=0.05)


def test_floor_stats_sale_absent_is_not_zero(rows):
    stats = floor_stats(dedupe(rows), kind="매매")
    assert stats == {}


def test_large_comps_threshold(rows):
    big = large_comps(dedupe(rows), min_py=60)
    assert len(big) == 18   # 2026-09-14 보고서 초판은 수기 집계로 17건이라 적었다 — 실측 18
    assert all(r["py"] >= 60 for r in big)
    assert big == sorted(big, key=lambda r: r["py"])


def test_large_comps_keep_build_year(rows):
    big = large_comps(dedupe(rows), min_py=60)
    assert big[0]["built"] in ("2001.12", "1993.05")


def test_group_comps_merges_same_terms(rows):
    groups = group_comps(large_comps(dedupe(rows), min_py=60))
    assert sum(g["n"] for g in groups) == 18
    road = [g for g in groups if g["rent"] == 800]
    assert len(road) == 1 and road[0]["n"] == 2
    assert road[0]["py_min"] < road[0]["py_max"]


def test_size_bands_rent_upper_floors(rows):
    """분할 검토용 — 1층 제외 면적대별 평당 월세. 45~60평 공백(1건)이 드러나야 한다."""
    bands = size_bands(dedupe(rows), edges=(0, 20, 30, 45, 60, 90, 1000), exclude_ground=True)
    by = {(b["lo"], b["hi"]): b for b in bands}
    assert by[(30, 45)]["n"] == 7 and by[(30, 45)]["median"] == pytest.approx(3.88, abs=0.01)
    assert by[(45, 60)]["n"] == 1
    assert by[(60, 90)]["n"] == 11 and by[(60, 90)]["median"] == pytest.approx(3.98, abs=0.01)


def test_size_bands_empty_band_has_no_median(rows):
    bands = size_bands(dedupe(rows), edges=(200, 300), exclude_ground=True)
    assert bands == [{"lo": 200, "hi": 300, "n": 0, "median": None, "min": None, "max": None}]


def test_marker_summary_reports_unmapped():
    summary = marker_summary(MARKERS)
    mapped = [m for m in summary if not m["err"]]
    unmapped = [m for m in summary if m["err"]]
    assert len(mapped) == 8
    assert len(unmapped) == 2
    assert sum(m["n"] for m in mapped) == 46    # 원문 카드 수(중복 포함). 13+11+8+5+3+2+2+2


def test_marker_summary_rows_have_unit_rent():
    summary = marker_summary(MARKERS)
    first = next(m for m in summary if m["x"] == 677)
    assert any(r["floor"] == "2층" and r["rent"] == 800 for r in first["rows"])
