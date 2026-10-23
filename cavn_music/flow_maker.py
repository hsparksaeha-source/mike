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
TILES_JS = """() => {
    document.querySelectorAll('[data-cavn-tile]').forEach(e => e.removeAttribute('data-cavn-tile'));
    const box = document.querySelector('[data-cavn-prompt]');
    const promptTop = box ? box.getBoundingClientRect().top : innerHeight;
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
        if (r.width < 60 || r.height < 40 || r.left < sideRight || r.top >= promptTop) return;
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

    # -- 프롬프트 칸
    def prompt_box(self, wait=30):
        """아래쪽 프롬프트 칸('무엇을 만들고 싶으신가요?'). 화면이 늦게 떠도 wait 초까지 기다린다."""
        deadline = time.time() + wait
        while True:
            found = self.page.evaluate("""(ph) => {
                document.querySelectorAll('[data-cavn-prompt]').forEach(e => e.removeAttribute('data-cavn-prompt'));
                const shown = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
                const boxes = [...document.querySelectorAll('textarea, input, [contenteditable=true], [contenteditable=""], [role=textbox]')]
                    .filter(shown);
                const hint = e => [e.placeholder, e.getAttribute('aria-placeholder'), e.getAttribute('data-placeholder'),
                                   e.getAttribute('aria-label'), e.innerText].filter(Boolean).join(' ');
                // 1) 안내 문구가 붙은 칸  2) 화면 아래쪽에 있는 가장 아래 글상자
                let box = boxes.find(e => hint(e).includes(ph));
                if (!box) {
                    const low = boxes.filter(e => e.tagName !== 'INPUT' && e.getBoundingClientRect().top > innerHeight * 0.6);
                    low.sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top);
                    box = low[0];
                }
                if (!box) return false;
                box.setAttribute('data-cavn-prompt', '1');
                return true;
            }""", PROMPT_PLACEHOLDER)
            if found:
                return self.page.locator("[data-cavn-prompt]").first
            if time.time() > deadline:
                raise RuntimeError("Flow 프롬프트 칸('무엇을 만들고 싶으신가요?')을 찾지 못했습니다. "
                                   "프로젝트 화면(전체 미디어)이 열려 있는지 확인해 주세요.")
            time.sleep(1)

    def send_prompt(self, text):
        box = self.prompt_box()
        box.click()
        self.page.keyboard.insert_text(text)
        time.sleep(0.5)
        self.page.keyboard.press("Enter")
        time.sleep(2)
        # Enter 로 안 보내졌으면(글이 그대로 남아 있으면) 오른쪽 화살표 버튼
        left = box.evaluate("e => 'value' in e ? e.value : e.innerText") or ""
        if text[:20] in left:
            send = self.page.locator("button").filter(has_text=re.compile(r"arrow_forward|send|보내기"))
            send = [b for b in send.all() if b.is_visible()]
            if send:
                send[-1].click()

    # -- 격자
    def tiles(self, kind=None):
        self.prompt_box()
        items = self.page.evaluate(TILES_JS)
        return [t for t in items if kind is None or t["kind"] == kind]

    def tile(self, key, refresh=False):
        if refresh:  # 화면이 다시 그려졌을 수 있으니 칸 표시를 새로 붙인다
            self.tiles()
        return self.page.locator(f"[data-cavn-tile={_css_str(key)}]").first

    def wait_new(self, kind, before_keys, want, timeout, settle=10):
        """kind 칸이 want 개 이상 새로 생기고 settle 초 동안 늘지 않을 때까지 기다린다."""
        deadline = time.time() + timeout
        last_count, last_change, last_note = -1, time.time(), 0
        while time.time() < deadline:
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
        plus = page.locator("button").filter(has_text=re.compile(r"^\s*add\s*$"))
        plus = [b for b in plus.all() if b.is_visible()] or \
            [b for b in page.get_by_role("button", name=re.compile(r"^(추가|만들기|새로 만들기|Add|Create)$")).all()
             if b.is_visible()]
        if not plus:
            raise RuntimeError("오른쪽 위 [+] 버튼을 찾지 못했습니다.")
        max(plus, key=lambda b: b.bounding_box()["x"]).click()   # 맨 오른쪽 위 [+]
        page.get_by_text("새 컬렉션", exact=True).filter(visible=True).first.click()
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

def make_track(flow, track, folder, scene_dir, n_images):
    folder.mkdir(parents=True, exist_ok=True)
    scene_dir.mkdir(parents=True, exist_ok=True)
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
    video = flow.wait_new("video", before_video, 1, VIDEO_TIMEOUT_SEC)[0]
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
        elif "/project/" not in page.url:
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

    def work(page):
        flow = Flow(page)
        failed = []
        for i, t in enumerate(todo, 1):
            log(f"[{i}/{len(todo)}] {t.number}. {t.title}")
            try:
                make_track(flow, t, out_dir / str(t.number), scene_dir, n_images)
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
