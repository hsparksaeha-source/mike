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
    "discard_button": ["삭제", "변경사항 삭제", "나가기", "Discard", "Discard changes", "Leave"],
}

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
        """thumbnails: {언어코드: 파일경로}. 결과 요약 dict 를 돌려준다."""
        self.open_translations(video_id)
        on_page = self.list_languages_on_page()
        done = self.load_progress(video_id)

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
                print(f"실패 ({exc.__class__.__name__}: {(str(exc).splitlines() or [''])[0][:120]})")
                shot = self._screenshot(video_id, code)
                print(f"      화면 캡처: {shot}")
                summary["failed"].append(code)
                self._close_dialog()
                continue
            print(status)
            if status == "완료":
                summary["ok"].append(code)
                done.add(code)
                self.save_progress(video_id, done)
            else:
                summary["skipped"].append(code)
        return summary

    def upload_one(self, language_name: str, image: Path) -> str:
        dialog = self._open_language_dialog(language_name)

        button = self._thumbnail_button(dialog)
        label = (button.inner_text() or button.get_attribute("aria-label") or "").strip()
        has_existing = bool(_exact(self.ui["change_button"]).match(label))
        if has_existing and not self.overwrite:
            self._close_dialog()
            return "이미 썸네일 있음 (건너뜀, 바꾸려면 --overwrite)"
        if self.dry_run:
            self._close_dialog()
            return "확인만 함 (--dry-run)"

        self._choose_file(dialog, button, image)
        self._save(dialog)
        time.sleep(self.step_delay)
        return "완료"

    # ------------------------------------------------------------------ 단계별 동작
    def _open_language_dialog(self, language_name):
        label = self._row_label(language_name).first
        label.scroll_into_view_if_needed()
        label.click()
        dialog = self._wait_dialog(10_000)
        if dialog is None:
            # 이름 클릭으로 안 열리면 같은 줄의 '게시됨' 칸이나 수정(연필) 버튼을 눌러 본다.
            cell_re = re.compile(r"^\s*(게시됨|초안|Published|Draft)\s*$|수정|Edit", re.I)
            for depth in range(1, 7):
                row = label.locator(f"xpath=ancestor::*[{depth}]")
                cells = row.get_by_text(cell_re)
                if cells.count() == 0:
                    cells = row.get_by_role("button", name=cell_re)
                if cells.count() == 0:
                    continue
                row.hover()
                try:
                    cells.first.click(timeout=3_000)
                except PlaywrightError:
                    break
                dialog = self._wait_dialog(8_000)
                break
        if dialog is None:
            raise RuntimeError("언어 창이 열리지 않았습니다")
        return dialog

    def _wait_dialog(self, timeout_ms):
        """썸네일 항목이 있는 창(dialog)을 기다린다."""
        label_re = _exact(self.ui["thumbnail_label"])
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            for dialog in self.page.get_by_role("dialog").all():
                try:
                    if dialog.is_visible() and dialog.get_by_text(label_re).count() > 0:
                        return dialog
                except PlaywrightError:
                    pass
            time.sleep(0.3)
        return None

    def _thumbnail_button(self, dialog):
        """'썸네일' 글자와 같은 줄에 있는 추가/변경 버튼을 찾는다."""
        label = dialog.get_by_text(_exact(self.ui["thumbnail_label"])).first
        label.wait_for(state="visible", timeout=10_000)
        button_re = _exact(self.ui["add_button"] + self.ui["change_button"])
        for depth in range(1, 8):
            box = label.locator(f"xpath=ancestor::*[{depth}]")
            buttons = box.get_by_role("button", name=button_re)
            if buttons.count() == 0:
                buttons = box.locator("button, [role=button]").filter(has_text=button_re)
            count = buttons.count()
            if count == 1:
                return buttons.first
            if count > 1:
                # 오디오/자막 줄까지 포함될 만큼 올라왔다 -> 문서 순서상 '썸네일' 바로 뒤의 버튼
                return buttons.first
        raise RuntimeError("썸네일 '추가' 버튼을 찾지 못했습니다")

    def _choose_file(self, dialog, button, image: Path):
        page = self.page
        # 1) 버튼을 누르면 바로 파일 선택창이 뜨는 경우
        try:
            with page.expect_file_chooser(timeout=6_000) as chooser:
                button.click()
            chooser.value.set_files(str(image))
            return
        except PlaywrightTimeout:
            pass
        # 2) '파일 업로드' 같은 메뉴가 먼저 뜨는 경우
        menu_re = _exact(self.ui["upload_menu"])
        for item in (page.get_by_role("menuitem", name=menu_re),
                     page.get_by_role("option", name=menu_re),
                     page.get_by_text(menu_re)):
            if item.count() > 0 and item.first.is_visible():
                try:
                    with page.expect_file_chooser(timeout=6_000) as chooser:
                        item.first.click()
                    chooser.value.set_files(str(image))
                    return
                except PlaywrightTimeout:
                    pass
        # 3) 숨겨진 파일 입력칸에 직접 넣기
        inputs = dialog.locator("input[type=file]")
        if inputs.count() == 0:
            inputs = page.locator("input[type=file]")
        if inputs.count() > 0:
            inputs.last.set_input_files(str(image))
            return
        raise RuntimeError("파일 선택창을 열지 못했습니다")

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
        dialog.wait_for(state="hidden", timeout=60_000)

    def _close_dialog(self):
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
                # '변경사항을 삭제할까요?' 확인창이 뜨면 삭제(나가기) 선택
                discard = page.get_by_role("button", name=_exact(self.ui["discard_button"]))
                if discard.count() > 0 and discard.first.is_visible():
                    discard.first.click(timeout=3_000)
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
