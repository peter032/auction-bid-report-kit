@echo off
rem 더블클릭 설치: 설치할 프로젝트 폴더를 묻는다
set /p TARGET=설치할 프로젝트 폴더 경로를 입력하세요 (예: C:\auction):
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" -Target "%TARGET%"
pause
