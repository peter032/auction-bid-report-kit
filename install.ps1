# 상가경매 입찰보고서 키트 설치
# 사용: powershell -ExecutionPolicy Bypass -File install.ps1 -Target "C:\내프로젝트"
param(
    [Parameter(Mandatory = $true)][string]$Target
)
$ErrorActionPreference = "Stop"
$Kit = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "== 1/5 Python 확인" -ForegroundColor Cyan
$ver = & python -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
if (-not $ver) { throw "Python 이 없습니다. https://www.python.org 에서 3.10 이상 설치 후 다시 실행하세요." }
if ([version]$ver -lt [version]"3.10") { throw "Python $ver - 3.10 이상이 필요합니다." }
Write-Host "   Python $ver"

Write-Host "== 2/5 파일 복사 -> $Target" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $Target | Out-Null
Copy-Item -Path (Join-Path $Kit "project\*") -Destination $Target -Recurse -Force -Exclude ".env.example"
$envExample = Join-Path $Kit "project\.env.example"
Copy-Item $envExample (Join-Path $Target ".env.example") -Force
$envFile = Join-Path $Target ".env"
if (Test-Path $envFile) {
    Write-Host "   .env 가 이미 있어 그대로 둡니다. (.env.example 의 키 이름과 맞는지 확인하세요)"
} else {
    Copy-Item $envExample $envFile
    Write-Host "   .env 를 만들었습니다 - 계정·키를 채워야 합니다."
}

Write-Host "== 3/5 Python 패키지 설치" -ForegroundColor Cyan
& python -m pip install -r (Join-Path $Kit "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "pip 설치 실패" }

Write-Host "== 4/5 Playwright 브라우저(Chromium) 설치" -ForegroundColor Cyan
& python -m playwright install chromium
if ($LASTEXITCODE -ne 0) { throw "playwright 브라우저 설치 실패" }

Write-Host "== 5/5 설치 검증 (테스트)" -ForegroundColor Cyan
Push-Location $Target
try {
    & python -X utf8 -m pytest scripts/auction/tests -q
    if ($LASTEXITCODE -ne 0) { throw "테스트 실패 - 위 출력을 확인하세요." }
} finally { Pop-Location }

Write-Host ""
Write-Host "설치 완료." -ForegroundColor Green
Write-Host "남은 일:"
Write-Host "  1) $envFile 에 옥션원 계정 · 공공데이터 키 · VWorld 키 입력"
Write-Host "  2) gstack 브라우저 스킬 설치 (네이버부동산 수집용) - 가이드 '2. gstack 설치' 참고"
Write-Host "  3) Claude Code 를 $Target 에서 열고: '입찰보고서 작성해줘 <옥션원 URL> <네이버부동산 지도 URL>'"
