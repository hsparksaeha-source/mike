"""Google Flow 자동 이미지 15장 + 영상 1개 만들기 (경음악·클래식용)

md 파일의 트랙마다 (트랙 번호 N):
  1. 에이전트 프롬프트 칸에 '이미지 프롬프트' + "이미지 15장 만들어 줘" → 15장 완성 기다림
  2. 새로 생긴 이미지 중 화면 맨 끝(=제일 처음 만든) 것을 프롬프트 칸에 끌어다 놓고
     '영상 프롬프트'(없으면 뮤직 비디오 콘셉트) + "이 이미지로 영상 만들어 줘" → 영상 완성 기다림
  3. 오른쪽 위 [+] → [새 컬렉션] → 새 컬렉션에 이미지 15장을 끌어다 넣음 (영상은 그대로 둠)
  4. 컬렉션에 마우스 올림 → [⋮] → [컬렉션 다운로드] → 받은 이미지 15장을 이미지\\N\\ 에 저장
     (다운로드하면서 뜬 창은 닫음)
  5. 영상은 따로 장면\\N.mp4 로 저장 (이미지 폴더에 섞이지 않게)

저장 위치: <저장 폴더>\\<md 파일 이름>\\이미지\\1 ~ N   이미지만 (캡컷 클래식 조립 프로그램이 읽는 번호 폴더)
           <저장 폴더>\\<md 파일 이름>\\장면\\1.mp4 ~ N.mp4   영상
이미지 15장과 영상이 이미 있는 트랙은 건너뛴다 (다시 실행하면 남은 트랙만 함).

사용법:
  python flow_maker.py <md 파일> [--out F:\\음악생성] [--only 1,3,5] [--images 15] [--dry-run]
"""

import argparse
import re
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

from md_parser import ask_md_path, ask_only, parse_only, parse_md_file  # noqa: E402
from thumb_agent.browser import start_real_chrome  # noqa: E402

FLOW_URL = "https://flow.google.com/"
DEFAULT_OUT = r"F:\음악생성"
PROFILE_DIR = Path.home() / "CavnFlowChromeProfile"  # 로그인 저장 (프로그램 폴더를 새로 받아도 유지)
DEBUG_PORT = 9224  # CAVN·Flow 가 같은 전용 크롬을 함께 씀 (썸네일 9222, 유튜브 자동입력 9223)

IMAGES_PER_TRACK = 15
IMAGE_TIMEOUT_SEC = 20 * 60
VIDEO_TIMEOUT_SEC = 20 * 60
DOWNLOAD_TIMEOUT_MS = 5 * 60_000
IMAGE_REQUEST = "위 프롬프트로 16:9 이미지 {n}장을 만들어 줘."
VIDEO_REQUEST = "이 이미지로 영상을 만들어 줘."
PROMPT_PLACEHOLDER = "무엇을 만들고 싶으신가요?"
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")
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
    const add = (tile, kind, key) => {
        if (seen.has(tile)) return;
        const r = tile.getBoundingClientRect();
        if (r.width < 60 || r.height < 40 || r.left < sideRight || inPrompt(r)) return;
        seen.add(tile);
        tile.setAttribute('data-cavn-tile', key);
        out.push({kind, key, x: r.left, y: r.top, text: tile.innerText || ''});
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
                .filter(Boolean).join('|')
            : (m.currentSrc || m.src || '');
        add(tile, isVideo ? 'video' : 'image', (isVideo ? 'video:' : 'image:') + src);
    });
    out.sort((a, b) => Math.abs(a.y - b.y) > 20 ? a.y - b.y : a.x - b.x);
    return out;
}"""


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
        box = self.prompt_box()
        box.click()
        self.page.keyboard.insert_text(text)
        time.sleep(0.5)
        self.page.keyboard.press("Enter")
        time.sleep(2)
        # Enter 로 안 보내졌으면(글이 그대로 남아 있으면) 오른쪽 화살표 버튼.
        # 보내면 Flow 가 입력칸을 새로 그리므로, 예전 칸을 기다리지 말고 다시 찾아서 확인한다.
        try:
            left = self.prompt_box(wait=5).evaluate(
                "e => 'value' in e ? e.value : e.innerText", timeout=3000) or ""
        except (RuntimeError, PlaywrightError):
            left = ""
        if text[:20] in left:
            send = self.page.locator("button").filter(has_text=re.compile(r"arrow_forward|send|보내기"))
            send = [b for b in send.all() if b.is_visible()]
            if send:
                send[-1].click()

    # -- 격자
    def tiles(self, kind=None):
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
        return self.page.locator(f"[data-cavn-tile={_css_str(key)}]").first

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

    def wait_new(self, kind, before_keys, want, timeout, settle=10, after_approval=False):
        """kind 칸이 want 개 이상 새로 생기고 settle 초 동안 늘지 않을 때까지 기다린다.
        after_approval: 확인 질문이 뜨면 승인된 뒤에 생긴 것만 센다 (그 사이 끝난 다른 트랙 영상을 잘못 세지 않게).
        질문이 90초 안에 안 뜨면(이미 '항상 승인'인 경우) 그냥 센다."""
        deadline = time.time() + timeout
        start = time.time()
        last_count, last_change, last_note = -1, time.time(), 0
        before_keys = set(before_keys)
        while time.time() < deadline:
            was_approved = self.approved
            self.approve()
            if after_approval:
                if self.approved and not was_approved:
                    before_keys |= {t["key"] for t in self.tiles(kind)}   # 승인 전에 있던 영상은 제외
                    last_count = -1
                if (self.question_seen and not self.approved) or (not self.question_seen and time.time() - start < 90):
                    if time.time() - last_note > 60:
                        log("  확인 질문(승인)을 기다리는 중... (못 누르면 Flow 에서 [승인]을 직접 눌러 주세요)")
                        last_note = time.time()
                    time.sleep(3)
                    continue
            new = [t for t in self.tiles(kind) if t["key"] not in before_keys and not t["key"].endswith(":")]
            if len(new) != last_count:
                last_count, last_change = len(new), time.time()
            if len(new) >= want and time.time() - last_change >= settle:
                return new
            if new and time.time() - last_change > 180:   # 3분 동안 더 안 생기면 있는 것만 사용
                log(f"  !! {kind} {len(new)}개만 만들어져서 그대로 진행합니다.")
                return new
            if time.time() - last_note > 60:
                log(f"  기다리는 중... (새 {'이미지' if kind == 'image' else '영상'} {len(new)}개)")
                last_note = time.time()
            time.sleep(3)
        raise RuntimeError(f"{'이미지가' if kind == 'image' else '영상이'} 제한 시간 안에 다 만들어지지 않았습니다.")

    def drag(self, source, target):
        page = self.page
        source.scroll_into_view_if_needed()
        s = source.bounding_box()
        t = target.bounding_box()
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

    # -- 컬렉션
    def new_collection(self):
        page = self.page
        before = len(self.tiles("collection"))
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
                top.append((box["x"], label, el))
        if not top:
            raise RuntimeError("화면 맨 위 줄의 [+] 버튼을 찾지 못했습니다.")
        # 이름으로 고르면 에이전트 창의 '새 세션' 같은 버튼이 걸리므로, 위치로만 고른다: 무리의 맨 왼쪽 = [+]
        plus = min(top, key=lambda t: t[0])[2]
        plus.click()
        # 메뉴 항목 글자에 아이콘 이름이 붙어 있을 수 있어서 '새 컬렉션'이 들어 있는 가장 작은 항목을 누른다
        item = None
        for _ in range(10):
            time.sleep(0.5)
            found = []
            for loc in (page.get_by_role("menuitem", name=re.compile("새 컬렉션")),
                        page.get_by_text(re.compile("새 컬렉션"))):
                for el, box in self._visible_boxes(loc):
                    found.append((box["width"] * box["height"], el))
                if found:
                    break
            if found:
                item = min(found, key=lambda t: t[0])[1]
                break
        if item is None:
            page.keyboard.press("Escape")
            raise RuntimeError("[+] 메뉴에서 '새 컬렉션'을 찾지 못했습니다.")
        item.click()
        for _ in range(20):
            time.sleep(0.5)
            cols = self.tiles("collection")
            if len(cols) > before:
                return cols[0]["key"]   # 새 컬렉션은 격자 맨 앞에 생김
        raise RuntimeError("새 컬렉션이 만들어지지 않았습니다.")

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

    def first_collection(self):
        cols = self.tiles("collection")
        if not cols:
            raise RuntimeError("컬렉션을 찾지 못했습니다.")
        return cols[0]["key"]   # 새로 만든 컬렉션은 격자 맨 앞

    def download_collection(self, key, dest_dir, n_expected):
        """[⋮] → [컬렉션 다운로드]. 압축 파일 하나로 오든, 이미지가 낱개로 여러 개 오든 모두 받는다.
        다운로드하면서 새 창(탭)이 열리면 다 받은 뒤 닫는다."""
        page = self.page
        got = []

        def on_download(dl):
            got.append(dl)
        page.on("download", on_download)
        pages_before = set(page.context.pages)
        try:
            self.hover_menu(key)
            page.get_by_text(re.compile("컬렉션 다운로드|Download collection", re.I)).filter(visible=True).first.click()
            deadline = time.time() + DOWNLOAD_TIMEOUT_MS / 1000
            last = (0, time.time())
            while time.time() < deadline:
                time.sleep(1)
                if len(got) != last[0]:
                    last = (len(got), time.time())
                one_zip = len(got) == 1 and got[0].suggested_filename.lower().endswith(".zip")
                if any(p not in pages_before for p in page.context.pages):
                    page.bring_to_front()   # 다운로드 창이 열려도 작업 화면을 앞으로
                idle = time.time() - last[1]
                if got and (one_zip or len(got) >= n_expected or idle > 60):
                    break
            if not got:
                raise RuntimeError("컬렉션 다운로드가 시작되지 않았습니다.")
            saved = []
            for i, dl in enumerate(got, 1):
                name = Path(dl.suggested_filename).name or f"image_{i}.jpg"
                dest = Path(dest_dir) / name
                n = 1
                while dest.exists():
                    dest = Path(dest_dir) / f"{Path(name).stem}_{n}{Path(name).suffix}"
                    n += 1
                dl.save_as(dest)
                saved.append(dest)
            return saved
        finally:
            page.remove_listener("download", on_download)
            for p in page.context.pages:   # 다운로드 때문에 열린 창은 닫기
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


def extract_images(zip_path, dest_dir):
    count = 0
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name = Path(info.filename).name
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


def track_done(image_folder, scene_dir, number, n_images):
    """이미지 n_images장 이상과 영상이 다 있으면 끝난 트랙."""
    if not image_folder.is_dir() or not video_path(scene_dir, number):
        return False
    return sum(f.suffix.lower() in IMAGE_EXTS for f in image_folder.iterdir()) >= n_images


# ---------------------------------------------------------------- 트랙 하나

def make_track(flow, track, folder, scene_dir, n_images, reuse=False):
    folder.mkdir(parents=True, exist_ok=True)
    scene_dir.mkdir(parents=True, exist_ok=True)

    if reuse:
        # 이 트랙 이미지가 이미 Flow 화면 맨 앞에 있음 → 새로 만들지 않고 그 이미지를 쓴다
        images = flow.tiles("image")[:n_images]
        if len(images) < n_images:
            raise RuntimeError(f"Flow 화면에 이미지가 {len(images)}장뿐이라 기존 이미지를 쓸 수 없습니다.")
        log(f"  Flow 화면 맨 앞의 기존 이미지 {len(images)}장을 씁니다 (새로 만들지 않음)")
    else:
        before = {t["key"] for t in flow.tiles()}
        log(f"  이미지 {n_images}장 요청")
        flow.send_prompt(f"{track.image_prompt}\n\n{IMAGE_REQUEST.format(n=n_images)}")
        images = flow.wait_new("image", before, n_images, IMAGE_TIMEOUT_SEC)
        images = images[:n_images] if len(images) > n_images else images
        log(f"  이미지 {len(images)}장 완성")

    first_made = images[-1]   # 새 이미지는 앞에 생기므로 맨 끝이 제일 처음 만든 것
    video_prompt = track.video_prompt or track.image_prompt
    log("  맨 끝 이미지를 프롬프트 칸에 끌어다 놓고 영상 요청")
    before_video = {t["key"] for t in flow.tiles()}
    flow.drag(flow.tile(first_made["key"], refresh=True), flow.prompt_box())
    flow.send_prompt(f"{video_prompt}\n\n{VIDEO_REQUEST}")
    video = flow.wait_new("video", before_video, 1, VIDEO_TIMEOUT_SEC, after_approval=True)[0]
    log("  영상 완성")

    log("  새 컬렉션 만들고 이미지 넣기")
    flow.new_collection()
    for i, img in enumerate(images, 1):
        source = flow.tile(img["key"], refresh=True)
        flow.drag(source, flow.tile(flow.first_collection()))
        if i % 5 == 0:
            log(f"    {i}/{len(images)}장 넣음")

    log("  컬렉션 다운로드")
    count = 0
    for path in flow.download_collection(flow.first_collection(), folder, len(images)):
        if path.suffix.lower() == ".zip":
            count += extract_images(path, folder)
            path.unlink()
        else:
            count += 1
    log(f"    이미지 {count}장 저장 → {folder}")
    if count < len(images):
        log(f"    !! {len(images)}장 중 {count}장만 받았습니다. 다시 실행하면 이 트랙을 다시 합니다.")

    log("  영상 다운로드")
    video_name = str(track.number)
    try:
        path = flow.download_via_menu(video["key"], re.compile("^\\s*(다운로드|Download)\\s*$", re.I), scene_dir,
                                      video_name, sub_re=re.compile(r"원본|720p|Original", re.I))
    except (PlaywrightTimeout, PlaywrightError, RuntimeError) as e:
        log(f"    (메뉴로 못 받아서 직접 받습니다: {str(e).splitlines()[0]})")
        flow.page.keyboard.press("Escape")
        path = flow.save_video_src(video["key"], scene_dir / f"{video_name}.mp4")
    log(f"    받음: 장면\\{path.name}")


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


def run(md_path, out_root, only=None, dry_run=False, page=None, confirm=True, n_images=IMAGES_PER_TRACK):
    md_path = Path(md_path)
    tracks = [t for t in parse_md_file(md_path) if not only or t.number in only]
    album_dir = Path(out_root) / safe_filename(md_path.stem)
    out_dir, scene_dir = album_dir / "이미지", album_dir / "장면"
    last = max((t.number for t in tracks), default=0)
    print(f"\nmd 파일 : {md_path.name}\n이미지  : {out_dir}\\1 ~ {last}\n영상    : {scene_dir}\\1.mp4 ~ {last}.mp4\n")
    todo = []
    for t in tracks:
        folder = out_dir / str(t.number)
        if not t.image_prompt:
            mark = "!! 이미지 프롬프트 없음(건너뜀)"
        elif track_done(folder, scene_dir, t.number, n_images):
            mark = "완료(건너뜀)"
        else:
            mark = ""
            todo.append(t)
        print(f"  {t.number:>2}. {t.title}  {mark}")
    if not any(t.image_prompt for t in tracks):
        print("이 md 파일에는 이미지 프롬프트가 없습니다. 이미지·영상 작업은 경음악·클래식 md 에서만 합니다.")
        return
    print(f"\n만들 트랙 {len(todo)}개 (트랙마다 이미지 {n_images}장 + 영상 1개)")
    if dry_run or not todo:
        return
    if confirm and input("시작할까요? (y/n): ").strip().lower() not in ("y", "yes", "ㅛ"):
        return
    reuse_first = False
    if confirm:
        print(f"\n{todo[0].number}번 트랙 이미지 {n_images}장을 지난번에 Flow 에서 이미 만들어 두었나요?")
        print("  (Flow 화면 맨 앞에 그 이미지들이 있으면 y → 새로 만들지 않고 그 이미지로 영상·컬렉션만 합니다)")
        reuse_first = input("기존 이미지 쓰기 (y/n): ").strip().lower() in ("y", "yes", "ㅛ")

    def work(page):
        flow = Flow(page)
        failed = []
        for i, t in enumerate(todo, 1):
            log(f"[{i}/{len(todo)}] {t.number}. {t.title}")
            try:
                make_track(flow, t, out_dir / str(t.number), scene_dir, n_images, reuse=reuse_first and i == 1)
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
