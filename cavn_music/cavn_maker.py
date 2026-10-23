"""CAVN AI(https://cavn.ai/create) 자동 곡 생성 + 다운로드

md 파일 하나 = CAVN 앨범 하나 (앨범 이름 = md 파일 이름).
곡마다: 커스텀 모드 → 제목·가사·음악 스타일·제외 스타일 입력 → [지금 만들기]
        → 2곡 생성 대기 → 재생바에서 곡 길이 확인 → 긴 곡부터 다운로드

저장 위치: <저장 폴더>\\<md 파일 이름>\\노래\\  (캡컷 조립 프로그램이 읽는 구조)
  긴 곡   제목.mp3 / 제목.wav / 제목.lrc / 제목.jpg / 제목_구간라벨.txt / 제목_가사본문.txt
  짧은 곡 제목 (1).mp3 / 제목 (1).wav / 제목 (1).lrc / 제목 (1).jpg
  (가사 비디오, 창작 증명서는 받지 않음)

AI 마스터링 (시작할 때 앨범 전체를 할지 한 번만 물어봄, 1곡당 5크레딧)
  [더 보기 옆 AI 마스터링] → '밝고 선명한' → [AI 처리 시작] → 끝나면 다운로드
  → 제목_mastered.wav (두 곡 모두면 제목 (1)_mastered.wav 도)  ← 가요 캡컷 조립 프로그램이 읽는 이름

이미 '제목.wav'와 '제목 (1).wav'가 둘 다 있는 곡은 건너뛴다 (중간에 멈춰도 다시 실행하면 이어서 함).
마스터링 파일만 빠진 곡은 곡을 새로 만들지 않고 마스터링만 한다.

사용법:
  python cavn_maker.py <md 파일> [--out F:\\음악생성] [--only 1,3,5] [--master 0|1|2] [--dry-run]
"""

import argparse
import re
import shutil
import sys
import time
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from md_parser import STYLE_MAX_LEN, parse_md_file  # noqa: E402
from thumb_agent.browser import start_real_chrome  # noqa: E402

CREATE_URL = "https://cavn.ai/create"
ALBUMS_URL = "https://cavn.ai/albums"
DEFAULT_OUT = r"F:\음악생성"
PROFILE_DIR = HERE / "browser_profile"
DEBUG_PORT = 9224  # 썸네일(9222)·유튜브 자동입력(9223)과 겹치지 않게

POP_STYLE_INCLUDES_GENRE = True  # 가요/팝: 음악 스타일 칸에 '장르'도 앞에 붙여 넣음
GENERATE_TIMEOUT_SEC = 15 * 60   # 곡 생성 최대 대기
DOWNLOAD_TIMEOUT_MS = 180_000
MASTER_STYLE = "밝고 선명한"     # AI 마스터링 스타일
MASTER_TIMEOUT_SEC = 10 * 60     # 마스터링 처리 최대 대기
CREDITS_PER_SONG = 5             # 곡 만들기 5크레딧/2곡, 마스터링 5크레딧/1곡
MASTER_TARGET = 1               # 마스터링을 하면: 1=긴 곡만, 2=두 곡 모두
MASTER_CHOICES = {0: "안 함", 1: "함 (앨범 전체, 긴 곡만)", 2: "함 (앨범 전체, 두 곡 모두)"}
GENERATING_RE = re.compile(r"생성\s*중|대기\s*중|처리\s*중|\d+\s*%|Generating|Queued|Pending", re.I)
TIME_PAIR_RE = re.compile(r"(\d{1,2}:\d{2}(?::\d{2})?)\s*/\s*(\d{1,2}:\d{2}(?::\d{2})?)")

# (메뉴 항목, 대화창 버튼, 저장 이름 꼬리, 기본 확장자)
AUDIO_ITEMS = [
    ("MP3 오디오 다운로드", None, "", ".mp3"),
    ("WAV 오디오 다운로드", None, "", ".wav"),
    ("스크롤 가사 다운로드", "LRC", "", ".lrc"),
    ("곡 커버 다운로드", None, "", ".jpg"),
]
TEXT_LYRIC_ITEMS = [
    ("텍스트 가사 다운로드", "구간 라벨 유지", "_구간라벨", ".txt"),
    ("텍스트 가사 다운로드", "가사 본문만", "_가사본문", ".txt"),
]
CONFIRM_BUTTONS = ["만들기", "생성", "확인", "저장", "완료", "Create", "OK", "Save"]


def log(msg):
    print(time.strftime("[%H:%M:%S] ") + msg, flush=True)


def safe_filename(name):
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip().rstrip(".")


def to_seconds(text):
    secs = 0
    for part in text.split(":"):
        secs = secs * 60 + int(part)
    return secs


def xpath_literal(s):
    if "'" not in s:
        return f"'{s}'"
    if '"' not in s:
        return f'"{s}"'
    return "concat(" + ", \"'\", ".join(f"'{p}'" for p in s.split("'")) + ")"


# ---------------------------------------------------------------- 화면 도우미

class Cavn:
    def __init__(self, page, create_url=CREATE_URL, albums_url=ALBUMS_URL):
        self.page = page
        self.create_url = create_url
        self.albums_url = albums_url

    # -- 위치로 왼쪽(곡 만들기) / 오른쪽(곡 목록) 구분: [지금 만들기] 버튼 오른쪽 끝이 경계
    #    (오른쪽 곡 목록의 앨범 칸은 화면 한가운데보다 왼쪽에 있어서 화면 절반으로 나누면 안 됨)
    def _mid_x(self):
        return self.page.evaluate("""() => {
            const b = [...document.querySelectorAll('button')].find(e =>
                (e.innerText || '').includes('지금 만들기') && e.getBoundingClientRect().width > 0);
            return b ? b.getBoundingClientRect().right + 10 : window.innerWidth / 2;
        }""")

    def _visible(self, locator, side=None):
        mid = self._mid_x()
        found = []
        for el in locator.all():
            try:
                if not el.is_visible():
                    continue
                box = el.bounding_box()
            except PlaywrightError:
                continue
            if not box:
                continue
            center = box["x"] + box["width"] / 2
            if side == "left" and center >= mid or side == "right" and center < mid:
                continue
            found.append(el)
        return found

    def left_textareas(self):
        return self._visible(self.page.locator("textarea"), "left")

    def click_text(self, text, exact=True, timeout=10_000):
        self.page.get_by_text(text, exact=exact).filter(visible=True).first.click(timeout=timeout)

    # -- 시작
    def open_create(self):
        self.page.goto(self.create_url, wait_until="domcontentloaded")
        try:
            self.page.get_by_text("지금 만들기").first.wait_for(timeout=20_000)
        except PlaywrightTimeout:
            log("CAVN 곡 만들기 화면이 보이지 않습니다. 열린 크롬에서 로그인해 주세요.")
            input("로그인을 마치고 곡 만들기 화면이 보이면 Enter 를 누르세요... ")
            self.page.goto(self.create_url, wait_until="domcontentloaded")
            self.page.get_by_text("지금 만들기").first.wait_for(timeout=30_000)
        time.sleep(2)

    # -- 앨범
    def ensure_album(self, name):
        """앨범이 없으면 만든다. 실제로 만들어진 앨범 이름을 돌려준다."""
        page = self.page
        page.goto(self.albums_url, wait_until="domcontentloaded")
        page.get_by_text("앨범 만들기").first.wait_for(timeout=20_000)
        time.sleep(2)
        if self._visible(page.get_by_text(name, exact=True)):
            log(f"앨범 '{name}' 이(가) 이미 있어서 그대로 씁니다.")
            return name
        log(f"앨범 '{name}' 만들기")
        page.get_by_text("앨범 만들기").filter(visible=True).first.click()
        box = page.locator("input:visible, textarea:visible").first
        box.wait_for(timeout=10_000)
        box.fill(name)
        actual = box.input_value().strip() or name
        if actual != name:
            log(f"  (앨범 이름 글자 수 제한 때문에 '{actual}' 로 저장됩니다)")
        dialog = page.locator("[role=dialog]:visible, [role=alertdialog]:visible")
        scope = dialog.last if dialog.count() else page
        for text in CONFIRM_BUTTONS:
            btn = scope.get_by_role("button", name=text, exact=True)
            btns = [b for b in btn.all() if b.is_visible() and b.is_enabled()]
            if btns:
                btns[-1].click()
                break
        else:
            box.press("Enter")
        page.get_by_text(actual, exact=True).first.wait_for(timeout=15_000)
        return actual

    def _album_triggers(self, side):
        loc = self.page.locator("button, [role=combobox], [aria-haspopup]").filter(
            has_text=re.compile(r"\(\d+\)\s*$"))
        return self._visible(loc, side)

    def select_album(self, name, side):
        triggers = self._album_triggers(side)
        if not triggers:
            raise RuntimeError(f"{'왼쪽' if side == 'left' else '오른쪽'} 앨범 선택 칸을 찾지 못했습니다.")
        trigger = triggers[-1] if side == "left" else triggers[0]
        if re.match(re.escape(name) + r"\s*\(\d+\)", trigger.inner_text().strip()):
            return
        trigger.click()
        time.sleep(1)
        option_re = re.compile(r"^\s*" + re.escape(name) + r"\s*(\(\d+\))?\s*$")
        options = self._visible(self.page.get_by_text(option_re))
        options = [o for o in options if o.evaluate("e => !e.closest('button[aria-haspopup], [role=combobox]')")] \
            or options
        if not options:
            self.page.keyboard.press("Escape")
            raise RuntimeError(f"앨범 목록에서 '{name}' 을(를) 찾지 못했습니다.")
        options[-1].click()
        time.sleep(1.5)

    # -- 입력
    def set_instrumental(self, on):
        """연주곡 스위치. 켜지면 가사 칸이 사라지므로 왼쪽 글상자 개수로 상태를 확인한다."""
        def is_on():
            return len(self.left_textareas()) <= 1
        if is_on() == on:
            return
        label = self._visible(self.page.get_by_text("연주곡", exact=True), "left")
        if not label:
            raise RuntimeError("'연주곡' 스위치를 찾지 못했습니다.")
        switch = label[0].evaluate_handle("""el => {
            let p = el;
            for (let i = 0; i < 4 && p; i++, p = p.parentElement) {
                const sw = p.querySelector('[role=switch], input[type=checkbox], button');
                if (sw) return sw;
            }
            return el;
        }""").as_element()
        try:
            switch.click()
        except PlaywrightError:
            label[0].click()
        time.sleep(1)
        if is_on() != on:
            label[0].click()
            time.sleep(1)
        if is_on() != on:
            raise RuntimeError("연주곡 스위치를 바꾸지 못했습니다.")

    def fill_form(self, track, title, style_text, lyrics_text):
        page = self.page
        self.click_text("커스텀 모드")
        time.sleep(1)
        self.set_instrumental(track.classical)

        inputs = self._visible(page.locator("input[type=text], input:not([type])"), "left")
        if not inputs:
            raise RuntimeError("제목 칸을 찾지 못했습니다.")
        inputs[0].fill(title)
        known = [inputs[0]]

        boxes = self.left_textareas()
        if track.classical:
            style_box = boxes[0]
        else:
            if len(boxes) < 2:
                raise RuntimeError("가사 칸을 찾지 못했습니다.")
            boxes[0].fill(lyrics_text)
            known.append(boxes[0])
            style_box = boxes[1]
        style_box.fill(style_text)
        known.append(style_box)
        if style_box.input_value().strip() != style_text.strip():
            raise RuntimeError("음악 스타일이 끝까지 들어가지 않았습니다 (글자 수 제한?).")

        if track.exclude:
            self.fill_exclude(track.exclude, known)

    def fill_exclude(self, text, known):
        """고급 설정 안의 제외 스타일 칸 (못 찾으면 건너뜀)."""
        page = self.page
        field = self._find_exclude_field(known)  # 고급 설정이 이미 열려 있으면 바로 찾음
        if not field:
            labels = self._visible(page.get_by_text("고급 설정", exact=True), "left")
            if labels:
                labels[0].click()
                time.sleep(1)
                field = self._find_exclude_field(known)
        if field:
            field.fill(text)
        else:
            log("  (고급 설정에서 '제외 스타일' 칸을 찾지 못해 건너뜁니다)")

    def _find_exclude_field(self, known):
        """왼쪽 칸들 중 이름표(placeholder·바로 위 글씨)에 '제외/Exclude'가 있는 칸.
        이미 채운 제목·가사·스타일 칸(known)은 빼고 찾는다."""
        fields = self._visible(self.page.locator("textarea, input[type=text], input:not([type])"), "left")
        for el in fields:
            if any(el.evaluate("(a, b) => a === b", k.element_handle()) for k in known):
                continue
            hint = el.evaluate("""el => {
                const parts = [el.placeholder, el.getAttribute('aria-label'), el.name, el.id];
                let p = el.parentElement;
                for (let i = 0; i < 3 && p; i++, p = p.parentElement) {
                    const t = (p.innerText || '').trim();
                    if (t) { if (t.length < 80) parts.push(t); break; }
                }
                return parts.filter(Boolean).join(' ');
            }""")
            if re.search(r"제외|exclude|negative|네거티브", hint or "", re.I):
                return el
        return None

    def click_create(self):
        btn = self._visible(self.page.get_by_role("button", name=re.compile("지금 만들기")), "left")
        if not btn:
            raise RuntimeError("[지금 만들기] 버튼을 찾지 못했습니다.")
        btn[0].click()

    # -- 곡 목록
    def song_rows(self, title):
        # [더 보기] 버튼에서 출발해 제목이 들어 있는 가장 가까운 상자 = 곡 한 줄.
        # (제목 글씨에서 출발하면 아래 재생바의 제목까지 잡혀서, 재생할 때마다 순서가 바뀜)
        xp = ("xpath=//*[normalize-space(text())='더 보기']"
              f"/ancestor::*[.//*[normalize-space(text())={xpath_literal(title)}]][1]")
        rows = []
        for el in self._visible(self.page.locator(xp), "right"):
            box = el.bounding_box()
            if box and box["height"] < 400:
                rows.append(el)
        rows.sort(key=lambda e: e.bounding_box()["y"])
        return rows

    def row_ready(self, row):
        try:
            text = row.inner_text()
        except PlaywrightError:
            return False
        return "더 보기" in text and not GENERATING_RE.search(text)

    def wait_new_rows(self, title, before):
        deadline = time.time() + GENERATE_TIMEOUT_SEC
        last_note = 0
        while time.time() < deadline:
            rows = self.song_rows(title)
            if len(rows) >= before + 2 and all(self.row_ready(r) for r in rows[:2]):
                time.sleep(5)
                return self.song_rows(title)[:2]
            if time.time() - last_note > 60:
                log(f"  생성 기다리는 중... (목록에 같은 제목 {len(rows)}개)")
                last_note = time.time()
            time.sleep(5)
        raise RuntimeError("곡 생성이 제한 시간 안에 끝나지 않았습니다.")

    # -- 곡 길이 (앨범 자켓을 눌러 재생 → 재생바 시간)
    def _player_total(self):
        text = self.page.evaluate("""() => {
            const els = [...document.querySelectorAll('body *')].filter(e =>
                e.children.length < 4 && /\\d:\\d\\d\\s*\\/\\s*\\d/.test(e.innerText || ''));
            els.sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top);
            return els.length ? els[0].innerText : '';
        }""")
        m = TIME_PAIR_RE.search(text or "")
        return to_seconds(m.group(2)) if m else None

    def _audio_duration(self):
        return self.page.evaluate("""() => {
            const a = [...document.querySelectorAll('audio, video')].find(x => !x.paused);
            return a && isFinite(a.duration) && a.duration > 0 ? a.duration : null;
        }""")

    def _pause(self, jacket):
        paused = self.page.evaluate("""() => {
            let n = 0;
            document.querySelectorAll('audio, video').forEach(a => { if (!a.paused) { a.pause(); n++; } });
            return n;
        }""")
        if not paused:
            try:
                jacket.click()
            except PlaywrightError:
                pass

    def song_length(self, row):
        jacket = row.locator("img").first
        before = self._player_total()
        jacket.click()
        length = None
        for _ in range(30):
            time.sleep(0.5)
            dur = self._audio_duration()
            total = self._player_total()
            if dur:
                length = round(dur)
                break
            if total and total != before:
                length = total
                break
        if length is None:
            length = self._player_total() or None
        self._pause(jacket)
        time.sleep(0.5)
        return length

    # -- 다운로드
    def _open_menu(self, row):
        more = row.get_by_text("더 보기").first
        more.scroll_into_view_if_needed()
        more.click()
        time.sleep(0.8)

    def download(self, row, item, choice, dest_base, default_ext):
        """더 보기 → 메뉴 항목 (→ 대화창 버튼) 을 눌러 받은 파일을 dest_base + 확장자로 저장."""
        page = self.page
        for attempt in (1, 2):
            try:
                self._open_menu(row)
                with page.expect_download(timeout=DOWNLOAD_TIMEOUT_MS) as info:
                    page.get_by_text(item, exact=True).filter(visible=True).last.click()
                    if choice:
                        self._click_dialog_choice(choice)
                dl = info.value
                ext = Path(dl.suggested_filename).suffix or default_ext
                dest = Path(str(dest_base) + ext.lower())
                dl.save_as(dest)
                self._close_overlays()
                return dest
            except (PlaywrightTimeout, PlaywrightError) as e:
                self._close_overlays()
                if attempt == 2:
                    log(f"    !! '{item}{' - ' + choice if choice else ''}' 받기 실패: {str(e).splitlines()[0]}")
                    if item == "곡 커버 다운로드":
                        return self._save_cover_image(row, dest_base)
                    return None
                time.sleep(3)

    def _click_dialog_choice(self, choice):
        """메뉴 항목을 누른 뒤 고르는 창이 뜨면 해당 버튼을 누른다 (안 뜨면 그냥 넘어감)."""
        btn = self.page.get_by_role("button", name=re.compile(re.escape(choice), re.I))
        try:
            btn.filter(visible=True).first.click(timeout=4_000)
        except PlaywrightTimeout:
            pass

    def _close_overlays(self):
        for _ in range(2):
            try:
                self.page.keyboard.press("Escape")
            except PlaywrightError:
                pass
            time.sleep(0.3)

    def _save_cover_image(self, row, dest_base):
        src = row.locator("img").first.get_attribute("src")
        if not src or src.startswith("data:"):
            return None
        resp = self.page.request.get(src)
        if not resp.ok:
            return None
        ext = Path(src.split("?")[0]).suffix or ".jpg"
        dest = Path(str(dest_base) + ext.lower())
        dest.write_bytes(resp.body())
        return dest

    # -- AI 마스터링
    def master(self, row, dest_base):
        """곡 줄의 [AI 마스터링] → 스타일 선택 → [AI 처리 시작] → 끝나면 받아서 dest_base + 확장자로 저장."""
        page = self.page
        buttons = self._visible(row.get_by_text("AI 마스터링", exact=True))
        if buttons:
            buttons[0].click()
        else:
            self._open_menu(row)
            page.get_by_text("AI 마스터링", exact=True).filter(visible=True).last.click()
        page.get_by_text("AI 마스터링 스타일 선택").first.wait_for(timeout=30_000)
        time.sleep(2)
        page.get_by_text(MASTER_STYLE, exact=True).filter(visible=True).first.click()
        time.sleep(0.5)
        page.get_by_role("button", name=re.compile("AI 처리 시작")).filter(visible=True).first.click()
        log(f"    '{MASTER_STYLE}' 마스터링 처리 기다리는 중...")

        download_btn = page.get_by_role("button", name=re.compile("다운로드")).or_(
            page.get_by_role("link", name=re.compile("다운로드"))).filter(visible=True)
        deadline = time.time() + MASTER_TIMEOUT_SEC
        while time.time() < deadline:
            if download_btn.count() and download_btn.first.is_enabled():
                break
            time.sleep(3)
        else:
            raise RuntimeError("마스터링이 제한 시간 안에 끝나지 않았습니다.")
        time.sleep(1)
        with page.expect_download(timeout=DOWNLOAD_TIMEOUT_MS) as info:
            download_btn.first.click()
            self._click_dialog_choice("WAV")  # 형식을 고르는 창이 뜨면 WAV
        dl = info.value
        ext = (Path(dl.suggested_filename).suffix or ".wav").lower()
        dest = Path(str(dest_base) + ext)
        dl.save_as(dest)
        if ext != ".wav":
            log(f"    !! 마스터링 파일이 wav가 아니라 {ext} 로 받아졌습니다.")
        log(f"    받음: {dest.name}")
        return dest


# ---------------------------------------------------------------- 곡 하나 처리

def download_song(cavn, row, base, items):
    saved = []
    for item, choice, tail, ext in items:
        path = cavn.download(row, item, choice, Path(str(base) + tail), ext)
        if path:
            saved.append(path.name)
            log(f"    받음: {path.name}")
    return saved


def make_track(cavn, track, out_dir, album_name, master=0, pop_include_genre=POP_STYLE_INCLUDES_GENRE):
    title = track.title
    fname = safe_filename(title)
    long_base = out_dir / fname
    short_base = out_dir / f"{fname} (1)"

    if status(out_dir, title, master) == "need_master":
        # 곡은 이미 받았고 마스터링만 빠짐 → 목록에서 그 곡을 찾아 마스터링만
        log("  곡은 이미 받았으니 마스터링만 합니다.")
        rows = cavn.song_rows(title)[:2]
        if len(rows) < 2:
            raise RuntimeError("곡 목록에서 이 제목의 곡 2개를 찾지 못했습니다.")
        lengths = [cavn.song_length(r) for r in rows]
        long_i = 0 if (lengths[0] or 0) >= (lengths[1] or 0) else 1
        master_songs(cavn, title, long_i, long_base, short_base, album_name, master)
        return

    style = track.style_box(pop_include_genre)
    if len(style) > STYLE_MAX_LEN:
        raise RuntimeError(f"음악 스타일이 {len(style)}자라 {STYLE_MAX_LEN}자를 넘습니다. md 파일을 줄여 주세요.")

    before = len(cavn.song_rows(title))
    cavn.fill_form(track, title, style, track.lyrics_box())
    cavn.click_create()
    log("  [지금 만들기] 누름. 2곡 생성 기다리는 중...")
    rows = cavn.wait_new_rows(title, before)

    lengths = [cavn.song_length(r) for r in rows]
    log(f"  곡 길이: {', '.join(f'{s // 60}:{s % 60:02d}' if s else '?' for s in lengths)}")

    if all(lengths) and lengths[0] != lengths[1]:
        long_i = 0 if lengths[0] > lengths[1] else 1
        log("  긴 곡 받기")
        download_song(cavn, rows[long_i], long_base, AUDIO_ITEMS + TEXT_LYRIC_ITEMS)
        log("  짧은 곡 받기")
        download_song(cavn, rows[1 - long_i], short_base, AUDIO_ITEMS)
    else:
        # 길이를 못 읽었으면: 둘 다 임시 이름으로 받고 wav 크기(=길이)로 긴 곡을 정한다
        log("  재생바에서 길이를 못 읽어 wav 파일 크기로 긴 곡을 정합니다.")
        tmp = out_dir / ".받는중"
        tmp.mkdir(exist_ok=True)
        for i, row in enumerate(rows):
            download_song(cavn, row, tmp / f"{fname}__{i}", AUDIO_ITEMS)
        sizes = [_size(tmp / f"{fname}__{i}.wav") for i in range(2)]
        long_i = 0 if sizes[0] >= sizes[1] else 1
        for i, base in ((long_i, long_base), (1 - long_i, short_base)):
            for f in sorted(tmp.glob(f"{glob_escape(fname)}__{i}.*")):
                shutil.move(str(f), str(base) + f.suffix)
        shutil.rmtree(tmp, ignore_errors=True)
        log("  긴 곡 가사 받기")
        download_song(cavn, rows[long_i], long_base, TEXT_LYRIC_ITEMS)

    if master:
        master_songs(cavn, title, long_i, long_base, short_base, album_name, master)


def master_songs(cavn, title, long_i, long_base, short_base, album_name, master):
    """긴 곡(과 짧은 곡)을 마스터링. 마스터링 화면으로 갔다가 곡 만들기 화면으로 돌아온다."""
    targets = [(long_i, long_base, "긴 곡")]
    if master == 2:
        targets.append((1 - long_i, short_base, "짧은 곡"))
    for i, base, name in targets:
        if Path(str(base) + "_mastered.wav").exists():
            continue
        log(f"  {name} AI 마스터링")
        rows = cavn.song_rows(title)[:2]  # 화면을 다녀오면 다시 찾아야 함 (순서는 그대로)
        try:
            cavn.master(rows[i], Path(str(base) + "_mastered"))
        finally:
            cavn.open_create()
            cavn.select_album(album_name, "right")


def glob_escape(name):
    return re.sub(r"([\[\]*?])", r"[\1]", name)


def _size(path):
    return path.stat().st_size if path.exists() else 0


def status(out_dir, title, master=0):
    """'todo' = 곡을 만들어야 함, 'need_master' = 곡은 받았고 마스터링만 남음, 'done' = 끝."""
    fname = safe_filename(title)
    if not ((out_dir / f"{fname}.wav").exists() and (out_dir / f"{fname} (1).wav").exists()):
        return "todo"
    need = [f"{fname}_mastered.wav"] + ([f"{fname} (1)_mastered.wav"] if master == 2 else [])
    if master and not all((out_dir / n).exists() for n in need):
        return "need_master"
    return "done"


def ask_master(album, count):
    """앨범 전체를 마스터링할지 처음에 한 번만 묻는다."""
    print("================================================")
    print(f"  앨범 「{album}」 ({count}곡)")
    print(f"  이 앨범 전체를 AI 마스터링('{MASTER_STYLE}') 할까요?")
    target = "긴 곡만" if MASTER_TARGET == 1 else "두 곡 모두"
    print(f"  ({target}, 1곡당 {CREDITS_PER_SONG}크레딧 → 제목_mastered.wav)")
    print("================================================")
    while True:
        answer = input("마스터링 (y/n): ").strip().lower()
        if answer in ("y", "yes", "ㅛ", "예", "네"):
            return MASTER_TARGET
        if answer in ("n", "no", "ㅜ", "아니요", "아니오"):
            return 0


# ---------------------------------------------------------------- 실행

def connect(pw):
    cdp = start_real_chrome(PROFILE_DIR, DEBUG_PORT)
    if not cdp:
        raise SystemExit("크롬을 찾지 못했습니다. 크롬을 설치해 주세요.")
    browser = pw.chromium.connect_over_cdp(cdp)
    context = browser.contexts[0] if browser.contexts else browser.new_context()
    page = context.pages[0] if context.pages else context.new_page()
    page.bring_to_front()
    return page


def run(md_path, out_root, only=None, dry_run=False, page=None,
        create_url=CREATE_URL, albums_url=ALBUMS_URL, confirm=True, master=None):
    md_path = Path(md_path)
    album = md_path.stem
    tracks = parse_md_file(md_path)
    if only:
        tracks = [t for t in tracks if t.number in only]
    if not tracks:
        raise SystemExit("md 파일에서 곡을 찾지 못했습니다.")

    out_dir = Path(out_root) / safe_filename(album) / "노래"
    kind = "연주곡(클래식·경음악)" if tracks[0].classical else "가요/팝"
    if master is None:
        master = 0 if dry_run else ask_master(album, len(tracks))
    print(f"\nmd 파일 : {md_path.name}\n앨범    : {album}\n종류    : {kind}\n저장 폴더: {out_dir}")
    print(f"AI 마스터링: {MASTER_CHOICES[master]}\n")
    todo = []
    marks = {"done": "완료(건너뜀)", "need_master": "마스터링만 남음"}
    for t in tracks:
        style_len = len(t.style_box(POP_STYLE_INCLUDES_GENRE))
        state = status(out_dir, t.title, master)
        mark = marks.get(state) or ("!! 스타일 1000자 초과" if style_len > STYLE_MAX_LEN else "")
        print(f"  {t.number:>2}. {t.title}  (스타일 {style_len}자) {mark}")
        for w in t.warnings:
            print(f"      !! {w}")
        if state != "done":
            todo.append((t, state))
    new = sum(1 for _, state in todo if state == "todo")
    credits = new * CREDITS_PER_SONG + len(todo) * master * CREDITS_PER_SONG
    print(f"\n만들 곡 {new}개 (곡마다 2곡 생성), 마스터링 {len(todo) * master}곡 → 약 {credits}크레딧")
    if dry_run or not todo:
        return
    if confirm and input("시작할까요? (y/n): ").strip().lower() not in ("y", "yes", "ㅛ"):
        return
    out_dir.mkdir(parents=True, exist_ok=True)

    def work(page):
        cavn = Cavn(page, create_url, albums_url)
        album_name = cavn.ensure_album(album)
        cavn.open_create()
        cavn.select_album(album_name, "left")
        cavn.select_album(album_name, "right")
        failed = []
        for i, (t, _) in enumerate(todo, 1):
            log(f"[{i}/{len(todo)}] {t.number}. {t.title}")
            try:
                cavn.select_album(album_name, "left")
                make_track(cavn, t, out_dir, album_name, master)
            except Exception as e:  # 한 곡이 실패해도 다음 곡은 계속
                log(f"  !! 실패: {e}")
                failed.append(t)
                cavn.page.goto("about:blank")  # 마스터링 화면 등에 남아 있을 수 있으니 처음부터
                cavn.open_create()
                cavn.select_album(album_name, "right")
        print()
        log(f"끝. 성공 {len(todo) - len(failed)}곡, 실패 {len(failed)}곡")
        for t in failed:
            print(f"  실패: {t.number}. {t.title}  (다시 실행하면 이 곡부터 이어서 합니다)")
        print(f"저장 폴더: {out_dir}")

    if page is not None:
        return work(page)
    with sync_playwright() as pw:
        work(connect(pw))


def main():
    ap = argparse.ArgumentParser(description="CAVN AI 자동 곡 생성 + 다운로드")
    ap.add_argument("md", help="Claude가 만든 음악 md 파일")
    ap.add_argument("--out", default=DEFAULT_OUT, help=f"저장 폴더 (기본 {DEFAULT_OUT})")
    ap.add_argument("--only", help="이 트랙 번호만 (예: 1,3,5)")
    ap.add_argument("--master", type=int, choices=[0, 1, 2],
                    help="앨범 전체 AI 마스터링 0=안 함, 1=긴 곡만, 2=두 곡 모두 (안 주면 시작할 때 물어봄)")
    ap.add_argument("--dry-run", action="store_true", help="md 파일만 읽어 보고 끝냄")
    args = ap.parse_args()
    only = {int(x) for x in re.findall(r"\d+", args.only)} if args.only else None
    run(args.md.strip('"'), args.out, only, args.dry_run, master=args.master)


if __name__ == "__main__":
    main()
