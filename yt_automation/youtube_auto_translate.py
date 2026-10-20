"""
유튜브 다국어 자동 번역기 -> 유튜브 스튜디오 자동 입력 프로그램

사용법:
  1. "50개국 번역기_maker.pyw" 에서 제목/설명을 번역하고
     [저장(엑셀/CSV 형식으로 현재 목록 전체 저장)] 버튼으로 CSV 파일을 저장한다.
  2. 아래 CSV_PATH 와 VIDEO_ID 를 채우고 이 스크립트를 실행한다.
  3. 자동으로 크롬이 열리고, 언어별로 제목/설명을 채워넣고 [업데이트]를 누른다.
"""

import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

PROFILE_DIR = r"C:\Users\lg\ChromeAutomationProfile"
MAPPING_PATH = Path(r"C:\Users\lg\Desktop\yt_automation\lang_mapping.json")

TITLE_MAX_LEN = 100


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

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=False,
            channel="chrome",
            viewport={"width": 1400, "height": 900},
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(f"https://studio.youtube.com/video/{video_id}/translations", wait_until="domcontentloaded")
        page.wait_for_timeout(2500)

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
                existing_names = get_existing_language_rows(page)
                process_language(page, yt_name, title, desc, existing_names)
                print(f"  -> 완료")
                success += 1
            except Exception as e:
                print(f"  -> 실패: {e}")
                failed.append(code)
                # 실패 시 혹시 열려있는 다이얼로그 닫기 시도
                try:
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(500)
                except Exception:
                    pass

            page.wait_for_timeout(1000)

        print("\n=== 완료 ===")
        print(f"성공: {success} / 실패: {len(failed)} / 건너뜀: {len(skipped)}")
        if failed:
            print("실패한 언어코드:", failed)
        if skipped:
            print("건너뛴 언어코드:", skipped)

        context.close()


if __name__ == "__main__":
    main()
