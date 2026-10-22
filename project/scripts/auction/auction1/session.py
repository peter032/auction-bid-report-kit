"""옥션원 로그인 세션 관리.

로그인만 브라우저(Playwright)로 하고, 이후 목록 요청은 같은 컨텍스트의
APIRequestContext 로 처리한다. 쿠키를 공유하므로 별도 세션 이식이 필요 없다.

로그인 상태는 storage_state 로 캐시해서 재실행 때 재로그인을 피한다.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

__all__ = ["LoginError", "Credentials", "load_credentials", "browser_session"]

BASE_URL = "https://www.auction1.co.kr"
LOGIN_URL = f"{BASE_URL}/common/login_box.php"
# 로그인 여부 확인용 페이지. 비로그인이면 로그인 폼으로 튕긴다.
GUARDED_URL = f"{BASE_URL}/auction/ca_list.php"

STATE_PATH = Path(os.environ.get("LOCALAPPDATA", "/tmp")) / "auction1" / "state.json"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class LoginError(RuntimeError):
    """로그인에 실패했다. 자격증명·계정상태를 확인해야 한다."""


@dataclass(frozen=True)
class Credentials:
    user_id: str
    password: str


def load_credentials(env_path: Path) -> Credentials:
    """.env 에서 옥션원 자격증명을 읽는다.

    값은 어떤 경로로도 로그에 남기지 않는다.
    """
    if not env_path.exists():
        raise LoginError(f".env 파일이 없다: {env_path}")

    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        matched = re.match(r"^\s*([A-Za-z0-9_]+)\s*=\s*(.*)$", line)
        if matched:
            values[matched.group(1)] = matched.group(2).strip()

    user_id = values.get("auction1_ID", "")
    password = values.get("auction1_PASSWORD", "")
    if not user_id or not password:
        raise LoginError(
            f"{env_path} 에 auction1_ID / auction1_PASSWORD 가 없다."
        )
    return Credentials(user_id, password)


class browser_session:
    """로그인된 Playwright 컨텍스트를 제공하는 컨텍스트 매니저.

        with browser_session(creds) as ctx:
            html = ctx.request.post(...).text()
    """

    def __init__(self, credentials: Credentials, *, headless: bool = True,
                 reuse_state: bool = True):
        self._credentials = credentials
        self._headless = headless
        self._reuse_state = reuse_state
        self._playwright = None
        self._browser = None
        self._context = None

    def __enter__(self):
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self._headless)

        state = STATE_PATH if (self._reuse_state and STATE_PATH.exists()) else None
        self._context = self._browser.new_context(
            storage_state=str(state) if state else None,
            user_agent=USER_AGENT,
            viewport={"width": 1440, "height": 1000},
        )

        page = self._context.new_page()
        if state is None or not _is_logged_in(page):
            _login(page, self._credentials)
            _save_state(self._context)
        page.close()
        return self._context

    def __exit__(self, *exc):
        for closer in (self._context, self._browser):
            if closer is not None:
                closer.close()
        if self._playwright is not None:
            self._playwright.stop()
        return False


def _is_logged_in(page: Page) -> bool:
    """캐시된 세션이 아직 유효한지 확인."""
    try:
        page.goto(GUARDED_URL, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(800)
    except Exception:
        return False
    return "login_box" not in page.url and "로그아웃" in page.content()


def _login(page: Page, credentials: Credentials) -> None:
    alerts: list[str] = []
    page.on("dialog", lambda d: (alerts.append(d.message), d.accept()))

    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_timeout(800)

    try:
        page.fill("#client_id", credentials.user_id)
        page.fill("#passwd", credentials.password)
    except Exception as exc:
        raise LoginError(
            f"로그인 폼 구조가 바뀌었다 (#client_id / #passwd 없음): {exc}"
        ) from exc

    try:
        with page.expect_navigation(timeout=20_000):
            page.click("form#fm_login button")
    except Exception:
        pass  # 실패 시 alert 만 뜨고 이동이 없을 수 있다. 아래에서 상태로 판정한다.
    page.wait_for_timeout(2_000)

    if not _is_logged_in(page):
        detail = f" 사이트 메시지: {alerts[0]}" if alerts else ""
        raise LoginError(
            "옥션원 로그인 실패. 아이디/비밀번호 또는 계정 상태를 확인해라." + detail
        )


def _save_state(context) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    context.storage_state(path=str(STATE_PATH))
    # 세션 쿠키 파일이므로 소유자만 읽게 한다 (POSIX 한정, Windows 에선 무시됨)
    try:
        STATE_PATH.chmod(0o600)
    except OSError:
        pass


def clear_state() -> None:
    """캐시된 로그인 상태 삭제 (재로그인 강제)."""
    if STATE_PATH.exists():
        STATE_PATH.unlink()
