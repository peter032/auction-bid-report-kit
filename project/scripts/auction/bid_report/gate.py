"""입찰보고서 입력 게이트.

필수(blocking)가 비면 보고서를 시작하지 않고 질문한다.
권장(assumed)이 비면 기본값으로 진행하되 보고서에 '가정'으로 표기한다.

CLI:  python -m bid_report.gate <case.yaml>
"""

import sys
from pathlib import Path

__all__ = ["check_case", "DEFAULT_BUYER", "REQUIRED", "RECOMMENDED", "format_questions"]


def _get(case: dict, dotted: str):
    node = case
    for part in dotted.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def _filled(value) -> bool:
    return value not in (None, "", [], {})


REQUIRED = [
    {"key": "case.사건번호",
     "check": lambda c: _filled(_get(c, "case.product_id"))
     or (_filled(_get(c, "case.사건번호")) and _filled(_get(c, "case.법원"))),
     "question": "옥션원 물건 URL(product_id 포함)을 알려주세요. 없으면 사건번호 + 관할법원을 함께 주세요.",
     "why": "사건번호는 법원마다 겹칩니다. 물건을 특정해야 권리·임차인·감정가·사진을 수집할 수 있습니다."},
    {"key": "naver_map_url",
     "check": lambda c: _filled(_get(c, "naver_map_url")),
     "question": "시세 조사할 네이버부동산 지도 URL을 알려주세요 (거래유형·물건종류·층 필터 적용한 상태).",
     "why": "필터(월세/매매·상가/사무실·층)가 비교군을 결정합니다. 임의로 잡으면 결론이 뒤집힙니다."},
]

DEFAULT_BUYER = "법인"   # 별도 언급 없으면 법인 명의

RECOMMENDED = [
    {"key": "buyer.명의", "default": DEFAULT_BUYER,
     "question": "취득 명의가 법인이 아니면 알려주세요 (개인 등).",
     "why": "과밀억제권역에서 신설법인은 취득세 9.4% 중과 — 입찰상한이 0.4억 이상 달라집니다."},
    {"key": "field.중개사청취", "default": "네이버 호가 기준(보정 없음)",
     "question": "인근 중개사에게 들은 실제 성사 임대료/매매가가 있나요?",
     "why": "봉담 건은 이 한 줄로 결론이 바뀌었습니다. 없으면 '호가 기준 초판'으로 표기합니다."},
    {"key": "field.임차인사업자번호", "default": "상호명 검색으로 대체",
     "question": "임차인 사업자등록번호(또는 정확한 상호)를 알고 계신가요?",
     "why": "재무·인원(국민연금)·평판 조회로 재계약 가능성을 판단합니다."},
    {"key": "field.현장임장", "default": "미실시",
     "question": "현장 임장 결과(층별 안내판·공실·관리비 체납·영업상태)가 있나요?",
     "why": "공실률과 관리비 인수 리스크는 현장에서만 확인됩니다."},
    {"key": "finance.금리", "default": 0.055,
     "question": "경락잔금대출 조건(LTV·금리)을 받아둔 게 있나요?",
     "why": "기본값 min(감정70%, 낙찰80%) · 5.5%로 계산합니다."},
    {"key": "assumptions.요구수익률", "default": 0.06,
     "question": "이 지역·층의 매도 요구수익률 기준이 있나요?",
     "why": "매매 호가가 없으면 역산이 불가해 6% 가정 + 5.5~6.5% 민감도로 대체합니다."},
]


def check_case(case: dict) -> dict:
    blocking = [dict(q, check=None) for q in REQUIRED if not q["check"](case)]
    assumed = [dict(q) for q in RECOMMENDED if not _filled(_get(case, q["key"]))]
    if (_get(case, "buyer.명의") or DEFAULT_BUYER) == "법인" and not _filled(_get(case, "buyer.법인설립연수")) \
            and _get(case, "buyer.법인설립연수") != 0:
        assumed.append({"key": "buyer.법인설립연수", "default": 0,
                        "question": "법인 설립 후 몇 년 됐나요? (본점 소재지도 함께)",
                        "why": "설립 5년 이내 + 과밀억제권역이면 취득세 중과 대상입니다."})
    for q in blocking:
        q.pop("check", None)
    return {"ok": not blocking, "blocking": blocking, "assumed": assumed}


def format_questions(result: dict) -> str:
    lines = []
    if result["blocking"]:
        lines.append("■ 필수 — 없으면 보고서를 시작하지 않습니다")
        lines += [f"{i}. {q['question']}\n   (왜: {q['why']})" for i, q in enumerate(result["blocking"], 1)]
    if result["assumed"]:
        lines.append("■ 권장 — 없으면 아래 기본값으로 진행하고 '가정'으로 표기합니다")
        lines += [f"{i}. {q['question']} → 기본값: {q['default']}\n   (왜: {q['why']})"
                  for i, q in enumerate(result["assumed"], 1)]
    return "\n".join(lines) if lines else "입력 완비 — 보고서 작성 가능"


if __name__ == "__main__":
    import yaml
    data = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
    res = check_case(data)
    sys.stdout.reconfigure(encoding="utf-8")
    print(format_questions(res))
    sys.exit(0 if res["ok"] else 2)
