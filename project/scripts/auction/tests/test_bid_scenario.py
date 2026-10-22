"""입찰보고서 시나리오·입찰상한 계산 테스트.

회귀 앵커는 2024타경78261 수원 권선동 파크앤시티타워Ⅱ 201호 (2026-09-14 보고서).
감정가 18.21억 · 전용 101.05평 · 요구수익률 7.5% · 취득세 9.4%(과밀억제권역 신설법인).

고정하는 함정:
1. 대출은 min(감정가×70%, 낙찰가×80%) — 저가 회차에서는 낙찰가 쪽이 구속한다.
2. 배수의 분모(총투자금)에 보증금을 넣지 않는다. 보증금은 반환채무다.
3. 취득세 중과는 '과밀억제권역 + 설립 5년 이내 법인' 둘 다일 때만.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bid_report.scenario import (
    Assumptions,
    Scenario,
    acquisition_tax_rate,
    cross_point,
    evaluate,
    next_min_price,
)

BASE = Assumptions(appraisal=18.21, area_py=101.05, cap_rate=0.075)
TAX = 0.094

A600 = Scenario("A0 현 조건", rent=600, deposit=5000)
A550 = Scenario("A550 감액 재계약", rent=550, deposit=5000)
A500 = Scenario("A500 시세 재계약", rent=500, deposit=5000)
B500 = Scenario("B′ 명도 후 재임차", rent=500, deposit=5000, vacancy_months=6, evict=True, mgmt_months=6)
C400 = Scenario("C 최악", rent=400, deposit=3000, vacancy_months=12, evict=True, mgmt_months=12)


def test_loan_is_bound_by_bid_at_low_rounds():
    r = evaluate(6.24603, A500, BASE, TAX)
    assert r.loan == pytest.approx(6.24603 * 0.8)          # 12.75억(감정 70%)보다 작다


def test_loan_is_bound_by_appraisal_at_high_bids():
    r = evaluate(17.0, A500, BASE, TAX)
    assert r.loan == pytest.approx(18.21 * 0.7)


def test_equity_excludes_deposit():
    r = evaluate(6.24603, A500, BASE, TAX)
    expected = 6.24603 * (1 + TAX + 0.008) - 6.24603 * 0.8
    assert r.equity == pytest.approx(expected)


def test_exit_value_is_rent_capitalized_plus_deposit():
    r = evaluate(8.0, A500, BASE, TAX)
    assert r.value == pytest.approx(500 * 12 / 1e4 / 0.075 + 0.5)   # 8.50억


@pytest.mark.parametrize("bid, scenario, multiple", [
    (6.246, A600, 1.66),
    (6.246, A550, 1.24),
    (6.246, A500, 0.82),
    (6.246, B500, 0.57),
    (6.246, C400, -0.31),
])
def test_multiples_match_report(bid, scenario, multiple):
    assert evaluate(bid, scenario, BASE, TAX).multiple == pytest.approx(multiple, abs=0.01)


@pytest.mark.parametrize("scenario, cross", [
    (A600, 7.13), (A550, 6.56), (A500, 6.00), (B500, 5.59), (C400, 4.15),
])
def test_cross_points_match_report(scenario, cross):
    assert cross_point(scenario, BASE, TAX) == pytest.approx(cross, abs=0.01)


def test_cross_point_rises_with_lower_tax():
    assert cross_point(A500, BASE, 0.046) == pytest.approx(6.44, abs=0.01)


def test_cross_point_falls_with_higher_cap_rate():
    strict = Assumptions(appraisal=18.21, area_py=101.05, cap_rate=0.08)
    assert cross_point(A550, strict, TAX) == pytest.approx(6.18, abs=0.01)


SPLIT_FLAT = Scenario("S1 분할 월세 동일", rent=500, deposit=5000, vacancy_months=4, evict=True, mgmt_months=4, capex=0.30)
SPLIT_UP = Scenario("S2 분할 월세 +9%", rent=550, deposit=5000, vacancy_months=4, evict=True, mgmt_months=4, capex=0.30)
SPLIT_CAP = Scenario("S3 분할 매도 7.0%", rent=500, deposit=5000, vacancy_months=4, evict=True, mgmt_months=4, capex=0.30, cap_rate=0.07)
SPLIT_BAD = Scenario("S4 분할 공사·공실 악화", rent=500, deposit=5000, vacancy_months=8, evict=True, mgmt_months=8, capex=0.50)


def test_capex_adds_to_equity():
    base = evaluate(6.246, Scenario("x", rent=500, deposit=5000, vacancy_months=4, evict=True, mgmt_months=4), BASE, TAX)
    split = evaluate(6.246, SPLIT_FLAT, BASE, TAX)
    assert split.equity == pytest.approx(base.equity + 0.30)
    assert split.multiple < base.multiple


def test_scenario_cap_rate_overrides_assumption():
    assert evaluate(6.246, SPLIT_CAP, BASE, TAX).value == pytest.approx(500 * 12 / 1e4 / 0.07 + 0.5)


@pytest.mark.parametrize("scenario, cross", [
    (SPLIT_FLAT, 5.26), (SPLIT_UP, 5.81), (SPLIT_CAP, 5.66), (SPLIT_BAD, 4.83),
])
def test_split_cross_points(scenario, cross):
    """2026-09-14 분할 임대 검토 — 통임대 재임차 B′ 5.59억 대비."""
    assert cross_point(scenario, BASE, TAX) == pytest.approx(cross, abs=0.01)


def test_vacancy_costs_lower_the_cross_point():
    assert cross_point(B500, BASE, TAX) < cross_point(A500, BASE, TAX)


@pytest.mark.parametrize("buyer, overcrowded, corp_age, rate", [
    ("법인", True, 0, 0.094),
    ("법인", True, 5, 0.046),      # 설립 5년 경과
    ("법인", False, 0, 0.046),     # 성장관리권역(화성·김포)
    ("개인", True, 0, 0.046),
])
def test_acquisition_tax_rate(buyer, overcrowded, corp_age, rate):
    assert acquisition_tax_rate(buyer, overcrowded, corp_age) == rate


def test_next_min_price_default_30_percent_cut():
    assert next_min_price(624_603_000) == 437_222_100


def test_next_min_price_custom_ratio():
    assert next_min_price(1_000_000_000, ratio=0.8) == 800_000_000
