"""옥션원 종합검색 폼의 한글 라벨 ↔ 사이트 코드 매핑.

2026-08-09 기준 `/auction/ca_title.php` 폼에서 실측한 값이다.
네트워크나 파싱에 의존하지 않는 순수 데이터 모듈.
"""

# 물건현황 (select name=state)
STATE: dict[str, str] = {
    "전체보기": "",
    "진행물건": "1,2,17,18",
    "신건": "1",
    "유찰": "2",
    "매각전부": "3,5,19",
    "매각/매각허가": "3,27",
    "잔금납부물건": "29",
    "배당기일/종결": "34",
    "진행외물건": "9,10,11,13,20,22,23,24",
    "미진행": "9,15,20,23",
    "변경/연기": "10,11",
    "불허가/허가취소": "22,24",
    "정지": "13",
}

# 물건종류 (checkbox clg_*, 최종적으로 s_class2 에 콤마로 합쳐 전송)
# 값은 (코드, 체크박스 그룹명)
PROPERTY_TYPE: dict[str, tuple[str, str]] = {
    # 주거용 (그룹 1)
    "아파트": ("1", "clg_1"),
    "주택": ("2", "clg_1"),
    "다가구(원룸등)": ("32", "clg_1"),
    "다세대(빌라)": ("8", "clg_1"),
    "근린주택": ("3", "clg_1"),
    # 상업용 및 업무용 (그룹 4)
    "근린상가": ("4", "clg_4"),
    "근린시설": ("5", "clg_4"),
    "오피스텔": ("19", "clg_4"),
    "사무실": ("6", "clg_4"),
    "창고": ("21", "clg_4"),
    "공장": ("13", "clg_4"),
    "아파트형공장": ("27", "clg_4"),
    "숙박시설": ("16", "clg_4"),
    "숙박(콘도등)": ("30", "clg_4"),
    "교육시설": ("15", "clg_4"),
    "종교시설": ("18", "clg_4"),
    "농가관련시설": ("22", "clg_4"),
    "의료시설": ("26", "clg_4"),
    "주유소(위험물)": ("20", "clg_4"),
    "목욕탕": ("28", "clg_4"),
    "노유자시설": ("44", "clg_4"),
    "분뇨쓰레기처리": ("51", "clg_4"),
    "자동차관련시설": ("52", "clg_4"),
    "장례관련시설": ("53", "clg_4"),
    "문화및집회시설": ("54", "clg_4"),
    # 토지 (그룹 9)
    "대지": ("9", "clg_9"),
    "농지": ("10", "clg_9"),
    "임야": ("11", "clg_9"),
    "잡종지": ("12", "clg_9"),
    "과수원": ("14", "clg_9"),
    "도로": ("7", "clg_9"),
}

# 시/도 (select name=sido)
SIDO: dict[str, str] = {
    "서울": "11",
    "전남광주": "12",
    "부산": "26",
    "대구": "27",
    "인천": "28",
    "대전": "30",
    "울산": "31",
    "세종": "36",
    "경기": "41",
    "강원": "51",
    "충북": "43",
    "충남": "44",
    "전북": "52",
    "경북": "47",
    "경남": "48",
    "제주": "50",
}

# 한 페이지당 목록 수 (select name=scale).
#
# 폼은 100까지 제공하지만 실제로는 80 이상을 요청해도 78행만 렌더된다.
# 그런데 페이지 링크는 요청한 scale 만큼 start 를 건너뛰므로,
# scale=100 으로 수집하면 페이지마다 22건씩 조용히 유실된다.
# 2026-08-09 실측: 20/30/40/50/60 은 요청 수 그대로, 80·100 은 78행.
SAFE_PAGE_SIZE = 60
FORM_MAX_PAGE_SIZE = 100


class UnknownCodeError(ValueError):
    """한글 라벨이 코드표에 없을 때."""


def state_code(label: str) -> str:
    """물건현황 한글 라벨 → 코드."""
    try:
        return STATE[label]
    except KeyError:
        raise UnknownCodeError(
            f"알 수 없는 물건현황: {label!r}. 가능한 값: {', '.join(STATE)}"
        ) from None


def sido_code(label: str) -> str:
    """시/도 한글 라벨 → 코드."""
    try:
        return SIDO[label]
    except KeyError:
        raise UnknownCodeError(
            f"알 수 없는 지역: {label!r}. 가능한 값: {', '.join(SIDO)}"
        ) from None


def property_type_codes(labels: list[str]) -> list[tuple[str, str]]:
    """물건종류 한글 라벨 목록 → [(코드, 체크박스 그룹명), ...]."""
    out = []
    for label in labels:
        try:
            out.append(PROPERTY_TYPE[label])
        except KeyError:
            raise UnknownCodeError(
                f"알 수 없는 물건종류: {label!r}. 가능한 값: {', '.join(PROPERTY_TYPE)}"
            ) from None
    return out
