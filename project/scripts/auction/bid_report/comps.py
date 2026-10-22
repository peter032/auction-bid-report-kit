"""네이버부동산 카드 원문 → 입찰보고서용 시세 비교군.

카드 파싱은 naver-land 스킬의 parse_listings.parse_card 를 그대로 쓴다(규칙 단일화).
여기서는 중복 제거 · 층별 통계 · 대형 비교군 · 마커 매핑만 한다.
"""

import importlib.util
import io
import re
import statistics
import sys
from pathlib import Path

__all__ = ["parse_cards", "trade_counts", "dedupe", "floor_stats", "large_comps", "marker_summary"]

_ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "parse_listings", _ROOT / ".claude" / "skills" / "naver-land" / "parse_listings.py")
_pl = importlib.util.module_from_spec(_spec)
# parse_listings 는 import 시 sys.stdout 을 UTF-8 래퍼로 갈아끼운다. 그 래퍼가 GC 되면
# 원래 버퍼까지 닫혀 pytest 캡처가 "I/O operation on closed file" 로 죽는다.
# buffer 속성이 없는 StringIO 로 잠시 바꿔 그 분기를 건너뛰게 한다.
_saved_stdout, sys.stdout = sys.stdout, io.StringIO()
try:
    _spec.loader.exec_module(_pl)
finally:
    sys.stdout = _saved_stdout

_BUILT = re.compile(r"(\d{4}\.\d{2})\((\d+)년차\)")
_AREA_TOL_PY = 0.15   # 중개사별 면적 반올림 차이 (수내동 실측 28.70 vs 28.72)


def parse_cards(raw: list[str]) -> list[dict]:
    rows = []
    for text in raw:
        card = _pl.parse_card(text)
        built = _BUILT.search(text)
        rows.append({
            "floor": card["floor"] or "미상",
            "py": card["py"],
            "trade": card["trade"],
            "deposit": card["deposit"],
            "rent": card["rent"],
            "sale": card["maemae"],
            "typ": card["typ"],
            "built": built.group(1) if built else None,
            "raw": text,
        })
    return rows


def trade_counts(rows: list[dict]) -> dict:
    counts = {"월세": 0, "매매": 0, "전세": 0}
    for r in rows:
        if r["trade"] in counts:
            counts[r["trade"]] += 1
    return counts


def _same(a: dict, b: dict) -> bool:
    return (a["floor"] == b["floor"] and a["trade"] == b["trade"]
            and a["deposit"] == b["deposit"] and a["rent"] == b["rent"] and a["sale"] == b["sale"]
            and abs(a["py"] - b["py"]) <= _AREA_TOL_PY)


def dedupe(rows: list[dict]) -> list[dict]:
    """같은 물건을 여러 중개사가 올린 카드를 1건으로. 면적 없는 카드는 비교 불가라 제외."""
    kept: list[dict] = []
    for r in rows:
        if not r["py"] or (r["rent"] is None and r["sale"] is None):
            continue
        if any(_same(k, r) for k in kept):
            continue
        kept.append(r)
    return kept


def _floor_key(floor: str):
    digits = re.match(r"(B?)(\d+)", floor or "")
    if not digits:
        return (2, 0)
    return (1 if digits.group(1) else 0, int(digits.group(2)))


def floor_stats(rows: list[dict], kind: str = "월세") -> dict:
    """층별 평당단가(만원/평). 해당 거래가 없는 층은 키 자체를 만들지 않는다(0 채움 금지)."""
    field = "rent" if kind == "월세" else "sale"
    groups: dict[str, list[float]] = {}
    for r in rows:
        if r["trade"] == kind and r[field]:
            groups.setdefault(r["floor"], []).append(r[field] / r["py"])
    return {
        floor: {"n": len(v), "min": min(v), "median": statistics.median(v), "max": max(v)}
        for floor, v in sorted(groups.items(), key=lambda kv: _floor_key(kv[0]))
    }


def size_bands(rows: list[dict], edges=(0, 20, 30, 45, 60, 90, 1000),
               exclude_ground: bool = True, kind: str = "월세") -> list[dict]:
    """면적대별 평당단가. 분할 임대 검토에서 '작게 쪼개면 평당 더 받나'와 '그 면적대 경쟁 매물 수'를 본다.

    1층은 상층부의 2~3배라 섞으면 소형 면적대 단가가 부풀려진다 → 기본 제외.
    """
    field = "rent" if kind == "월세" else "sale"
    out = []
    for lo, hi in zip(edges, edges[1:]):
        v = [r[field] / r["py"] for r in rows
             if r["trade"] == kind and r[field] and lo <= r["py"] < hi
             and not (exclude_ground and r["floor"] == "1층")]
        out.append({"lo": lo, "hi": hi, "n": len(v),
                    "median": statistics.median(v) if v else None,
                    "min": min(v) if v else None, "max": max(v) if v else None})
    return out


def large_comps(rows: list[dict], min_py: float = 60) -> list[dict]:
    """본건과 같은 체급(대형 통임대) 비교군. 소형 호실 시세와 섞으면 결론이 뒤집힌다."""
    big = [dict(r, ppp=(r["rent"] / r["py"]) if r["rent"] else None) for r in rows if r["py"] >= min_py]
    return sorted(big, key=lambda r: r["py"])


def group_comps(rows: list[dict]) -> list[dict]:
    """같은 층·준공·보증금·월세 조건을 한 줄로 묶어 면적·평당단가를 범위로 표기한다(슬라이드용)."""
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        dong = re.match(r"([가-힣]+동)", r["raw"])
        key = (dong.group(1) if dong else "", r["floor"], r["built"], r["deposit"], r["rent"], r["sale"])
        groups.setdefault(key, []).append(r)
    out = []
    for (dong, floor, built, deposit, rent, sale), members in groups.items():
        pys = [m["py"] for m in members]
        ppps = [(rent or sale) / m["py"] for m in members if (rent or sale)]
        typs = [m["typ"] for m in members if m["typ"]]
        out.append({"dong": dong, "typ": max(set(typs), key=typs.count) if typs else "",
                    "floor": floor, "built": built, "deposit": deposit, "rent": rent,
                    "sale": sale, "py_min": min(pys), "py_max": max(pys),
                    "ppp_min": min(ppps) if ppps else None, "ppp_max": max(ppps) if ppps else None,
                    "n": len(members)})
    return sorted(out, key=lambda g: g["py_min"])


def marker_summary(markers: list[dict]) -> list[dict]:
    """scrape_markers.js 결과 → 마커별 파싱 행. 수집 실패 마커도 err 와 함께 남긴다."""
    out = []
    for m in markers:
        rows = dedupe(parse_cards(m.get("cards", [])))
        out.append({
            "label": m.get("label", ""), "x": m["x"], "y": m["y"],
            "n": m.get("n", 0), "err": m.get("err", ""), "rows": rows,
        })
    return out
