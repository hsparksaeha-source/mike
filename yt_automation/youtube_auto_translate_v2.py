"""
유튜브 다국어 자동 번역기 -> 유튜브 스튜디오 자동 입력 프로그램

사용법:
  1. "50개국 번역기_maker.pyw" 에서 제목/설명을 번역하고
     [저장(엑셀/CSV 형식으로 현재 목록 전체 저장)] 버튼으로 CSV 파일을 저장한다.
  2. 아래 CSV_PATH 와 VIDEO_ID 를 채우고 이 스크립트를 실행한다.
  3. 자동으로 크롬이 열리고, 언어별로 제목/설명을 채워넣고 [업데이트]를 누른다.

v2 (원본 youtube_auto_translate.py 와 하는 일은 같고, 아래 두 가지만 다름):
  - 크롬을 '자동 조종 모드'로 열지 않고 평소처럼 켠 다음 연결한다.
    (구글이 자동 조종 크롬에서 "로그인할 수 없음 - 브라우저 또는 앱이 안전하지 않을 수 있습니다"로 막기 때문)
    작업이 끝나도 크롬 창은 닫지 않고 남겨 둔다 (다음 실행 때 그대로 다시 씀).
  - 중간에 구글 '본인 인증' 창(또는 '오류가 발생했습니다' 화면)이 뜨면, 프로그램이 크롬에서 완전히
    손을 뗀다(연결을 끊음). 크롬이 평소 크롬과 똑같은 상태에서 사람이 인증을 마치고 까만 창에서
    Enter 를 누르면, 다시 연결해서 그 언어부터 이어서 한다.
    (프로그램이 연결된 채로 인증하면 구글이 인증을 받아 주지 않고 '오류가 발생했습니다'가 나올 수 있음)
"""

import csv
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

PROFILE_DIR = r"C:\Users\lg\ChromeAutomationProfile"
MAPPING_PATH = Path(r"C:\Users\lg\Desktop\yt_automation\lang_mapping.json")

TITLE_MAX_LEN = 100
DEBUG_PORT = 9223  # 썸네일 프로그램(9222)과 겹치지 않게
VERIFY_TIMEOUT_SEC = 900  # 본인 인증을 기다리는 최대 시간 (15분)
VERIFY_TEXTS = ["본인 인증", "본인임을 확인", "Verify it's you", "Verify it’s you", "Confirm it's you",
                "오류가 발생했습니다", "Something went wrong"]


# ---------------------------------------------------------------- 크롬 (평소처럼 켜고 연결)

def find_chrome():
    candidates = []
    for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            candidates.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
    candidates += [shutil.which(n) for n in ("chrome", "google-chrome", "google-chrome-stable")]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def debug_port_alive(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1):
            return True
    except Exception:
        return False


def start_real_chrome(profile_dir, port=DEBUG_PORT):
    """평소처럼 크롬을 켜고(이미 켜져 있으면 그대로) 연결 주소를 돌려준다. 못 켜면 None."""
    url = f"http://127.0.0.1:{port}"
    if debug_port_alive(port):
        return url
    exe = find_chrome()
    if not exe:
        return None
    subprocess.Popen([
        exe, f"--remote-debugging-port={port}", f"--user-data-dir={profile_dir}",
        "--start-maximized", "--no-first-run", "--no-default-browser-check",
    ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        time.sleep(0.5)
        if debug_port_alive(port):
            return url
    return None


# ---------------------------------------------------------------- 구글 본인 인증

class VerificationNeeded(Exception):
    pass


def verification_showing(page):
    """구글 '본인 인증' 창이 떠 있거나, 인증(로그인) 화면으로 넘어갔는지."""
    try:
        if "accounts.google.com" in page.url:
            return True
        for text in VERIFY_TEXTS:
            if page.get_by_text(text, exact=False).filter(visible=True).count() > 0:
                return True
    except Exception:
        return False
    return False


class Session:
    """크롬 연결 상태. 본인 인증 동안 연결을 끊었다가 다시 붙기 위해 page 를 여기서 관리한다."""

    def __init__(self, p, profile_dir):
        self.p = p
        self.cdp_url = start_real_chrome(profile_dir)
        self.browser = None
        self.context = None
        if self.cdp_url:
            self._connect()
        else:
            print("[안내] 크롬을 평소처럼 켜지 못해 예전 방식으로 엽니다.")
            self.context = p.chromium.launch_persistent_context(
                profile_dir,
                headless=False,
                channel="chrome",
                viewport={"width": 1400, "height": 900},
            )
            self.page = self.context.pages[0] if self.context.pages else self.context.new_page()

    def _connect(self):
        self.browser = self.p.chromium.connect_over_cdp(self.cdp_url)
        context = self.browser.contexts[0] if self.browser.contexts else self.browser.new_context()
        # 이미 열려 있는 스튜디오 탭이 있으면 그 탭을 그대로 쓴다 (사람이 인증을 마친 탭)
        studio_tabs = [pg for pg in context.pages if "studio.youtube.com" in pg.url]
        self.page = studio_tabs[-1] if studio_tabs else context.new_page()

    def disconnect(self):
        """크롬 창은 그대로 두고 프로그램의 연결만 끊는다."""
        try:
            self.browser.close()
        except Exception:
            pass
        self.browser = None

    def finish(self):
        if self.browser is not None:
            self.disconnect()
        elif self.context is not None:
            self.context.close()


def wait_for_verification(sess, studio_url):
    """본인 인증 창(또는 오류 화면)이 있으면, 사람이 인증을 마칠 때까지 기다렸다가 언어 화면을 다시 연다.
    인증 창이 있었으면 True."""
    if not verification_showing(sess.page):
        return False
    while True:
        print("\n  ⚠️ 구글 '본인 인증' 창(또는 '오류가 발생했습니다' 화면)이 보입니다.")
        if sess.browser is not None:
            try:
                sess.page.bring_to_front()
            except Exception:
                pass
            sess.disconnect()
            print("     프로그램이 크롬에서 잠시 손을 뗐습니다. 크롬을 평소처럼 쓰시면 됩니다.")
            print("     1) 크롬에서 [다음]을 누르고 안내대로 인증을 마쳐 주세요.")
            print("     2) '오류가 발생했습니다'가 보이면 F5(새로고침)를 눌러 주세요.")
            print("     3) 영상의 '언어' 화면(언어 표)이 정상으로 보이면, 이 까만 창에서 Enter 를 누르세요.")
            try:
                input("     인증이 끝났으면 Enter... ")
            except EOFError:
                pass
            sess._connect()
        else:
            print("     크롬 창에서 [다음]을 누르고 안내대로 인증을 마쳐 주세요.")
            print(f"     인증이 끝나면 자동으로 이어서 진행합니다. (최대 {VERIFY_TIMEOUT_SEC // 60}분 기다림)")
            deadline = time.time() + VERIFY_TIMEOUT_SEC
            while time.time() < deadline and verification_showing(sess.page):
                time.sleep(2)
        # 인증 전에 열려 있던 언어 창 등은 저장되지 않았을 수 있으니 언어 화면을 새로 연다
        sess.page.goto(studio_url, wait_until="domcontentloaded")
        sess.page.wait_for_timeout(3000)
        if not verification_showing(sess.page):
            break
        print("     아직 인증 창이나 오류 화면이 보입니다. 다시 한 번 확인해 주세요.")
    print("  ✅ 인증 확인됨. 이어서 진행합니다.\n")
    return True


def extract_video_id(text):
    """전체 유튜브 스튜디오/시청 URL이 들어와도, 순수 영상 ID만 들어와도 모두 처리한다."""
    text = text.strip().strip('"').strip("'")
    m = re.search(r"studio\.youtube\.com/video/([A-Za-z0-9_-]{5,})", text)
    if m:
        return m.group(1)
    m = re.search(r"youtu\.be/([A-Za-z0-9_-]{5,})", text)
    if m:
        return m.group(1)
    m = re.search(r"[?&]v=([A-Za-z0-9_-]{5,})", text)
    if m:
        return m.group(1)
    # 그 외에는 이미 순수 ID로 간주
    return text


def load_mapping():
    with open(MAPPING_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_csv_rows(csv_path):
    rows = []
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row.get("언어코드", "").strip()
            title = row.get("영상 제목", "").strip()
            desc = row.get("영상 설명", "").strip()
            if not code:
                continue
            if title == "번역 실패" or "서버 과부하" in desc:
                continue
            rows.append({"code": code, "title": title, "desc": desc})
    return rows


def get_existing_language_rows(page):
    """번역 테이블에 이미 있는 언어명(한국어 표시명) 목록을 가져온다."""
    names = page.evaluate("""
() => {
    const rows = document.querySelectorAll('ytgn-video-languages-section table tr, ytgn-video-languages-section .language-dialog-row');
    const out = [];
    document.querySelectorAll('a, span').forEach(el => {});
    // 번역 테이블의 언어 열은 링크(a) 형태
    document.querySelectorAll('table a').forEach(a => {
        const t = (a.innerText || '').trim();
        if (t) out.push(t);
    });
    return out;
}
""")
    return set(names)


def open_language_dialog(page, yt_name, existing_names):
    if yt_name in existing_names:
        page.get_by_text(yt_name, exact=True).first.click()
    else:
        page.get_by_role("button", name="언어 추가").click()
        page.wait_for_timeout(600)
        page.get_by_text(yt_name, exact=True).first.click()
    page.wait_for_timeout(1200)


def fill_contenteditable(page, container_selector, text):
    box = page.locator(f"{container_selector} #textbox")
    box.click()
    box.evaluate(
        """
(el, text) => {
    el.focus();
    document.execCommand('selectAll', false, null);
    document.execCommand('delete', false, null);
    if (text) {
        document.execCommand('insertText', false, text);
    }
    el.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
    el.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
}
""",
        text or "",
    )
    page.wait_for_timeout(300)


def process_language(page, yt_name, title, desc, existing_names):
    open_language_dialog(page, yt_name, existing_names)

    title = title[:TITLE_MAX_LEN]

    fill_contenteditable(page, "ytcp-social-suggestions-textbox.metadata-title", title)
    fill_contenteditable(page, "ytcp-social-suggestions-textbox.metadata-description", desc)

    update_btn = page.locator("ytcp-button.ytgn-language-dialog-update")
    update_btn.click()
    page.wait_for_timeout(2500)

    # [업데이트]를 누르자 본인 인증 창이 뜨면 저장이 안 됐을 수 있으므로, 아래에서 Esc로 닫지 말고
    # 인증을 기다린 뒤 이 언어를 다시 한다.
    if verification_showing(page):
        raise VerificationNeeded()

    # 다이얼로그/배경막을 확실히 닫는다 (안 닫히면 다음 언어 클릭이 막힘)
    for _ in range(3):
        try:
            close_btn = page.locator(
                "ytcp-dialog[opened] #close-icon-button, tp-yt-paper-dialog #close-icon-button"
            )
            if close_btn.count() > 0 and close_btn.first.is_visible():
                close_btn.first.click()
            else:
                page.keyboard.press("Escape")
        except Exception:
            pass
        page.wait_for_timeout(600)
        backdrop = page.locator("tp-yt-iron-overlay-backdrop.opened")
        if backdrop.count() == 0:
            break


def main():
    if len(sys.argv) < 3:
        print("사용법: python youtube_auto_translate.py <CSV경로> <VIDEO_ID>")
        sys.exit(1)

    csv_path = sys.argv[1]
    video_id = extract_video_id(sys.argv[2])
    print(f"영상 ID: {video_id}")

    mtime = datetime.fromtimestamp(Path(csv_path).stat().st_mtime)
    age_min = (datetime.now() - mtime).total_seconds() / 60
    print(f"CSV 파일 저장 시각: {mtime.strftime('%Y-%m-%d %H:%M:%S')} ({age_min:.0f}분 전)")
    if age_min > 30:
        print("!! 주의: 이 CSV가 30분보다 오래됐어요. 방금 번역기 앱에서 새로 저장한 파일이 맞는지 확인해주세요.")
        print("!! 계속하려면 Enter, 중단하려면 Ctrl+C")
        try:
            input()
        except EOFError:
            pass

    mapping = load_mapping()
    rows = load_csv_rows(csv_path)
    print(f"CSV에서 {len(rows)}개 언어 로드 완료")

    studio_url = f"https://studio.youtube.com/video/{video_id}/translations"
    with sync_playwright() as p:
        sess = Session(p, PROFILE_DIR)
        sess.page.goto(studio_url, wait_until="domcontentloaded")
        sess.page.wait_for_timeout(2500)
        wait_for_verification(sess, studio_url)

        success, failed, skipped = 0, [], []

        for i, row in enumerate(rows, 1):
            code, title, desc = row["code"], row["title"], row["desc"]
            yt_name = mapping.get(code)
            if not yt_name:
                print(f"[{i}/{len(rows)}] SKIP - 매핑 없음: {code}")
                skipped.append(code)
                continue

            print(f"[{i}/{len(rows)}] {yt_name} ({code}) 처리 중...")
            try:
                wait_for_verification(sess, studio_url)
                try:
                    existing_names = get_existing_language_rows(sess.page)
                    process_language(sess.page, yt_name, title, desc, existing_names)
                except Exception:
                    # 본인 인증 창 때문에 막힌 것이면 인증을 기다렸다가 이 언어를 한 번 더
                    if not wait_for_verification(sess, studio_url):
                        raise
                    print(f"[{i}/{len(rows)}] {yt_name} ({code}) 다시 시도...")
                    existing_names = get_existing_language_rows(sess.page)
                    process_language(sess.page, yt_name, title, desc, existing_names)
                print(f"  -> 완료")
                success += 1
            except Exception as e:
                print(f"  -> 실패: {e}")
                failed.append(code)
                # 실패 시 혹시 열려있는 다이얼로그 닫기 시도
                try:
                    sess.page.keyboard.press("Escape")
                    sess.page.wait_for_timeout(500)
                except Exception:
                    pass

            sess.page.wait_for_timeout(1000)

        print("\n=== 완료 ===")
        print(f"성공: {success} / 실패: {len(failed)} / 건너뜀: {len(skipped)}")
        if failed:
            print("실패한 언어코드:", failed)
        if skipped:
            print("건너뛴 언어코드:", skipped)

        sess.finish()


if __name__ == "__main__":
    main()
