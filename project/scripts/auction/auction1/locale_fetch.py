"""입지 스코어용 공공 API 수집기 — 상권 · K-apt · VWorld.

순수 계산은 `locale.py` 에 있다. 여기는 네트워크만 담당한다.

키는 `.env` 의 두 개로 충분하다:
  - `DATA_GO_KR_KEY` — 상권(B553077) · 단지목록(AptListService4) · 기본정보(AptBasisInfoServiceV5)
    **세 서비스가 같은 키 하나로 열린다.** 각각 활용신청만 돼 있으면 된다.
  - `vworld_KEY` — 지오코딩. **개발키로 충분하다**(로컬 스크립트 호출은 도메인 제한에 안 걸림).

2026-09-10 스파이크에서 물린 함정 네 가지를 여기서 고정한다:

1. 공공데이터포털이 주는 **인코딩키를 unquote 해서** 보내야 한다. 원문 그대로면 403.
2. 상권 API는 **HTTP만** 받는다. HTTPS 는 403.
3. K-apt 오퍼레이션명에 **`4` 접미사**가 붙는다(`getLegaldongAptList4`).
   접미사 없는 이름·`3`·`V4` 는 전부 NO_OPENAPI_SERVICE_ERROR. 공식 문서에 안 나와 있다.
4. `kaptAddr` 는 "경기도 수원권선구 호매실동 1420" 처럼 시·구가 붙어 나온다.
   "수원시 권선구" 로 띄우지 않으면 지오코딩이 실패한다.

배후 단지 후보를 찾는 방식: 상권 API로 **반경 밖 여유분까지** 긁어 법정동 목록을 얻고,
그 법정동들의 K-apt 단지를 전부 받아 좌표를 찍은 뒤 거리로 자른다.
업소가 하나도 없는 법정동의 단지는 이 방식으로 못 잡는다 — 그래서 여유분을 둔다.
"""

import hashlib
import json
import math
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .locale import BACKING_RADIUS_M, PARCEL_RADIUS_M, Complex, summarize

__all__ = [
    "locale_of",
    "load_keys",
    "geocode",
    "stores_in_radius",
    "complexes_near",
    "haversine_m",
    "fix_kapt_address",
    "geo_cache_key",
]

SANGGWON = "http://apis.data.go.kr/B553077/api/open/sdsc2/storeListInRadius"
APT_LIST = "http://apis.data.go.kr/1613000/AptListService4/getLegaldongAptList4"
APT_INFO = "http://apis.data.go.kr/1613000/AptBasisInfoServiceV5/getAphusBassInfoV5"
VWORLD = "https://api.vworld.kr/req/address"

# 법정동 후보를 모을 때 배후 반경에 더하는 여유. 경계 너머 단지를 놓치지 않기 위한 것.
DONG_SCAN_MARGIN_M = 600

CACHE_DIR = Path(os.environ.get("LOCALAPPDATA", "/tmp")) / "auction1" / "locale_cache"

# "수원권선구" -> "수원시 권선구". 이미 '시 '가 있으면 건드리지 않는다.
_SIGU = re.compile(r"(?<![가-힣])([가-힣]{2,3})([가-힣]{2,4}구)(?=\s)")


def fix_kapt_address(addr: str) -> str:
    """K-apt 지번주소의 붙은 시·구를 띄운다. 없으면 원문 그대로."""
    if "시 " in addr:
        return addr
    return _SIGU.sub(r"\1시 \2", addr, count=1)


def load_keys(env_path=".env") -> tuple[str, str]:
    """`.env` 에서 키 두 개를 읽는다. 같은 이름이 여러 번 나오면 첫 값을 쓴다."""
    data: dict[str, str] = {}
    for line in Path(env_path).read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        data.setdefault(k.strip(), v.strip())
    return urllib.parse.unquote(data["DATA_GO_KR_KEY"]), data["vworld_KEY"]


def _cached(name: str, loader):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{name}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    value = loader()
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return value


def _get_json(url: str, timeout: int = 90) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371000.0
    rad = math.radians
    a = (
        math.sin(rad(lat2 - lat1) / 2) ** 2
        + math.cos(rad(lat1)) * math.cos(rad(lat2)) * math.sin(rad(lon2 - lon1) / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def stores_in_radius(key: str, lat: float, lon: float, radius_m: int) -> list[dict]:
    """반경 내 상가업소 전량. 페이지네이션을 끝까지 돈다."""

    def load():
        out: list[dict] = []
        page = 1
        while True:
            qs = urllib.parse.urlencode(
                {
                    "serviceKey": key,
                    "radius": radius_m,
                    "cx": lon,
                    "cy": lat,
                    "numOfRows": 1000,
                    "pageNo": page,
                    "type": "json",
                },
                quote_via=urllib.parse.quote,
            )
            body = _get_json(f"{SANGGWON}?{qs}").get("body", {})
            items = body.get("items") or []
            out += items
            if len(out) >= body.get("totalCount", 0) or not items or page > 12:
                return out
            page += 1

    return _cached(f"stores_{lat:.6f}_{lon:.6f}_{radius_m}", load)


def geo_cache_key(kind: str, address: str) -> str:
    """지오코딩 캐시 파일명.

    주소를 그대로 쓰면 안 된다. 한글을 percent-encoding 하면 글자당 9자라
    파일명 길이 제한에서 잘리고, `road_경기도 수원시 권선구 ...` 까지가 전부 같아져
    **한 동네 단지들이 첫 단지의 좌표를 공유하게 된다.**
    (2026-09-10 실측: 호매실 17개 단지가 모두 같은 좌표로 캐시돼 전부 800m 밖으로 밀렸다.)
    """
    digest = hashlib.sha1(f"{kind}_{address}".encode("utf-8")).hexdigest()[:16]
    return f"geo_{digest}"


def geocode(vkey: str, address: str, kind: str = "road"):
    """VWorld 지오코딩. 실패하면 None — 좌표를 지어내지 않는다."""

    def load():
        qs = urllib.parse.urlencode(
            {
                "service": "address",
                "request": "getcoord",
                "version": "2.0",
                "crs": "epsg:4326",
                "address": address,
                "refine": "true",
                "simple": "false",
                "format": "json",
                "type": kind,
                "key": vkey,
            }
        )
        res = _get_json(f"{VWORLD}?{qs}", timeout=30).get("response", {})
        if res.get("status") != "OK":
            return None
        pt = res["result"]["point"]
        return [float(pt["y"]), float(pt["x"])]

    got = _cached(geo_cache_key(kind, address), load)
    return (got[0], got[1]) if got else None


def _apt_list(dkey: str, bjd: str) -> list[dict]:
    def load():
        qs = urllib.parse.urlencode(
            {"serviceKey": dkey, "bjdCode": bjd, "numOfRows": 300, "pageNo": 1},
            quote_via=urllib.parse.quote,
        )
        items = _get_json(f"{APT_LIST}?{qs}")["response"]["body"]["items"]
        return items.get("item", []) if isinstance(items, dict) else items

    return _cached(f"aptlist_{bjd}", load) or []


def _apt_info(dkey: str, code: str):
    def load():
        qs = urllib.parse.urlencode(
            {"serviceKey": dkey, "kaptCode": code}, quote_via=urllib.parse.quote
        )
        return _get_json(f"{APT_INFO}?{qs}")["response"]["body"]["item"]

    try:
        return _cached(f"aptinfo_{code}", load)
    except Exception:
        return None


def complexes_near(dkey, vkey, lat, lon, radius_m=BACKING_RADIUS_M) -> list[Complex]:
    """반경 내 공동주택 단지. K-apt 는 법정동 단위라 좌표를 찍어 거리로 자른다."""
    scan = stores_in_radius(dkey, lat, lon, radius_m + DONG_SCAN_MARGIN_M)
    bjds = sorted({s.get("ldongCd") for s in scan if s.get("ldongCd")})

    out: list[Complex] = []
    for bjd in bjds:
        for apt in _apt_list(dkey, bjd):
            info = _apt_info(dkey, apt["kaptCode"])
            if not info:
                continue
            point = None
            if info.get("doroJuso"):
                point = geocode(vkey, info["doroJuso"], "road")
            if not point and info.get("kaptAddr"):
                point = geocode(vkey, fix_kapt_address(info["kaptAddr"]), "parcel")
            if not point:
                continue
            dist = haversine_m(lat, lon, point[0], point[1])
            if dist > radius_m:
                continue
            out.append(
                Complex(
                    name=info.get("kaptName", apt["kaptCode"]),
                    households=int(info.get("kaptdaCnt") or 0),
                    sale_type=info.get("codeSaleNm") or "",
                    distance_m=round(dist),
                )
            )
            time.sleep(0.05)
    out.sort(key=lambda c: c.distance_m)
    return out


def locale_of(lat: float, lon: float, env_path=".env") -> dict:
    """물건 좌표 -> 입지 판정 한 건."""
    dkey, vkey = load_keys(env_path)
    apts = complexes_near(dkey, vkey, lat, lon)
    stores = stores_in_radius(dkey, lat, lon, PARCEL_RADIUS_M)
    result = summarize(apts, stores)
    result["배후단지"] = [
        (c.name, c.households, c.sale_type, c.distance_m) for c in apts
    ]
    return result
