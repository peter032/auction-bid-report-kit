# -*- coding: utf-8 -*-
import sys, json, io, re, statistics, importlib.util

spec = importlib.util.spec_from_file_location(
    "ps", __import__("os").path.join(__import__("os").path.dirname(__file__), "parse_sale.py"))
ps = importlib.util.module_from_spec(spec); spec.loader.exec_module(ps)

TMP = __import__('os').environ.get('TEMP', '/tmp').replace(chr(92), '/') + '/'
allcards = json.load(open(TMP + 'raw.txt', encoding='utf-8'))
marks = json.load(open(TMP + 'markers.json', encoding='utf-8'))


def band(fl):
    if fl.startswith('B'):
        return 'B'
    try:
        n = int(fl)
    except Exception:
        return '기타'
    if n == 1:
        return '1층'
    if n <= 5:
        return '2~5층'
    return '6층↑'


# 전체 기준선 (중복제거)
rows = [ps.parse(t) for t in allcards]
rows = [r for r in rows if r['price'] and r['ppp']]
ded = []
for r in rows:
    if any(d['floor'] == r['floor'] and d['price'] == r['price']
           and d['py'] is not None and r['py'] is not None and abs(d['py'] - r['py']) <= 0.15 for d in ded):
        continue
    ded.append(r)
med = {}
for b in set(band(r['floor']) for r in ded):
    v = [r['ppp'] for r in ded if band(r['floor']) == b]
    med[b] = statistics.median(v)
print('밴드별 중앙값(만원/평):', {k: int(v) for k, v in sorted(med.items())})

URGENT = re.compile(r'급매|급처|사정상|분양가\s*이하|최저|싸게|급 ')

out = []
for m in marks:
    rs = [ps.parse(t) for t in m['cards']]
    rs = [r for r in rs if r['price'] and r['ppp']]
    # 마커 내부 중복 제거
    u = []
    for r in rs:
        if any(d['floor'] == r['floor'] and d['price'] == r['price']
               and abs((d['py'] or 0) - (r['py'] or 0)) <= 0.15 for d in u):
            continue
        u.append(r)
    flagged = []
    for r in u:
        b = band(r['floor'])
        ratio = r['ppp'] / med[b] if med.get(b) else None
        urg = bool(URGENT.search(r['desc'] or ''))
        if (ratio is not None and ratio <= 0.75) or urg:
            flagged.append({'floor': r['floor'], 'py': round(r['py'], 1), 'ppp': r['ppp'],
                            'price': r['price'], 'ratio': round(ratio, 2) if ratio else None,
                            'urgent': urg, 'desc': r['desc'], 'band': b})
    flagged.sort(key=lambda x: x['ratio'] if x['ratio'] else 9)
    out.append({'label': m['label'], 'x': m['x'], 'y': m['y'], 'n': len(u), 'flagged': flagged})

json.dump(out, open(TMP + 'flagged.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
tot = sum(len(o['flagged']) for o in out)
print('마커', len(out), '| 매물', sum(o['n'] for o in out), '| 후보', tot)
for o in out:
    if o['flagged']:
        print(f"\n■ {o['label']} ({o['n']}건) → 후보 {len(o['flagged'])}")
        for f in o['flagged']:
            tag = '급매' if f['urgent'] else ''
            print(f"   {f['floor']}층 {f['py']}평 {f['ppp']:,}만/평 {f['price']:,}만 "
                  f"(밴드比 {f['ratio']}) {tag} {f['desc'][:34]}")
