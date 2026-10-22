"""시나리오 손익 · 배수 · 1:1 입찰상한.

단위: 가격·대출·투자금은 **억원**, 월세·보증금·평당비용은 **만원**.

배수 = 매도차익 ÷ 총투자금. 1.00 이상이 부가남 합격선(100원 넣고 100원 먹기).
총투자금에 보증금을 넣지 않는다 — 보증금은 반환채무라 자기자본 차감 항목이 아니다.
"""

from dataclasses import dataclass

__all__ = ["Assumptions", "Scenario", "Result", "evaluate", "cross_point",
           "acquisition_tax_rate", "next_min_price", "TAX_BASE", "TAX_HEAVY"]

TAX_BASE = 0.046    # 상가 취득세 4% + 지방교육세·농특세
TAX_HEAVY = 0.094   # 지방세법 §13② 대도시 중과 (표준세율×3 − 중과기준세율×2 + 부가세)


@dataclass(frozen=True)
class Assumptions:
    appraisal: float                # 감정가 (억)
    area_py: float                  # 전용 평
    cap_rate: float = 0.06          # 매도 요구수익률 (2026-10-22 기본값 7.5% → 6%)
    interest_rate: float = 0.055
    legal_rate: float = 0.008       # 법무사 등
    sale_fee: float = 0.009         # 매도 중개보수
    ltv_appraisal: float = 0.7
    ltv_bid: float = 0.8
    evict_per_py: float = 10.0      # 명도비 (만원/평, 부가남 표준)
    mgmt_per_py: float = 1.0        # 공실 중 관리비 (만원/평/월) — 관리사무소 확인 전 가정


@dataclass(frozen=True)
class Scenario:
    name: str
    rent: float                     # 월세 (만원)
    deposit: float                  # 보증금 (만원)
    vacancy_months: float = 0       # 공실 기간 이자 부담
    evict: bool = False             # 명도비 발생 여부
    mgmt_months: float = 0          # 공실 관리비 부담 개월
    capex: float = 0.0              # 추가 공사비 (억) — 분할 가벽·출입문·설비 분리 등
    cap_rate: float | None = None   # 이 시나리오만의 매도 요구수익률 (None = Assumptions 값)


@dataclass(frozen=True)
class Result:
    loan: float
    acquisition: float
    other: float
    equity: float
    annual_net: float
    leverage_yield: float
    rent_yield: float
    value: float
    multiple: float


def evaluate(bid: float, s: Scenario, a: Assumptions, tax: float) -> Result:
    loan = min(a.appraisal * a.ltv_appraisal, bid * a.ltv_bid)
    acquisition = bid * (tax + a.legal_rate)
    interest = loan * a.interest_rate
    evict = a.evict_per_py * a.area_py / 1e4 if s.evict else 0.0
    other = (evict + s.vacancy_months / 12 * interest
             + s.mgmt_months * a.mgmt_per_py * a.area_py / 1e4 + s.capex)
    equity = bid + acquisition + other - loan
    annual_rent = s.rent * 12 / 1e4
    deposit = s.deposit / 1e4
    annual_net = annual_rent - interest
    value = annual_rent / (s.cap_rate or a.cap_rate) + deposit
    multiple = (value * (1 - a.sale_fee) - (bid + acquisition + other)) / equity
    return Result(
        loan=loan, acquisition=acquisition, other=other, equity=equity,
        annual_net=annual_net, leverage_yield=annual_net / equity,
        rent_yield=annual_rent / (bid - deposit), value=value, multiple=multiple,
    )


def cross_point(s: Scenario, a: Assumptions, tax: float, target: float = 1.0) -> float:
    """배수가 target 이 되는 낙찰가. 배수는 낙찰가에 대해 단조 감소한다."""
    lo, hi = 0.01, max(a.appraisal, s.rent * 12 / 1e4 / (s.cap_rate or a.cap_rate)) * 2
    for _ in range(80):
        mid = (lo + hi) / 2
        if evaluate(mid, s, a, tax).multiple >= target:
            lo = mid
        else:
            hi = mid
    return lo


def acquisition_tax_rate(buyer: str, overcrowded: bool, corp_age_years: float) -> float:
    """법인이 과밀억제권역(대도시)에서 설립 5년 이내면 중과.

    ⚠️ 판단 근거는 지방세법 §13② 원문 + 수도권정비계획법 시행령 별표1. 세무사 컨펌 전 확정 금지.
    """
    if buyer == "법인" and overcrowded and corp_age_years < 5:
        return TAX_HEAVY
    return TAX_BASE


def next_min_price(min_price: int, ratio: float = 0.7) -> int:
    """다음 회차 최저가. 수원지법 등 30% 저감이 기본, 법원마다 20%도 있다."""
    return int(round(min_price * ratio))
