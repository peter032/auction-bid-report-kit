"""소재지 문자열에서 층·호수를 뽑아 지하 여부를 판정한다.

옥션원 목록의 소재지는 `... 건물명 <층> <호수>` 꼴이라 층 정보가 그대로 노출된다.
따라서 상세 페이지에 들어가지 않고 목록만으로 지하 물건을 걸러낼 수 있다.

판정은 세 값 중 하나다.
  True  — 지하 (제외 대상)
  False — 지상 (통과)
  None  — 판정 불가. **버리지 않고** 사람이 보도록 '층미상'으로 남긴다.
"""

import re
from dataclasses import dataclass

__all__ = ["FloorInfo", "parse_floor"]


# 층 토큰. 공백으로 끊은 토큰의 '앞부분'과 일치해야 한다.
# 건물명 안의 숫자('연리지7', '108동')가 층으로 오인되는 것을 막기 위해
# 문자열 전체 정규식이 아니라 토큰 단위로, 토큰 선두에 고정해 검사한다.
#
# 실전 표기 변형 (2026-08-09 서울 422건에서 관찰):
#   1층 · 2층 · 지1층 · 지2층 · 지하2층 · B1층      (기본형)
#   지하층 · 비층                                   (층 번호 없는 지하)
#   비1층                                           ('비'로 지하를 표기)
#   제2층 · 제지하층 · 제지하1층                     (등기부식 '제' 접두)
#   지하층190호                                     (층·호수가 붙어 있음)
_FLOOR_TOKEN = re.compile(
    r"^제?(?P<pre>지하|지상|[지비Bb])?(?P<num>\d+)?층(?P<rest>.*)$"
)
# '1,2층' '1~3층' 처럼 복수 층을 가리키는 표기. 단정하지 않고 미상 처리한다.
_MULTI_FLOOR = re.compile(r"^제?(?:지하|지상|[지비Bb])?\d+(?:[,~\-]\d+)+층")

# 호수 토큰. '비101호', '에프-비1048호', '30호외1개호' 모두 대상.
_UNIT_TOKEN = re.compile(r"호$")
# '14호 외 1개호' 처럼 호수 뒤에 붙는 꼬리 표기. 호수 자체가 아니다.
_UNIT_TAIL = re.compile(r"^\d+개호$")
_UNIT_TAIL_WORDS = {"외"}
# 지하 호수 관례: '비' 바로 뒤에 숫자. '비상1호'·'나비빌딩'은 걸리지 않는다.
_BASEMENT_UNIT = re.compile(r"(?:^|[-])비\d+호")

_BASEMENT_PREFIXES = ("지하", "지", "비", "B", "b")


@dataclass(frozen=True)
class FloorInfo:
    """소재지에서 뽑아낸 층·호수 정보."""

    floor_label: str  # 원문 그대로의 층 표기 ('지1층', '3층', 없으면 '')
    floor_number: int | None  # 지하는 음수, 지상은 양수, 판정 불가는 None
    unit: str  # 호수 표기 ('비123호', 없으면 '')
    is_basement: bool | None  # True 지하 / False 지상 / None 판정 불가
    reason: str  # 판정 근거 (결과 파일에 남겨 검토 가능하게 한다)


def parse_floor(address: str) -> FloorInfo:
    """소재지 문자열 → FloorInfo."""
    tokens = _tail_tokens(address)
    found = _find_floor(tokens)

    # 꼬리 구간에서 층을 못 찾았으면 소재지 전체로 한 번 더 본다.
    # (건물명이 쉼표 앞에 오는 변형 표기 대비)
    if found.number is None and not found.ambiguous:
        full_tokens = address.split()
        retried = _find_floor(full_tokens)
        if retried.number is not None or retried.ambiguous:
            tokens, found = full_tokens, retried

    floor_label, floor_number = found.label, found.number
    # '지하층190호' 처럼 층 토큰에 호수가 붙어 있으면 그것이 호수다.
    unit = found.glued_unit or _find_unit(tokens)

    if floor_number is not None:
        is_basement = floor_number < 0
        reason = f"층 표기 '{floor_label}'"
        return FloorInfo(floor_label, floor_number, unit, is_basement, reason)

    # 층 표기가 없거나 애매한 경우 → 호수로 보조 판정
    if unit and _BASEMENT_UNIT.search(unit):
        return FloorInfo(
            floor_label, None, unit, True, f"호수 '{unit}' 이 지하 호수 표기"
        )

    if found.ambiguous:
        return FloorInfo(
            floor_label, None, unit, None, f"복수 층 표기 '{floor_label}' — 확인 필요"
        )

    return FloorInfo("", None, unit, None, "층 표기 없음 — 확인 필요")


def _tail_tokens(address: str) -> list[str]:
    """건물명 이후 구간을 공백 토큰으로 쪼갠다.

    소재지는 `시도 시군구 동 지번, 건물명 층 호수` 꼴이라
    첫 쉼표 뒤가 층·호수가 들어있는 구간이다.
    ('1,2층' 처럼 층 표기 안에도 쉼표가 있을 수 있어 뒤에서 자르면 안 된다.)
    쉼표가 없으면 전체를 대상으로 한다.
    """
    tail = address.split(",", 1)[-1]
    return tail.split()


@dataclass(frozen=True)
class _FloorMatch:
    label: str = ""
    number: int | None = None
    ambiguous: bool = False
    glued_unit: str = ""


def _find_floor(tokens: list[str]) -> _FloorMatch:
    """토큰에서 층 표기를 찾는다.

    같은 소재지에 '108동 2층' 처럼 층 후보가 여럿일 수 있으므로 마지막 것을 쓴다.
    """
    found = _FloorMatch()

    for token in tokens:
        if _MULTI_FLOOR.match(token):
            found = _FloorMatch(label=token, ambiguous=True)
            continue

        matched = _FLOOR_TOKEN.match(token)
        if not matched:
            continue

        pre = matched.group("pre") or ""
        digits = matched.group("num")
        # '층'만 덩그러니 있는 토큰은 층 표기로 보지 않는다.
        if not pre and not digits:
            continue

        # 층 번호가 없는 '지하층' · '비층' 은 지하 1층으로 본다.
        value = int(digits) if digits else 1
        sign = -1 if pre in _BASEMENT_PREFIXES else 1
        rest = matched.group("rest") or ""
        found = _FloorMatch(
            label=token,
            number=sign * value,
            glued_unit=rest if _UNIT_TOKEN.search(rest) else "",
        )

    return found


def _is_floor_token(token: str) -> bool:
    if _MULTI_FLOOR.match(token):
        return True
    matched = _FLOOR_TOKEN.match(token)
    return bool(matched and (matched.group("pre") or matched.group("num")))


def _find_unit(tokens: list[str]) -> str:
    """토큰에서 호수 표기를 찾는다. 층 토큰은 제외한다.

    '14호 외 1개호' 처럼 뒤에 부가 표기가 따라오는 경우가 있어
    뒤에서부터 훑되 '외'·'N개호' 같은 꼬리 토큰은 건너뛴다.
    """
    for token in reversed(tokens):
        if _is_floor_token(token) or token in _UNIT_TAIL_WORDS:
            continue
        if _UNIT_TAIL.fullmatch(token):
            continue
        if _UNIT_TOKEN.search(token):
            return token
    return ""
