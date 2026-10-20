"""스튜디오 조작용 브라우저 열기.

- 기본: 이 프로그램 전용 크롬 프로필(browser_profile 폴더)을 사용. 처음 한 번만 로그인하면 계속 유지됨.
- cdp_url 을 주면 이미 켜 둔 크롬(--remote-debugging-port)에 연결해서 그 창을 그대로 사용.
- real_chrome=True(기본): 프로그램이 크롬을 '자동 조종 모드'로 열지 않고, 평소처럼 크롬을 켠 다음
  거기에 연결한다. 구글이 자동 조종 크롬에서는 로그인을 막기 때문("로그인할 수 없음 -
  브라우저 또는 앱이 안전하지 않을 수 있습니다").
"""

import os
import shutil
import subprocess
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled", "--start-maximized"]


def find_chrome(chrome_path=None):
    """설치된 크롬 실행 파일 경로 (없으면 None)."""
    candidates = [chrome_path] if chrome_path else []
    for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            candidates.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
    candidates += [shutil.which(n) for n in ("chrome", "google-chrome", "google-chrome-stable")]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def _debug_port_alive(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1):
            return True
    except Exception:
        return False


def start_real_chrome(profile_dir, port=9222, chrome_path=None):
    """평소처럼 크롬을 켜고(이미 켜져 있으면 그대로) 연결 주소를 돌려준다. 크롬이 없으면 None."""
    url = f"http://127.0.0.1:{port}"
    if _debug_port_alive(port):
        return url
    exe = find_chrome(chrome_path)
    if not exe:
        return None
    subprocess.Popen([
        exe, f"--remote-debugging-port={port}", f"--user-data-dir={Path(profile_dir).resolve()}",
        "--start-maximized", "--no-first-run", "--no-default-browser-check",
    ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        time.sleep(0.5)
        if _debug_port_alive(port):
            return url
    print("[안내] 크롬에 연결하지 못해 예전 방식으로 엽니다.")
    return None


@contextmanager
def open_studio_page(profile_dir="browser_profile", channel="chrome", cdp_url=None,
                     headless=False, slow_mo=0, real_chrome=True, debug_port=9222, chrome_path=None):
    if not cdp_url and real_chrome and not headless:
        cdp_url = start_real_chrome(profile_dir, debug_port, chrome_path)
    with sync_playwright() as pw:
        if cdp_url:
            browser = pw.chromium.connect_over_cdp(cdp_url, slow_mo=slow_mo)
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
