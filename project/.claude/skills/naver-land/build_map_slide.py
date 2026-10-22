# -*- coding: utf-8 -*-
"""마커별 저평가·급매 후보 → 지도 위 지시선 슬라이드(HTML) 생성

사용:
  python build_map_slide.py <출력폴더> [--title "제목"] [--sub "부제"]
전제:
  %TEMP%/flagged.json   (flag_candidates.py 산출)
  %TEMP%/map_crop.png   (크롭한 지도 캡처)
출력:
  <출력폴더>/slides.html  → html-slides의 capture_and_build.py로 PPTX 변환
"""
import json, base64, os, re, sys, argparse

ap = argparse.ArgumentParser()
ap.add_argument('outdir')
ap.add_argument('--title', default='상가·사무실 매매 — 저평가 · 급매 후보 지도')
ap.add_argument('--sub', default='네이버부동산 기준 · 금액 단위 만원 · 평당단가는 전용면적 기준')
A = ap.parse_args()

TMP = os.environ.get('TEMP', '/tmp').replace(chr(92), '/') + '/'
OUT = A.outdir.rstrip('/') + '/'
os.makedirs(OUT, exist_ok=True)

img = base64.b64encode(open(TMP + 'map_crop.png', 'rb').read()).decode()
from PIL import Image
CW, CH = Image.open(TMP + 'map_crop.png').size
CROP_X, CROP_Y = 140, 57   # STEP: 크롭 좌상단 (지도 크롭 좌표와 반드시 일치시킬 것)

MX, MY, MH = 24, 66, 772
MW = int(MH * CW / CH)
SX, SY = MW / float(CW), MH / float(CH)
tx = lambda x: MX + (x - CROP_X) * SX
ty = lambda y: MY + (y - CROP_Y) * SY

BOX_L, BOX_R = 1210, 1576

data = json.load(open(TMP + 'flagged.json', encoding='utf-8'))
def kind(f):
    if f['ratio'] is not None and f['ratio'] < 0.15:
        return 'err'
    if f['ratio'] is not None and f['ratio'] <= 0.75:
        return 'under'
    return 'urgent'

boxes = [b for b in data if b['flagged']]
boxes.sort(key=lambda b: b['y'])

# 박스 높이 산정 후 세로 배치
HDR, ROW, PAD = 25, 21, 9
for b in boxes:
    b['h'] = HDR + ROW * len(b['flagged']) + PAD
total = sum(b['h'] for b in boxes)
gap = max(8, (MH - total) / (len(boxes) - 1)) if len(boxes) > 1 else 8
y = MY
for b in boxes:
    b['by'] = y
    y += b['h'] + gap

def esc(s):
    return (s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

rows_html, lines, dots = [], [], []
for b in boxes:
    mx, my = tx(b['x']), ty(b['y'])
    ax, ay = BOX_L, b['by'] + b['h'] / 2
    mid = (mx + ax) / 2
    lines.append(f'<path d="M {mx:.0f} {my:.0f} C {mid:.0f} {my:.0f} {mid:.0f} {ay:.0f} {ax:.0f} {ay:.0f}" '
                 f'fill="none" stroke="#e8590c" stroke-width="1.6" opacity=".85"/>')
    dots.append(f'<circle cx="{mx:.0f}" cy="{my:.0f}" r="12" fill="none" stroke="#e8590c" stroke-width="2.4"/>'
                f'<circle cx="{mx:.0f}" cy="{my:.0f}" r="3.2" fill="#e8590c"/>')
    rs = []
    for f in b['flagged']:
        k = kind(f)
        badge = {'under': '<span class="bg bu">저평가</span>',
                 'urgent': '<span class="bg bq">급매</span>',
                 'err': '<span class="bg be">오류의심</span>'}[k]
        ratio = f'{f["ratio"]:.2f}' if f['ratio'] is not None else '-'
        rs.append(
            f'<tr class="{k}"><td class="fl">{f["floor"]}층</td><td class="py">{f["py"]}평</td>'
            f'<td class="pp">{f["ppp"]:,}</td><td class="pr">{f["price"]:,}</td>'
            f'<td class="rt">{ratio}</td><td class="bd">{badge}</td></tr>')
    rows_html.append(
        f'<div class="box" style="top:{b["by"]:.0f}px;height:{b["h"]:.0f}px">'
        f'<div class="bh">매물 {b["n"]}건 중 <b>{len(b["flagged"])}건</b> 포착</div>'
        f'<table>{"".join(rs)}</table></div>')

nomark = [b for b in data if not b['flagged']]
nodots = ''.join(
    f'<circle cx="{tx(b["x"]):.0f}" cy="{ty(b["y"]):.0f}" r="9" fill="none" stroke="#adb5bd" stroke-width="1.8"/>'
    for b in nomark)

html = f'''<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#fff;font-family:'Malgun Gothic','맑은 고딕',sans-serif}}
.slide{{position:relative;width:1600px;height:900px;background:#fff;overflow:hidden}}
.title{{position:absolute;left:24px;top:16px;font-size:21px;font-weight:800;color:#111}}
.title span{{color:#e8590c}}
.sub{{position:absolute;left:24px;top:43px;font-size:11.5px;color:#666}}
.legend{{position:absolute;right:24px;top:20px;font-size:11px;color:#444;display:flex;gap:14px;align-items:center}}
.legend i{{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:4px;vertical-align:-1px}}
.map{{position:absolute;left:{MX}px;top:{MY}px;width:{MW}px;height:{MH}px;
      border:1px solid #dee2e6;border-radius:5px;object-fit:fill}}
svg.ov{{position:absolute;left:0;top:0;width:1600px;height:900px;pointer-events:none}}
.box{{position:absolute;left:{BOX_L}px;width:{BOX_R-BOX_L}px;background:#fff;
     border:1px solid #ffd8a8;border-left:3px solid #e8590c;border-radius:4px;
     box-shadow:0 1px 4px rgba(0,0,0,.10);padding:4px 7px}}
.bh{{font-size:11px;font-weight:700;color:#8a3d00;margin-bottom:3px;letter-spacing:-.3px}}
.bh b{{color:#e8590c}}
table{{width:100%;border-collapse:collapse}}
td{{font-size:11px;padding:1.5px 0;color:#212529;white-space:nowrap;line-height:1.35}}
.fl{{width:30px;font-weight:700}}
.py{{width:48px;color:#555;text-align:right;padding-right:6px}}
.pp{{width:54px;text-align:right;font-weight:700;color:#1864ab;padding-right:6px}}
.pr{{width:56px;text-align:right;color:#333;padding-right:5px}}
.rt{{width:32px;text-align:right;color:#868e96;font-size:10px;padding-right:4px}}
tr.err .pp{{color:#c92a2a}}
tr.urgent .pp{{color:#333}}
.bg{{display:inline-block;font-size:9px;padding:1px 4px;border-radius:2px;font-weight:700;color:#fff}}
.bu{{background:#1864ab}} .bq{{background:#e8590c}} .be{{background:#c92a2a}}
.foot{{position:absolute;left:24px;bottom:10px;width:1150px;font-size:10px;color:#868e96;line-height:1.5}}
.colhdr{{position:absolute;left:{BOX_L}px;top:{MY-14}px;width:{BOX_R-BOX_L}px;font-size:9.5px;color:#868e96}}
</style></head><body>
<div class="slide" id="slide-1">
  <div class="title">{A.title}</div>
  <div class="sub">{A.sub}</div>
  <div class="legend">
    <span><i style="background:#1864ab"></i>저평가(층 밴드 중앙값의 75% 이하)</span>
    <span><i style="background:#e8590c"></i>급매 문구</span>
    <span><i style="background:#c92a2a"></i>입력오류 의심</span>
    <span><i style="background:#adb5bd"></i>후보 없음</span>
  </div>
  <img class="map" src="data:image/png;base64,{img}">
  <div class="colhdr">층 · 전용평 · <b style="color:#1864ab">평당단가</b> · 매매가 · 밴드比</div>
  <svg class="ov">{''.join(lines)}{nodots}{''.join(dots)}</svg>
  {''.join(rows_html)}
  <div class="foot">
    밴드별 평당단가 중앙값: 1층 7,695 · 2~5층 2,324 · 6층↑ 2,250 · 지하 1,079 (만원/평) &nbsp;|&nbsp;
    밴드比 = 해당 매물 평당단가 ÷ 소속 밴드 중앙값 &nbsp;|&nbsp;
    마커 1개 = 건물 1개(그 건물의 매물 묶음) &nbsp;|&nbsp;
    호가 기준이며 실거래가 아님 — 수익률 판단 시 보정 필요<br>
    지도상 &lsquo;매물 139&rsquo;와 마커 숫자는 <b>중개사 중복등록 포함</b> 수치 —
    박스의 &lsquo;N건&rsquo;은 동일 층·면적·금액 중복을 제거한 실물건 수(전체 139 → 104)
  </div>
</div></body></html>'''

open(OUT + 'slides.html', 'w', encoding='utf-8').write(html)
print('boxes', len(boxes), 'rows', sum(len(b['flagged']) for b in boxes), 'lastY', y)
print(OUT + 'slides.html')
