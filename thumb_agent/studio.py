"""YouTube 스튜디오 '언어' 화면을 브라우저로 조작해서 언어별 썸네일을 넣는다.

YouTube Data API 에는 언어별(현지화) 썸네일을 올리는 기능이 없기 때문에,
사람이 하는 것과 똑같이 스튜디오 화면에서
  언어 이름 클릭 -> 썸네일 '추가' -> 파일 선택 -> '업데이트'
를 자동으로 반복한다.
"""

import json
import re
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from .folder import ensure_uploadable
from .languages import LANGUAGES, LanguageTable

STUDIO_URL = "https://studio.youtube.com/video/{video_id}/translations"

# 스튜디오 화면의 글자 (한국어/영어 UI 모두 지원). config.json 의 "ui_text" 로 덮어쓸 수 있다.
DEFAULT_UI_TEXT = {
    "thumbnail_label": ["썸네일", "Thumbnail"],
    "add_button": ["추가", "Add"],
    "change_button": ["변경", "수정", "바꾸기", "Change", "Edit", "Replace"],
    "upload_menu": ["파일 업로드", "업로드", "이미지 업로드", "Upload file", "Upload"],
    "save_button": ["업데이트", "게시", "저장", "완료", "Publish", "Update", "Save", "Done"],
    "close_button": ["닫기", "Close"],
    # 저장하지 않고 창을 닫을 때 뜨는 확인창의 버튼 (방금 고른 썸네일만 취소됨).
    # '삭제' 한 단어는 번역 자체를 지우는 버튼일 수 있으므로 절대 넣지 않는다.
    "discard_button": ["변경사항 삭제", "변경사항 취소", "나가기", "Discard changes", "Discard", "Leave"],
}

# upload_all 에 {ALL_LANGUAGES: 이미지} 로 넘기면 모든 언어에 같은 썸네일
ALL_LANGUAGES = "*"

VIDEO_ID_RE = re.compile(r"(?:v=|youtu\.be/|/video/|/shorts/|/live/)([A-Za-z0-9_-]{11})")


def parse_video_id(text: str) -> str:
    text = text.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", text):
        return text
    m = VIDEO_ID_RE.search(text)
    if not m:
        raise ValueError(f"동영상 주소/ID를 이해하지 못했습니다: {text}")
    return m.group(1)


def _exact(words):
    """버튼/라벨 글자 목록 -> 정확히 일치하는 정규식."""
    return re.compile(r"^\s*(" + "|".join(re.escape(w) for w in words) + r")\s*$", re.I)


class StudioThumbnailUploader:
    def __init__(self, page, table: LanguageTable, *, ui_text=None, log_dir="logs",
                 progress_dir="progress", step_delay=1.0, overwrite=False, dry_run=False,
                 studio_url=STUDIO_URL):
        self.page = page
        self.studio_url = studio_url
        self.table = table
        self.ui = {**DEFAULT_UI_TEXT, **(ui_text or {})}
        self.log_dir = Path(log_dir)
        self.progress_dir = Path(progress_dir)
        self.step_delay = step_delay
        self.overwrite = overwrite
        self.dry_run = dry_run

    # ------------------------------------------------------------------ 진행 기록
    def _progress_path(self, video_id):
        return self.progress_dir / f"{video_id}.json"

    def load_progress(self, video_id) -> set:
        path = self._progress_path(video_id)
        if path.exists():
            return set(json.loads(path.read_text(encoding="utf-8")).get("done", []))
        return set()

    def save_progress(self, video_id, done: set):
        self.progress_dir.mkdir(parents=True, exist_ok=True)
        self._progress_path(video_id).write_text(
            json.dumps({"video_id": video_id, "done": sorted(done)}, ensure_ascii=False, indent=2),
            encoding="utf-8")

    # ------------------------------------------------------------------ 화면 열기
    def open_translations(self, video_id):
        url = self.studio_url.format(video_id=video_id)
        print(f"\n스튜디오 언어 화면을 엽니다: {url}")
        self.page.goto(url, wait_until="domcontentloaded")
        if "accounts.google.com" in self.page.url:
            raise RuntimeError("로그인이 필요합니다. 먼저 'python main.py login' 으로 로그인해 주세요.")
        # 언어 표가 나타날 때까지 기다린다 (아는 언어 이름이 하나라도 보이면 준비 완료).
        known = [n for _, ko, en in LANGUAGES for n in (*ko, *en)]
        pattern = _exact(known)
        try:
            self.page.get_by_text(pattern).filter(visible=True).first.wait_for(timeout=60_000)
        except PlaywrightTimeout:
            self._screenshot(video_id, "table_not_found")
            raise RuntimeError("언어 표를 찾지 못했습니다. 동영상 ID, 로그인 채널을 확인해 주세요.")
        time.sleep(self.step_delay)

    def list_languages_on_page(self) -> dict:
        """스튜디오 표에 보이는 언어들 -> {언어코드: 화면에 보이는 이름}."""
        found = {}
        for code, ko_names, en_names in LANGUAGES:
            for name in (*ko_names, *en_names):
                if self._row_label(name).count() > 0:
                    found[code] = name
                    break
        for alias, code in self.table_aliases().items():
            if code not in found and self._row_label(alias).count() > 0:
                found[code] = alias
        return found

    def table_aliases(self):
        return self.table.extra_aliases

    def _row_label(self, name):
        # '언어 추가' 목록처럼 숨겨진 곳의 같은 글자는 제외하고 화면에 보이는 것만
        return self.page.get_by_text(_exact([name])).filter(visible=True)

    # ------------------------------------------------------------------ 메인 루프
    def upload_all(self, video_id, thumbnails: dict) -> dict:
        """thumbnails: {언어코드: 파일경로}. 결과 요약 dict 를 돌려준다.

        {ALL_LANGUAGES: 파일경로} 를 주면 스튜디오에 등록된 모든 언어에 같은 이미지를 넣는다.
        """
        self.open_translations(video_id)
        on_page = self.list_languages_on_page()
        done = self.load_progress(video_id)
        if ALL_LANGUAGES in thumbnails:
            same = thumbnails[ALL_LANGUAGES]
            thumbnails = {code: same for code in on_page}

        summary = {"ok": [], "skipped": [], "failed": [], "not_in_studio": [], "no_file": []}
        summary["no_file"] = sorted(c for c in on_page if c not in thumbnails)
        targets = []
        for code, path in thumbnails.items():
            if code not in on_page:
                summary["not_in_studio"].append(code)
            elif code in done and not self.overwrite:
                summary["skipped"].append(code)
            else:
                targets.append((code, path))

        print(f"스튜디오에 있는 언어 {len(on_page)}개 / 올릴 썸네일 {len(targets)}개"
              f" (이미 완료 {len(summary['skipped'])}개 건너뜀)")

        for i, (code, path) in enumerate(targets, 1):
            name = on_page[code]
            print(f"[{i}/{len(targets)}] {name} <- {Path(path).name} ... ", end="", flush=True)
            try:
                status = self.upload_one(name, Path(path))
            except Exception as exc:  # 한 언어가 실패해도 다음 언어는 계속 진행
                print(f"실패 {(str(exc).splitlines() or [''])[0][:300]}")
                shot = self._screenshot(video_id, code)
                print(f"      화면 캡처: {shot}")
                summary["failed"].append(code)
                self._close_dialog()
                continue
            print(status)
            if status.startswith("완료"):
                summary["ok"].append(code)
                done.add(code)
                self.save_progress(video_id, done)
            else:
                summary["skipped"].append(code)
        return summary

    def upload_one(self, language_name: str, image: Path) -> str:
        step = "언어 창 열기"
        try:
            self.last_open_method = None
            dialog = self._open_language_dialog(language_name)

            step = "썸네일 버튼 찾기"
            button = self._thumbnail_button(dialog)
            label = (button.inner_text() or button.get_attribute("aria-label") or "").strip()
            has_existing = bool(_exact(self.ui["change_button"]).match(label))
            if has_existing and not self.overwrite:
                self._close_dialog()
                return "이미 썸네일 있음 (건너뜀 - 바꾸려면 '새 이미지로 바꾸기' 선택)"
            if self.dry_run:
                self._close_dialog()
                return f"확인만 함 (창 열기: {self.last_open_method}, 버튼: '{label}')"

            step = "이미지 파일 선택"
            image = ensure_uploadable(image, self.log_dir / "converted")
            self._choose_file(dialog, button, image)

            step = "업데이트 누르기"
            self._save(dialog)
        except Exception as exc:
            raise RuntimeError(f"[{step}] {exc.__class__.__name__}: {(str(exc).splitlines() or [''])[0]}") from exc
        time.sleep(self.step_delay)
        return f"완료 (창 열기: {self.last_open_method})"

    # ------------------------------------------------------------------ 단계별 동작
    def _open_language_dialog(self, language_name):
        """언어 이름을 눌러 그 언어의 창을 연다. 막히면 여러 방법을 차례로 시도한다."""
        page = self.page
        label = self._row_label(language_name).first
        try:
            label.scroll_into_view_if_needed(timeout=10_000)
        except PlaywrightError:
            pass
        cell_re = re.compile(r"^\s*(게시됨|초안|Published|Draft)\s*$", re.I)
        edit_re = re.compile(r"수정|편집|Edit", re.I)

        def row_at(depth):
            return label.locator(f"xpath=ancestor::*[{depth}]")

        def click_row_cell():
            # 같은 줄의 '게시됨' 칸 또는 수정(연필) 버튼
            for depth in range(1, 7):
                row = row_at(depth)
                targets = row.get_by_text(cell_re)
                if targets.count() == 0:
                    targets = row.get_by_role("button", name=edit_re)
                if targets.count() == 0:
                    continue
                row.hover(force=True, timeout=3_000)
                targets.first.click(timeout=3_000, force=True)
                return
            raise RuntimeError("같은 줄의 칸을 찾지 못함")

        def js_click_ancestors():
            # 화면 위에 다른 것이 덮여 있어도 동작하도록 이름과 그 부모 요소에 직접 클릭 신호를 보낸다
            label.evaluate("""el => {
                for (let node = el, i = 0; node && i < 4; node = node.parentElement, i++) {
                    node.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
                    if (document.querySelector('[role=dialog], tp-yt-paper-dialog, ytcp-dialog')) break;
                }
            }""")

        attempts = [
            ("일반 클릭", lambda: label.click(timeout=5_000)),
            ("직접 클릭", lambda: label.evaluate("el => el.click()")),
            ("부모 요소 클릭", js_click_ancestors),
            ("같은 줄 칸 클릭", click_row_cell),
            ("강제 클릭", lambda: label.click(timeout=5_000, force=True)),
        ]
        errors = []
        for method, action in attempts:
            try:
                action()
            except Exception as exc:
                errors.append(f"{method}: {exc.__class__.__name__}")
                continue
            dialog = self._wait_dialog(6_000)
            if dialog is not None:
                self.last_open_method = method
                return dialog
            errors.append(f"{method}: 창 안 열림")
            page.keyboard.press("Escape")
        raise RuntimeError("언어 창이 열리지 않았습니다 (" + ", ".join(errors) + ")")

    def _wait_dialog(self, timeout_ms):
        """썸네일 항목이 있는 언어 창을 기다린다 (timeout_ms=0 이면 한 번만 확인)."""
        deadline = time.time() + timeout_ms / 1000
        while True:
            try:
                dialog = self._find_dialog()
            except PlaywrightError:
                dialog = None
            if dialog is not None or time.time() >= deadline:
                return dialog
            time.sleep(0.3)

    def _find_dialog(self):
        label_re = _exact(self.ui["thumbnail_label"])
        save_re = _exact(self.ui["save_button"])
        button_re = _exact(self.ui["add_button"] + self.ui["change_button"])
        candidates = self.page.locator("[role=dialog], [aria-modal=true], tp-yt-paper-dialog, ytcp-dialog").all()
        for dialog in candidates:
            if (dialog.is_visible() and dialog.get_by_text(label_re).count() > 0
                    and dialog.get_by_role("button", name=button_re).count() > 0):
                return dialog
        # 창 표시가 없는 경우: 화면의 '썸네일' 글자에서 위로 올라가며 '업데이트' 버튼을 품은 가장 작은 영역.
        # 언어 표 맨 위의 '썸네일' 제목 칸도 같은 글자라서, 가장 가까이에 업데이트 버튼이 있는 쪽을 고른다.
        labels = self.page.get_by_text(label_re)
        best = None
        for i in range(labels.count()):
            label = labels.nth(i)
            if not label.is_visible():
                continue
            for depth in range(1, 9):
                box = label.locator(f"xpath=ancestor::*[{depth}]")
                if (box.get_by_role("button", name=save_re).count() > 0
                        and box.get_by_role("button", name=button_re).count() > 0):
                    if best is None or depth < best[0]:
                        best = (depth, box)
                    break
        return best[1] if best else None

    def _thumbnail_button(self, dialog):
        """'썸네일' 글자와 **같은 줄**에 있는 추가/변경 버튼을 찾는다.

        언어 창에는 썸네일·오디오·수동 자막 줄마다 똑같은 '추가' 버튼이 있으므로,
        화면상 위치(세로 높이)가 '썸네일' 글자와 같은 버튼만 고른다. 없으면 아무것도 누르지 않고 멈춘다.
        """
        label_re = _exact(self.ui["thumbnail_label"])
        button_re = _exact(self.ui["add_button"] + self.ui["change_button"])
        named_re = re.compile(r"(썸네일|thumbnail).*(추가|변경|add|change|upload|업로드)", re.I)

        labels = dialog.get_by_text(label_re)
        labels.first.wait_for(state="visible", timeout=10_000)
        candidates = []
        for loc in (dialog.get_by_role("button", name=button_re),
                    dialog.get_by_role("button", name=named_re),
                    dialog.locator("button, [role=button], ytcp-button, tp-yt-paper-button").filter(has_text=button_re),
                    dialog.get_by_text(button_re)):
            candidates.extend(loc.all())

        best = None
        for i in range(labels.count()):
            label = labels.nth(i)
            if not label.is_visible():
                continue
            lb = label.bounding_box()
            if not lb:
                continue
            label_y = lb["y"] + lb["height"] / 2
            for button in candidates:
                try:
                    if not button.is_visible():
                        continue
                    bb = button.bounding_box()
                except PlaywrightError:
                    continue
                if not bb or bb["x"] + bb["width"] <= lb["x"]:
                    continue  # 글자보다 왼쪽에 있는 버튼은 제외
                diff = abs(bb["y"] + bb["height"] / 2 - label_y)
                if diff > max(lb["height"], bb["height"]) * 0.75 + 6:
                    continue  # 다른 줄(오디오, 자막)의 버튼
                key = (diff, bb["width"] * bb["height"])
                if best is None or key < best[0]:
                    best = (key, button)
        if best is None:
            raise RuntimeError("썸네일 줄의 '추가' 버튼을 찾지 못해 아무것도 누르지 않고 멈췄습니다")
        return best[1]

    def _is_image_input(self, element) -> bool:
        accept = (element.get_attribute("accept") or "").lower()
        return "image" in accept or any(ext in accept for ext in (".jpg", ".jpeg", ".png"))

    def _choose_file(self, dialog, button, image: Path):
        page = self.page

        def use_chooser(chooser):
            # 오디오/동영상용 파일 선택창이면 이미지를 넣지 않고 멈춘다
            accept = (chooser.element.get_attribute("accept") or "").lower()
            if accept and not self._is_image_input(chooser.element):
                chooser.set_files([])
                raise RuntimeError(f"썸네일이 아닌 파일 선택창이 열려 멈췄습니다 (accept={accept})")
            chooser.set_files(str(image))

        # 1) 버튼을 누르면 바로 파일 선택창이 뜨는 경우
        try:
            with page.expect_file_chooser(timeout=6_000) as chooser:
                button.click()
            use_chooser(chooser.value)
            return
        except PlaywrightTimeout:
            pass
        # 오디오 트랙 같은 다른 창이 열렸으면 멈춘다
        if page.get_by_text(re.compile(r"오디오 트랙|audio track", re.I)).filter(visible=True).count() > 0:
            raise RuntimeError("썸네일이 아닌 '오디오 트랙' 창이 열려 멈췄습니다")
        # 2) '파일 업로드' 같은 메뉴가 먼저 뜨는 경우 (메뉴 항목만 누른다)
        menu_re = _exact(self.ui["upload_menu"])
        for item in (page.get_by_role("menuitem", name=menu_re),
                     page.get_by_role("option", name=menu_re)):
            if item.count() > 0 and item.first.is_visible():
                try:
                    with page.expect_file_chooser(timeout=6_000) as chooser:
                        item.first.click()
                    use_chooser(chooser.value)
                    return
                except PlaywrightTimeout:
                    pass
        # 3) 숨겨진 '이미지용' 파일 입력칸에 직접 넣기
        for scope in (dialog, page):
            for element in scope.locator("input[type=file]").all():
                if self._is_image_input(element):
                    element.set_input_files(str(image))
                    return
        raise RuntimeError("썸네일 파일 선택창을 열지 못했습니다")

    def _save(self, dialog):
        save_re = _exact(self.ui["save_button"])
        save = dialog.get_by_role("button", name=save_re)
        if save.count() == 0:
            save = dialog.locator("button, [role=button]").filter(has_text=save_re)
        save = save.first
        # 이미지 업로드/처리가 끝나 버튼이 활성화될 때까지 기다린다.
        deadline = time.time() + 90
        while time.time() < deadline:
            if save.is_visible() and save.is_enabled() and save.get_attribute("aria-disabled") != "true":
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("'업데이트' 버튼이 활성화되지 않았습니다 (이미지 거부 가능성)")
        save.click()
        # 창이 닫힐 때까지 기다린다
        deadline = time.time() + 60
        while self._wait_dialog(0) is not None:
            if time.time() > deadline:
                raise RuntimeError("'업데이트' 후 창이 닫히지 않았습니다")
            time.sleep(0.5)

    def _close_dialog(self):
        page = self.page
        self._close_role_dialogs()
        # 창 표시(role)가 없는 창이 아직 떠 있으면 Esc
        if self._wait_dialog(0) is not None:
            page.keyboard.press("Escape")
            time.sleep(0.5)

    def _close_role_dialogs(self):
        page = self.page
        for dialog in page.get_by_role("dialog").all():
            try:
                if not dialog.is_visible():
                    continue
                close = dialog.get_by_role("button", name=_exact(self.ui["close_button"]))
                if close.count() > 0:
                    close.first.click(timeout=3_000)
                else:
                    page.keyboard.press("Escape")
                time.sleep(0.5)
                # '저장하지 않고 나갈까요?' 확인창이 뜨면 '나가기' 선택.
                # 언어 창(썸네일 항목이 있는 창) 안의 버튼은 절대 누르지 않고, 별도 확인창에서만 찾는다.
                label_re = _exact(self.ui["thumbnail_label"])
                for confirm in page.get_by_role("dialog").all():
                    if not confirm.is_visible() or confirm.get_by_text(label_re).count() > 0:
                        continue
                    discard = confirm.get_by_role("button", name=_exact(self.ui["discard_button"]))
                    if discard.count() > 0 and discard.first.is_visible():
                        discard.first.click(timeout=3_000)
                        break
            except PlaywrightError:
                pass

    def _screenshot(self, video_id, tag) -> str:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        path = self.log_dir / f"{video_id}_{tag}_{datetime.now():%H%M%S}.png"
        try:
            self.page.screenshot(path=str(path), full_page=True)
        except PlaywrightError:
            pass
        return str(path)
