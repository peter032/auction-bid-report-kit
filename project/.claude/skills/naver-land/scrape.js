// 네이버 부동산 매물 목록 전체 스크롤 추출
// 사용: $B eval ~/.claude/skills/naver-land/scrape.js
// 결과: window.__items (카드 원문 텍스트 배열), window.__meta ({count, container})
//        반환값 "done count=N"
// 전제: STEP 2에서 '매물 목록' 패널이 열려 있어야 함 (ArticleCard 존재).
(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  // 1) 스크롤 컨테이너 탐색: 카드의 가장 가까운 스크롤 가능 조상
  let card = document.querySelector('li[class*="ArticleCard-module"]');
  if (!card) return "NO_CARDS — 매물 목록 패널이 열려있는지 확인 (STEP 2)";
  let sc = card;
  while (sc && sc !== document.body) {
    const s = getComputedStyle(sc);
    if ((s.overflowY === 'auto' || s.overflowY === 'scroll') && sc.scrollHeight > sc.clientHeight + 20) break;
    sc = sc.parentElement;
  }
  if (!sc || sc === document.body) {
    sc = [...document.querySelectorAll('div,ul')].find(e => {
      const s = getComputedStyle(e);
      return (s.overflowY === 'auto' || s.overflowY === 'scroll')
        && e.scrollHeight > e.clientHeight + 50
        && e.querySelector('li[class*="ArticleCard"]');
    });
  }

  // 2) 카드 수집 (서명으로 중복 제거)
  const seen = new Map();
  const collect = () => {
    document.querySelectorAll('li[class*="ArticleCard-module"]').forEach(li => {
      const t = (li.textContent || '').replace(/\s+/g, ' ').replace('관심매물', '').trim();
      // 실제 매물 카드만: 가격 + 층 패턴 보유
      if (!/(월세|전세|매매)/.test(t)) return;
      if (!/\d+층/.test(t)) return;
      const key = t.slice(0, 90); // 가격+면적+층 서명
      if (!seen.has(key)) seen.set(key, t);
    });
  };
  collect();

  // 3) 끝까지 스크롤
  if (sc) {
    let last = -1, stable = 0;
    for (let i = 0; i < 100; i++) {
      sc.scrollTop = sc.scrollTop + Math.max(300, sc.clientHeight * 0.8);
      await sleep(320);
      collect();
      if (Math.abs(sc.scrollTop - last) < 2) { stable++; if (stable >= 4) break; }
      else stable = 0;
      last = sc.scrollTop;
    }
  }

  window.__items = [...seen.values()];
  window.__meta = { count: seen.size, container: sc ? (sc.className || '').toString().slice(0, 40) : 'NONE' };
  return "done count=" + seen.size;
})()
