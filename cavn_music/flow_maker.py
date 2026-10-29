"""Google Flow 자동 이미지 15장 + 영상 1개 만들기
(경음악·클래식: 이미지 프롬프트로 / 가요·칸쏘네: 주인공 캐릭터 + 곡 제목 + 가사로)

md 파일의 트랙마다 (트랙 번호 N):
  1. 에이전트 프롬프트 칸에 '이미지 프롬프트' + "이미지 15장 만들어 줘" → 15장 완성 기다림
  2. 새로 생긴 이미지 중 화면 맨 끝(=제일 처음 만든) 것을 프롬프트 칸에 끌어다 놓고
     '영상 프롬프트'(없으면 뮤직 비디오 콘셉트) + "이 이미지로 영상 만들어 줘" → 영상 완성 기다림
  3. 오른쪽 위 [+] → [새 컬렉션] → 새 컬렉션에 이미지 15장을 끌어다 넣음 (영상은 그대로 둠)
  4. 컬렉션에 마우스 올림 → [⋮] → [컬렉션 다운로드] → 받은 이미지 15장을 이미지\\N번\\ 에 저장
     (다운로드하면서 뜬 창은 닫음)
  5. 영상은 따로 장면\\N.mp4 로 저장 (이미지 폴더에 섞이지 않게)

저장 위치: <저장 폴더>\\<md 파일 이름>\\이미지\\1번 ~ N번   이미지만 (캡컷 클래식 조립 프로그램이 읽는 번호 폴더)
           <저장 폴더>\\<md 파일 이름>\\장면\\1.mp4 ~ N.mp4   영상
이미지 15장과 영상이 이미 있는 트랙은 건너뛴다 (다시 실행하면 남은 트랙만 함).

사용법:
  python flow_maker.py <md 파일> [--out F:\\음악생성] [--only 1,3,5] [--images 15] [--dry-run]
"""

import argparse
import json
import os
import re
import shutil
import sys
import time
import zipfile
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from log_file import record
from md_parser import ask_md_path, ask_only, parse_only, parse_md_file  # noqa: E402
from thumb_agent.browser import start_real_chrome  # noqa: E402

FLOW_URL = "https://flow.google.com/"
DEFAULT_OUT = r"F:\음악생성"
PROFILE_DIR = Path.home() / "CavnFlowChromeProfile"  # 로그인 저장 (프로그램 폴더를 새로 받아도 유지)
DEBUG_PORT = 9224  # CAVN·Flow 가 같은 전용 크롬을 함께 씀 (썸네일 9222, 유튜브 자동입력 9223)

IMAGES_PER_TRACK = 15
IMAGE_TIMEOUT_SEC = 20 * 60
FAIL_SETTLE_SEC = 15      # 일부가 '실패'로 끝났을 때, 더 안 늘면 이만큼 기다렸다가 만들어진 것만으로 진행
VIDEO_TIMEOUT_SEC = 20 * 60
DOWNLOAD_TIMEOUT_MS = 5 * 60_000
IMAGE_REQUEST = "위 프롬프트로 16:9 이미지 {n}장을 만들어 줘."
VIDEO_REQUEST = "이 이미지로 영상을 만들어 줘."
# 가요·칸쏘네 (이미지 프롬프트 대신 곡 제목 + 가사, 주인공 캐릭터)
LYRIC_IMAGE_REQUEST = "캐릭터({names})를 주인공으로 가사에 맞게 16:9 이미지 {{n}}장을 만들어 주세요."
LYRIC_VIDEO_REQUEST = "이 이미지로 가사에 맞게 영상을 만들어 주세요."
PROMPT_PLACEHOLDER = "무엇을 만들고 싶으신가요?"
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")
NEW_GRACE_SEC = 8   # 보낸 뒤 이 초 안에 '새로' 보이는 칸은 Flow 가 만든 것일 수 없음 → 예전 칸으로 본다
VIDEO_EXTS = (".mp4", ".mov", ".webm")


def log(msg):
    print(time.strftime("[%H:%M:%S] ") + msg, flush=True)


def safe_filename(name):
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip().rstrip(".")


# 화면의 미디어 칸(이미지·영상·컬렉션)을 위에서 아래, 왼쪽에서 오른쪽 순서로 읽는다.
# 왼쪽 메뉴(라이브러리)와 아래 프롬프트 칸은 빼고, 가운데 격자만 본다.
TILES_JS = """(box) => {
    // box.prompt = 입력창, box.panel = 오른쪽 에이전트 대화 창. 그 안의 것(붙인 이미지, 대화 속 미리보기)만 빼고
    // 격자는 입력창 아래로도 이어지므로 다 센다
    const inside = (r, a, pad, padTop) => a && r.left + r.width / 2 > a.x - pad && r.left + r.width / 2 < a.x + a.width + pad
        && r.top + r.height / 2 > a.y - padTop && r.top + r.height / 2 < a.y + a.height + pad;
    const inPrompt = r => box && (inside(r, box.prompt, 20, 60) || inside(r, box.panel, 0, 0));
    document.querySelectorAll('[data-cavn-tile]').forEach(e => e.removeAttribute('data-cavn-tile'));
    // Flow 그림 주소 끝의 크기 표시(=w600-rw 등)는 칸 크기에 따라 바뀌므로 떼고 비교한다
    const norm = u => (u || '').split('?')[0].replace(/=[\\w-]*$/, '');
    const side = [...document.querySelectorAll('*')].find(e =>
        (e.innerText || '').trim() === '전체 미디어' && e.getBoundingClientRect().width > 0);
    const sideRight = side ? side.getBoundingClientRect().right + 5 : 0;
    const tileOf = el => {
        let t = el;
        for (let i = 0; i < 6 && t.parentElement; i++) {
            const p = t.parentElement, r = p.getBoundingClientRect(), mr = el.getBoundingClientRect();
            if (r.width > mr.width + 40 || r.height > mr.height + 80) break;
            t = p;
        }
        return t;
    };
    const seen = new Set(), out = [];
    const add = (tile, kind, key, extra) => {
        if (seen.has(tile)) return;
        const r = tile.getBoundingClientRect();
        if (r.width < 60 || r.height < 40 || r.left < sideRight || inPrompt(r)) return;
        seen.add(tile);
        tile.setAttribute('data-cavn-tile', key);
        out.push({kind, key, x: r.left, y: r.top, text: (tile.innerText || '') + (extra ? ' \\n' + extra : '')});
    };
    // 컬렉션: '컬렉션' 글씨가 있는 칸 (썸네일이 없을 수도 있음)
    document.querySelectorAll('*').forEach(e => {
        if (e.children.length || !/컬렉션|Collection/i.test(e.textContent || '')) return;
        let t = e;
        for (let i = 0; i < 6 && t.parentElement; i++) {
            const r = t.parentElement.getBoundingClientRect();
            if (r.width > 400 || r.height > 400) break;
            t = t.parentElement;
        }
        const n = out.filter(o => o.kind === 'collection').length;
        add(t, 'collection', 'collection-' + n);
    });
    document.querySelectorAll('video, img').forEach(m => {
        const r = m.getBoundingClientRect();
        if (r.width < 60 || r.height < 40) return;
        const tile = tileOf(m);
        if (seen.has(tile) || [...seen].some(s => s.contains(tile))) return;
        const isVideo = m.tagName === 'VIDEO' || !!tile.querySelector('video') ||
            /play_circle|videocam|movie/.test(tile.innerText || '');
        const src = isVideo
            ? [m.currentSrc || m.src || '', m.poster || '', tile.querySelector('img') ? tile.querySelector('img').src : '']
                .filter(Boolean).map(norm).join('|')
            : norm(m.currentSrc || m.src || '');
        add(tile, isVideo ? 'video' : 'image', (isVideo ? 'video:' : 'image:') + src,
            m.alt || m.getAttribute('aria-label') || tile.getAttribute('aria-label') || '');
    });
    out.sort((a, b) => Math.abs(a.y - b.y) > 20 ? a.y - b.y : a.x - b.x);
    return out;
}"""


ICON_WORDS = re.compile(r"\b(image|photo|play_circle|play_arrow|videocam|movie|favorite|favorite_border|more_vert|"
                        r"more_horiz|download|file_download|check|check_box|check_box_outline_blank|close|warning|refresh)\b")


def caption(text):
    """격자 칸 글씨에서 사람이 읽는 그림 제목 (예: 'image\nSora reflecting at cafe table' → 'Sora reflecting at cafe table')."""
    lines = [re.sub(r"\s+", " ", ICON_WORDS.sub(" ", ln)).strip() for ln in (text or "").splitlines()]
    lines = [ln for ln in lines if len(ln) >= 4 and not ln.startswith("제목 없")]
    return lines[0][:80] if lines else ""


def norm_title(text):
    return re.sub(r"[^0-9a-z가-힣]+", " ", (text or "").lower()).strip()


def tile_title(text):
    """격자 칸 글씨에서 그림 제목만 (예: 'image Sora walking into room' → 'sora walking into room').
    Flow 는 그림마다 제목을 붙이고, 내려받은 파일 이름도 그 제목이다. 그림 주소가 바뀌어도 제목은 그대로다."""
    t = norm_title(ICON_WORDS.sub(" ", text or ""))
    return t if len(t) >= 4 and not t.startswith("제목 없") else ""


def file_title(path):
    """내려받은 이미지 파일 이름 → 제목 (예: Sora_holding_mug_529db99e.jpg → 'sora holding mug')."""
    stem = re.sub(r"_[0-9a-f]{6,}$", "", Path(path).stem)
    return norm_title(stem.replace("_", " "))


def same_title(a, b):
    """파일 이름은 제목이 길면 잘릴 수 있어서 앞부분이 같으면 같은 그림으로 본다."""
    if not a or not b:
        return False
    return a == b or (min(len(a), len(b)) >= 12 and (a.startswith(b) or b.startswith(a)))


class VideoRefused(RuntimeError):
    """Flow 가 영상 만들기를 거절함 (정책 위반, 유명인과 닮음 등) → 영상만 건너뛴다."""


class Flow:
    def __init__(self, page):
        self.page = page
        self.question_seen = False   # 이번 요청에 확인 질문이 떴는지
        self.approved = False        # 그 질문이 승인됐는지

    # -- 프롬프트 칸
    def prompt_box(self, wait=30):
        """아래쪽 프롬프트 칸('무엇을 만들고 싶으신가요?'). 화면이 늦게 떠도 wait 초까지 기다린다.
        Flow 입력칸은 겉 화면 구조에서 바로 안 보이는 곳(shadow DOM)에 있을 수 있어서, 그 안까지 찾는
        Playwright 찾기 기능을 쓴다. 보낸 뒤엔 칸이 새로 그려지므로 쓸 때마다 다시 찾는다."""
        page = self.page
        deadline = time.time() + wait
        while True:
            height = page.evaluate("innerHeight")
            for loc in (page.get_by_placeholder(PROMPT_PLACEHOLDER),
                        page.locator(f"[aria-placeholder*='{PROMPT_PLACEHOLDER}'], [data-placeholder*='{PROMPT_PLACEHOLDER}']"),
                        page.locator("[contenteditable=true], [contenteditable='']"),
                        page.get_by_role("textbox"),
                        page.locator("textarea")):
                low = []
                for b in loc.all():
                    try:
                        box = b.bounding_box() if b.is_visible() else None
                    except PlaywrightError:
                        box = None
                    try:
                        is_search = box and b.evaluate(
                            "(e, ph) => /검색|search/i.test((e.placeholder || '') + (e.getAttribute('aria-label') || ''))"
                            " || (e.tagName === 'INPUT' && !(e.placeholder || '').includes(ph))",
                            PROMPT_PLACEHOLDER, timeout=2000)
                    except PlaywrightError:
                        is_search = True
                    if box and box["width"] > 150 and not is_search:   # 위쪽 검색칸 등은 빼고
                        # 보통은 화면 아래쪽 칸. 보낸 뒤 에이전트 창이 열려 위치가 바뀌어도 찾도록 위쪽도 허용
                        low.append((box["y"] + (height if box["y"] > height * 0.5 else 0), b))
                if low:
                    target = max(low, key=lambda t: t[0])[1]   # 화면 맨 아래 칸 우선
                    try:
                        page.evaluate("() => document.querySelectorAll('[data-cavn-prompt]')"
                                      ".forEach(e => e.removeAttribute('data-cavn-prompt'))")
                        target.evaluate("e => e.setAttribute('data-cavn-prompt', '1')", timeout=3000)
                        return page.locator("[data-cavn-prompt]").first
                    except PlaywrightError:
                        pass   # 그 사이 다시 그려짐 → 다시 찾기
            if time.time() > deadline:
                # 원인을 알 수 있게 화면에 있는 글상자들을 적어 둔다
                seen = []
                for b in page.locator("textarea, input, [contenteditable], [role=textbox]").all()[:8]:
                    try:
                        seen.append(b.evaluate("""e => { const r = e.getBoundingClientRect();
                            return `${e.tagName}${e.getAttribute('contenteditable') !== null ? '[ce]' : ''} `
                                 + `${Math.round(r.left)},${Math.round(r.top)} ${Math.round(r.width)}x${Math.round(r.height)} `
                                 + `'${(e.placeholder || e.getAttribute('aria-label') || '').slice(0, 20)}'`; }""", timeout=2000))
                    except PlaywrightError:
                        pass
                raise RuntimeError("Flow 프롬프트 칸('무엇을 만들고 싶으신가요?')을 찾지 못했습니다. "
                                   f"(화면 크기 {page.evaluate('innerWidth')}x{height}, 글상자: {' | '.join(seen) or '없음'})")
            time.sleep(1)

    def send_prompt(self, text):
        # 보내기 직전의 [승인] 버튼 수를 기준으로, 이 요청에 새로 생기는 질문만 승인한다
        self.mark_old_questions()
        self.asks_before = self.ask_count()
        box = self.prompt_box()
        box.click()
        self.page.keyboard.insert_text(text)
        time.sleep(0.8)
        # 보내기는 프롬프트 칸 오른쪽 아래 구석의 → 화살표로 (Enter 는 안 보내질 때가 있음). 화살표를 못 찾으면 Enter
        if not self._click_send_arrow():
            self.page.keyboard.press("Enter")
        time.sleep(2)
        # 글이 칸에 그대로 남아 있으면 안 보내진 것 → 화살표를 다시 누른다.
        # 보내면 Flow 가 입력칸을 새로 그리므로, 예전 칸을 기다리지 말고 다시 찾아서 확인한다.
        for attempt in range(4):
            if not self._prompt_text():
                return
            if self._click_send_arrow():
                log("    아직 안 보내져서 프롬프트 칸의 보내기(→) 화살표를 다시 눌렀습니다.")
            time.sleep(2.5)
        if self._prompt_text():
            log("    !! 프롬프트를 보내지 못했습니다. Flow 프롬프트 칸 오른쪽 아래의 → 화살표를 직접 눌러 주세요.")

    def _prompt_text(self):
        try:
            text = self.prompt_box(wait=5).evaluate("e => 'value' in e ? e.value : e.innerText", timeout=3000) or ""
        except (RuntimeError, PlaywrightError):
            return ""
        return re.sub(r"\s+", " ", text).strip()

    def _click_send_arrow(self):
        """프롬프트 칸 오른쪽 아래 구석의 보내기(→) 화살표 버튼을 누른다."""
        try:
            pb = self.prompt_box(wait=3).bounding_box()
        except (RuntimeError, PlaywrightError):
            pb = None
        cands = []
        for loc in (self.page.locator("button").filter(has_text=re.compile(r"arrow_forward|arrow_upward|send|보내기")),
                    self.page.get_by_role("button", name=re.compile(r"보내기|전송|제출|send|submit", re.I))):
            cands += self._visible_boxes(loc)
        if not cands:
            return False
        if pb:   # 프롬프트 칸 근처(오른쪽 아래)에 있는 것 중 가장 오른쪽 아래
            near = [(el, b) for el, b in cands
                    if pb["x"] - 40 < b["x"] < pb["x"] + pb["width"] + 120 and pb["y"] - 40 < b["y"] < pb["y"] + pb["height"] + 120]
            cands = near or cands
        el = max(cands, key=lambda eb: (eb[1]["y"] + eb[1]["x"]))[0]
        try:
            el.click(timeout=3000)
        except PlaywrightError:
            return False
        return True

    # -- 격자
    def tiles(self, kind=None):
        if self._picker_open():   # 애셋 고르기 창이 열려 있으면 격자를 훑을 수 없다
            self.close_picker()
        try:   # 입력칸을 못 찾아도 이미지 세기는 그대로 한다 (입력칸 안의 이미지만 못 뺄 뿐)
            box = self.prompt_box(wait=3).evaluate("""e => {
                const rect = x => { const r = x.getBoundingClientRect();
                                    return {x: r.left, y: r.top, width: r.width, height: r.height}; };
                // 입력칸이 오른쪽 에이전트 대화 창 안에 있으면 그 창 전체를 뺀다 (세로로 길고 좁은 상자)
                let p = e, panel = null;
                for (let i = 0; i < 12 && p.parentElement; i++) {
                    p = p.parentElement;
                    const r = p.getBoundingClientRect();
                    if (r.height > innerHeight * 0.5 && r.width < innerWidth * 0.45) { panel = rect(p); break; }
                    if (r.width >= innerWidth * 0.45) break;
                }
                return {prompt: rect(e), panel};
            }""", timeout=3000)
        except (RuntimeError, PlaywrightError):
            box = None
        items = self.page.evaluate(TILES_JS, box)
        return [t for t in items if kind is None or t["kind"] == kind]

    def tile(self, key, refresh=False):
        if refresh:  # 화면이 다시 그려졌을 수 있으니 칸 표시를 새로 붙인다
            self.tiles()
        loc = self.page.locator(f"[data-cavn-tile={_css_str(key)}]")
        if loc.count():
            return loc.first
        if not refresh:
            return loc.first
        # 격자가 길면 화면 밖의 칸은 아예 그려지지 않음 → 격자를 위에서부터 내려 가며 찾는다
        found = self.find_tile(key)
        if found is None:
            raise RuntimeError("Flow 화면에서 그 이미지·영상 칸을 찾지 못했습니다 (격자를 끝까지 내려 봐도 없음).")
        return found

    def _scroll_grid(self, to_top=False):
        """가운데 격자를 한 화면만큼 내린다 (to_top 이면 맨 위로). 더 못 내려가면 False."""
        return self.page.evaluate("""top => {
            const cands = [...document.querySelectorAll('*')].filter(e => {
                const s = getComputedStyle(e);
                return /(auto|scroll)/.test(s.overflowY) && e.scrollHeight > e.clientHeight + 20
                    && e.clientWidth > innerWidth * 0.4;
            });
            const el = cands.sort((a, b) => b.clientWidth * b.clientHeight - a.clientWidth * a.clientHeight)[0]
                || document.scrollingElement;
            if (top) { el.scrollTop = 0; return true; }
            const before = el.scrollTop;
            el.scrollTop = before + el.clientHeight * 0.8;
            return el.scrollTop > before;
        }""", to_top)

    def find_tile(self, key, max_steps=40):
        self._scroll_grid(to_top=True)
        time.sleep(1)
        for _ in range(max_steps):
            self.tiles()
            loc = self.page.locator(f"[data-cavn-tile={_css_str(key)}]")
            if loc.count():
                return loc.first
            if not self._scroll_grid():
                break
            time.sleep(1)
        return None

    def has_tile(self, key):
        return self.find_tile(key) is not None

    def scan_grid(self, match, kind=None, max_steps=40):
        """격자에서 match(칸) 가 참인 첫 칸. 지금 화면부터 보고, 없으면 맨 위에서부터 내려 가며 찾는다."""
        for t in self.tiles(kind):
            if match(t):
                return t
        self._scroll_grid(to_top=True)
        time.sleep(1)
        for _ in range(max_steps):
            for t in self.tiles(kind):
                if match(t):
                    return t
            if not self._scroll_grid():
                break
            time.sleep(1)
        return None

    def find_image(self, img, used_keys=(), used_titles=(), top=None):
        """이미지 칸을 주소로, 주소가 바뀌었으면 제목으로 찾는다. 이미 쓴 칸은 빼고. 못 찾으면 None.
        top: 격자 맨 앞 몇 장 안에서만 찾는다 (같은 제목의 예전 트랙 그림이 아래쪽에 있을 수 있어서)."""
        title = tile_title(img.get("text"))
        by_title = title and title not in used_titles

        def match(t):
            if t["key"] in used_keys:
                return False
            return t["key"] == img["key"] or bool(by_title and tile_title(t["text"]) == title)
        if top is None:
            return self.scan_grid(match, "image")
        self._scroll_grid(to_top=True)
        time.sleep(0.8)
        return next((t for t in self.tiles("image")[:top] if match(t)), None)

    def click_send(self):
        """프롬프트 칸이 비어 있을 때 오른쪽 보내기(→) 화살표를 누른다."""
        if self._prompt_text():
            return False
        return self._click_send_arrow()

    def _visible_boxes(self, loc):
        out = []
        for el in loc.all():
            try:
                box = el.bounding_box() if el.is_visible() else None
            except PlaywrightError:
                box = None
            if box:
                out.append((el, box))
        return out

    DENY_RE = re.compile(r"^\s*(close\s*)?거부\s*$")
    APPROVE_RE = re.compile(r"^\s*(check\s*)?승인\s*$")

    def _questions(self, new_only=True):
        """에이전트 확인 질문마다 하나씩 있는 [거부] 칸들 (화면 순서).
        보내기 전에 있던 질문(예전 대화 포함)은 표시해 두고 새 질문만 돌려준다."""
        out = []
        for el, box in self._visible_boxes(self.page.get_by_text(self.DENY_RE)):
            try:
                old = el.evaluate("e => e.hasAttribute('data-cavn-old')", timeout=2000)
            except PlaywrightError:
                continue
            if not (new_only and old):
                out.append((el, box))
        return out

    def mark_old_questions(self):
        for el, _ in self._questions(new_only=False):
            try:
                el.evaluate("e => e.setAttribute('data-cavn-old', '1')", timeout=2000)
            except PlaywrightError:
                pass
        self.question_seen = False
        self.approved = False

    def approve(self):
        """에이전트가 'N 크레딧을 사용하여 … 시작하시겠습니까?' 하고 물으면 [승인]을 누른다 ([항상 승인] 아님).
        승인 칸은 '버튼' 표시가 없을 수 있고, 대화 창에 예전 질문과 '승인' 말풍선도 남아 있어서
        → 새로 생긴 질문의 [거부] 칸을 찾고, 그 바로 위에 있는 [승인] 칸을 누른다.
        이미 승인됐으면(사람이 눌렀어도) [거부] 아래에 '승인' 말풍선이 생기므로 그것도 승인으로 본다."""
        questions = self._questions()
        if not questions:
            return False
        self.question_seen = True
        deny_el, deny = questions[-1]
        above, below = None, False
        for el, box in self._visible_boxes(self.page.get_by_text(self.APPROVE_RE)):
            dy = deny["y"] - box["y"]
            if 0 < dy < 260 and abs(box["x"] - deny["x"]) < 120 and (above is None or dy < above[0]):
                above = (dy, el)
            if -500 < dy < 0:
                below = True   # 승인 말풍선 → 이미 승인됨
        if below:
            self._done_question(deny_el, "    (확인 질문이 이미 승인되어 있습니다)")
            return True
        if not above:
            return False
        try:
            above[1].click(timeout=3000)
        except PlaywrightError:
            return False
        self._done_question(deny_el, "    에이전트 확인 질문에 [승인]을 눌렀습니다.")
        return True

    def _done_question(self, deny_el, message):
        try:
            deny_el.evaluate("e => e.setAttribute('data-cavn-old', '1')", timeout=2000)
        except PlaywrightError:
            pass
        self.approved = True
        log(message)

    REFUSE_JS = """() => {
        const re = /정책|유명인|실존 인물|만들 수 없|생성할 수 없|생성할 수가 없|policy|violat|can.?t (generate|create)|unable to (generate|create)|public figure|celebrit/i;
        return [...document.querySelectorAll('p, div, span')].filter(e => {
            const own = [...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join(' ').trim();
            const r = e.getBoundingClientRect();
            return own.length > 6 && re.test(own) && r.width > 0 && r.height > 0;
        }).length;
    }"""

    NEED_IMAGE_JS = """() => [...document.querySelectorAll('p, div, span')].filter(e => {
        const own = [...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join(' ').trim();
        const r = e.getBoundingClientRect();
        return own.length > 6 && /이미지를 (선택|첨부|올려|알려)|첨부해 주|어떤 이미지|which image|select an image|attach an image/i.test(own)
            && r.width > 0 && r.height > 0;
    }).length"""

    def need_image_count(self):
        """대화 창의 '영상에 쓸 이미지를 선택(첨부)해 주세요' 같은 답 수."""
        try:
            return self.page.evaluate(self.NEED_IMAGE_JS)
        except PlaywrightError:
            return 0

    ASK_JS = """() => [...document.querySelectorAll('p, div, span')].filter(e => {
        const own = [...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join(' ').trim();
        const r = e.getBoundingClientRect();
        return own.length > 6 && /하시겠습니까|할까요\\?|진행할까요|would you like|do you want/i.test(own) && r.width > 0 && r.height > 0;
    }).length"""

    def ask_count(self):
        """대화 창의 '…시작하시겠습니까?' 같은 확인 질문 글 수."""
        try:
            return self.page.evaluate(self.ASK_JS)
        except PlaywrightError:
            return 0

    def refusal_count(self):
        """대화 창에 '정책 위반 / 유명인과 닮음 → 만들 수 없음' 같은 거절 글이 몇 개 있는지."""
        try:
            return self.page.evaluate(self.REFUSE_JS)
        except PlaywrightError:
            return 0

    def wait_new(self, kind, before_keys, want, timeout, settle=10, after_approval=False, refusals_before=None,
                 on_need_image=None, need_before=None):
        """kind 칸이 want 개 이상 새로 생기고 settle 초 동안 늘지 않을 때까지 기다린다.
        after_approval: 확인 질문이 뜨면 승인된 뒤에 생긴 것만 센다 (그 사이 끝난 다른 트랙 영상을 잘못 세지 않게).
        질문이 90초 안에 안 뜨면(이미 '항상 승인'인 경우) 그냥 센다."""
        deadline = time.time() + timeout
        start = time.time()
        last_count, last_change, last_note = -1, time.time(), 0
        before_keys = set(before_keys)
        fails_before = self.failed_count()
        send_tries = [40, 150]   # [승인] 칸이 안 보이면 이 초에 보내기(→) 화살표를 눌러 본다
        if refusals_before is None:   # 보내기 전에 센 값을 받는 게 정확함 (거절이 바로 뜰 수도 있어서)
            refusals_before = self.refusal_count() if kind == "video" else 0
        if need_before is None:   # 보내기 전에 센 값을 받는 게 정확함 (답이 바로 올 수도 있어서)
            need_before = self.need_image_count() if on_need_image else 0
        while time.time() < deadline:
            self.click_retry()
            if on_need_image and self.need_image_count() > need_before:
                # 에이전트가 '어떤 이미지로 만들지 선택해 주세요' 하고 멈춤 → 이미지를 다시 올리고 제목을 적어 다시 보낸다
                log("  에이전트가 영상에 쓸 이미지를 물어서, 이미지를 다시 올리고 제목을 적어 보냅니다")
                need_before = self.need_image_count()
                on_need_image()
                on_need_image = None
                start = time.time()
                continue
            if kind == "video" and self.refusal_count() > refusals_before:
                raise VideoRefused("Flow 가 영상을 만들 수 없다고 했습니다 (정책 위반·유명인과 닮음 등).")
            was_approved = self.approved
            self.approve()
            if after_approval:
                if self.approved and not was_approved:
                    before_keys |= {t["key"] for t in self.tiles(kind)}   # 승인 전에 있던 영상은 제외
                    last_count = -1
                if (self.question_seen and not self.approved) or (not self.question_seen and time.time() - start < 90):
                    if send_tries and time.time() - start > send_tries[0]:
                        send_tries.pop(0)
                        # 확인 질문 글은 새로 떴는데 [승인] 칸을 못 찾을 때만
                        if self.ask_count() > getattr(self, "asks_before", 0) and self.click_send():
                            log("    [승인] 칸이 안 보여서 프롬프트 칸의 보내기(→) 화살표를 눌렀습니다.")
                            self.question_seen = self.approved = True   # 화살표가 [승인]으로 보내진다
                    if time.time() - last_note > 60:
                        log("  확인 질문(승인)을 기다리는 중... (못 누르면 Flow 에서 [승인]을 직접 눌러 주세요)")
                        last_note = time.time()
                    time.sleep(3)
                    continue
            if kind == "video":
                # 새 영상은 격자 맨 앞에 생긴다. 격자를 내렸다 올리면 예전 영상의 주소가 바뀌어 새 것처럼 보일 수 있어서
                # (7번 트랙에 3번 영상을 받던 문제) 맨 위 줄에 있는 영상만 센다
                self._scroll_grid(to_top=True)
                every = self.tiles()
                top = {t["key"] for t in every if t["y"] <= min((u["y"] for u in every), default=0) + 40}
                new = [t for t in every if t["kind"] == "video" and t["key"] in top
                       and t["key"] not in before_keys and not t["key"].endswith(":")]
            else:
                self._scroll_grid(to_top=True)
                new = [t for t in self.tiles(kind) if t["key"] not in before_keys and not t["key"].endswith(":")]
            if new and time.time() - start < NEW_GRACE_SEC:
                # 이렇게 빨리 생길 수는 없다 → 화면이 다시 그려져 주소가 바뀐 예전 칸 (새 이미지 50개 문제)
                before_keys |= {t["key"] for t in new}
                new = []
            fails = max(0, self.failed_count() - fails_before)   # Flow 가 못 만든 칸 ('실패 … 수요가 많습니다')
            if len(new) + fails != last_count:
                last_count, last_change = len(new) + fails, time.time()
            if len(new) >= want and time.time() - last_change >= settle:
                return new
            if new and fails and len(new) + fails >= want and time.time() - last_change >= FAIL_SETTLE_SEC:
                log(f"  !! Flow 가 {fails}장은 만들지 못했습니다(실패). 만들어진 {len(new)}장으로 진행합니다.")
                return new
            if new and time.time() - last_change > 180:   # 3분 동안 더 안 생기면 있는 것만 사용
                log(f"  !! {kind} {len(new)}개만 만들어져서 그대로 진행합니다.")
                return new
            if time.time() - last_note > 60:
                log(f"  기다리는 중... (새 {'이미지' if kind == 'image' else '영상'} {len(new)}개)")
                last_note = time.time()
            time.sleep(3)
        raise RuntimeError(f"{'이미지가' if kind == 'image' else '영상이'} 제한 시간 안에 다 만들어지지 않았습니다.")

    FAILED_JS = """() => [...document.querySelectorAll('*')].filter(e => {
        const own = [...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join(' ');
        const r = e.getBoundingClientRect();
        return /^\\s*(warning\\s*)?실패(\\s|$)|^\\s*Failed(\\s|$)/.test(own) && r.width > 0 && r.height > 0;
    }).length"""

    def failed_count(self):
        """격자에 있는 '실패' 칸 수."""
        try:
            return self.page.evaluate(self.FAILED_JS)
        except PlaywrightError:
            return 0

    RETRY_RE = re.compile(r"^\s*(refresh\s*)?(다시\s*시도|Try again|Retry)\s*$", re.I)

    def click_retry(self):
        """대화 창에 오류와 함께 [다시 시도]가 뜨면 누른다 (안 누르면 다음으로 안 넘어감).
        글자로 '다시 시도'라고 적힌 버튼만 누른다 (격자의 실패 칸에 있는 아이콘 버튼은 누르지 않음)."""
        try:
            cands = self.page.get_by_role("button", name=self.RETRY_RE).all() + \
                self.page.get_by_text(re.compile(r"^\s*다시\s*시도\s*$")).all()
            for el in cands:
                # 한 번 누른 버튼(과 그 안의 글씨)은 다시 누르지 않는다
                if not el.is_visible() or el.evaluate(
                        "e => !!(e.closest('[data-cavn-retried]') || e.querySelector('[data-cavn-retried]'))"):
                    continue
                text = (el.inner_text() or "").strip()
                if not re.search(r"다시\s*시도|Try again|Retry", text, re.I):
                    continue
                el.evaluate("e => (e.closest('button,[role=button]') || e).setAttribute('data-cavn-retried', '1')")
                el.click()
                log("  Flow 에 오류가 떠서 [다시 시도]를 눌렀습니다.")
                time.sleep(3)
                return True
        except PlaywrightError:
            pass
        return False

    # -- 캐릭터 ([+] → 캐릭터 → 프로젝트 '캐릭터목록' → 이름 → [프롬프트에 추가])
    def _boxes(self, loc, region=None):
        """보이는 것들 중 region(x0, x1, y0, y1) 안에 가운데가 있는 것 [(요소, 상자)]."""
        out = []
        for el, box in self._visible_boxes(loc):
            cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            if region and not (region[0] <= cx <= region[1] and region[2] <= cy <= region[3]):
                continue
            out.append((el, box))
        return out

    def _open_asset_picker(self):
        """프롬프트 칸 아래쪽의 [+] 를 눌러 애셋 고르기 창을 연다. 창의 검색칸 상자를 돌려준다."""
        search = self.page.get_by_placeholder(re.compile("애셋 검색|Search assets", re.I))
        found = self._boxes(search)
        if found:
            return found[0][1]
        pb = self.prompt_box().bounding_box()
        # 화면 맨 아래 프롬프트 칸 옆(왼쪽 아래)의 [+] (맨 위 [+] 가 아님 → 프롬프트 칸 근처만 본다)
        plus = self._boxes(self.page.get_by_role("button", name=re.compile(r"^\s*(add|\+)\s*$|추가|add media|add asset", re.I)),
                           (pb["x"] - 80, pb["x"] + pb["width"] + 40, pb["y"] - 20, pb["y"] + pb["height"] + 120))
        if not plus:
            raise RuntimeError("프롬프트 칸의 [+] 버튼을 찾지 못했습니다.")
        plus.sort(key=lambda eb: (eb[1]["x"], -eb[1]["y"]))   # 프롬프트 칸 왼쪽 아래의 [+]
        plus[0][0].click()
        for _ in range(20):
            time.sleep(0.5)
            found = self._boxes(search)
            if found:
                return found[0][1]
        raise RuntimeError("[+] 를 눌러도 애셋 고르기 창이 열리지 않았습니다.")

    def _click_text_in(self, text, region, exact=True):
        loc = self.page.get_by_text(text, exact=exact) if exact else self.page.get_by_text(text)
        found = self._boxes(loc, region)
        if not found:
            return False
        found.sort(key=lambda eb: (eb[1]["y"], eb[1]["x"]))
        found[0][0].click()
        time.sleep(1)
        return True

    def _prompt_attach_count(self):
        """프롬프트 칸 위에 올라가 있는 그림(캐릭터·이미지) 수."""
        try:
            pb = self.prompt_box(wait=3).bounding_box()
        except (RuntimeError, PlaywrightError):
            return 0
        if not pb:
            return 0
        # 프롬프트 칸은 섀도 DOM 안에 있어서, 숨은 칸 안까지 내려가며 그림(img·video·배경 그림)을 센다
        return self.page.evaluate("""pb => {
            const all = [];
            const walk = root => {
                for (const e of root.querySelectorAll('*')) {
                    all.push(e);
                    if (e.shadowRoot) walk(e.shadowRoot);
                }
            };
            walk(document);
            return all.filter(m => {
                const r = m.getBoundingClientRect();
                if (r.width < 12 || r.width > 160 || r.height < 12 || r.height > 160) return false;
                const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
                if (!(cx > pb.x - 40 && cx < pb.x + pb.width + 40 && cy > pb.y - 140 && cy < pb.y + pb.height + 30)) return false;
                if (m.tagName === 'IMG' || m.tagName === 'VIDEO' || m.tagName === 'CANVAS') return true;
                const bg = getComputedStyle(m).backgroundImage;
                return bg && bg !== 'none' && bg.includes('url(');
            }).length;
        }""", pb)

    def _picker_rect(self):
        """애셋 고르기 창 전체의 상자 (검색칸에서 위로 올라가며 충분히 큰 상자). 못 찾으면 None."""
        boxes = self._boxes(self.page.get_by_placeholder(re.compile("애셋 검색|Search assets", re.I)))
        if not boxes:
            return None
        # 왼쪽 종류 칸(전체·이미지·…·캐릭터)과 왼쪽 위 프로젝트 칸까지 들어 있어야 하므로,
        # 검색칸보다 왼쪽으로 충분히 넓고(100px 이상) 화면 전체는 아닌 상자를 고른다
        return boxes[0][0].evaluate("""e => {
            const sb = e.getBoundingClientRect();
            let p = e;
            for (let i = 0; i < 20 && p.parentElement; i++) {
                p = p.parentElement;
                const r = p.getBoundingClientRect();
                if (r.width >= innerWidth * 0.85 || r.height >= innerHeight * 0.95) break;
                if (r.left <= sb.left - 100 && r.width >= 450 && r.height >= 250)
                    return {x: r.left, y: r.top, width: r.width, height: r.height};
            }
            return null;
        }""")

    def _picker_open(self):
        return bool(self._boxes(self.page.get_by_placeholder(re.compile("애셋 검색|Search assets", re.I))))

    def close_picker(self):
        """애셋 고르기 창이 열려 있으면 닫는다. 열린 채로 두면 뒤의 격자를 훑거나(스캔) 이미지를 올릴 수 없다."""
        for k in range(6):
            if not self._picker_open():
                return True
            if k < 4:
                self.page.keyboard.press("Escape")
            else:   # Esc 로 안 닫히면 프롬프트 칸을 한 번 눌러 창 밖을 누른다
                try:
                    pb = self.prompt_box(wait=3).bounding_box()
                    self.page.mouse.click(pb["x"] + pb["width"] / 2, pb["y"] + pb["height"] / 2)
                except (RuntimeError, PlaywrightError, TypeError):
                    pass
            time.sleep(1)
        if self._picker_open():
            log("    !! 애셋 고르기 창이 닫히지 않습니다")
            return False
        return True

    def add_character(self, name, project):
        """캐릭터 하나를 프롬프트 칸에 올린다. 안 되면 창을 닫고 한 번 더 해 본다."""
        for attempt in (1, 2):
            try:
                return self._add_character_once(name, project)
            except (RuntimeError, PlaywrightError) as e:
                if attempt == 2:
                    raise
                log(f"    (캐릭터 올리기 다시 시도: {str(e).splitlines()[0]})")
                self.close_picker()
            finally:
                if attempt == 2:
                    self.close_picker()

    def _add_character_once(self, name, project):
        attached_before = self._prompt_attach_count()
        sb = self._open_asset_picker()
        # 고르기 창 안만 본다 (창 밖 격자의 영상 ▶ 단추를 프로젝트 칸으로 잘못 누르던 문제)
        pr = self._picker_rect() or {"x": sb["x"] - 200, "y": sb["y"] - 40, "width": 10_000, "height": 10_000}
        px0, px1, py1 = pr["x"] - 2, pr["x"] + pr["width"] + 2, pr["y"] + pr["height"] + 2
        vh = self.page.evaluate("innerHeight")
        # 왼쪽 종류 칸(전체·이미지·…·캐릭터)은 창 상자를 잘못 잡아도 놓치지 않게 검색칸 왼쪽 아래를 넓게 본다
        left_col = (min(px0, sb["x"] - 320), sb["x"] - 5, sb["y"] + sb["height"], max(py1, vh))
        below = (px0, px1, sb["y"] + sb["height"], py1 + 600)          # 창 안쪽 (검색칸 아래, 펼친 목록 포함)
        # 1) 왼쪽 '캐릭터' (창이 막 열렸을 때는 종류 칸이 늦게 그려질 수 있음)
        for k in range(8):
            if self._click_text_in("캐릭터", left_col):
                break
            time.sleep(1)
        else:
            raise RuntimeError("애셋 고르기 창에서 '캐릭터'를 찾지 못했습니다.")
        # 2) 왼쪽 위 프로젝트 고르기 → '캐릭터목록'
        if not self._boxes(self.page.get_by_text(name, exact=True), (sb["x"] - 10, px1, sb["y"], py1)):
            row = (px0, sb["x"] - 5, sb["y"] - 15, sb["y"] + sb["height"] + 15)
            drop = []
            play = re.compile(r"play|재생|▶", re.I)
            for k in range(8):   # 창이 막 열렸을 때는 왼쪽 위 칸이 늦게 그려질 수 있음
                if k == 3:   # 프롬프트 칸이 가운데로 가 있으면 창 모양이 달라짐 → 검색칸 왼쪽을 더 넓게
                    row = (min(row[0], sb["x"] - 900), row[1], row[2], row[3])
                drop = [(e, bx) for e, bx in self._boxes(self.page.locator("button, [role=button], [role=combobox]"), row)
                        if not play.search((e.text_content() or "") + " " + (e.get_attribute("aria-label") or ""))]
                if drop:
                    break
                time.sleep(1)
            if not drop:
                raise RuntimeError("애셋 고르기 창 왼쪽 위의 프로젝트 고르기 칸을 찾지 못했습니다.")
            # 날짜(프로젝트 이름) 옆의 아래 화살표를 눌러야 프로젝트 목록이 펼쳐진다
            # → 화살표나 날짜(숫자)가 들어 있는 칸을 먼저, 그다음 왼쪽부터
            arrowish = re.compile(r"arrow_drop_down|expand_more|keyboard_arrow_down|▾|▼|\d")
            drop.sort(key=lambda eb: (not arrowish.search(eb[0].text_content() or ""), eb[1]["x"]))
            el, box = drop[0]
            arrow = self._boxes(self.page.get_by_text(re.compile(r"^\s*(arrow_drop_down|expand_more|keyboard_arrow_down|▾|▼)\s*$")),
                                (box["x"], box["x"] + box["width"] + 10, box["y"] - 5, box["y"] + box["height"] + 5))
            if arrow:
                arrow[0][0].click()
            else:
                self.page.mouse.click(box["x"] + box["width"] - 12, box["y"] + box["height"] / 2)
            time.sleep(1)
            if not self._boxes(self.page.get_by_text(project, exact=True), below):
                el.click()   # 화살표로 안 열리면 칸 자체를 한 번 더
                time.sleep(1)
            # 프로젝트가 많아지면 '캐릭터목록' 이 목록 아래쪽에 있음 → 목록을 내려 가며 찾는다
            found = False
            for _ in range(15):
                if self._click_text_in(project, below):
                    found = True
                    break
                self.page.mouse.move(box["x"] + 80, box["y"] + box["height"] + 120)
                self.page.mouse.wheel(0, 300)
                time.sleep(0.7)
            if not found:
                self.page.keyboard.press("Escape")
                raise RuntimeError(f"프로젝트 '{project}' 를 찾지 못했습니다. Flow 프로젝트 이름을 확인해 주세요.")
        # 3) 이름 찾기: 검색칸에 이름을 넣고, 그래도 안 보이면 목록을 내려 가며
        search = self._boxes(self.page.get_by_placeholder(re.compile("애셋 검색|Search assets", re.I)))
        if search:
            search[0][0].fill(name)
            time.sleep(1.5)
        list_area = (sb["x"] - 10, sb["x"] + sb["width"] * 0.6, sb["y"] + sb["height"], py1)
        for _ in range(15):
            if self._click_text_in(name, list_area):
                break
            self.page.mouse.move(sb["x"] + 80, sb["y"] + 150)
            self.page.mouse.wheel(0, 400)
            time.sleep(0.8)
        else:
            self.page.keyboard.press("Escape")
            raise RuntimeError(f"캐릭터 '{name}' 을(를) 찾지 못했습니다. 캐릭터목록 프로젝트의 이름을 확인해 주세요.")
        # 4) [프롬프트에 추가] (이름을 누르는 것만으로 올라가고 창이 닫히는 경우도 있음)
        clicked_add = False
        for _ in range(6):
            if self._prompt_attach_count() > attached_before:   # 벌써 올라갔으면 끝
                break
            if not self._picker_open():   # 이름을 누르자 창이 닫힘 = 바로 올라간 것
                clicked_add = True
                break
            add = self._boxes(self.page.get_by_role("button", name=re.compile("프롬프트에 추가|Add to prompt", re.I)))
            if not add:
                add = self._boxes(self.page.get_by_text(re.compile(r"프롬프트에\s*추가|Add to prompt", re.I)))
            if add:
                add[-1][0].click()
                clicked_add = True
                time.sleep(1.5)
                break
            time.sleep(1)
        # 그림을 셀 수 없게 그려지는 경우도 있으니, [프롬프트에 추가]를 눌렀으면 (창이 남아 있으면 닫고) 올라간 것으로 본다
        added = self._prompt_attach_count() > attached_before or clicked_add
        if not added:
            if self._picker_open():
                self.page.keyboard.press("Escape")
            raise RuntimeError(f"캐릭터 '{name}' 를 프롬프트에 올리지 못했습니다 ([프롬프트에 추가] 버튼을 찾지 못함).")
        self.close_picker()
        log(f"    캐릭터 '{name}' 를 프롬프트에 올림")

    def drag(self, source, target):
        """source 를 target 에 끌어다 놓는다. 둘 다 화면 안에 있어야 한다 (아니면 False).
        (격자를 내려서 그림을 보이게 하면 맨 위 컬렉션 칸이 화면 밖으로 나가 놓기가 안 되던 문제)"""
        page = self.page
        source.scroll_into_view_if_needed()
        s = source.bounding_box()
        t = target.bounding_box()
        vh = page.evaluate("innerHeight")
        off = lambda b: not b or b["y"] < 0 or b["y"] + b["height"] / 2 > vh
        if off(t):
            self._scroll_grid(to_top=True)
            time.sleep(0.8)
            s, t = source.bounding_box(), target.bounding_box()
        if off(s) or off(t):
            return False
        page.mouse.move(s["x"] + s["width"] / 2, s["y"] + s["height"] / 2)
        page.mouse.down()
        steps = 12
        for i in range(1, steps + 1):
            page.mouse.move(s["x"] + s["width"] / 2 + (t["x"] + t["width"] / 2 - s["x"] - s["width"] / 2) * i / steps,
                            s["y"] + s["height"] / 2 + (t["y"] + t["height"] / 2 - s["y"] - s["height"] / 2) * i / steps)
            time.sleep(0.05)
        time.sleep(0.3)
        page.mouse.up()
        time.sleep(1)
        return True

    # -- 컬렉션
    # 눌러서는 안 되는 버튼: 에이전트 창 [닫기 ✕] (누르면 프롬프트 칸이 가운데로 내려가 다음 일이 다 꼬임),
    # 세션 기록·새 세션, 설정·도움말, 접기, 그림 칸
    NO_CLICK_RE = re.compile(r"닫기|close|세션|session|기록|history|edit|menu|설정|settings|도움|help|접기|collapse|expand|"
                             r"keyboard_arrow|more_vert|계정|account", re.I)

    def new_collection(self):
        page = self.page
        before = len(self.tiles("collection"))
        # 왼쪽 '라이브러리' 옆 [+] 가 바로 새 컬렉션을 만든다 → 이것부터
        item = self._library_plus()
        if item is not None:
            log("    [+] 시도: 왼쪽 라이브러리 [+]")
            return self._finish_collection(item, before)
        # 화면 맨 위 줄, 검색칸 오른쪽에 모인 버튼들(+, ?, ⚙, ⋮, 그 오른쪽의 에이전트 창 버튼들) 중 맨 왼쪽 = [+]
        # (그림만 있고 글자가 없어서 위치로 찾는다. 대화 창 입력칸의 + 와 '새 세션' 버튼은 아님)
        width = page.evaluate("innerWidth")
        # 검색칸 바로 옆의 필터 버튼은 빼려고, 검색칸 오른쪽 끝보다 충분히 오른쪽에 있는 버튼만 본다
        searches = [b for _, b in self._visible_boxes(page.locator("input")) if b["y"] < 200]
        search = max(searches, key=lambda b: b["width"]) if searches else None
        search_right = search["x"] + search["width"] if search else width * 0.55
        row_y = search["y"] + search["height"] / 2 if search else 60   # 검색칸과 같은 가로줄 (에이전트 창 버튼은 그 아래)
        top = []
        for el, box in self._visible_boxes(page.locator("button, [role=button]")):
            same_row = abs(box["y"] + box["height"] / 2 - row_y) < 25
            if same_row and box["x"] > search_right + 100 and box["width"] < 80:
                try:
                    label = el.evaluate("e => ((e.getAttribute('aria-label') || '') + ' ' + (e.innerText || '')).trim()",
                                        timeout=2000)
                except PlaywrightError:
                    label = ""
                if self.NO_CLICK_RE.search(label) or len(label) > 12 and not re.search(r"\badd\b|추가|\+", label):
                    continue
                top.append((box["x"], label, el))
        # 맨 왼쪽부터 하나씩 눌러 보고 '새 컬렉션' 메뉴가 뜨는 버튼을 쓴다 (아니면 Esc 로 닫고 다음 버튼).
        # 그래도 안 되면 왼쪽 '라이브러리' 옆 [+]. 무엇을 눌렀고 무엇이 떴는지 까만 창에 남긴다.
        tried = []
        item = None
        for x, label, el in sorted(top, key=lambda t: t[0])[:3]:
            try:
                el.click(timeout=3000)
            except PlaywrightError:
                continue
            item = self._find_menu_item("새 컬렉션")
            tried.append(f"x={int(x)} '{label[:15]}' → {self._menu_texts() or '메뉴 없음'}")
            if item:
                break
            page.keyboard.press("Escape")
            time.sleep(0.6)
        log("    [+] 시도: " + " / ".join(tried or ["화면 맨 위 줄 버튼 없음"]))
        if item is None:
            raise RuntimeError("'새 컬렉션' 메뉴를 찾지 못했습니다.")
        return self._finish_collection(item, before)

    def _finish_collection(self, item, before):
        if item is not True:   # True = 라이브러리 [+] 가 메뉴 없이 바로 컬렉션을 만든 경우
            item.click()
        for _ in range(20):
            time.sleep(0.5)
            cols = self.tiles("collection")
            if len(cols) > before:
                return cols[0]["key"]   # 새 컬렉션은 격자 맨 앞에 생김
        raise RuntimeError("새 컬렉션이 만들어지지 않았습니다.")

    def _find_menu_item(self, text, wait=3):
        """열린 메뉴에서 text 가 들어 있는 가장 작은 항목 (아이콘 이름이 붙어 있어도 됨)."""
        page = self.page
        deadline = time.time() + wait
        while time.time() < deadline:
            time.sleep(0.5)
            for loc in (page.get_by_role("menuitem", name=re.compile(text)), page.get_by_text(re.compile(text))):
                found = [(box["width"] * box["height"], el) for el, box in self._visible_boxes(loc)]
                if found:
                    return min(found, key=lambda t: t[0])[1]
        return None

    def _menu_texts(self):
        texts = []
        for el, _ in self._visible_boxes(self.page.locator("[role=menu], [role=menuitem], [role=dialog]"))[:6]:
            try:
                t = el.evaluate("e => (e.innerText || '').replace(/\\s+/g, ' ').trim()", timeout=2000)
            except PlaywrightError:
                t = ""
            if t:
                texts.append(t[:40])
        return ", ".join(texts)

    def _library_plus(self):
        """왼쪽 '라이브러리' 글씨와 같은 줄의 [+]. 메뉴가 뜨면 '새 컬렉션' 항목, 바로 만들어지면 True."""
        page = self.page
        labels = self._visible_boxes(page.get_by_text(re.compile(r"^\s*라이브러리\s*$")))
        if not labels:
            return None
        _, lab = labels[0]
        cy = lab["y"] + lab["height"] / 2
        before = len(self.tiles("collection"))
        for el, box in self._visible_boxes(page.locator("button, [role=button]")):
            if abs(box["y"] + box["height"] / 2 - cy) < 20 and box["x"] > lab["x"] + lab["width"] and box["x"] < lab["x"] + 400:
                try:
                    label = el.evaluate("e => ((e.getAttribute('aria-label') || '') + ' ' + (e.innerText || '')).trim()",
                                        timeout=2000)
                except PlaywrightError:
                    label = ""
                if self.NO_CLICK_RE.search(label):   # 라이브러리 접기(^) 는 누르지 않는다
                    continue
                try:
                    el.click(timeout=3000)
                except PlaywrightError:
                    continue
                item = self._find_menu_item("새 컬렉션", wait=2)
                if item is not None:
                    return item
                if len(self.tiles("collection")) > before:
                    return True
                page.keyboard.press("Escape")
        return None

    def hover_menu(self, key):
        """칸에 마우스를 올리면 나오는 [⋮] 를 누른다."""
        tile = self.tile(key)
        tile.scroll_into_view_if_needed()
        tile.hover()
        time.sleep(0.8)
        box = tile.bounding_box()
        buttons = self.page.locator("button").filter(has_text=re.compile(r"more_vert|more_horiz|⋮"))
        buttons = [b for b in buttons.all() if b.is_visible()] or \
            [b for b in self.page.get_by_role("button", name=re.compile("더보기|옵션|More|options", re.I)).all()
             if b.is_visible()]
        inside = []
        for b in buttons:
            r = b.bounding_box()
            if r and box["x"] <= r["x"] <= box["x"] + box["width"] and box["y"] <= r["y"] <= box["y"] + box["height"]:
                inside.append(b)
        if not inside:
            raise RuntimeError("칸 위의 [⋮] 버튼을 찾지 못했습니다.")
        inside[0].click()
        time.sleep(0.8)

    def download_via_menu(self, key, item_re, dest_dir, name_hint, sub_re=None):
        page = self.page
        self.hover_menu(key)
        with page.expect_download(timeout=DOWNLOAD_TIMEOUT_MS) as info:
            page.get_by_text(item_re).filter(visible=True).first.click()
            if sub_re:
                # 화질 등을 고르는 작은 메뉴가 더 뜨면 첫 번째 항목 (안 뜨면 그냥 넘어감)
                try:
                    page.get_by_text(sub_re).filter(visible=True).first.click(timeout=3000)
                except PlaywrightError:
                    pass
        dl = info.value
        dest = Path(dest_dir) / (name_hint + (Path(dl.suggested_filename).suffix or ".zip").lower())
        dl.save_as(dest)
        page.keyboard.press("Escape")
        return dest

    def collection_count(self):
        """새 컬렉션 칸에 적힌 그림 수 ('제목 없는 컬렉션 9' → 9, 비어 있으면 0). 못 읽으면 None."""
        cols = self.tiles("collection")
        if not cols:
            return None
        nums = re.findall(r"\d+", cols[0]["text"].replace("컬렉션", " "))
        return int(nums[-1]) if nums else 0

    def first_collection(self):
        cols = self.tiles("collection")
        if not cols:
            raise RuntimeError("컬렉션을 찾지 못했습니다.")
        return cols[0]["key"]   # 새로 만든 컬렉션은 격자 맨 앞

    def download_collection(self, key, dest_dir, n_expected, menu_re=None, sub_re=None, kinds=None):
        """[⋮] → [컬렉션 다운로드]. 압축 파일 하나로 오든, 이미지가 낱개로 여러 개 오든 모두 받는다.
        - 다운로드는 새로 열리는 창(탭)에서 일어날 수 있어서, 모든 창의 다운로드를 지켜본다.
        - 크롬이 프로그램을 거치지 않고 바로 '다운로드' 폴더에 저장하는 경우도 있어서,
          그 폴더에 새로 생긴 이미지/zip 도 찾아 복사한다.
        - 다운로드 때문에 열린 창은 다 받은 뒤 닫는다."""
        page = self.page
        context = page.context
        got = []

        def on_download(dl):
            got.append(dl)

        def on_page(p):
            p.on("download", on_download)
        watched = list(context.pages)
        for p in watched:
            p.on("download", on_download)
        context.on("page", on_page)
        pages_before = set(context.pages)
        start = time.time()
        # 프로그램이 크롬을 조종하는 동안에는 받은 파일이 임시 폴더에 이상한 이름으로 저장되므로,
        # 크롬에게 '다운로드\Flow_컬렉션' 폴더에 원래 이름(제목 없는 컬렉션.zip …)으로 저장하라고 지정한다
        watch_dirs = [DOWNLOADS_DIR]
        collect_dir = DOWNLOADS_DIR / "Flow_컬렉션"
        try:
            collect_dir.mkdir(parents=True, exist_ok=True)
            browser = context.browser
            if browser is not None:
                cdp = browser.new_browser_cdp_session()
                cdp.send("Browser.setDownloadBehavior",
                         {"behavior": "allow", "downloadPath": str(collect_dir.resolve()), "eventsEnabled": True})
                watch_dirs.insert(0, collect_dir)
        except Exception as e:  # 안 되면 보통 다운로드 폴더만 지켜본다
            log(f"    (다운로드 폴더 지정 실패, 기본 다운로드 폴더를 봅니다: {str(e).splitlines()[0]})")
        try:
            page.evaluate("""() => { for (const o of [window, Window.prototype]) {
                try { delete o.showSaveFilePicker; } catch (e) {} } }""")
            self.hover_menu(key)
            menu_re = menu_re or re.compile("컬렉션 다운로드|Download collection", re.I)
            kinds = kinds or (".zip",) + IMAGE_EXTS
            page.get_by_text(menu_re).filter(visible=True).first.click()
            if sub_re:   # 화질 등을 고르는 작은 메뉴가 더 뜨면 첫 번째 항목 (안 뜨면 그냥 넘어감)
                try:
                    page.get_by_text(sub_re).filter(visible=True).first.click(timeout=3000)
                except PlaywrightError:
                    pass
            deadline = time.time() + DOWNLOAD_TIMEOUT_MS / 1000
            last = (0, time.time())
            folder_files = []
            fronted = False
            while time.time() < deadline:
                time.sleep(1)
                if not fronted and any(p not in pages_before for p in context.pages):
                    page.bring_to_front()   # 다운로드 창이 열려도 작업 화면을 앞으로 (뒤로 가면 화면이 멈출 수 있음)
                    fronted = True
                folder_files = [f for d in watch_dirs for f in new_files_in(d, start) if sniff_ext(f) in kinds]
                count = len(got) + len(folder_files)
                if count != last[0]:
                    last = (count, time.time())
                names = [d.suggested_filename.lower() for d in got] + [f.name.lower() for f in folder_files]
                one_zip = any(n.endswith(".zip") for n in names)
                idle = time.time() - last[1]
                if count and (one_zip and idle > 3 or count >= n_expected and idle > 3 or idle > 60):
                    break
            if not got and not folder_files:
                raise RuntimeError("컬렉션 다운로드가 시작되지 않았습니다.")
            saved = []
            for i, dl in enumerate(got, 1):
                dest = unique_path(Path(dest_dir), Path(dl.suggested_filename).name or f"image_{i}")
                dl.save_as(dest)
                kind = sniff_ext(dest)
                if kind not in kinds:   # 덜 받아졌거나 다른 파일 → 버림
                    dest.unlink(missing_ok=True)
                    continue
                if dest.suffix.lower() != kind:
                    fixed = unique_path(Path(dest_dir), dest.stem + kind)
                    dest.rename(fixed)
                    dest = fixed
                saved.append(dest)
            if not saved and folder_files:   # 크롬이 '다운로드' 폴더에 직접 저장한 경우 → 그 파일을 옮김
                # (복사하면 다운로드 폴더에 '제목 없는 컬렉션' 파일이 계속 쌓여서 어느 앨범 것인지 헷갈림)
                log(f"    ('{folder_files[0].parent}' 에 저장된 {len(folder_files)}개를 옮깁니다)")
                for f in folder_files:
                    kind = sniff_ext(f)
                    name = f.name if f.suffix.lower() == kind else f.stem + kind
                    dest = unique_path(Path(dest_dir), name)
                    try:
                        shutil.move(str(f), str(dest))
                    except OSError:   # 크롬이 아직 잡고 있으면 복사만
                        shutil.copy2(f, dest)
                    saved.append(dest)
            if not saved:
                raise RuntimeError("받은 파일이 이미지·영상이 아니거나 덜 받아졌습니다.")
            return saved
        finally:
            for p in watched:
                try:
                    p.remove_listener("download", on_download)
                except Exception:
                    pass
            try:
                context.remove_listener("page", on_page)
            except Exception:
                pass
            for p in context.pages:   # 다운로드 때문에 열린 창은 닫기
                if p not in pages_before and p != page:
                    try:
                        p.close()
                    except PlaywrightError:
                        pass
            try:
                page.bring_to_front()
                page.keyboard.press("Escape")
            except PlaywrightError:
                pass

    def save_video_src(self, key, dest):
        src = self.tile(key).locator("video").first.evaluate("v => v.currentSrc || v.src")
        resp = self.page.request.get(src)
        if not resp.ok:
            raise RuntimeError("영상 파일을 받지 못했습니다.")
        dest.write_bytes(resp.body())
        return dest


def _css_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


DOWNLOADS_DIR = Path.home() / "Downloads"   # 크롬 기본 다운로드 폴더


PARTIAL_EXTS = (".crdownload", ".tmp", ".part", ".partial", ".download")


def new_files_in(folder, since):
    """folder 에 since 이후 새로 생긴, 다 받아진 이미지/zip 파일들.
    Flow 는 확장자 없는 이름(예: 32035c07-e744-…)으로 내려줄 때가 있어서 속 내용으로 판단한다."""
    if not folder.is_dir():
        return []
    out = []
    for f in folder.iterdir():
        try:
            st = f.stat()
        except OSError:
            continue
        if not f.is_file() or st.st_mtime < since - 2 or f.suffix.lower() in PARTIAL_EXTS:
            continue
        if sniff_ext(f):
            out.append(f)
    return sorted(out, key=lambda f: f.stat().st_mtime)


def sniff_ext(path):
    """파일 앞부분을 보고 .zip / .jpg / .png / .webp / .mp4 / .webm 중 무엇인지 (모르면 '')."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(12)
    except OSError:
        return ""
    if head.startswith(b"PK\x03\x04"):
        return ".zip"
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if head.startswith(b"\x89PNG"):
        return ".png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    if head[4:8] == b"ftyp":
        return ".mp4"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return ".webm"
    return ""


def unique_path(folder, name):
    dest = folder / name
    n = 1
    while dest.exists():
        dest = folder / f"{Path(name).stem}_{n}{Path(name).suffix}"
        n += 1
    return dest


def extract_images(zip_path, dest_dir):
    count = 0
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            # 그림 제목에 ':' 같은 글자가 있으면 윈도우 파일 이름으로 못 씀 (예: 'Clock showing 11:45 PM')
            name = re.sub(r'[\\/:*?"<>|]', "_", info.filename.replace("\\", "/").split("/")[-1]).strip()
            if info.is_dir() or not name.lower().endswith(IMAGE_EXTS):
                continue
            target = dest_dir / name
            n = 1
            while target.exists():
                target = dest_dir / f"{Path(name).stem}_{n}{Path(name).suffix}"
                n += 1
            target.write_bytes(z.read(info))
            count += 1
    return count


def video_path(scene_dir, number):
    for ext in VIDEO_EXTS:
        if (scene_dir / f"{number}{ext}").exists():
            return scene_dir / f"{number}{ext}"
    return None


def image_folder(out_dir, number):
    """트랙 이미지 폴더 '1번', '2번' … (다른 자동화 프로그램과 맞춘 이름).
    예전 이름('1')으로 만든 폴더가 있으면 '1번'으로 바꿔서 이어 쓴다."""
    folder = out_dir / f"{number}번"
    old = out_dir / str(number)
    if not folder.exists() and old.is_dir():
        try:
            old.rename(folder)
        except OSError:
            return old
    return folder


NO_VIDEO_NAME = ".영상없음"   # Flow 가 이 트랙 영상을 거절해서 영상 없이 끝낸 표시
DONE_NAME = ".flow완료"   # Flow 가 일부를 '실패'로 못 만들어서 15장보다 적어도, 만든 것은 다 받았다는 표시


def track_done(image_folder, scene_dir, number, n_images):
    """이미지 n_images장 이상(또는 만든 것 전부를 받았다는 표시)과 영상이 다 있으면 끝난 트랙."""
    if not image_folder.is_dir():
        return False
    if not video_path(scene_dir, number) and not (image_folder / NO_VIDEO_NAME).exists():
        return False
    if (image_folder / DONE_NAME).exists():
        return True
    return sum(f.suffix.lower() in IMAGE_EXTS for f in image_folder.iterdir()) >= n_images


# ---------------------------------------------------------------- 이미지 만들기·받기 (썸네일 프로그램도 씀)

def request_images(flow, prompt, n_images, request=IMAGE_REQUEST, characters=(), project=None):
    """에이전트에 프롬프트 + 'N장 만들어 줘'를 보내고 새 이미지 N장이 생길 때까지 기다린다.
    characters 가 있으면 먼저 [+] 로 그 캐릭터들을 프롬프트 칸에 올린다."""
    # 새 그림은 격자 맨 위에 생긴다. 격자가 내려가 있으면 맨 위 그림을 '새 그림' 으로 잘못 센다 (새 이미지 50개 문제)
    flow._scroll_grid(to_top=True)
    time.sleep(1)
    before = {t["key"] for t in flow.tiles()}
    for name in characters:
        flow.add_character(name, project)
    if characters:
        flow.close_picker()
    log(f"  이미지 {n_images}장 요청")
    flow.send_prompt(f"{prompt}\n\n{request.format(n=n_images)}")
    images = flow.wait_new("image", before, n_images, IMAGE_TIMEOUT_SEC)
    images = images[:n_images] if len(images) > n_images else images
    # 다 만들어진 직후 Flow 가 그림 주소를 한 번 더 바꿀 때가 있어서, 잠시 뒤 다시 읽는다
    time.sleep(5)
    again = [t for t in flow.tiles("image") if t["key"] not in before]
    if len(again) >= len(images):
        images = again[:len(images)]
    log(f"  이미지 {len(images)}장 완성")
    return images


_dumped = False
_shots = {}


def save_screen(flow, folder, name, limit=6):
    """문제가 생긴 순간의 Flow 화면을 이미지\\_확인화면 에 저장 (트랙마다 몇 장까지만)."""
    if _shots.get(folder, 0) >= limit:
        return
    _shots[folder] = _shots.get(folder, 0) + 1
    try:
        shot_dir = folder.parent / "_확인화면"
        shot_dir.mkdir(parents=True, exist_ok=True)
        flow.page.screenshot(path=str(shot_dir / f"{name}.png"))
    except (PlaywrightError, OSError):
        pass


def dump_tiles(flow, folder):
    """실제 Flow 화면의 격자 칸 구조를 파일로 한 번 남긴다 (그림을 못 찾는 문제를 고칠 때 보려고)."""
    global _dumped
    if _dumped:
        return
    _dumped = True
    try:
        html = flow.page.evaluate("""() => [...document.querySelectorAll('[data-cavn-tile]')].slice(0, 4)
            .map(e => e.getAttribute('data-cavn-tile').slice(0, 150) + '\\n' + e.outerHTML.slice(0, 5000)).join('\\n\\n=====\\n\\n')""")
        (folder.parent / "Flow칸정보.txt").write_text(html, encoding="utf-8")
    except (PlaywrightError, OSError):
        pass


def collect_images(flow, images, folder):
    """새 컬렉션에 이미지를 넣고 컬렉션 다운로드 → folder 에 이미지 저장. 받은 장수를 돌려준다."""
    folder.mkdir(parents=True, exist_ok=True)
    log("  새 컬렉션 만들고 이미지 넣기")
    flow.new_collection()
    # 그림 주소는 만든 뒤에 바뀔 수 있어서, 주소로 못 찾으면 그림 제목(Flow 가 붙인 이름)으로 찾는다.
    # 예전처럼 '격자 몇 번째' 로 찾으면 다른 트랙 그림을 넣거나 같은 그림을 두 번 넣어 몇 장씩 모자랐다.
    titles = [tile_title(img.get("text")) for img in images]
    use_titles = all(titles) and len(set(titles)) == len(titles)   # 제목이 다 있고 서로 다를 때만 제목으로 찾는다
    if not use_titles:
        images = [dict(img, text="") for img in images]
    if use_titles and folder.is_dir():
        # 지난번에 이미 받아 둔 그림(같은 제목의 파일)은 빼고 나머지만 넣는다
        local = [file_title(f) for f in folder.iterdir() if f.suffix.lower() in IMAGE_EXTS]
        have = [img for img in images if any(same_title(tile_title(img.get("text")), lt) for lt in local)]
        if have:
            images = [img for img in images if img not in have]
            titles = [tile_title(img.get("text")) for img in images]
            log(f"    이미 받아 둔 {len(have)}장은 빼고 {len(images)}장만 컬렉션에 넣습니다")
            if not images:
                return 0
    track_titles = set(titles) if use_titles else set()
    used_keys, used_titles = set(), set()
    added = 0
    pos = 0   # 제목도 모를 때: 격자 맨 앞에서 몇 번째 그림을 넣어 볼 차례인지
    counted = flow.collection_count()
    dump_tiles(flow, folder)
    for i, img in enumerate(images, 1):
        done = False
        for attempt in range(4):
            found = flow.find_image(img, used_keys, used_titles, top=len(images) + 6) if attempt == 0 else None
            from_grid = found is None
            if found is None:
                # 격자 맨 앞(이 트랙 장수만큼) 그림을 차례로. 제목을 알면 이 트랙 제목인 것만
                flow._scroll_grid(to_top=True)
                time.sleep(1)
                near = [t for t in flow.tiles("image")[:len(images) + 2]
                        if not (track_titles and tile_title(t["text"]) not in track_titles)
                        and tile_title(t["text"]) not in used_titles]
                if pos >= len(near):
                    break
                if attempt == 0:
                    log(f"    ({i}번째 이미지를 주소·제목으로 못 찾아서 격자 앞쪽에서 찾습니다)")
                found = near[pos]
            if not flow.drag(flow.tile(found["key"], refresh=True), flow.tile(flow.first_collection())):
                log(f"    ({i}번째 이미지와 컬렉션 칸이 한 화면에 안 보여서 다시 해 봅니다)")
                flow._scroll_grid(to_top=True)
                time.sleep(1)
                continue
            # 컬렉션 칸의 숫자가 늘었는지로 정말 들어갔는지 본다 (같은 그림을 또 넣으면 숫자가 그대로)
            now = None
            for _ in range(12):
                now = flow.collection_count()
                if now is None or counted is None or now > counted:
                    break
                time.sleep(0.5)
            if now is None or counted is None or now > counted:
                counted = now
                used_keys.add(found["key"])
                if use_titles and tile_title(found["text"]):
                    used_titles.add(tile_title(found["text"]))
                if counted is None:
                    pos += 1
                done = True
                break
            save_screen(flow, folder, f"컬렉션_{folder.name}_{i}번째_{attempt + 1}")
            if from_grid:
                pos += 1   # 이미 넣은 그림이었음 → 다음 그림
        if done:
            added += 1
        else:
            log(f"    !! {i}번째 이미지를 Flow 화면에서 찾지 못해 건너뜁니다")
        if i % 5 == 0:
            log(f"    {i}/{len(images)}장 넣음")
    if not added:
        raise RuntimeError("컬렉션에 넣을 이미지를 Flow 화면에서 찾지 못했습니다.")

    log("  컬렉션 다운로드")
    count = 0
    for path in flow.download_collection(flow.first_collection(), folder, counted or added):
        if path.suffix.lower() == ".zip":
            count += extract_images(path, folder)
            path.unlink()
        else:
            count += 1
    log(f"    이미지 {count}장 저장 → {folder}")
    return count


# ---------------------------------------------------------------- 트랙 하나

STATE_NAME = ".flow기록.json"   # 이 트랙에서 Flow 에 만든 이미지·영상 (다시 실행할 때 또 만들지 않으려고)


def load_state(folder):
    try:
        return json.loads((folder / STATE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _set_hidden(path, hidden):
    """윈도우에서 기록 파일을 숨김 파일로 (탐색기·캡컷 조립에서 안 보이게). 숨김 파일은 덮어쓰기가 안 되므로 쓰기 전엔 푼다."""
    if os.name != "nt" or not path.exists():
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x2 if hidden else 0x80)
    except (OSError, AttributeError):
        pass


def save_state(folder, **values):
    state = load_state(folder)
    state.update(values)
    path = folder / STATE_NAME
    try:
        _set_hidden(path, False)
        path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        _set_hidden(path, True)
    except OSError:
        pass


def lyric_prompt(track):
    return f"{track.title}\n\n{track.lyrics}".strip()


def make_track(flow, track, folder, scene_dir, n_images, reuse=False, reuse_video=False, cast=None, project=None):
    """cast(캐릭터 이름 목록)가 있으면 가요·칸쏘네 방식: 캐릭터 + 곡 제목 + 가사로 이미지, 가사에 맞게 영상."""
    folder.mkdir(parents=True, exist_ok=True)
    scene_dir.mkdir(parents=True, exist_ok=True)

    # 지난번에 이 트랙의 이미지·영상을 Flow 에 만들어 놓고 받기에서 실패했으면, 기록해 둔 그 칸을 찾아 다시 쓴다
    state = load_state(folder)
    saved_images = [{"key": k, "text": tx} for k, tx in
                    zip(state.get("images") or [], (state.get("titles") or []) + [""] * len(state.get("images") or []))]
    local = [f for f in folder.iterdir() if f.suffix.lower() in IMAGE_EXTS]
    if not reuse and ((folder / DONE_NAME).exists() or len(local) >= n_images):
        # 이미지는 다 받아 두었고 영상만 없음 → 받아 둔 그림과 같은 제목의 그림을 Flow 에서 찾아 영상만 만든다
        log(f"  이미지 {len(local)}장은 이미 받아 두었습니다 → 영상만 만듭니다")
        titles = [file_title(f) for f in sorted(local)]
        tile = flow.scan_grid(lambda t: any(same_title(tile_title(t["text"]), ft) for ft in titles), "image")
        if tile is None:
            raise RuntimeError("받아 둔 이 트랙 그림을 Flow 화면에서 찾지 못해 영상을 만들 수 없습니다.")
        make_video(flow, track, folder, scene_dir, tile, cast)
        return
    if (not reuse and len(saved_images) >= n_images and flow.find_image(saved_images[-1])
            and flow.find_image(saved_images[0])):
        log(f"  지난번에 Flow 에 만들어 둔 이 트랙 이미지 {len(saved_images)}장을 다시 씁니다 (새로 만들지 않음)")
        images = saved_images[:n_images]
        reuse = "state"
        if state.get("video") and flow.has_tile(state["video"]):
            log("  지난번에 만들어 둔 이 트랙 영상도 다시 씁니다 (새로 만들지 않음)")
            reuse_video = "state"

    if reuse == "state":
        pass
    elif reuse:
        # 이 트랙 이미지가 이미 Flow 화면 맨 앞에 있음 → 새로 만들지 않고 그 이미지를 쓴다
        images = flow.tiles("image")[:n_images]
        if len(images) < n_images:
            raise RuntimeError(f"Flow 화면에 이미지가 {len(images)}장뿐이라 기존 이미지를 쓸 수 없습니다.")
        log(f"  Flow 화면 맨 앞의 기존 이미지 {len(images)}장을 씁니다 (새로 만들지 않음)")
    elif cast:
        from cast import join_names
        images = request_images(flow, lyric_prompt(track), n_images,
                                request=LYRIC_IMAGE_REQUEST.format(names=join_names(cast)),
                                characters=cast, project=project)
    else:
        images = request_images(flow, track.image_prompt, n_images)
    save_state(folder, images=[img["key"] for img in images], titles=[img.get("text", "") for img in images])

    have_video = video_path(scene_dir, track.number) is not None
    if (folder / NO_VIDEO_NAME).exists():
        log("  이 트랙 영상은 지난번에 Flow 가 거절해서 건너뜁니다")
        video = None
    elif have_video:
        log(f"  영상은 이미 받아 두었습니다 (장면\\{video_path(scene_dir, track.number).name}) → 영상은 건너뜀")
        video = None
    elif reuse_video == "state":
        video = {"key": state["video"]}
    elif reuse_video:
        # 이 트랙 영상도 이미 만들어 둠 → 격자 맨 앞의 영상을 쓴다 (크레딧 안 씀)
        videos = flow.tiles("video")
        if not videos:
            raise RuntimeError("Flow 화면에서 기존 영상을 찾지 못했습니다.")
        video = videos[0]
        log("  Flow 화면 맨 앞의 기존 영상을 씁니다 (새로 만들지 않음)")
    else:
        first_made = images[-1]   # 새 이미지는 앞에 생기므로 맨 끝이 제일 처음 만든 것
        video = make_video(flow, track, folder, scene_dir, first_made, cast, download=False)
    if video:
        save_state(folder, video=video["key"])
        # 영상을 먼저 받는다 (이미지 컬렉션에서 실패해도 영상은 남도록 → 다시 실행할 때 영상을 또 만들지 않음)
        download_video(flow, video, scene_dir, track.number)

    collect_images(flow, images, folder)
    count = sum(f.suffix.lower() in IMAGE_EXTS for f in folder.iterdir())   # 지난번에 받아 둔 것까지
    if count < len(images):
        log(f"    !! {len(images)}장 중 {count}장만 받았습니다. 다시 실행하면 기록해 둔 이미지로 이 트랙을 다시 받습니다.")
    else:
        (folder / STATE_NAME).unlink(missing_ok=True)   # 다 받았으니 기록은 지움
        if count < n_images:   # Flow 가 몇 장을 '실패'로 못 만듦 → 받은 것으로 끝난 트랙으로 침
            (folder / DONE_NAME).write_text(f"{count}", encoding="utf-8")


def make_video(flow, track, folder, scene_dir, source, cast=None, download=True):
    """source 이미지를 프롬프트 칸에 끌어다 놓고 영상을 요청한다. 거절되면 None."""
    if cast:
        video_text = f"{lyric_prompt(track)}\n\n{LYRIC_VIDEO_REQUEST}"
    else:
        video_text = f"{track.video_prompt or track.image_prompt}\n\n{VIDEO_REQUEST}"
    log("  이 트랙 이미지 한 장을 프롬프트 칸에 끌어다 놓고 영상 요청")
    before_video = {t["key"] for t in flow.tiles()}
    found = flow.find_image(source)   # 그림 주소가 바뀌었으면 제목으로
    if found is None:
        raise RuntimeError("영상에 쓸 이 트랙 이미지를 Flow 화면에서 찾지 못했습니다.")
    name = caption(found["text"]) or caption(source.get("text"))
    if name:   # 끌어다 놓기가 안 되어도 에이전트가 알 수 있게 그림 제목도 적는다
        video_text += f"\n(사용할 이미지: '{name}')"

    def attach():
        f = flow.find_image(source) or found
        loc = flow.tile(f["key"], refresh=True)
        if not flow.drag(loc, flow.prompt_box()):
            loc.scroll_into_view_if_needed()
            flow.drag(loc, flow.prompt_box())
        time.sleep(1.5)

    def answer():
        attach()
        flow.send_prompt(f"'{name}' 이미지로 영상을 만들어 주세요." if name else LYRIC_VIDEO_REQUEST)

    attach()
    refusals_before, need_before = flow.refusal_count(), flow.need_image_count()
    flow.send_prompt(video_text)
    try:
        video = flow.wait_new("video", before_video, 1, VIDEO_TIMEOUT_SEC, after_approval=True,
                              refusals_before=refusals_before, on_need_image=answer, need_before=need_before)[0]
        log("  영상 완성")
    except VideoRefused as e:
        # 영상은 싱글곡에만 따로 쓰는 것이라, 거절되면 영상 없이 이미지만 받고 넘어간다
        log(f"  !! {e} 영상은 건너뛰고 이미지만 받습니다.")
        (folder / NO_VIDEO_NAME).write_text("Flow 가 영상을 거절함", encoding="utf-8")
        video = None
    if video and download:
        download_video(flow, video, scene_dir, track.number)
    return video


def download_video(flow, video, scene_dir, number):
    log("  영상 다운로드")
    video_name = str(number)
    path = None
    try:
        # 컬렉션처럼 다운로드 폴더에 완성된 영상 파일이 생길 때까지 기다렸다가, 진짜 영상인지 확인하고 옮긴다
        # (덜 받아진 파일을 저장해서 영상이 깨지던 문제)
        files = flow.download_collection(video["key"], scene_dir, 1,
                                         menu_re=re.compile(r"^\s*(file_download|download)?\s*(다운로드|Download)\s*$", re.I),
                                         sub_re=re.compile(r"원본|720p|Original", re.I), kinds=(".mp4", ".webm"))
        if files:
            path = files[0]
            target = scene_dir / f"{video_name}{path.suffix}"
            if target.exists():
                target.unlink()
            path = path.rename(target)
            for extra in files[1:]:
                extra.unlink(missing_ok=True)
    except (PlaywrightTimeout, PlaywrightError, RuntimeError) as e:
        log(f"    (메뉴로 못 받아서 직접 받습니다: {str(e).splitlines()[0]})")
        flow.page.keyboard.press("Escape")
    if path is None or sniff_ext(path) not in (".mp4", ".webm"):
        path = flow.save_video_src(video["key"], scene_dir / f"{video_name}.mp4")
        if sniff_ext(path) not in (".mp4", ".webm"):
            path.unlink(missing_ok=True)
            raise RuntimeError("영상 파일이 제대로 받아지지 않았습니다. Flow 에서 직접 받아 주세요.")
    log(f"    받음: 장면\\{path.name} ({path.stat().st_size // 1024:,}KB)")


# ---------------------------------------------------------------- 실행

def connect(pw):
    cdp = start_real_chrome(PROFILE_DIR, DEBUG_PORT)
    if not cdp:
        raise SystemExit("크롬을 찾지 못했습니다. 크롬을 설치해 주세요.")
    browser = pw.chromium.connect_over_cdp(cdp)
    context = browser.contexts[0] if browser.contexts else browser.new_context()
    # CAVN·Flow 가 같은 크롬을 쓰므로 이 사이트 탭을 찾아 쓰고, 없으면 새 탭
    page = next((p for p in context.pages if "flow.google" in p.url), None) or context.new_page()
    page.bring_to_front()
    if "/project/" not in page.url:
        page.goto(FLOW_URL, wait_until="domcontentloaded")
        print("\n크롬에서 Flow 에 로그인하고, 작업할 프로젝트를 열어 주세요 (새 프로젝트도 됨).")
        input("프로젝트 화면(전체 미디어)이 보이면 Enter 를 누르세요... ")
        # 프로젝트를 다른 탭에서 열었을 수도 있으니, 프로젝트가 열린 탭을 다시 찾는다
        projects = [p for p in context.pages if "flow.google" in p.url and "/project/" in p.url]
        if projects:
            page = projects[-1]
        if "/project/" not in page.url:
            print("!! 프로젝트가 열린 탭을 찾지 못했습니다. 지금 탭에서 그대로 진행합니다.")
        page.bring_to_front()
    log(f"작업 탭: {page.url}")
    return page


def run(md_path, out_root, only=None, dry_run=False, page=None, confirm=True, n_images=IMAGES_PER_TRACK,
        cast_group=None, cast=None):
    """cast_group: 가요·칸쏘네 md 에 쓸 캐릭터목록 묶음 이름 (안 주면 물어봄).
    cast: {트랙 번호: [이름…]} (안 주면 confirm 일 때 곡마다 묻고, 아니면 기본값)"""
    md_path = Path(md_path)
    tracks = [t for t in parse_md_file(md_path) if not only or t.number in only]
    album_dir = Path(out_root) / safe_filename(md_path.stem)
    out_dir, scene_dir = album_dir / "이미지", album_dir / "장면"
    last = max((t.number for t in tracks), default=0)
    print(f"\nmd 파일 : {md_path.name}\n이미지  : {out_dir}\\1번 ~ {last}번\n영상    : {scene_dir}\\1.mp4 ~ {last}.mp4\n")
    todo = []
    for t in tracks:
        folder = image_folder(out_dir, t.number)
        if not t.image_prompt and not t.lyrics:
            mark = "!! 이미지 프롬프트·가사 없음(건너뜀)"
        elif track_done(folder, scene_dir, t.number, n_images):
            mark = "완료(건너뜀)"
        else:
            mark = ""
            todo.append(t)
        print(f"  {t.number:>2}. {t.title}  {mark}")
    if not any(t.image_prompt or t.lyrics for t in tracks):
        print("이 md 파일에는 이미지 프롬프트도 가사도 없습니다.")
        return
    print(f"\n만들 트랙 {len(todo)}개 (트랙마다 이미지 {n_images}장 + 영상 1개)")
    if dry_run or not todo:
        return
    # 가요·칸쏘네 (이미지 프롬프트 없이 가사만 있는 곡): 주인공 캐릭터를 정한다
    project, cast_map = None, dict(cast or {})
    lyric_todo = [t for t in todo if not t.image_prompt]
    if lyric_todo:
        from cast import ask_cast, ask_group, default_names, load_cast
        project, groups = load_cast()
        if not groups:
            print("!! 캐릭터목록.txt 가 없거나 비어 있어서 가요·칸쏘네 곡은 건너뜁니다.")
            todo = [t for t in todo if t.image_prompt]
        else:
            group = cast_group if cast_group in groups else (ask_group(groups) if confirm else next(iter(groups)))
            print(f"캐릭터 묶음: {group}  (Flow 프로젝트 '{project}')")
            missing = [t for t in lyric_todo if t.number not in cast_map]
            if confirm:
                cast_map.update(ask_cast(missing, groups[group]))
            else:
                cast_map.update({t.number: default_names(t, groups[group]) for t in missing})
    if confirm and input("시작할까요? (y/n): ").strip().lower() not in ("y", "yes", "ㅛ"):
        return
    reuse_first = reuse_video_first = False
    if confirm:
        print(f"\n{todo[0].number}번 트랙 이미지 {n_images}장을 지난번에 Flow 에서 이미 만들어 두었나요?")
        print("  (Flow 화면 맨 앞에 그 이미지들이 있으면 y → 새로 만들지 않고 그 이미지로 영상·컬렉션만 합니다)")
        reuse_first = input("기존 이미지 쓰기 (y/n): ").strip().lower() in ("y", "yes", "ㅛ")
        if reuse_first:
            print(f"{todo[0].number}번 트랙 영상도 이미 만들어 두었나요? (y → 새로 만들지 않고 컬렉션·다운로드만 합니다)")
            reuse_video_first = input("기존 영상 쓰기 (y/n): ").strip().lower() in ("y", "yes", "ㅛ")

    def work(page):
        flow = Flow(page)
        failed = []
        for i, t in enumerate(todo, 1):
            log(f"[{i}/{len(todo)}] {t.number}. {t.title}")
            try:
                names = cast_map.get(t.number) if not t.image_prompt else None
                if names:
                    log(f"  주인공: {', '.join(names)}")
                make_track(flow, t, image_folder(out_dir, t.number), scene_dir, n_images,
                           reuse=reuse_first and i == 1, reuse_video=reuse_video_first and i == 1,
                           cast=names, project=project)
            except Exception as e:  # 한 트랙이 실패해도 다음 트랙은 계속
                log(f"  !! 실패: {e}")
                failed.append(t)
                try:
                    page.keyboard.press("Escape")
                except PlaywrightError:
                    pass
        print()
        log(f"끝. 성공 {len(todo) - len(failed)}개, 실패 {len(failed)}개")
        for t in failed:
            print(f"  실패: {t.number}. {t.title}  (다시 실행하면 이 트랙부터 이어서 합니다)")
        print(f"저장 폴더: {out_dir}")

    with record(album_dir / "Flow작업기록.txt"):   # 실행 기록을 앨범 폴더에도 남김
        if page is not None:
            return work(page)
        with sync_playwright() as pw:
            work(connect(pw))


def main():
    ap = argparse.ArgumentParser(description="Google Flow 이미지 15장 + 영상 1개 자동 만들기")
    ap.add_argument("md", nargs="?", help="Claude가 만든 음악 md 파일 (없으면 실행할 때 물어봄)")
    ap.add_argument("--out", default=DEFAULT_OUT, help=f"저장 폴더 (기본 {DEFAULT_OUT})")
    ap.add_argument("--only", help="이 트랙 번호만 (예: 1,3,5)")
    ap.add_argument("--images", type=int, default=IMAGES_PER_TRACK, help="트랙마다 이미지 장수 (기본 15)")
    ap.add_argument("--dry-run", action="store_true", help="md 파일만 읽어 보고 끝냄")
    args = ap.parse_args()
    md = ask_md_path(args.md)
    only = parse_only(args.only) if args.only else (None if args.dry_run else ask_only())
    run(md, args.out, only, args.dry_run, n_images=args.images)


if __name__ == "__main__":
    main()
