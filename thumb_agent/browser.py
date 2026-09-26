"""스튜디오 조작용 브라우저 열기.

- 기본: 이 프로그램 전용 크롬 프로필(browser_profile 폴더)을 사용. 처음 한 번만 로그인하면 계속 유지됨.
- cdp_url 을 주면 이미 켜 둔 크롬(--remote-debugging-port)에 연결해서 그 창을 그대로 사용.
"""

from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled", "--start-maximized"]


@contextmanager
def open_studio_page(profile_dir="browser_profile", channel="chrome", cdp_url=None,
                     headless=False, slow_mo=0):
    with sync_playwright() as pw:
        if cdp_url:
            browser = pw.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.new_page()
            try:
                yield page
            finally:
                page.close()
            return

        options = dict(
            user_data_dir=str(Path(profile_dir).resolve()),
            headless=headless,
            slow_mo=slow_mo,
            args=LAUNCH_ARGS,
            ignore_default_args=["--enable-automation"],
            no_viewport=True,
            locale="ko-KR",
        )
        try:
            context = pw.chromium.launch_persistent_context(channel=channel or None, **options)
        except PlaywrightError:
            if not channel:
                raise
            print(f"[안내] '{channel}' 브라우저를 찾지 못해 내장 크로미움으로 실행합니다.")
            context = pw.chromium.launch_persistent_context(**options)
        page = context.pages[0] if context.pages else context.new_page()
        try:
            yield page
        finally:
            context.close()
