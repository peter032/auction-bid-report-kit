# 상가경매 입찰보고서 키트

Claude Code에게 **옥션원 경매 물건 URL + 네이버부동산 지도 URL**을 주면, 물건 수집 → 시세 조사 → 수익 시나리오 → 입찰 상한 계산까지 해서 **입찰보고서 PPTX(13~14장)와 계산표**를 만들어 주는 스킬 묶음입니다.

> 대상: Windows PC에서 Claude Code를 쓰는 개인 투자자
> 결과물 예: 물건 개요 · 옥션원 원문 캡처 · 현황 사진 · 권리분석 · 시세 비교군 · 매물 지도 · 수요 · 시나리오별 배수 · 입찰 상한 · 리스크 · 실행 계획

---

## 0. 준비물

| 항목 | 필요한 이유 | 비용 |
|---|---|---|
| Windows 10/11 | 설치 스크립트·PowerPoint 검수가 Windows 기준 | — |
| [Claude Code](https://claude.com/claude-code) | 스킬을 실행하는 주체 | Claude 구독 |
| Python 3.10 이상 | 수집·계산·PPTX 생성 | 무료 |
| Git | gstack 설치 | 무료 |
| **옥션원 유료 회원 계정** | 물건 상세·사진·감정평가서 수집 | 유료 |
| 네이버 계정 | 네이버부동산 매물 상세 열람 | 무료 |
| 공공데이터포털 인증키 | 입지등급(배후세대·상가 밀도) | 무료 (활용신청) |
| VWorld 개발키 | 주소 → 좌표 | 무료 |
| PowerPoint (선택) | 완성된 슬라이드를 PNG로 내보내 검수 | — |

## 1. 설치

1. 이 폴더(`auction-bid-report-kit`)를 원하는 곳에 압축 해제합니다.
2. `install.bat`을 더블클릭하고, 보고서 작업을 할 **프로젝트 폴더 경로**를 입력합니다 (없으면 새로 만듭니다. 예: `C:\auction`).
   - 또는 PowerShell에서: `powershell -ExecutionPolicy Bypass -File install.ps1 -Target "C:\auction"`
3. 스크립트가 자동으로 하는 일
   - 프로젝트 폴더에 스킬·코드·SOP 복사
   - `.env` 파일 생성 (이미 있으면 건드리지 않음)
   - Python 패키지 설치 (`requirements.txt`)
   - Playwright 브라우저(Chromium) 설치
   - 테스트 실행 → `NN passed`가 나오면 설치 성공

설치 후 프로젝트 폴더 구조:

```
C:\auction\
├─ .env                                   ← 계정·키 (직접 입력)
├─ .claude\skills\auction-bid-report\     ← 입찰보고서 스킬
├─ .claude\skills\naver-land\             ← 네이버부동산 수집 스킬
├─ docs\업무절차서(SOP)\                  ← 상세 절차서 2종
└─ scripts\auction\
   ├─ bid_report\                         ← 게이트·수집·비교군·시나리오·PPTX 생성
   ├─ auction1\                           ← 옥션원 로그인·파싱·입지등급
   └─ tests\                              ← 설치 검증 테스트
```

## 2. gstack 설치 (네이버부동산 수집용 브라우저)

네이버부동산은 일반 자동화 브라우저를 차단(429)합니다. 실제 화면이 뜨는(headed) 브라우저를 Claude가 조종하도록 **gstack**의 browse 기능을 씁니다.

Git Bash에서:

```bash
git clone --single-branch --depth 1 https://github.com/garrytan/gstack.git ~/.claude/skills/gstack
cd ~/.claude/skills/gstack && ./setup
```

설치 확인: `~/.claude/skills/gstack/browse/dist/browse status`

## 3. 계정·API 키 입력

프로젝트 폴더의 `.env`를 메모장으로 열어 채웁니다.

| 키 | 얻는 곳 |
|---|---|
| `auction1_ID` / `auction1_PASSWORD` | 옥션원 로그인 계정 |
| `DATA_GO_KR_KEY` | [공공데이터포털](https://www.data.go.kr) → 아래 3개 API **각각 활용신청** → 마이페이지의 **일반 인증키(Encoding)** |
| `vworld_KEY` | [VWorld 오픈API](https://www.vworld.kr/dev/v4dv_2ddataguide2_s001.do) → 인증키 발급(개발키로 충분) |

공공데이터포털 활용신청 3건 (같은 키 하나로 열립니다):
- 소상공인시장진흥공단_상가(상권)정보
- 국토교통부_공동주택 단지 목록제공 서비스
- 국토교통부_공동주택 기본 정보제공 서비스

> ⚠ `.env`에는 비밀번호가 들어갑니다. 다른 사람에게 보내거나 Git에 올리지 마세요.

## 4. 사용법

Claude Code를 **프로젝트 폴더에서** 열고 이렇게 요청합니다.

```
입찰보고서 작성해줘
https://www.auction1.co.kr/auction/ca_view.php?product_id=XXXXXXX
https://fin.land.naver.com/map?...(거래유형·물건종류·층 필터를 걸어 둔 지도 URL)
```

- **필수 입력 2가지**: 옥션원 물건 URL(또는 사건번호 + 관할법원), 네이버부동산 지도 URL
- 그 외(취득 명의, 중개사 청취 시세, 현장 임장 결과, 대출 조건)는 없으면 기본값으로 진행하고 보고서에 **'가정'**으로 표시합니다
- 네이버 매물 상세를 열 때 로그인 창이 뜨면 직접 로그인해 주면 됩니다

진행 순서 (스킬이 알아서 수행):

```
입력 확인 → 옥션원 수집(상세·사진·캡처) → 권리·임차인 분석 → 네이버 시세 실측(매물 상세까지)
→ 지도 매핑 → 입지등급 → 취득세 원문 확인 → 시나리오·입찰 상한 계산 → PPTX 생성 → 슬라이드 전수 검수
```

결과물 위치: `output\finance\상가투자\매물검토\{사건번호}_{동}_{건물}\`

| 파일 | 내용 |
|---|---|
| `(입찰보고서)….pptx` | 슬라이드 13~14장 (편집 가능한 네이티브 도형·표) |
| `report_tables.md` | 자동 계산표 + 가정 항목 |
| `case.yaml` | 보고서의 모든 입력·문장 — 고친 뒤 다시 빌드하면 PPTX가 갱신됨 |
| `raw\` · `images\` | 원자료·사진 |

수정 후 다시 만들기:

```
cd scripts\auction
python -X utf8 -m bid_report.build_report "<보고서폴더>\case.yaml"
```

## 5. 기본 가정값

| 항목 | 기본값 | 바꾸는 곳 |
|---|---|---|
| 요구수익률 | **6%** (민감도 5.5~6.5% 자동) | `case.yaml` → `assumptions.요구수익률` |
| 취득 명의 | 법인 (설립 5년 이내) | `case.yaml` → `buyer` |
| 취득세 | 법인·과밀억제권역·5년 이내면 9.4%, 아니면 4.6% | `buyer.과밀억제권역` (법제처 원문 확인) |
| 대출 | min(감정가 70%, 낙찰가 80%) · 금리 5.5% | `case.yaml` → `finance` |
| 명도비 | 평당 10만원 | `assumptions.명도비_평당` |
| 공실 관리비 | 평당 월 1만원 | `assumptions.관리비_평당` |

> 💡 **판단 기준**: '배수' = 매도차익 ÷ 총투자금. 1.00 이상(100원 넣고 100원 남기기)이 합격선이고, 배수 1.00이 되는 낙찰가가 **입찰 상한**입니다.

## 6. 한계와 주의

- **법원 경매 전용**입니다. 온비드·신탁공매(`pubauct`) 페이지는 자동 수집이 안 됩니다 — 공고문·감정평가서를 직접 읽어 `case.yaml`을 채우는 방식으로만 가능합니다. 신탁공매는 최저가에 **건물분 부가세가 포함**되고 체납관리비·명도·압류 정리가 매수인 몫이라 계산 전제가 다릅니다.
- 네이버 매물은 **호가**입니다. 중개사 청취가 없으면 보고서에 "호가 기준 초판"으로 표시됩니다.
- 세금·법률 판단은 법제처 원문으로 확인하지만, **최종 판단은 세무사·법무사**에게 받으세요.
- 공공 API(K-apt 등)가 장애일 때는 입지등급을 '미산출'로 표시하고 진행합니다.
- 이 보고서는 개인 검토용입니다. 투자 결과에 대한 책임은 사용자에게 있습니다.

## 7. 포함되지 않은 것

| 항목 | 이유 | 대안 |
|---|---|---|
| 부가남 상가투자 지식베이스 (SOP의 `output/education/expert-kb/buganam/`) | 유료 강의 자료 — 저작권 | SOP의 분석 체크리스트 순서만 참고 |
| 배후단지·상권 외곽선 지도 스크립트 (SOP §10) | 특정 보고서 폴더에 묶인 실험 기능 | 선택 기능 — 없어도 보고서 생성 가능 |
| 옥션원 목록 검색·스크리닝 CLI (`auction1_search.py` 등) | 신규 물건 발굴용, 보고서와 별개 | 옥션원 웹에서 직접 검색 |

## 8. 문제 해결

| 증상 | 해결 |
|---|---|
| `LoginError: .env 에 auction1_ID…` | `.env`에 옥션원 계정 입력 |
| 옥션원 상세가 로그인 페이지로 옴 | 자동으로 재로그인합니다. 반복되면 계정·유료 기간 확인 |
| 네이버 `429` / 지도는 보이는데 매물이 안 나옴 | headed 모드가 아닙니다. gstack `connect` 후 `status`가 `headed`인지 확인. 자세한 내용은 `docs\업무절차서(SOP)\네이버부동산_매물조사_SOP.md` |
| 입지등급 `KeyError: 'response'` | 공공데이터 API 장애 또는 활용신청 미승인. 승인 후 1~2시간 대기 |
| 콘솔 한글 깨짐 | 명령에 `python -X utf8` 사용 |
| 슬라이드 PNG 검수가 안 됨 | PowerPoint 미설치 — PPTX를 직접 열어 확인 |

상세 절차·함정·사례는 `docs\업무절차서(SOP)\상가경매_입찰보고서_SOP.md`에 있습니다.
