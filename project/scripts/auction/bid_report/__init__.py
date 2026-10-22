"""상가경매 입찰보고서 표준화 패키지.

gate        입력 게이트 — 누락 정보를 질문 목록으로 만든다
fetch_case  옥션원 상세·사진·캡처 수집 (네트워크)
comps       네이버부동산 카드 → 층별 통계·대형 비교군·마커 매핑
scenario    시나리오 손익·배수·1:1 입찰상한
build_report case.yaml + 산출물 → PPTX
"""
