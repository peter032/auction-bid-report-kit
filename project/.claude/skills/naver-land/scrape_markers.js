// 네이버 부동산 지도 — 마커별 소속 매물 수집
// 사용: $B eval .claude/skills/naver-land/scrape_markers.js
// 결과: window.__mark = [{label, x, y, n, cards[]}], window.__markDone = true
// 전제: 지도가 열려 있고 초록 "매물 N" 버블이 렌더된 상태 (패널은 닫혀 있어도 됨)
//
// ⚠️ 핵심: 마커를 클릭하면 목록 패널이 지도 좌측(x<590)을 덮어 그 아래 마커가 안 잡힌다.
//          그래서 매 클릭 전에 '창닫기'로 패널을 먼저 닫는다. (이 처리 없으면 4/13 실패)
(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  const fireEl = (el, x, y) => {
    const o = {bubbles: true, cancelable: true, clientX: x, clientY: y, view: window, button: 0};
    ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'].forEach(t =>
      el.dispatchEvent(t.startsWith('pointer') ? new PointerEvent(t, o) : new MouseEvent(t, o)));
  };

  const closePanel = async () => {
    const btn = [...document.querySelectorAll('button')]
      .find(e => (e.textContent || '').trim().startsWith('창닫기'));
    if (btn) { const r = btn.getBoundingClientRect(); fireEl(btn, r.x + 5, r.y + 5); await sleep(1200); }
  };

  const readCards = () => [...document.querySelectorAll('li[class*="ArticleCard-module"]')]
    .map(li => (li.textContent || '').replace(/\s+/g, ' ').replace('관심매물', '').trim())
    .filter(t => /(매매|월세|전세)/.test(t) && /\d+층/.test(t));

  // 마커 좌표를 먼저 전부 확보 (패널이 닫힌 상태에서)
  await closePanel();
  const markers = [...document.querySelectorAll('button[class*=BubbleMarker]')].map(e => {
    const r = e.getBoundingClientRect();
    return {label: (e.textContent || '').trim(), x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2)};
  });
  if (!markers.length) return 'NO_MARKERS — 지도 렌더 대기 후 재시도 (보통 3~5초)';

  const res = [];
  for (const m of markers) {
    await closePanel();
    const el = document.elementFromPoint(m.x, m.y);
    if (!el || !/BubbleMarker/.test(String(el.className))) {
      res.push({...m, n: 0, cards: [], err: 'hidden:' + (el ? el.tagName : 'none')});
      continue;
    }
    fireEl(el, m.x, m.y);
    await sleep(2000);
    const cards = readCards();
    res.push({...m, n: cards.length, cards});
  }

  window.__mark = res;
  window.__markDone = true;
  return 'done markers=' + res.length
    + ' cards=' + res.reduce((a, b) => a + b.n, 0)
    + ' failed=' + res.filter(r => r.err).length;
})()
