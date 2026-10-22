# 네이버부동산 매물조사 SOP (Standard Operating Procedure)

> 네이버 부동산 지도 URL 1개 → 해당 반경 전체 매물 추출 → 평수·평당단가 환산 → 중복 제거 → 엑셀 산출(A), 필요 시 저평가·급매 지도 PPTX(B)까지의 표준 절차서
> 적용 대상: 상가·사무실·아파트 등 네이버부동산(`fin.land.naver.com/map`) 매물 시세조사
> 도구 베이스: gstack browse (headed) + naver-land 스킬
> 검증 사례
> - 2026-07-06 의왕 오전동 서해그랑블 상가 **월세** 27건 (parse_listings.py)
> - 2026-09-12 성남 분당 수내동 상가·사무실 **매매** 139건 → 중복제거 107건 (parse_sale.py)
> - 2026-09-12 성남 분당 수내동 **저평가·급매 지도 PPTX** — 마커 13개 × 매물 104건 → 후보 18건 1장 (파이프라인 B)

---

## 0. 핵심 원칙

```
A) headed 브라우저 → 매물마커 클릭 → 가상스크롤 전량 로딩 → 카드 원문 파싱 → 중복 제거 → 엑셀
B) 마커별 매물 매핑 → 층 밴드 대비 저평가·급매 판정 → 지도 캡처+지시선 → PPTX
```

**절대 규칙**:
1. **headless 금지** — 헤드리스로 붙으면 `front-api`가 전부 **429(봇 차단)**. 반드시 `connect`로 headed 전환.
2. **호가는 호가다** — 추출값은 전부 중개사 호가. 실거래가 아니며 수익률 판단 시 보정 필요.
3. **"매물 N" ≠ 카드 수 ≠ 실제 물건 수** — 3단계 차이가 난다. 보고 시 반드시 명시.
   - 네이버 "매물 N" 표기: 중개사별 등록 건 합계
   - 추출 카드 수: 그룹 접힘 반영 후
   - 중복 제거 후: 같은 물건을 여러 중개사가 올린 건 통합
4. **값을 지어내지 않는다** — 카드에 없는 임차정보·연식은 공란 처리. 상세페이지를 열지 않았으면 "미확인"이라고 쓴다.
5. **이상치는 지우지 말고 표시한다** — 평당단가가 튀는 건 네이버 입력오류일 수 있으니 삭제 말고 플래그.
6. **시세 판단에 쓸 매물은 상세를 연다** — 카드 면적란에 **호실 전체 면적**을 적고 **구분임대 한 칸 월세**를 붙이는 사례가 있다. 2026-10-02 광진두산위브파크: 카드 "전용 161.96㎡ 월 130만" → 상세 "**실평수 약 10평**·단독공유주방". 이 오독으로 경매 입찰보고서 기준선이 월 125만(X)으로 잡혀 결론이 뒤집혔다(정정 210만). → STEP 4-1

---

## 1. 도구·자산 맵

| 도구/자산 | 위치 | 역할 |
|---|---|---|
| gstack browse | `~/.claude/skills/gstack/browse/dist/browse` | headed 브라우저 (429 우회 필수) |
| naver-land 스킬 | `.claude/skills/naver-land/SKILL.md` | 절차 정의 |
| 스크롤 수집 | `.claude/skills/naver-land/scrape.js` | 가상스크롤 끝까지 → `window.__items` |
| **월세/임대 파서** | `.claude/skills/naver-land/parse_listings.py` | 보증금·월세·평당 월임대단가 표 + 엑셀 |
| **매매 파서** | `.claude/skills/naver-land/parse_sale.py` | 매매가·평당 매매단가·임차내용·중복제거 표 + 엑셀 |
| 마커 수집 | `.claude/skills/naver-land/scrape_markers.js` | 마커별 소속 매물 수집 (패널 자동 닫기 내장) |
| 후보 판정 | `.claude/skills/naver-land/flag_candidates.py` | 층 밴드 중앙값 대비 저평가·급매·오류 플래그 |
| 지도 슬라이드 | `.claude/skills/naver-land/build_map_slide.py` | 지도 캡처 + 지시선 + 콜아웃 HTML 생성 |
| html-slides 스킬 | `~/.claude/skills/html-slides/scripts/capture_and_build.py` | HTML → 캡처 → PPTX (SPACE 검수 필수) |

**출력 위치 규칙**:
- 시세조사 산출물: `output/finance/상가투자/{동네}_{거래유형}매물_{YYYYMMDD}.xlsx` (+ 동명 `.md`)
- 경매 입찰검토 연계 시: `output/finance/상가투자/검색/네이버매물_{동네}_{날짜}.xlsx`
- 지도 슬라이드: `output/finance/상가투자/{동네}_저평가지도/` (slides.html + slide_images/ + PPTX)

---

## 2. URL 파라미터 해독 (선택 조건 확인용)

```
https://fin.land.naver.com/map?center={좌표코드}&zoom=16&realEstateTypes=D02-D01&tradeTypes=A1
```

| 파라미터 | 값 | 의미 |
|---|---|---|
| `tradeTypes` | `A1` / `B1` / `B2` | 매매 / 전세 / 월세 |
| `realEstateTypes` | `D02`, `D01` | 상가, 사무실 (하이픈으로 다중선택) |
| `zoom` | 16 | 값이 작을수록 넓은 범위 = 매물 多 (수집시간 ↑) |

⚠️ **먼저 URL을 읽고 거래유형을 확정할 것.** 매매면 `parse_sale.py`, 월세/전세면 `parse_listings.py`.

---

## 3. 파이프라인 A — 표·엑셀 (5단계)

### STEP 1. 브라우저 준비 (headed 전환)

```bash
B="$HOME/.claude/skills/gstack/browse/dist/browse"
"$B" status                       # Mode 확인
"$B" connect                      # → Mode: headed 로 바뀌어야 함
"$B" useragent "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
```

**게이트**: `"$B" status`의 `Mode:` 가 반드시 **`headed`** 여야 다음 단계로 간다. `launched`면 아직 봇차단 상태다.

#### ⚠️ 함정 — connect 실패 3종 (2026-09-12 실측)

| 증상 | 원인 | 처치 |
|---|---|---|
| `Connect failed: Server failed to start within 15s` | 기동이 느린 것뿐, 실제로는 성공한 경우 多 | **에러 무시하고 `status` 재확인**. headed면 진행 |
| `Cannot recreate context in headed mode. Use disconnect first.` | 이미 headed 상태 | 정상. 그대로 진행 (useragent만 재설정) |
| `Port 34567 (from BROWSE_PORT env) is in use` | 죽은 서버가 포트 점유 | `netstat -ano \| grep "34567.*LISTENING"` → `taskkill //PID {PID} //F` → 재 `connect` |

> `useragent`가 "Cannot recreate context"로 거부되면, `goto` 후 `document.title`이 `Npay 부동산...`인지로 대체 검증한다.

---

### STEP 2. 페이지 열기 + 차단 여부 검증

```bash
"$B" goto "<네이버 부동산 map URL>"
"$B" wait --networkidle
"$B" viewport 1280x900
"$B" js "document.title"
"$B" network | grep -E "articleClusters|boundedArticlesCount"
```

**게이트 (2개 모두 통과해야 함)**:
- `document.title` = `Npay 부동산 매물지도: ...` → 정상 / `네이버페이` = 404 리다이렉트(UA 재설정)
- `article/map/articleClusters` → **200** → 정상 / **429** = 봇차단 (STEP 1로 복귀)

> 429 상태에서도 지도·단지마커는 그려진다. **지도가 보인다고 통과로 착각하지 말 것.** 반드시 network 상태코드로 판정.

---

### STEP 3. 매물 목록 패널 열기

```bash
"$B" screenshot /tmp/nl.png        # Read 툴로 열어 초록색 "매물 N" 버블 픽셀좌표 확인
```

좌표(x, y)를 넣어 클릭:

```bash
"$B" js "(()=>{const x=639,y=834;const el=document.elementFromPoint(x,y);const o={bubbles:true,cancelable:true,clientX:x,clientY:y,view:window,button:0};el.dispatchEvent(new PointerEvent('pointerdown',o));el.dispatchEvent(new MouseEvent('mousedown',o));el.dispatchEvent(new PointerEvent('pointerup',o));el.dispatchEvent(new MouseEvent('mouseup',o));el.dispatchEvent(new MouseEvent('click',o));return 'clicked '+el.tagName})()"
"$B" screenshot /tmp/nl2.png       # '매물 목록' 패널 열림 확인
```

- "매물 N" 버블은 캔버스가 아닌 **DOM 버튼**이라 `elementFromPoint`로 잡힌다.
- 반환값이 `clicked BUTTON 매물...` 이면 성공.
- 실패 시: `"$B" handoff "매물 N 마커를 클릭해 목록 패널을 열어주세요"` → 사용자가 직접 클릭 → `"$B" resume`

---

### STEP 4. 전량 수집 (가상스크롤)

```bash
"$B" eval .claude/skills/naver-land/scrape.js     # 프로젝트 루트에서 상대경로로
"$B" js "JSON.stringify(window.__meta)"           # {count: N} — 화면 '매물 N'과 대조
"$B" js "JSON.stringify(window.__items)" > /tmp/raw.txt
```

**게이트**: `__meta.count`가 화면의 "매물 N"과 **같거나 근소하게 적어야** 정상. 절반 이하면 스크롤이 덜 된 것이니 `eval` 재실행.

#### ⚠️ 함정
- `eval`은 최대 ~32초 걸리며 **stdout이 비어도 실패가 아니다**. 반드시 `window.__meta`로 결과를 확인한다.
- `$B eval`에 `~/...` 경로를 주면 실패. **프로젝트 상대경로 또는 절대경로** 사용.
- `/tmp` = `C:\Users\{user}\AppData\Local\Temp`. 파이썬에는 실경로로 넘긴다.
- 카드 본문은 CSS로만 말줄임 처리되므로 **`textContent`에는 카드 설명 전문이 들어있다**.
- ⚠️ **그러나 카드 설명 ≠ 매물 상세.** 면적·가격의 단위(통임대인지 구분임대 한 칸인지), 현재업종·관리비·권리금은 **상세에만 있다**.
  시세 판단에 쓸 매물은 **STEP 4-1 로 상세를 연다.** (구 SOP의 '상세페이지 진입 불필요'는 2026-10-02 오독 사고로 폐기)

---

### STEP 4-1. 매물 상세 확인 ★시세 판단용이면 필수

```bash
# 1) 카드에서 상세 링크(articleNo) 수집 — 클릭보다 안정적 (클릭은 페이지 이동으로 JS 상태가 날아간다)
"$B" js "JSON.stringify([...document.querySelectorAll('li[class*=ArticleCard]')]
  .filter(li=>/(매매|월세)/.test(li.textContent||''))
  .map(li=>({href:li.querySelector('a')?.getAttribute('href'),
             head:(li.textContent||'').replace(/\s+/g,' ').slice(0,70)})))"
# → [{"href":"/articles/2652312912", ...}, ...]   ※ 중개사 그룹 카드는 href 가 null → 펼친 뒤 재수집

# 2) 상세 순회
for id in 2652312912 2652177942 ...; do
  "$B" goto "https://fin.land.naver.com/articles/$id"; sleep 2
  "$B" js "document.body.innerText" > "/tmp/details/$id.txt"
done
```

#### ⚠️ 함정 — 네이버 로그인 필요
- 미로그인 상태로 카드를 클릭/상세 진입하면 `nid.naver.com/nidlogin.login?...&realname=Y` 로 **리다이렉트**된다.
- 해결: `"$B" handoff "네이버 로그인해 주세요"` → 사용자 로그인 → `"$B" resume`
- **로그인 후 지도 중심·필터가 초기화**되므로 반드시 **원래 map URL 로 다시 `goto`** 하고 목록 패널을 다시 연다.
- `connect` 가 "Server failed to start within 15s" 를 뱉어도 실제로는 headed 로 붙어 있을 수 있다 → `document.title` 이 `Npay 부동산…` 이면 정상.

#### 본문 추출
`창닫기` ~ `건축물 정보` 구간만 남기면 제목·가격·기본정보·매물소개가 깔끔하다.

#### 상세에서 반드시 읽을 항목

| 항목 | 왜 |
|---|---|
| **매물 소개 본문** | "실평수 약 10평", "점포6개 총보증금5400만원 월790만원", "공유주방 6실 구분임대" — **면적·가격의 진짜 단위** |
| 현재업종 / 입주가능일 | `공실(빈점포)` · `즉시입주` = 공실 신호 |
| 관리비 | 호실당 관리비 × 실수 = 월 관리비 (경매 체납관리비 추정의 분모) |
| 권리금 / 융자금 | `무권리` · `렌트프리`는 공실 유인책 = 수요 약세 |
| 전용률 | 계약면적 대비 30%대면 단지내상가 공용 과다 |

#### 모순 탐지 — 이게 조기 경보다
- 면적이 몇 배 차이나는 매물이 **같은 월세** → 하나는 구분임대 한 칸이다
- 매매 호가 대비 월세 수익률이 1~2%로 비현실적 → **월세 쪽이 한 칸 가격**일 가능성
- 상세 "실평수" ≠ 카드 "전용면적" → **상세를 믿는다**

#### 구분임대(공유주방·구분점포) 처리
- 실제 수익 = 한 칸 가격 × 실수 (예: 보증 900/월 130 × 6실 = 보증 5,400만 / 월 780만)
- **통임대 비교군과 섞지 않는다.** 경매 보고서는 `case.yaml` `comps.exclude_contains` 로 제외
- 설비가 없는 물건이면 전환비·기존 운영자와의 경쟁을 가격에 넣지 않는다 (명도 후 옵션)

---

### STEP 5. 파싱 → 표 + 엑셀

**매매 (tradeTypes=A1)**
```bash
python .claude/skills/naver-land/parse_sale.py \
  "%TEMP%/raw.txt" \
  "output/finance/상가투자/{동네}_매매매물_{YYYYMMDD}.xlsx" \
  --title "{지역} 상가·사무실 매매 매물 ({날짜} 기준, 네이버부동산)" \
  > "output/finance/상가투자/{동네}_매매매물_{YYYYMMDD}.md"
```

**월세·전세 (tradeTypes=B1/B2)**
```bash
python .claude/skills/naver-land/parse_listings.py \
  "%TEMP%/raw.txt" \
  "output/finance/상가투자/{동네}_임대매물_{YYYYMMDD}.xlsx" \
  --title "..."
```

---

## 3-B. 파이프라인 B — 저평가·급매 지도 PPTX (선택, 4단계)

> 파이프라인 A 완료 후 진행. "어디가 싼지 지도로 보고 싶다" / "급매 찾아줘" 요청 시.
> 검증 사례: 2026-09-12 수내동 — 마커 13개 · 매물 104건 → 후보 18건 → 1장 PPTX

### 왜 되는가 (핵심 발견)

초록색 "매물 N" 버블은 **canvas가 아니라 DOM 버튼**(`button[class*=BubbleMarker]`)이다.
→ `getBoundingClientRect()`로 화면 픽셀 좌표를 정확히 읽을 수 있고, 지시선을 눈대중이 아니라 좌표로 꽂는다.

⚠️ **지도의 회색 원 ①②③④는 매물이 아니라 지하철 출구 번호**다(canvas 렌더링). 매물은 초록 버블만.
⚠️ **마커 1개 = 건물 1개**다. 네이버는 개별 매물 핀을 제공하지 않으므로 콜아웃은 건물 단위로 묶인다.

### STEP B1. 마커별 매물 수집

```bash
"$B" eval .claude/skills/naver-land/scrape_markers.js
# 완료 대기 (마커수 × 약 3.2초)
"$B" js "String(window.__markDone)"          # true 될 때까지 폴링
"$B" js "JSON.stringify(window.__mark.map(m=>({l:m.label,n:m.n,e:m.err})))"
"$B" js "JSON.stringify(window.__mark)" > /tmp/markers.json
```

**게이트**: 반환 문자열의 `failed=0` 확인. 1 이상이면 해당 마커만 수동 재시도(아래 함정 참조).

#### ⚠️ 함정 — 패널이 마커를 가린다 (13개 중 4개 실패했던 원인)
마커를 클릭하면 목록 패널이 지도 좌측(**x < 590**)을 덮어, 그 아래 마커는 `elementFromPoint`가 `ScrollBox`/`DIV`를 반환한다.
→ `scrape_markers.js`는 **매 클릭 전에 '창닫기' 버튼을 눌러 패널을 닫도록** 내장돼 있다. 직접 스크립트를 쓸 땐 반드시 이 처리를 넣을 것.
→ 그래도 남으면: 패널 닫기 → `sleep 3` → 해당 좌표만 단건 클릭.

#### ⚠️ 함정 — 마커 내 가상스크롤
매물이 많은 마커(예 35건)는 패널을 스크롤하지 않으면 **일부만 잡힌다**(실측 35 → 30). 보고 시 미확인 건수를 명시할 것.

### STEP B2. 지도 캡처 + 크롭

```bash
"$B" js "...창닫기 클릭..."                    # 패널 닫고 깨끗한 지도 확보
"$B" js "...마커 좌표 재열거..."                # 수집 때 좌표와 동일한지 대조 ★필수
"$B" screenshot /tmp/map_clean.png
python -c "from PIL import Image; Image.open(r'%TEMP%/map_clean.png').crop((140,57,1213,900)).save(r'%TEMP%/map_crop.png')"
```

- 크롭 `(140, 57, 1213, 900)` = 좌측 사이드바·상단 네비·우측 툴바 제거. **이 값을 바꾸면 `build_map_slide.py`의 `CROP_X, CROP_Y`도 같이 바꿔야 한다.**
- **게이트**: 캡처 직전 마커 좌표가 수집 때와 같아야 지시선이 맞는다. 다르면 지도가 이동한 것이니 재수집.

### STEP B3. 후보 판정

```bash
PYTHONIOENCODING=utf-8 python .claude/skills/naver-land/flag_candidates.py
```

| 태그 | 기준 | 색 |
|---|---|---|
| **저평가** | 평당단가 ≤ 소속 층 밴드 중앙값 × 0.75 | 파랑 |
| **급매** | 설명에 `급매·급처·사정상·분양가이하·최저·싸게` | 주황 |
| **오류의심** | 밴드比 < 0.15 | 빨강 |

- 층 밴드: `1층` / `2~5층` / `6층↑` / `지하`. 1층은 상층부의 3배 수준이라 **전체 중앙값 하나로 판정하면 안 된다.**
- **오류의심을 저평가와 섞지 말 것.** 네이버 입력오류(예 66㎡ 1층 5,500만)가 최저가를 차지해 판단을 망친다.
- 급매 문구인데 밴드比 1.0 초과인 건이 흔하다 → 문구와 단가를 **한 줄에 같이** 보여줘야 걸러진다.

### STEP B4. 슬라이드 생성 → PPTX

```bash
python .claude/skills/naver-land/build_map_slide.py "output/finance/상가투자/{동네}_저평가지도" \
  --title "{지역} 상가·사무실 매매 — 저평가 · 급매 후보 지도" \
  --sub "네이버부동산 {날짜} 기준 · 매물 N건(중복제거) · 금액 단위 만원 · 평당단가는 전용면적 기준"

cd "output/finance/상가투자/{동네}_저평가지도"
python ~/.claude/skills/html-slides/scripts/capture_and_build.py slides.html {파일명}.pptx --width 1600 --height 900
```

- 슬라이드 1600×900. 지도 좌측, 콜아웃 우측 컬럼(x 1210~1576), 베지어 지시선으로 연결.
- 콜아웃 행 = `층 · 전용평 · 평당단가 · 매매가 · 밴드比 · 태그`. **평균은 넣지 않는다**(개별 매물을 보는 게 목적).
- 후보 없는 마커는 회색 원으로만 표기 → 화면이 깔끔해진다.

#### ⚠️ 함정 — PPTX 파일이 열려 있으면 `PermissionError`
PowerPoint에서 연 채로 재생성하면 쓰기가 막힌다. 닫고 재실행하거나 다른 파일명으로 출력.

### STEP B5. 시각 검수 (html-slides SPACE 기준) — 필수

캡처 이미지를 **Read로 직접 열어** 확인한다. 실측에서 걸린 불합격 3건:

| 증상 | 원인 | 처치 |
|---|---|---|
| 하단 각주 잘림 | 지도 높이 + 각주가 900px 초과 | `MH` 축소 (806 → 772) |
| 화면 25%가 네이버 UI | 크롭 안 함 | STEP B2 크롭 적용 |
| 각주가 지도와 겹침 | 지도 하단과 각주 간격 부족 | `MH` 추가 축소 + `bottom` 조정 |

#### ⚠️ 숫자 3개가 달라 보이는 문제 (반드시 각주로 해소)
같은 슬라이드에 **지도 "매물 139" / 제목 "104건" / 박스 "22건 중"** 이 동시에 뜬다. 각각 중복제거 단계가 달라서다.
→ 각주에 "지도 숫자는 중개사 중복등록 포함, 박스 N건은 중복 제거 후 실물건 수" 를 반드시 명기한다.

---

## 4. 계산·정규화 규칙

| 항목 | 규칙 |
|---|---|
| **전용평수** | 전용㎡ ÷ 3.305785 (계약면적 아님 — **반드시 전용 기준**) |
| **평당 매매단가** | 매매가(만원) ÷ 전용평 |
| **평당 월임대단가** | 월세(만원) ÷ 전용평 |
| **층** | `해당층/총층층` → 해당층만. `B1`(지하), `고/중/저` 표기도 수용 |
| **금액 단위** | 만원. `X억 Y` → (X×10,000 + Y). 범위(`~`)는 원문 유지·평당 생략 |
| **임차 관련 내용** | 설명문에서 `보증금/월세` 패턴, `월세 N`, `수익률 N%`, 키워드(`세입자`·`임차인`·`임대중`·`성업`·`공실`·`명도`·`실입주`) 추출 |

### 중복 제거 기준 (매매 파서)

```
같은 층 + 같은 매매가 + 전용평수 차이 0.15평 이내 → 동일 매물 1건으로 통합
```

- **완전일치로는 안 걸러진다.** 네이버가 중개사별로 면적 반올림을 달리해 `28.70평` / `28.72평` 처럼 미세하게 어긋난다. (수내동 실측: 완전일치 118건 → 허용오차 적용 107건)
- 통합된 건수는 `중복등록` 컬럼에 남긴다 — 중개사가 많이 올린 물건 = 오래 안 팔린 물건의 힌트.
- 통합 시 **임차정보·설명이 비어있는 쪽에 채워 넣는다** (정보 손실 방지).

---

## 5. 보고 형식

1. **한 줄 결론** — 지역/거래유형, `원본 N건 → 중복제거 M건`
2. **파일 링크** — xlsx + md
3. **층별 평당단가 테이블** (건수 / 최저 / 중앙값 / 최고) ← 전체 107행을 채팅에 붙이지 말 것
4. **임차 내용 커버리지** — "설명에 임차정보 표기 N건 / 미표기 M건(상세페이지 확인 필요)"
5. **⚠️ 이상치 플래그** — 평당단가 상·하위 이탈 건은 원문과 대조해 "입력오류 의심" 명기

---

## 6. 완료 전 체크리스트

- [ ] `articleClusters` 200 확인 (429 아님)
- [ ] `__meta.count`와 화면 "매물 N" 대조
- [ ] 엑셀 행 수 = 표 건수 (`load_workbook`으로 `max_row` 확인)
- [ ] 평당단가 최저·최고 2건 원문 역추적 → 파싱오류 vs 실제 이상치 판정
- [ ] 층 파싱 누락 없음 (빈 층 값 0건)
- [ ] 산출물 2종(xlsx/md) 지정 경로에 존재

**지도 PPTX까지 만든 경우 추가**
- [ ] `scrape_markers.js` 반환값 `failed=0`
- [ ] 캡처 직전 마커 좌표 = 수집 때 좌표 (지시선 정확도 근거)
- [ ] 크롭 좌표와 `CROP_X/CROP_Y` 일치
- [ ] 캡처 이미지를 Read로 열어 SPACE 5항목 육안 검수
- [ ] 각주에 중복제거 단계 차이 명기
- [ ] 마커 내 가상스크롤 누락 건수 보고에 포함

> ⚠️ 콘솔에 한글이 깨져 보이는 건 Windows 터미널 인코딩 문제일 뿐 데이터 손상이 아니다. `openpyxl`로 되읽어 검증한다.

---

## 7. 후속 연계

| 목적 | 다음 절차 |
|---|---|
| 경매 입찰 검토 | `상가경매_입찰보고서_SOP.md` STEP 3(시세 실측)에 본 엑셀 투입 |
| 부가남식 분석 | `output/education/expert-kb/buganam/persona.md` + `분석체크리스트.md` 로드 |
| 수익률 역산 | 호가 수익률에 **+0.5~1.0%p 보정** 후 `(월세×12) ÷ 요구수익률 + 보증금` |

---

*최종 갱신: 2026-09-12 (수내동 매매 139건 + 저평가·급매 지도 PPTX 케이스 반영)*
