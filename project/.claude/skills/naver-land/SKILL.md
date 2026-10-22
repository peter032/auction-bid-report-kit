---
name: naver-land-listings
description: "네이버 부동산(fin.land.naver.com) 지도 URL에서 매물 목록을 자동 추출해 표·엑셀로 정리하는 스킬. headed 브라우저로 봇차단(429) 우회 → 매물마커 클릭 → 가상스크롤 전체 로딩 → 카드 파싱 → 평수·평당단가 계산. 트리거: 네이버 부동산, 네이버부동산, 매물 정리, 매물 목록, 시세조사, land.naver, fin.land, 부동산 매물"
---

# 네이버 부동산 매물 추출 표준 절차

네이버 부동산 지도 URL(`fin.land.naver.com/map?...`)을 받으면 매물 목록을 자동 추출해
`층 | 전용평수 | 임대보증금 | 월임대료 | 평당 월임대 단가 | 매매 금액 | 평당 매매 단가` 표와 엑셀로 정리한다.

> **검증**: 2026-07-06 의왕 오전동 서해그랑블 상가 27건 추출 성공. 이 절차 그대로 재현 가능.

---

## ⚠️ 핵심 노하우 (실패 없이 가려면 반드시 지킬 것)

1. **headed(실제) 브라우저 필수.** 헤드리스로 접근하면 `front-api`가 전부 **429(봇 차단)** 로 즉시 거부된다.
   → `$B connect`로 headed 모드 전환 후 진행.
2. **데스크톱 User-Agent 설정.** 기본 UA면 404 리다이렉트됨.
3. **뷰포트 고정(예 1280x900).** 스크린샷 픽셀과 클릭 좌표를 일치시키기 위함.
4. **"매물 N" 마커는 지도 위 DOM 버튼.** 캔버스가 아니라 `elementFromPoint`로 클릭 가능.
5. **목록은 가상스크롤(ScrollBox).** 끝까지 스크롤해야 전체 카드가 로드됨. `scrape.js`가 처리.
6. **"매물 N"과 추출 카드 수는 다를 수 있음.** 같은 매물을 여러 중개사가 올린 그룹(`중개사 N곳에서 등록`)이 접혀 있어서다. 보고 시 명시.
7. **카드 면적·월세를 그대로 시세로 쓰지 않는다.** 구분임대(공유주방·구분점포)는 카드에 호실 전체 면적 + 한 칸 월세가 섞여 올라온다 → STEP 3-1 상세 확인.
8. **층 파싱은 `B?` 포함.** `B1/20층` 을 `1층` 으로 떨어뜨리면 지하가 1층 단가에 섞여 시세가 2~3배 부풀려진다 (2026-10-02 수정).

---

## 절차 (STEP)

### STEP 0 — 브라우저 준비 (gstack browse)
```bash
_B="$HOME/.claude/skills/gstack/browse/dist/browse"
"$B" status 2>&1                 # 없으면 자동 기동됨
"$B" connect 2>&1                # headed 모드 전환 (429 우회 핵심)
"$B" useragent "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
```
> `$B`는 `~/.claude/skills/gstack/browse/dist/browse` (없으면 gstack 스킬 SETUP 참고).

### STEP 1 — 페이지 열기
```bash
"$B" goto "<네이버 부동산 map URL>"
"$B" wait --networkidle
"$B" viewport 1280x900           # 스크린샷↔클릭 좌표 정렬
"$B" js "document.title"         # 'Npay 부동산' 이면 정상 / '네이버페이'(404)면 UA 재설정
```
- 정상 확인: `network`에 `article/map/articleClusters → 200` 이 찍혀야 함. `429`면 STEP 0의 connect/UA 재확인.

### STEP 2 — 매물 목록 패널 열기 ("매물 N" 마커 클릭)
```bash
"$B" screenshot /tmp/nl.png      # Read 툴로 열어 "매물 N" 초록 버블 위치(픽셀) 확인
```
스크린샷에서 "매물 N" 버블의 픽셀(x,y)을 읽고 아래로 클릭 (좌표만 교체):
```bash
"$B" js "(()=>{const x=639,y=834;const el=document.elementFromPoint(x,y);const o={bubbles:true,cancelable:true,clientX:x,clientY:y,view:window,button:0};el.dispatchEvent(new PointerEvent('pointerdown',o));el.dispatchEvent(new MouseEvent('mousedown',o));el.dispatchEvent(new PointerEvent('pointerup',o));el.dispatchEvent(new MouseEvent('mouseup',o));el.dispatchEvent(new MouseEvent('click',o));return 'clicked '+el.tagName})()"
"$B" screenshot /tmp/nl2.png     # '매물 목록' 패널이 열렸는지 확인
```
- 자동 클릭이 안 되면: `"$B" handoff "매물 N 마커를 클릭해 목록 패널을 열어주세요"` → 사용자 클릭 → `"$B" resume`.

### STEP 3 — 전체 카드 스크롤 추출
```bash
"$B" eval ~/.claude/skills/naver-land/scrape.js        # ScrollBox 끝까지 스크롤+수집 → window.__items 저장
"$B" js "JSON.stringify(window.__meta)"                 # {count: N} 확인
"$B" js "JSON.stringify((window.__items||[]).filter(t=>/(월세|전세|매매)/.test(t)&&/\\d+층/.test(t)))" > /tmp/listings.json
```
> `/tmp` 는 Git Bash에서 `C:\Users\<user>\AppData\Local\Temp` 로 매핑됨. 파이썬은 이 실경로로 접근.

### STEP 3-1 — 매물 상세 확인 ★시세 판단에 쓸 거면 필수

카드 텍스트는 요약이다. **면적·가격의 진짜 단위는 상세에만 있다.**
중개사가 **호실 전체 면적**을 면적란에 적고 **구분임대 한 칸 월세**를 붙이는 사례가 실재한다
(2026-10-02 광진두산위브파크: 카드 "전용 161.96㎡ 월 130만" → 상세 "**실평수 약 10평**·단독공유주방").

```bash
# 1) 카드에서 상세 링크(articleNo) 수집 — 클릭보다 안정적
"$B" js "JSON.stringify([...document.querySelectorAll('li[class*=ArticleCard]')]
  .filter(li=>/(매매|월세)/.test(li.textContent||''))
  .map(li=>({href:li.querySelector('a')?.getAttribute('href'),
             head:(li.textContent||'').replace(/\s+/g,' ').slice(0,70)})))"
# → [{"href":"/articles/2652312912", ...}, ...]

# 2) 상세 순회 (⚠️ 네이버 로그인 필요)
for id in 2652312912 2652177942 ...; do
  "$B" goto "https://fin.land.naver.com/articles/$id"; sleep 2
  "$B" js "document.body.innerText" > "/tmp/details/$id.txt"
done
```

**로그인**: 미로그인 상태로 카드를 클릭하면 `nid.naver.com/nidlogin.login` 으로 리다이렉트된다.
→ `"$B" handoff "네이버 로그인해 주세요"` → 사용자 로그인 → `"$B" resume`
→ **로그인 후 지도 위치·필터가 초기화되므로 원래 map URL 로 다시 `goto`** 한다.

**본문 추출**: `창닫기` ~ `건축물 정보` 구간만 남기면 제목·가격·기본정보·매물소개가 깔끔하다.

**상세에서 꼭 읽을 항목**

| 항목 | 왜 |
|---|---|
| **매물 소개 본문** | "실평수 약 10평", "점포6개 총 월790만" — 면적·가격의 진짜 단위 |
| 현재업종 / 입주가능일 | `공실(빈점포)`·`즉시입주` = 공실 신호 |
| 관리비 | 호실당 관리비 × 실수 = 월 관리비 (경매 체납관리비 추정의 분모) |
| 권리금 / 융자금 | `무권리`·`렌트프리`는 공실 유인책 = 수요 약세 |

**모순 탐지 (조기 경보)**
- 면적이 몇 배 차이나는 매물이 **같은 월세** → 하나는 구분임대 한 칸
- 매매 호가 대비 월세 수익률이 1~2%로 비현실적 → 월세 쪽이 한 칸 가격
- 상세 "실평수" ≠ 카드 "전용면적" → **상세를 믿는다**

### STEP 4 — 파싱 → 표 + 엑셀
```bash
python ~/.claude/skills/naver-land/parse_listings.py \
  "%TEMP%/listings.json" \
  "<출력.xlsx 경로>" \
  --title "<보고서 제목>"
```
- stdout에 마크다운 표가 출력됨(그대로 사용자에게 제시).
- 지정 경로에 `.xlsx` 생성(헤더고정·천단위서식).

---

## 파싱 규칙 (parse_listings.py 내장)
- **전용평수** = 전용㎡ ÷ 3.305785
- **평당 월임대 단가** = 월세 ÷ 전용평 (만원/평)
- **평당 매매 단가** = 매매금액 ÷ 전용평 (만원/평)
- 층: `해당층/총층층` → **해당층**만 표기 (예 `1/2층`→1층)
- 금액 단위: **만원**. 매매 `X억 Y` → (X·10000 + Y) 만원. 범위(`~`)는 원문 유지·평당 생략.
- 유형(복합상가/단지내상가/사무실 등)·중개사그룹(`중개사 N곳`)은 비고로.

---

## 출력 형식 (사용자에게 보고)
1. **한 줄 요약** (단지/위치, 총 N건, "매물 N"과 카드수 차이 사유)
2. 마크다운 표 (요청 컬럼 순서)
3. 요약 통계 (월세 평당 레인지, 매매 평당 레인지, 최고/최저)
4. 엑셀 저장 경로

## 관련
- 상가 경매/투자 분석으로 이어지면 → 부가남 프로토콜 로드
  (`output/education/expert-kb/buganam/persona.md` + `분석체크리스트.md`)
