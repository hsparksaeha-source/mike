"""Tkinter 창 프로그램에서 썸네일 등록 기능을 쓰기 위한 도우미.

번역 프로그램(youtube_translator_maker.pyw)이 이것을 불러서
'유튜브 로그인', '썸네일 자동 등록' 버튼을 동작시킨다.
"""

import argparse
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from main import BASE_DIR, browser_options, load_config, run_uploads

from .languages import LanguageTable
from .studio import parse_video_id


class _QueueWriter:
    def __init__(self, q):
        self.q = q

    def write(self, text):
        if text:
            self.q.put(text)

    def flush(self):
        pass


class ThumbnailRunner:
    def __init__(self, root, set_status):
        """set_status(text, color): 메인 창의 상태 표시줄을 바꾸는 함수."""
        self.root = root
        self.set_status = set_status
        self.cfg = load_config("config.json")
        self.table = LanguageTable(self.cfg.get("language_aliases"))
        self.worker = None
        self.log_queue = queue.Queue()
        self.log_window = None
        self.log_text = None
        self._login_done = threading.Event()

    # ------------------------------------------------------------------ 공용
    def code_for(self, lang_code):
        """번역 프로그램의 언어코드(zh-CN, he, tl ...) -> 스튜디오용 언어코드."""
        return self.table.code_for(lang_code) or lang_code

    def needs_login(self):
        return not (BASE_DIR / self.cfg.get("profile_dir", "browser_profile")).exists()

    def busy(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("진행 중", "썸네일 작업이 아직 진행 중입니다.")
            return True
        return False

    def _args(self, overwrite=False, dry_run=False):
        return argparse.Namespace(cdp=None, only=None, overwrite=overwrite, dry_run=dry_run)

    def _run(self, target, *args):
        self.show_log()

        def wrapper():
            old_out, old_err = sys.stdout, sys.stderr
            sys.stdout = sys.stderr = _QueueWriter(self.log_queue)
            try:
                target(*args)
            except Exception as exc:
                print(f"\n[오류] {exc}")
                self._status(f"❌ 썸네일 오류: {exc}", "red")
            finally:
                sys.stdout, sys.stderr = old_out, old_err
        self.worker = threading.Thread(target=wrapper, daemon=True)
        self.worker.start()

    def _status(self, text, color="blue"):
        self.root.after(0, self.set_status, text, color)

    # ------------------------------------------------------------------ 기록 창
    def show_log(self):
        if self.log_window is not None and self.log_window.winfo_exists():
            self.log_window.lift()
            return
        win = tk.Toplevel(self.root)
        win.title("썸네일 등록 진행 기록")
        win.geometry("760x480")
        text = tk.Text(win, wrap="word", state="disabled")
        scroll = ttk.Scrollbar(win, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.log_window, self.log_text = win, text
        self._poll_log()

    def _poll_log(self):
        if self.log_window is None or not self.log_window.winfo_exists():
            return
        chunks = []
        while not self.log_queue.empty():
            chunks.append(self.log_queue.get_nowait())
        if chunks:
            self.log_text.configure(state="normal")
            self.log_text.insert(tk.END, "".join(chunks))
            self.log_text.see(tk.END)
            self.log_text.configure(state="disabled")
        self.root.after(150, self._poll_log)

    # ------------------------------------------------------------------ 로그인
    def login(self):
        if self.busy():
            return
        self._login_done.clear()
        self._run(self._login_worker)

    def _login_worker(self):
        from .browser import open_studio_page

        self._status("크롬 창에서 구글 로그인 후 채널을 선택하고, 안내창의 [확인]을 눌러 주세요.", "red")
        with open_studio_page(**browser_options(self.cfg, self._args())) as page:
            page.goto("https://studio.youtube.com/")
            self.root.after(0, self._ask_login_done)
            self._login_done.wait()
        print("로그인 정보가 저장되었습니다.\n")
        self._status("✅ 유튜브 로그인 완료! 이제 썸네일 자동 등록을 누르면 됩니다.", "green")

    def _ask_login_done(self):
        messagebox.showinfo("유튜브 로그인",
                            "⚠️ 아직 [확인]을 누르지 마세요!\n\n"
                            "1. 작업표시줄에서 새로 열린 크롬 창을 여세요 (이 창 뒤에 있을 수 있습니다).\n"
                            "2. 구글 로그인 후 썸네일을 넣을 채널을 선택하세요.\n"
                            "3. YouTube 스튜디오 화면이 보이면 그때 [확인]을 눌러 주세요.")
        self._login_done.set()

    # ------------------------------------------------------------------ 업로드
    def upload(self, video, thumbs, overwrite=False, dry_run=False):
        """thumbs: {번역 프로그램 언어코드: 이미지 경로}"""
        if self.busy():
            return
        try:
            video_id = parse_video_id(video)
        except ValueError as exc:
            messagebox.showwarning("동영상 주소", str(exc))
            return
        studio_thumbs = {}
        for code, path in thumbs.items():
            studio_thumbs.setdefault(self.code_for(code), Path(path))
        self._status("🖼️ 썸네일 등록 중... (크롬 창을 건드리지 마세요)")
        self._run(self._upload_worker, video_id, studio_thumbs, overwrite, dry_run)

    def _upload_worker(self, video_id, thumbs, overwrite, dry_run):
        if "*" in thumbs:
            print(f"\n===== 동영상 {video_id} / 모든 언어에 같은 썸네일: {thumbs['*'].name}")
        else:
            print(f"\n===== 동영상 {video_id} / 썸네일 {len(thumbs)}개")
        code = run_uploads(self.cfg, self._args(overwrite, dry_run), self.table, [(video_id, thumbs)])
        if code == 0:
            self._status("✅ 시험 실행 완료! 문제없으면 [썸네일 자동 등록]을 누르세요." if dry_run
                         else "✅ 썸네일 등록이 완료되었습니다!", "green")
        else:
            self._status("⚠️ 일부 언어 썸네일이 실패했습니다. 다시 누르면 실패한 언어만 다시 시도합니다.", "red")
