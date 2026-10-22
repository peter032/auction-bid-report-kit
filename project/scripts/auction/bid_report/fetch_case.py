"""옥션원 물건 1건 수집 — 상세 HTML · 파싱 JSON · 페이지 캡처 · 현황사진 전량.

CLI:  python -m bid_report.fetch_case <product_id> <출력폴더>

실측 함정 (2026-09-14):
1. 캐시된 storage_state 가 만료되면 상세가 12KB '옥션원 로그인' 페이지로 온다.
   login_box.php 마커가 없어 기존 is_rejected() 를 통과한다 → **매 실행 clear_state() 로 새로 로그인**.
2. 사진 원본 CDN 은 직접 요청 시 403. 상세페이지를 연 **같은 로그인 컨텍스트**에서
   ca_photo.php 를 열어야 서명 URL 이 발급된다 → 응답 가로채기로 저장.
3. ca_photo.php 를 networkidle 로 열면 빈 페이지 — domcontentloaded + 대기.
"""

import base64
import html as html_module
import json
import re
import sys
import time
from pathlib import Path

__all__ = ["extract_photos", "is_login_page", "fetch_case"]

VIEW_URL = "https://www.auction1.co.kr/auction/ca_view.php?product_id={pid}"
PHOTO_URL = ("https://www.auction1.co.kr/auction/ca_photo.php?product_id={pid}"
             "&pnum={num}&p=1&igroup={igroup}&filzi2=1&sample_key=0&person_hide=0")

# 라벨:번호:원본경로:썸네일경로:부가:1:igroup:1:b64썸네일:b64원본
_PHOTO_SPAN = re.compile(r">([^:<>]{1,10}):(\d+):([^<]*?)</span>")


def extract_photos(raw_html: str) -> list[dict]:
    photos, seen = [], set()
    for label, num, rest in _PHOTO_SPAN.findall(raw_html):
        fields = rest.split(":")
        if len(fields) < 7 or num in seen:
            continue
        try:
            url = base64.b64decode(fields[-1]).decode()
        except Exception:
            continue
        if not url.startswith("https://cdn-file.auction1.co.kr/"):
            continue
        seen.add(num)
        photos.append({"label": re.sub(r"\d+$", "", label), "raw_label": label, "num": num,
                       "igroup": fields[4], "url": url})
    return photos


def is_login_page(raw_html: str) -> bool:
    title = re.search(r"<title>(.*?)</title>", raw_html, re.S)
    if title and "로그인" in title.group(1):
        return True
    return "login_box.php" in raw_html


def _section_y(page, names: list[str]) -> dict:
    return page.evaluate("""(names) => {
        const out = {};
        for (const n of names) {
          const el = [...document.querySelectorAll('h1,h2,h3,h4,div,span,td,strong,b')]
            .find(e => (e.textContent || '').trim().startsWith(n) && e.children.length < 4);
          if (el) out[n] = Math.round(el.getBoundingClientRect().top + window.scrollY);
        }
        return out;
    }""", names)


def fetch_case(product_id: str, outdir: Path) -> dict:
    from PIL import Image
    here = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(here))
    from auction1.detail_parse import parse_detail
    from auction1.session import browser_session, clear_state, load_credentials

    raw_dir, img_dir = outdir / "raw", outdir / "images"
    raw_dir.mkdir(parents=True, exist_ok=True)
    img_dir.mkdir(parents=True, exist_ok=True)
    creds = load_credentials(here.parents[1] / ".env")

    for attempt in (1, 2):
        clear_state()
        captured: dict[str, bytes] = {}
        with browser_session(creds, headless=True) as ctx:
            def on_response(resp):
                try:
                    if "cdn-file.auction1" in resp.url and resp.ok:
                        body = resp.body()
                        if len(body) > 6000:
                            captured.setdefault(resp.url.split("?")[0], body)
                except Exception:
                    pass
            ctx.on("response", on_response)
            page = ctx.new_page()
            page.set_viewport_size({"width": 1000, "height": 1400})
            page.goto(VIEW_URL.format(pid=product_id), wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(4000)
            detail = page.content()
            if is_login_page(detail):
                if attempt == 2:
                    raise RuntimeError("재로그인 후에도 로그인 페이지 — 계정/세션 확인 필요")
                continue
            page.screenshot(path=str(raw_dir / "auction_full.png"), full_page=True)
            ys = _section_y(page, ["매각물건현황", "건축물정보", "매각사례분석"])
            photos = extract_photos(detail)
            for p in photos:
                pg = ctx.new_page()
                try:
                    pg.goto(PHOTO_URL.format(pid=product_id, num=p["num"], igroup=p["igroup"]),
                            wait_until="domcontentloaded", timeout=45_000, referer=page.url)
                    pg.wait_for_timeout(3000)
                    for src in pg.eval_on_selector_all("img", "e => e.map(x => x.src)"):
                        key = src.split("?")[0]
                        if "cdn-file" in src and key not in captured:
                            r = ctx.request.get(src, headers={"Referer": pg.url})
                            if r.ok and len(r.body()) > 6000:
                                captured[key] = r.body()
                finally:
                    pg.close()
                time.sleep(1.5)
        break

    (raw_dir / "detail.html").write_text(detail, encoding="utf-8")
    parsed = parse_detail(detail)
    (raw_dir / "detail.json").write_text(json.dumps(parsed, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    text = re.sub(r"<script.*?</script>|<style.*?</style>", "", detail, flags=re.S)
    text = html_module.unescape(re.sub(r"<[^>]+>", "\n", re.sub(r"</(td|th)>", " | ", text)))
    (raw_dir / "detail.txt").write_text("\n".join(l.strip() for l in text.splitlines() if l.strip()), encoding="utf-8")

    saved = []
    for p in photos:
        base = p["url"].split("?")[0]
        body = captured.get(base)
        if body:
            name = f"{p['num']}_{p['raw_label']}.jpg"
            (img_dir / name).write_bytes(body)
            saved.append(name)

    full = Image.open(raw_dir / "auction_full.png")
    w, h = full.size
    top = max(0, ys.get("매각물건현황", 600) - 460)
    split = ys.get("건축물정보", h // 2) - 20
    end = min(h, ys.get("매각사례분석", split + 600) + 260)
    full.crop((0, top, w, split)).save(img_dir / "auc_p1.png")
    full.crop((0, split, w, end)).save(img_dir / "auc_p2.png")

    summary = {"product_id": product_id, "photos_found": len(photos), "photos_saved": len(saved),
               "missing": [p["raw_label"] for p in photos if f"{p['num']}_{p['raw_label']}.jpg" not in saved],
               "lat": parsed["위도"], "lon": parsed["경도"], "sections_y": ys}
    (raw_dir / "fetch_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return summary


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    result = fetch_case(sys.argv[1], Path(sys.argv[2]))
    print(json.dumps(result, ensure_ascii=False, indent=1))
    sys.exit(0 if result["photos_saved"] == result["photos_found"] else 3)
