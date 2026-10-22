"""case.yaml → 입찰보고서 PPTX(14장) + 계산표 markdown.

CLI:  python -m bid_report.build_report <case.yaml> [--check]

- 수치표(시나리오·배수·입찰상한·시세 비교군·마커 콜아웃)는 **전부 계산해서 넣는다**. 손으로 옮겨 적지 않는다.
- yaml 문장 안의 `{cross[A550]}` `{mult[6.246][B]}` `{tax_pct}` 는 계산값으로 치환된다.
- 입력 게이트(gate.check_case)에서 필수가 비면 빌드를 거부한다.
"""

import argparse
import statistics
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bid_report import comps as cp
from bid_report.gate import DEFAULT_BUYER, check_case, format_questions
from bid_report.pptx_kit import (
    BLUE, CARD, DARK, Deck, GRAD, GRAY, GRID, KPI, LEVEL, LINE, MUTE, MUTE2, OK, PARA, PIC,
    PRIMARY, PRIMARY_D, PRIMARY_L, RECT, TB, TEXT, WHITE, foot,
)
from bid_report.scenario import Assumptions, Scenario, acquisition_tax_rate, cross_point, evaluate
from pptx.enum.shapes import MSO_SHAPE

LARGE_PY = 60


class _Safe(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def money(v):
    """만원 → '1억' / '5,000' / '1억 5,000'."""
    if v is None:
        return "—"
    eok, man = divmod(int(v), 10000)
    if eok and man:
        return f"{eok}억 {man:,}"
    return f"{eok}억" if eok else f"{man:,}"


def rng(a, b, fmt="{:.1f}"):
    return fmt.format(a) if abs(a - b) < 0.05 else f"{fmt.format(a)}~{fmt.format(b)}"


def _scenario(spec: dict) -> Scenario:
    return Scenario(name=spec["name"], rent=spec["rent"], deposit=spec["deposit"],
                    vacancy_months=spec.get("vacancy_months", 0), evict=spec.get("evict", False),
                    mgmt_months=spec.get("mgmt_months", 0), capex=spec.get("capex", 0.0),
                    cap_rate=spec.get("cap_rate"))


class Report:
    def __init__(self, case_path: Path):
        self.path = case_path
        self.base = case_path.parent
        self.c = yaml.safe_load(case_path.read_text(encoding="utf-8"))
        gate = check_case(self.c)
        if not gate["ok"]:
            raise SystemExit("입력 게이트 실패 — 아래를 채운 뒤 다시 실행\n" + format_questions(gate))
        self.assumed = gate["assumed"]
        k, fin, asm, buyer = self.c["case"], self.c.get("finance", {}), self.c.get("assumptions", {}), self.c.get("buyer") or {}
        self.A = Assumptions(
            appraisal=k["감정가"] / 1e8, area_py=k["전용평"],
            cap_rate=asm.get("요구수익률", 0.06), interest_rate=fin.get("금리", 0.055),
            ltv_appraisal=fin.get("LTV_감정", 0.7), ltv_bid=fin.get("LTV_낙찰", 0.8),
            evict_per_py=asm.get("명도비_평당", 10.0), mgmt_per_py=asm.get("관리비_평당", 1.0))
        self.tax = acquisition_tax_rate(buyer.get("명의") or DEFAULT_BUYER, buyer.get("과밀억제권역", False), buyer.get("법인설립연수", 0))
        self.sc = {s["code"]: _scenario(s) for s in self.c["scenarios"]}
        self.split = self.c.get("split") or None
        self.split_sc = {s["code"]: _scenario(s) for s in (self.split or {}).get("scenarios", [])}
        self.min_price = k["최저가"] / 1e8
        comps_cfg = self.c.get("comps", {})
        self.large_py = comps_cfg.get("min_py", LARGE_PY)
        self.comps_floor = comps_cfg.get("floor")   # None = 층 무관(기존 동작)
        self.comps_exclude = comps_cfg.get("exclude_contains") or []   # 면적 오기·성격 다른 매물 제외
        self._comps()
        self._numbers()

    # ------------------------------------------------------------ 계산
    def _comps(self):
        nv = self.c.get("naver", {})
        self.rows = self.ded = []
        self.markers = []
        if nv.get("raw"):
            import json
            self.rows = cp.parse_cards(json.loads((self.base / nv["raw"]).read_text(encoding="utf-8")))
            self.ded = cp.dedupe(self.rows)
        if nv.get("markers"):
            import json
            self.markers = cp.marker_summary(json.loads((self.base / nv["markers"]).read_text(encoding="utf-8")))

    def _numbers(self):
        cap = self.A.cap_rate
        self.cross = {code: cross_point(s, self.A, self.tax) for code, s in self.sc.items()}
        self.split_cross = {code: cross_point(s, self.A, self.tax) for code, s in self.split_sc.items()}
        self.bids = [self.min_price] + [b for b in self.c.get("bid_rows", []) if abs(b - self.min_price) > 1e-6]
        self.mult = {f"{b:.3f}".rstrip("0").rstrip("."): {code: evaluate(b, s, self.A, self.tax).multiple
                                                          for code, s in self.sc.items()} for b in self.bids}
        self.sens = []
        for dc in (-0.005, 0, 0.005):
            a = Assumptions(**{**self.A.__dict__, "cap_rate": round(cap + dc, 4)})
            self.sens.append((f"{a.cap_rate*100:.1f}% · {self.tax*100:.1f}%" + ("  기준" if dc == 0 else ""),
                              {code: cross_point(s, a, self.tax) for code, s in self.sc.items()}, dc == 0))
        if self.tax > 0.05:
            self.sens.append((f"{cap*100:.1f}% · 4.6% (개인)",
                              {code: cross_point(s, self.A, 0.046) for code, s in self.sc.items()}, False))
        self.fmt = _Safe(
            cross=_Safe({k: f"{v:.2f}" for k, v in {**self.cross, **self.split_cross}.items()}),
            mult=_Safe({b: _Safe({k: f"{v:.2f}" for k, v in m.items()}) for b, m in self.mult.items()}),
            tax_pct=f"{self.tax*100:.1f}", cap_pct=f"{cap*100:.1f}", min_price=f"{self.min_price:.3f}",
            n_raw=len(self.rows), n_ded=len(self.ded),
            n_large=len(self.comps_pool()),
            n_markers=len(self.markers), n_mapped=len([m for m in self.markers if not m["err"]]),
            n_marker_cards=sum(m["n"] for m in self.markers if not m["err"]))

    def t(self, value):
        """yaml 문장 치환. 리스트·중첩도 처리."""
        if isinstance(value, str):
            try:
                return value.format_map(self.fmt)
            except (ValueError, IndexError):
                return value
        if isinstance(value, list):
            return [self.t(v) for v in value]
        return value

    def img(self, name):
        return str(self.base / "images" / name) if name else None

    # ------------------------------------------------------------ 표 데이터
    def comps_pool(self):
        """본건과 같은 체급의 비교군. 층을 지정하면 그 층만 — 지하 물건에 1층이 섞이면 결론이 뒤집힌다."""
        rows = self.ded
        if self.comps_floor:
            rows = [r for r in rows if r["floor"] == self.comps_floor]
        for bad in self.comps_exclude:
            rows = [r for r in rows if bad not in r["raw"]]
        return cp.large_comps(rows, self.large_py)

    def comps_table(self, limit=7):
        k = self.c["case"]
        rows = [("매물", "전용", "층/준공", "보증/월세", "평당")]
        groups = cp.group_comps(self.comps_pool())
        if len(groups) > limit:
            groups = sorted(groups, key=lambda g: g["n"], reverse=True)[:limit]
            groups.sort(key=lambda g: g["py_min"])
        for g in groups:
            rows.append((f"{g['dong']} {g.get('typ', '')}".strip() or "—",
                         rng(g["py_min"], g["py_max"]) + "평",
                         f"{g['floor']} · {(g['built'] or '')[:4]}",
                         f"{money(g['deposit'])} / {g['rent']:,}" if g["rent"] else f"매매 {money(g['sale'])}",
                         rng(g["ppp_min"], g["ppp_max"], "{:.2f}") if g["ppp_min"] else "—"))
        subj = self.c["tenant_now"]
        rows.append((f"본건 {k['건물명']}", f"{k['전용평']:.2f}평", f"{k['층']} · {k['사용승인'][:4]}",
                     f"{money(subj['deposit'])} / {subj['rent']:,}", f"{subj['rent']/k['전용평']:.2f}"))
        return rows

    def floor_table(self, top=2):
        stats = cp.floor_stats(self.ded)
        chosen = sorted(stats.items(), key=lambda kv: kv[1]["n"], reverse=True)[:top]
        chosen.sort(key=lambda kv: cp._floor_key(kv[0]))
        return [("층", "n", "최저", "중앙값", "최고")] + [
            (f, v["n"], f"{v['min']:.1f}", f"{v['median']:.1f}", f"{v['max']:.1f}") for f, v in chosen]

    def callouts(self):
        out = []
        for m in self.markers:
            if m["err"] or not m["rows"]:
                continue
            groups = cp.group_comps(m["rows"])
            dongs = sorted({g["dong"] for g in groups if g["dong"]})
            years = sorted({(g["built"] or "")[:4] for g in groups if g["built"]})
            head = f"{'·'.join(dongs)} {' / '.join(years)}".strip()
            lines = []
            for g in sorted(groups, key=lambda g: g["py_max"], reverse=True)[:3]:
                price = f"{money(g['deposit'])}/{g['rent']:,}" if g["rent"] else f"매매 {money(g['sale'])}"
                ppp = f" @{rng(g['ppp_min'], g['ppp_max'])}" if g["ppp_min"] else ""
                lines.append(f"{g['floor']} {rng(g['py_min'], g['py_max'], '{:.0f}')}평 {price}{ppp}")
            big = any(g["py_max"] >= self.large_py for g in groups)
            out.append({"x": m["x"], "y": m["y"], "head": head, "body": "\n".join(lines[:2]), "big": big})
        return out

    # ------------------------------------------------------------ 슬라이드
    def build(self):
        d = Deck()
        c, k, v = self.c, self.c["case"], self.c["verdict"]
        T = self.t

        # 1 COVER
        s = d.slide()
        GRAD(s, 0, 0, 1280, 720, DARK, "404040")
        TEXT(s, 90, 120, 1100, 22, "상 가  경 매  분 석  ·  입 찰  보 고 서", size=15, bold=True, color=PRIMARY_L, lh=1.0)
        sh, tf = TB(s, 90, 152, 1120, 130)
        PARA(tf, [(f"{k['사건번호']} ", {'color': WHITE}), (k["건물명"], {'color': PRIMARY_L})], size=44, bold=True, lh=1.3)
        PARA(tf, [(k["호실표기"], {'color': WHITE})], size=44, bold=True, lh=1.3)
        TEXT(s, 90, 300, 1120, 26, f"{k['법원']} {k['계']}   |   {k['신주소']}   |   {k.get('현황', '')}", size=18, color="CCCCCC")
        mx = 90
        for label, val in [("감정가", f"{k['감정가']/1e8:.2f}억"),
                           (f"{k['회차']}차 최저가 ({k['최저가']/k['감정가']*100:.0f}%)", f"{self.min_price:.3f}억"),
                           ("매각기일", k["매각기일"]), ("전용 평당 최저가", f"{k['최저가']/1e4/k['전용평']:,.0f}만원")]:
            RECT(s, mx, 352, 212, 64, fill="3B3B3B", line="565656", radius=10)
            sh2, tf2 = TB(s, mx + 22, 364, 180, 44)
            PARA(tf2, label, size=12, color=MUTE2, lh=1.2, space_after=4)
            PARA(tf2, val, size=18, bold=True, color=WHITE, lh=1.2)
            mx += 226
        GRAD(s, 90, 452, 1100, 104, PRIMARY, PRIMARY_L)
        sh3, tf3 = TB(s, 116, 466, 1050, 80)
        PARA(tf3, f"종합 판정   ({c.get('edition', '초판')})", size=14, bold=True, color="F2CCD1", lh=1.2, space_after=4)
        PARA(tf3, T(v["headline"]), size=21, bold=True, color=WHITE, lh=1.25)
        PARA(tf3, T(v["sub"]), size=13.5, color="F7DDE1", lh=1.3, space_before=4)
        TEXT(s, 90, 574, 1100, 22, T(v["flags"]), size=14, bold=True, color=PRIMARY_L)
        TEXT(s, 620, 672, 600, 20, T(c.get("cover_foot", "")), size=13, color=MUTE, align='r', lh=1.0)

        # 2 OVERVIEW
        o = c["overview"]
        s = d.slide("01  OVERVIEW", T(o["title"]), T(o["subtitle"]))
        GRID(s, 60, 160, [tuple(r) for r in o["rows"]], [118, 570], rowh=int(526 / len(o["rows"])), size=13.5,
             left=(0, 1), header=False)
        KPI(s, 776, 160, 444, 166, f"감정가 (전용 평당 {k['감정가']/1e4/k['전용평']:,.0f}만)", f"{k['감정가']/1e8:.2f}", "억", o.get("appraisal_sub"))
        KPI(s, 776, 340, 444, 166, f"{k['회차']}차 최저가 (전용 평당 {k['최저가']/1e4/k['전용평']:,.0f}만)", f"{self.min_price:.3f}", "억",
            f"감정가의 {k['최저가']/k['감정가']*100:.0f}% · 유찰 {k['회차']-1}회", red=True)
        KPI(s, 776, 520, 444, 166, "입찰보증금 (10%)", f"{k['최저가']*0.1/1e4:,.0f}", "만", f"매각기일 {k['매각기일']} · {k['계']}", vs=26)

        # 3 AUCTION SHEET
        s = d.slide("02  AUCTION SHEET", "옥션원 물건명세 — 원문 캡처", T(c.get("sheet_subtitle", "매각물건현황 · 임차인현황 · 건축물정보 · 매각사례분석")))
        PIC(s, self.img("auc_p1.png"), 60, 150, 560, 530)
        PIC(s, self.img("auc_p2.png"), 650, 150, 570, 530)

        # 4 PHOTOS
        ph = c["photos"]
        s = d.slide("03  SITE PHOTOS", T(ph["title"]), T(ph["subtitle"]))
        PIC(s, self.img(ph["main"]), 60, 150, 560, 330)
        for i, name in enumerate(ph["side"][:2]):
            PIC(s, self.img(name), 640 + i * 300, 150, 280, 330)
        for i, card in enumerate(ph["cards"][:2]):
            CARD(s, 60 + i * 580, 496, 560 if i == 0 else 580, 186, LEVEL[card[0]], T(card[1]), T(card[2]))

        # 5 PLAN · LOCATION
        pl = c["plan"]
        s = d.slide("04  FLOOR PLAN · LOCATION", T(pl["title"]), T(pl["subtitle"]))
        PIC(s, self.img(pl["floor_plan"]), 60, 150, 380, 450)
        PIC(s, self.img(pl["location"]), 460, 150, 380, 450)
        for i, name in enumerate(pl.get("exterior", [])[:2]):
            PIC(s, self.img(name), 860, 150 + i * 270, 360, 258)
        TEXT(s, 60, 612, 780, 70, T(pl["note"]), size=13, lh=1.5)

        # 6 TITLE
        r = c["rights"]
        s = d.slide("05  TITLE ANALYSIS", T(r["title"]), T(r["subtitle"]))
        bad = tuple(i + 1 for i, row in enumerate(r["registry"]) if "말소기준" in str(row[-1]))
        GRID(s, 60, 158, [("접수", "권리종류", "권리자", "채권금액", "소멸")] + [tuple(x) for x in r["registry"]],
             [110, 110, 230, 150, 110], rowh=42, left=(), bad=bad)
        ty = 158 + 42 * (len(r["registry"]) + 1) + 18
        TEXT(s, 60, ty, 710, 22, T(r["tenant_title"]), size=16, bold=True)
        GRID(s, 60, ty + 30, [("임차인", "점유", "사업자등록", "보증금 / 월세", "대항력")] + [tuple(x) for x in r["tenants"]],
             [170, 180, 120, 150, 90], rowh=44, left=(), head="F5F6F8")
        foot(s, T(r["tenant_note"]), y=ty + 30 + 44 * (len(r["tenants"]) + 1) + 12, w=710)
        for i, card in enumerate(r["cards"][:2]):
            CARD(s, 800, 158 + i * 266, 420, 250 if i == 0 else 258, LEVEL[card[0]], T(card[1]), T(card[2]))

        # 7 TENANT (선택)
        tn = c.get("tenant")
        if tn:
            s = d.slide("06  TENANT", T(tn["title"]), T(tn["subtitle"]))
            GRID(s, 60, 158, [tuple(x) for x in tn["finance_rows"]], [150, 170, 170, 170], rowh=40,
                 good=tuple(tn.get("finance_good", [])))
            foot(s, T(tn["finance_note"]), y=158 + 40 * len(tn["finance_rows"]) + 10, w=660)
            GRID(s, 60, 500, [tuple(x) for x in tn["headcount_rows"]], [330, 330], rowh=40,
                 bad=(len(tn["headcount_rows"]) - 1,))
            for i, kp in enumerate(tn["kpis"][:2]):
                KPI(s, 752 + i * 243, 158, 225, 140, kp[0], kp[1], kp[2], kp[3], red=kp[4], vs=30)
            RECT(s, 752, 316, 468, 366, fill="F5F6F8", radius=12)
            sh, tf = TB(s, 776, 334, 420, 330)
            PARA(tf, "재계약 판단", size=15, bold=True, lh=1.2, space_after=10)
            PARA(tf, [("남을 이유", {'bold': True, 'color': "15803D"})], size=13, space_after=2)
            PARA(tf, "\n".join("· " + x for x in tn["stay"]), size=12.5, lh=1.45, space_after=8)
            PARA(tf, [("나갈 이유", {'bold': True, 'color': PRIMARY_D})], size=13, space_after=2)
            PARA(tf, "\n".join("· " + x for x in tn["leave"]), size=12.5, lh=1.45, space_after=10)
            PARA(tf, T(tn["conclusion"]), size=13, lh=1.45)

        # 8 MARKET
        mk = c["market"]
        s = d.slide("07  MARKET COMPS", T(mk["title"]), T(mk["subtitle"]))
        TEXT(s, 60, 150, 640, 22, T(mk["comps_title"]), size=15.5, bold=True, color=PRIMARY)
        ctab = self.comps_table()
        GRID(s, 60, 178, ctab, [170, 110, 110, 170, 80], rowh=40, bad=(len(ctab) - 1,), size=12)
        foot(s, T(mk["comps_note"]), y=178 + 40 * len(ctab) + 10, w=640, size=10.5)
        GRID(s, 60, 590, self.floor_table(), [128] * 5, rowh=30, size=11.5, head="F5F6F8")
        TEXT(s, 730, 150, 490, 22, "본건 적용 시세 (추정)", size=15.5, bold=True)
        est = [("기준", "평당", "월 임대료")] + [tuple(x) for x in mk["estimate_rows"]]
        GRID(s, 730, 178, est, [200, 140, 150], rowh=44,
             good=tuple(i for i, x in enumerate(est) if "기준" in str(x[0]) and i),
             bad=tuple(i for i, x in enumerate(est) if "현 임차" in str(x[0])))
        CARD(s, 730, 190 + 44 * len(est), 490, 682 - (190 + 44 * len(est)), PRIMARY, T(mk["judgement_title"]), T(mk["judgement"]))

        # 9 MAP
        mp = c["map"]
        s = d.slide("08  LISTING MAP", "매물 지도 — 본건 주변 마커별 조건",
                    T("네이버부동산 지도뷰 캡처 · 마커 {n_mapped}/{n_markers} 매핑({n_marker_cards}카드) · 층 · 전용 · 보증금/월세 @전용평당(만원)"))
        MX, MY, MH = 60, 146, 540
        placed = PIC(s, self.img(mp["image"]), MX, MY, 790, MH)
        if placed:
            dx, dy, dw, dh, sc = placed
            ox, oy = mp["crop_offset"]
            tx = lambda x: dx + (x - ox) * sc
            ty_ = lambda y: dy + (y - oy) * sc
            if mp.get("subject_px"):
                sx, sy = tx(mp["subject_px"][0]), ty_(mp["subject_px"][1])
                RECT(s, sx - 13, sy - 13, 26, 26, fill=PRIMARY, line=WHITE, lw=2, shape=MSO_SHAPE.STAR_5_POINT)
                RECT(s, sx - 170, sy - 13, 150, 26, fill=PRIMARY, radius=6)
                TEXT(s, sx - 170, sy - 9, 150, 20, T(mp["subject_label"]), size=11.5, bold=True, color=WHITE, align='c', lh=1.0)
            calls = sorted(self.callouts(), key=lambda q: q["y"])
            BX, BW, BH = 880, 340, 60
            gap = (MH - BH * len(calls)) / max(1, len(calls) - 1)
            for i, q in enumerate(calls):
                by = MY + i * (BH + gap)
                col = PRIMARY if q["big"] else GRAY
                LINE(s, tx(q["x"]), ty_(q["y"]), BX, by + BH / 2, color=col, w=1.2)
                RECT(s, tx(q["x"]) - 9, ty_(q["y"]) - 9, 18, 18, line=col, lw=2.2, shape=MSO_SHAPE.OVAL)
                RECT(s, BX, by, BW, BH, fill=WHITE, line=col, lw=1.2, radius=6)
                sh, tf = TB(s, BX + 10, by + 5, BW - 20, BH - 10, 'm')
                PARA(tf, q["head"], size=11.5, bold=True, color=col, lh=1.15, space_after=1)
                PARA(tf, q["body"], size=10.5, lh=1.2)
        foot(s, T(mp["note"]), y=690, w=1080, size=10)

        # 10 DEMAND
        dm = c["demand"]
        s = d.slide("09  DEMAND", T(dm["title"]), T(dm["subtitle"]))
        KPI(s, 60, 158, 260, 150, "실효 배후세대 (800m)", f"{dm['배후세대_실효']:,}", "세대", f"{dm['배후단지수']}개 단지")
        KPI(s, 336, 158, 260, 150, "상가필지 (220m)", dm["상가필지"], "필지", dm.get("표본경고") or None)
        KPI(s, 612, 158, 260, 150, "세대 / 필지", dm["세대당필지"], f" {dm['입지등급']}", f"우량 기준선 500 대비 {dm['기준선대비']:.0f}%" if isinstance(dm["기준선대비"], (int, float)) else dm["기준선대비"], red=dm["입지등급"] in ("B", "C"))
        GRID(s, 60, 330, [("배후 단지", "세대", "형태", "거리")] + [(a, f"{b:,}", c_, f"{d_}m") for a, b, c_, d_ in dm["단지"][:8]],
             [330, 170, 180, 132], rowh=40)
        for i, card in enumerate(dm["cards"][:2]):
            CARD(s, 900, 158 + i * 286, 320, 270 if i == 0 else 238, LEVEL[card[0]], T(card[1]), T(card[2]), bsize=12)

        # 10-A DEVELOPMENT / 10-B LEASING (선택) — KPI 3 + 표 + 카드 2 의 같은 틀
        # development: 인근 개발 호재(거리는 실측해서 넣는다 · 추정 금지)
        # leasing: 임대 전략 — 어떤 임차를 얼마에, 얼마나 걸려 놓을 것인가
        # area_map (선택): 배후 단지·상권 외곽선 지도 + 번호 대응표
        am = c.get("area_map")
        if am:
            s = d.slide(am.get("chapter", "09-M  CATCHMENT MAP"), T(am["title"]), T(am["subtitle"]))
            PIC(s, self.img(am["image"]), 60, 146, 556, 544)
            rows = [tuple(x) for x in am["rows"]]
            rowh = min(34, int(500 / len(rows)))
            GRID(s, 640, 146, rows, am.get("colw", [50, 290, 120, 120]), rowh=rowh, size=11.5, left=(1,),
                 good=tuple(am.get("good", ())))
            foot(s, T(am["note"]), x=640, y=146 + rowh * len(rows) + 10, w=580, size=10.5)

        # population: 배후 인구 구조(영유아·학령) — 학원·키즈 업종 임차 물건에서 쓴다
        for key, chapter, colw in (("population", "09-P  POPULATION", [190, 140, 190, 130, 170]),
                                   ("development", "09-A  DEVELOPMENT", [190, 140, 190, 130, 170]),
                                   ("leasing", "09-B  LEASING", [200, 110, 130, 130, 250])):
            cfg = c.get(key)
            if not cfg:
                continue
            s = d.slide(cfg.get("chapter", chapter), T(cfg["title"]), T(cfg["subtitle"]))   # chapter: 같은 틀을 다른 주제로 쓸 때
            for i, kp in enumerate(cfg.get("kpis", [])[:3]):
                KPI(s, 60 + i * 276, 158, 260, 150, kp[0], kp[1], kp[2], kp[3], red=bool(kp[4]))
            rows = [tuple(x) for x in cfg["rows"]]
            GRID(s, 60, 330, rows, cfg.get("colw", colw), rowh=42, size=11.5, left=(0, 4),
                 good=tuple(cfg.get("good", ())), bad=tuple(cfg.get("bad", ())))
            foot(s, T(cfg["note"]), y=330 + 42 * len(rows) + 12, w=820, size=10.5)
            for i, card in enumerate(cfg["cards"][:2]):
                CARD(s, 900, 158 + i * 286, 320, 270 if i == 0 else 238, LEVEL[card[0]], T(card[1]), T(card[2]), bsize=12)

        # 11 SCENARIOS
        sc_ = c["scenario_text"]
        s = d.slide("10  SCENARIOS", T(sc_["title"]),
                    T("대출 min(감정{la}%, 낙찰{lb}%) · 금리 {ir}% · 취득세 {tax_pct}% · 법무 0.8% · 요구수익률 {cap_pct}% · 배수 = 매도차익 ÷ 총투자금(보증금 미포함)"
                      .replace("{la}", f"{self.A.ltv_appraisal*100:.0f}").replace("{lb}", f"{self.A.ltv_bid*100:.0f}")
                      .replace("{ir}", f"{self.A.interest_rate*100:.1f}")))
        srows = [("시나리오", "월세 / 보증금", "부대비", f"매도가치 @{self.A.cap_rate*100:.1f}%")]
        good = ()
        for i, spec in enumerate(c["scenarios"], 1):
            sc = self.sc[spec["code"]]
            srows.append((f"{spec['code']} {sc.name}", f"{sc.rent:,.0f} / {sc.deposit:,.0f}", spec.get("cost_note", "0"),
                          f"{evaluate(self.min_price, sc, self.A, self.tax).value:.2f}억"))
            if spec.get("key"):
                good = (i,)
        GRID(s, 60, 158, srows, [230, 150, 290, 150], rowh=40, good=good, left=(0, 2))
        by = 158 + 40 * len(srows) + 14
        TEXT(s, 60, by, 820, 22, "낙찰가별 배수 (1.00 이상 = 부가남 합격선)", size=15, bold=True)
        codes = [sp["code"] for sp in c["scenarios"]]
        mrows = [("낙찰가", "총투자금") + tuple(codes)]
        labels = c.get("bid_labels", {})
        for b in self.bids:
            key = f"{b:.3f}".rstrip("0").rstrip(".")
            base = evaluate(b, self.sc[codes[0]], self.A, self.tax)
            cells = []
            for code in codes:
                m = evaluate(b, self.sc[code], self.A, self.tax).multiple
                cells.append(f"{m:.2f}" + (" ✓" if m >= 1 else ""))
            mrows.append((f"{b:.3f}억  {labels.get(key, '')}".strip(), f"{base.equity:.2f}억", *cells))
        cw = [190, 110] + [int(520 / len(codes))] * len(codes)
        GRID(s, 60, by + 28, mrows, cw, rowh=min(40, int((680 - by - 28) / len(mrows))), bad=(1,))
        a0 = self.sc[codes[0]]
        base_code = next((sp["code"] for sp in c["scenarios"] if sp.get("market")), codes[-1])
        KPI(s, 900, 158, 320, 160, "최저가 기준 표면 수익률", f"{evaluate(self.min_price, a0, self.A, self.tax).rent_yield*100:.1f}", "%",
            f"월 {a0.rent:,.0f} · 보 {a0.deposit:,.0f} ({a0.name})", vs=30)
        mb = self.sc[base_code]
        KPI(s, 900, 332, 320, 160, "시세 정합 수익률", f"{evaluate(self.min_price, mb, self.A, self.tax).rent_yield*100:.1f}", "%",
            f"월 {mb.rent:,.0f} · 보 {mb.deposit:,.0f}", red=True, vs=30)
        CARD(s, 900, 506, 320, 176, PRIMARY, "읽는 법", T(sc_["reading"]), bsize=12)

        # 12 BID PRICE
        s = d.slide("11  BID PRICE", T(v["bid_title"]), "1:1 교차점 = 배수 1.00이 되는 낙찰가 · 요구수익률·취득세 민감도 포함")
        brows = [("요구수익률 · 취득세",) + tuple(codes)]
        good = ()
        for i, (label, crosses, is_base) in enumerate(self.sens, 1):
            brows.append((label,) + tuple(f"{crosses[cd]:.2f}억" for cd in codes))
            if is_base:
                good = (i,)
        GRID(s, 60, 158, brows, [220] + [int(600 / len(codes))] * len(codes), rowh=46, good=good, left=(0,))
        foot(s, T(v["bid_note"]), y=158 + 46 * len(brows) + 10, w=820, size=11)
        ry = 440
        for rec in v["recs"][:3]:
            col = LEVEL[rec[0]]
            RECT(s, 60, ry, 1160, 72, fill="F5F6F8", radius=10)
            RECT(s, 60, ry, 4, 72, fill=col)
            TEXT(s, 92, ry + 25, 300, 22, T(rec[1]), size=14, bold=True, color=col, lh=1.0)
            TEXT(s, 400, ry + 23, 320, 26, T(rec[2]), size=18, bold=True, lh=1.0)
            TEXT(s, 730, ry + 26, 480, 22, T(rec[3]), size=12.5, color=GRAY, lh=1.0)
            ry += 82
        RECT(s, 900, 158, 320, 230, fill="FFF1F2", radius=10)
        RECT(s, 900, 158, 4, 230, fill=PRIMARY)
        sh, tf = TB(s, 924, 176, 280, 196, 'm')
        PARA(tf, T(v["forbid_title"]), size=16, bold=True, color=PRIMARY_D, lh=1.2, space_after=8)
        PARA(tf, T(v["forbid_body"]), size=12.5, lh=1.5)

        # 12-A SPLIT OPTION (선택 — case.yaml 에 split 이 있을 때만)
        sp = self.split
        if sp:
            s = d.slide("11-A  SPLIT OPTION", T(sp["title"]), T(sp["subtitle"]))
            unit = sp.get("unit_py", 50)
            TEXT(s, 60, 148, 640, 22, "면적대별 평당 월세 (네이버 호가 · 1층 제외 · 중복제거)", size=14.5, bold=True)
            bands = cp.size_bands(self.ded, edges=tuple(sp.get("rent_bands", (0, 20, 30, 45, 60, 90, 1000))))
            brow, hl = [("면적대", "매물 수", "평당 중앙", "범위")], ()
            for i, b in enumerate(bands, 1):
                label = f"{b['lo']}~{b['hi']}평" if b["hi"] < 1000 else f"{b['lo']}평↑"
                med = "—" if not b["n"] else ("표본 1건" if b["n"] == 1 else f"{b['median']:.2f}만")
                brow.append((label, b["n"], med, f"{b['min']:.1f}~{b['max']:.1f}" if b["n"] else "—"))
                if b["lo"] <= unit < b["hi"]:
                    hl = (i,)
            GRID(s, 60, 176, brow, [180, 130, 170, 160], rowh=30, size=12, good=hl)
            y2 = 176 + 30 * len(brow) + 14
            TEXT(s, 60, y2, 640, 22, T(sp["sale_title"]), size=14.5, bold=True)
            srow = [("사례", "가격", "전용 평당")] + [tuple(r) for r in sp["sale_rows"]]
            GRID(s, 60, y2 + 28, srow, [360, 140, 140], rowh=30, size=12)
            foot(s, T(sp["sale_note"]), x=60, y=y2 + 28 + 30 * len(srow) + 8, w=640, size=10.5)

            TEXT(s, 730, 148, 490, 22, "분할 시나리오 — 1:1 교차점(입찰상한)", size=14.5, bold=True)
            base_code = sp["base_code"]
            base = self.cross[base_code]
            crow = [("시나리오", "가정", "교차점"), (f"{base_code} 통임대 (기준)", sp.get("base_note", ""), f"{base:.2f}억")]
            good, bad = [], []
            for i, spec in enumerate(sp["scenarios"], 2):
                cx = self.split_cross[spec["code"]]
                crow.append((f"{spec['code']} {spec['name']}", spec.get("note", ""), f"{cx:.2f}억"))
                (good if cx > base else bad).append(i)
            GRID(s, 730, 176, crow, [150, 240, 100], rowh=44, size=11.5, good=tuple(good), bad=tuple(bad), left=(0, 1))
            cy = 176 + 44 * len(crow) + 12
            ch = (682 - cy - 12) / 2
            for i, card in enumerate(sp["cards"][:2]):
                CARD(s, 730, cy + i * (ch + 12), 490, ch, LEVEL[card[0]], T(card[1]), T(card[2]), tsize=13.5, bsize=11.5)

        # 13 RISK
        s = d.slide("12  RISK", T(c["risk_title"]), T(c.get("risk_subtitle", "부가남 레드플래그 대조")))
        risks = c["risks"][:7]
        h = min(70, int((540 - 7 * (len(risks) - 1)) / len(risks)))
        ry = 150
        for level, title, body in risks:
            col = LEVEL[level]
            RECT(s, 60, ry, 1160, h, fill="F5F6F8", radius=10)
            RECT(s, 60, ry, 4, h, fill=col)
            sh, tf = TB(s, 88, ry + 9, 1112, h - 16, 'm')
            PARA(tf, T(title), size=13.5, bold=True, color=col, lh=1.15, space_after=3)
            PARA(tf, T(body), size=11.5, lh=1.35)
            ry += h + 7

        # 14 ACTIONS
        ac = c["actions"]
        s = d.slide()
        GRAD(s, 0, 0, 1280, 720, DARK, "404040")
        TEXT(s, 90, 52, 1100, 22, f"실 행 계 획   ·   {c.get('written', '')}", size=15, bold=True, color=PRIMARY_L, lh=1.0)
        TEXT(s, 90, 82, 1100, 46, T(ac["headline"]), size=34, bold=True, color=WHITE, lh=1.2)
        TEXT(s, 90, 134, 1100, 24, T(ac["sub"]), size=15, color="CCCCCC", lh=1.2)
        for i, box in enumerate(ac["boxes"][:2]):
            x = 90 + i * 558
            RECT(s, x, 178, 532 if i == 0 else 542, 84, fill="3B3B3B", line=LEVEL[box[0]], radius=10)
            sh, tf = TB(s, x + 24, 194, 484, 52, 'm')
            PARA(tf, T(box[1]), size=12.5, color=MUTE2, lh=1.2, space_after=4)
            PARA(tf, T(box[2]), size=19, bold=True, color=WHITE, lh=1.2)
        TEXT(s, 90, 284, 1100, 22, T(ac["todo_title"]), size=15, bold=True, color=PRIMARY_L, lh=1.0)
        todos = ac["todo"][:5]
        gap = 8
        h = min(74, int((374 - gap * (len(todos) - 1)) / max(1, len(todos))))
        iy = 308
        for n, (t1, t2) in enumerate(todos, 1):
            RECT(s, 90, iy, 1100, h, fill="3B3B3B", line="565656", radius=10)
            RECT(s, 108, iy + (h - 38) // 2, 38, 38, fill=PRIMARY, radius=8)
            TEXT(s, 108, iy + (h - 38) // 2 + 10, 38, 22, f"{n:02d}", size=14, bold=True, color=WHITE, align='c', lh=1.0)
            sh, tf = TB(s, 166, iy + 10, 1004, h - 20, 'm')
            PARA(tf, T(t1), size=16 if h >= 74 else 14.5, bold=True, color=WHITE, lh=1.2, space_after=3)
            PARA(tf, T(t2), size=12 if h >= 74 else 11, color=MUTE2, lh=1.25)
            iy += h + gap
        assumed = ", ".join(q["key"].split(".")[-1] for q in self.assumed)
        TEXT(s, 90, 680, 1100, 20, T(c.get("sources", "")) + (f"  ·  가정 항목: {assumed}" if assumed else ""),
             size=11.5, color=MUTE, align='c')

        out = self.base / c["output"]
        d.save(out)
        return out, d.page

    # ------------------------------------------------------------ MD 표
    def tables_md(self) -> str:
        codes = [sp["code"] for sp in self.c["scenarios"]]
        lines = [f"## 계산표 (자동 생성 — {self.path.name})", "",
                 f"전제: 감정가 {self.A.appraisal:.2f}억 · 전용 {self.A.area_py}평 · 요구수익률 {self.A.cap_rate*100:.1f}% · "
                 f"취득세 {self.tax*100:.1f}% · 금리 {self.A.interest_rate*100:.1f}% · 대출 min(감정{self.A.ltv_appraisal*100:.0f}%, 낙찰{self.A.ltv_bid*100:.0f}%)", "",
                 "### 낙찰가별 배수", "", "| 낙찰가 | 대출 | 총투자금 | " + " | ".join(codes) + " |",
                 "|---|---:|---:|" + "---:|" * len(codes)]
        for b in self.bids:
            r0 = evaluate(b, self.sc[codes[0]], self.A, self.tax)
            cells = [f"{evaluate(b, self.sc[cd], self.A, self.tax).multiple:.2f}" for cd in codes]
            lines.append(f"| {b:.3f}억 | {r0.loan:.2f}억 | {r0.equity:.2f}억 | " + " | ".join(cells) + " |")
        lines += ["", "### 1:1 교차점 (입찰상한)", "", "| 요구수익률 · 취득세 | " + " | ".join(codes) + " |",
                  "|---|" + "---:|" * len(codes)]
        for label, crosses, _ in self.sens:
            lines.append(f"| {label} | " + " | ".join(f"{crosses[cd]:.2f}억" for cd in codes) + " |")
        if self.ded:
            lines += ["", f"### 시세 — 원문 {len(self.rows)}카드 → 중복제거 {len(self.ded)}건", "",
                      "| 층 | n | 최저 | 중앙값 | 최고 |", "|---|---:|---:|---:|---:|"]
            for f, st in cp.floor_stats(self.ded).items():
                lines.append(f"| {f} | {st['n']} | {st['min']:.1f} | {st['median']:.1f} | {st['max']:.1f} |")
        if self.split:
            sp = self.split
            lines += ["", "### 분할 임대 검토 — 1:1 교차점", "", "| 시나리오 | 가정 | 교차점 |", "|---|---|---:|",
                      f"| {sp['base_code']} 통임대 (기준) | {sp.get('base_note', '')} | {self.cross[sp['base_code']]:.2f}억 |"]
            lines += [f"| {x['code']} {x['name']} | {x.get('note', '')} | {self.split_cross[x['code']]:.2f}억 |"
                      for x in sp["scenarios"]]
            if self.ded:
                lines += ["", "| 면적대(1층 제외) | 매물 수 | 평당 월세 중앙 |", "|---|---:|---:|"]
                for b in cp.size_bands(self.ded, edges=tuple(sp.get("rent_bands", (0, 20, 30, 45, 60, 90, 1000)))):
                    median = "" if b["median"] is None else f"{b['median']:.2f}만"
                    lines.append(f"| {b['lo']}~{b['hi']}평 | {b['n']} | {median} |")
        if self.assumed:
            lines += ["", "### ⚠️ 가정으로 진행한 항목", ""] + [f"- {q['key']}: 기본값 {q['default']} — {q['why']}" for q in self.assumed]
        return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("case")
    ap.add_argument("--check", action="store_true", help="게이트만 검사")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    path = Path(a.case)
    if a.check:
        import yaml as _y
        res = check_case(_y.safe_load(path.read_text(encoding="utf-8")) or {})
        print(format_questions(res))
        sys.exit(0 if res["ok"] else 2)
    rep = Report(path)
    out, pages = rep.build()
    md = path.parent / "report_tables.md"
    md.write_text(rep.tables_md(), encoding="utf-8")
    print(f"saved: {out} ({pages} slides)\ntables: {md}")


if __name__ == "__main__":
    main()
