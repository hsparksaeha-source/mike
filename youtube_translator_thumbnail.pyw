import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import pyperclip
import csv
import time
import os
import html
import requests
import re
import sys

# 같은 폴더의 썸네일 자동 등록 기능(thumb_agent) 불러오기
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from thumb_agent.folder import describe_scan, scan_folder
from thumb_agent.tk_thumbs import ThumbnailRunner

API_KEY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "google_translate_api_key.txt")


def load_api_key():
    if not os.path.isfile(API_KEY_PATH):
        raise FileNotFoundError(
            f"구글 번역 API 키 파일을 찾을 수 없습니다: {API_KEY_PATH}\n"
            f"그 위치에 텍스트 파일을 만들고 API 키를 붙여넣어 주세요."
        )
    with open(API_KEY_PATH, encoding="utf-8") as f:
        key = f.read().strip()
    if not key:
        raise ValueError(f"API 키 파일이 비어있습니다: {API_KEY_PATH}")
    return key


GOOGLE_TRANSLATE_API_KEY = load_api_key()

# 구글 번역이 지원하는 전체 언어 목록
ALL_SUPPORTED_LANGS = {
    'af': '아프리칸스어', 'sq': '알바니아어', 'am': '암하라어', 'ar': '아랍어', 'hy': '아르메니아어',
    'az': '아제르바이잔어', 'eu': '바스크어', 'be': '벨라루스어', 'bn': '벵골어', 'bs': '보스니아어',
    'bg': '불가리아어', 'ca': '카탈루냐어', 'ceb': '세부아노어', 'ny': '치츄아어', 'zh-CN': '중국어(간체)',
    'zh-TW': '중국어(번체)', 'co': '코르시카어', 'hr': '크로아티아어', 'cs': '체코어', 'da': '덴마크어',
    'nl': '네덜란드어', 'en': '영어', 'eo': '에스페란토', 'et': '에스토니아어', 'tl': '필리핀어',
    'fi': '핀란드어', 'fr': '프랑스어', 'fy': '프리지아어', 'gl': '갈리시아어', 'ka': '조지아어',
    'de': '독일어', 'el': '그리스어', 'gu': '구자라트어', 'ht': '아이티크리올어', 'ha': '하우사어',
    'haw': '하와이어', 'he': '히브리어', 'hi': '힌디어', 'hmn': '몽어', 'hu': '헝가리어',
    'is': '아이슬란드어', 'ig': '이보어', 'id': '인도네시아어', 'ga': '아일랜드어', 'it': '이탈리아어',
    'ja': '일본어', 'jw': '자바어', 'kn': '칸나다어', 'kk': '카자흐어', 'km': '크메르어', 'ko': '한국어',
    'ku': '쿠르드어', 'ky': '키르기스어', 'lo': '라오어', 'la': '라틴어', 'lv': '라트비아어',
    'lt': '리투아니아어', 'lb': '룩셈부르크어', 'mk': '마케도니아어', 'mg': '말라가시어', 'ms': '말레이어',
    'ml': '말라얄람어', 'mt': '몰타어', 'mi': '마오리어', 'mr': '마라티어', 'mn': '몽골어',
    'my': '미얀마어(버마어)', 'ne': '네팔어', 'no': '노르웨이어', 'or': '오디아어', 'ps': '파슈토어',
    'fa': '페르시아어', 'pl': '폴란드어', 'pt': '포르투갈어', 'pa': '펀자브어', 'ro': '루마니아어',
    'ru': '러시아어', 'sm': '사모아어', 'gd': '스코틀랜드게일어', 'sr': '세르비아어', 'st': '세소토어',
    'sn': '쇼나어', 'sd': '신디어', 'si': '싱할라어', 'sk': '슬로바키아어', 'sl': '슬로베니아어',
    'so': '소말리어', 'es': '스페인어', 'su': '순다어', 'sw': '스와힐리어', 'sv': '스웨덴어',
    'tg': '타지크어', 'ta': '타밀어', 'te': '텔루구어', 'th': '태국어', 'tr': '튀르키예어',
    'uk': '우크라이나어', 'ur': '우르두어', 'ug': '위구르어', 'uz': '우즈베크어', 'vi': '베트남어',
    'cy': '웨일스어', 'xh': '코사어', 'yi': '이디시어', 'yo': '요루바어', 'zu': '줄루어'
}

# 기본 50개 언어로 롤백 (안정성 최우선)
DEFAULT_LANGS = {
    'en': '영어', 'ja': '일본어', 'zh-CN': '중국어(간체)', 'zh-TW': '중국어(번체)', 'es': '스페인어',
    'fr': '프랑스어', 'de': '독일어', 'ru': '러시아어', 'pt': '포르투갈어', 'it': '이탈리아어',
    'vi': '베트남어', 'th': '태국어', 'id': '인도네시아어', 'ar': '아랍어', 'hi': '힌디어',
    'bn': '벵골어', 'ms': '말레이어', 'tr': '튀르키예어', 'fa': '페르시아어', 'ur': '우르두어',
    'pl': '폴란드어', 'uk': '우크라이나어', 'nl': '네덜란드어', 'el': '그리스어', 'sv': '스웨덴어',
    'ro': '루마니아어', 'hu': '헝가리어', 'cs': '체코어', 'da': '덴마크어', 'fi': '핀란드어',
    'sk': '슬로바키아어', 'no': '노르웨이어', 'bg': '불가리아어', 'hr': '크로아티아어', 'lt': '리투아니아어',
    'sl': '슬로베니아어', 'lv': '라트비아어', 'et': '에스토니아어', 'sr': '세르비아어', 'ca': '카탈루냐어',
    'he': '히브리어', 'af': '아프리칸스어', 'sw': '스와힐리어', 'tl': '필리핀어', 'ta': '타밀어',
    'te': '텔루구어', 'ml': '말라얄람어', 'mr': '마라티어', 'gu': '구자라트어', 'kn': '칸나다어'
}

def add_clipboard_support(widget):
    menu = tk.Menu(widget, tearoff=0)
    menu.add_command(label="잘라내기 (Ctrl+X)", command=lambda: widget.event_generate("<<Cut>>"))
    menu.add_command(label="복사 (Ctrl+C)", command=lambda: widget.event_generate("<<Copy>>"))
    menu.add_command(label="붙여넣기 (Ctrl+V)", command=lambda: widget.event_generate("<<Paste>>"))
    
    def show_menu(event):
        menu.tk_popup(event.x_root, event.y_root)
    widget.bind("<Button-3>", show_menu)
    
    def force_paste(event):
        widget.event_generate("<<Paste>>")
        return "break"
    widget.bind("<Control-v>", force_paste)
    widget.bind("<Control-V>", force_paste)

class YouTubeTranslatorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("유튜브 다국어 자동 번역기 + 썸네일 자동 등록")
        self.root.geometry("950x1000")
        
        self.active_langs = {}
        self.lang_widgets = {}
        self.thumb_paths = {}      # 언어코드 -> 썸네일 이미지 경로
        self.folder_thumbs = {}    # 썸네일 폴더에서 찾은 {스튜디오 언어코드: 경로}
        self.last_scan = None
        self.thumbs = ThumbnailRunner(self.root, self.set_status)

        self.create_top_frame()
        self.create_thumbnail_frame()
        self.create_language_control_frame()
        self.create_bottom_frame()
        self.create_footer_frame()

        for code, name in DEFAULT_LANGS.items():
            self.add_language_card(code, name)

    def create_top_frame(self):
        top_frame = ttk.LabelFrame(self.root, text="[ 원본 입력 ]", padding=(15, 15))
        top_frame.pack(side="top", fill="x", padx=15, pady=5)

        ttk.Label(top_frame, text="영상 제목:").grid(row=0, column=0, sticky="w", pady=5)
        self.entry_title_src = ttk.Entry(top_frame, width=80)
        self.entry_title_src.grid(row=0, column=1, sticky="w", padx=10, pady=5)
        add_clipboard_support(self.entry_title_src)

        ttk.Label(top_frame, text="영상 설명:").grid(row=1, column=0, sticky="nw", pady=5)
        self.text_desc_src = tk.Text(top_frame, width=80, height=5)
        self.text_desc_src.grid(row=1, column=1, sticky="w", padx=10, pady=5)
        add_clipboard_support(self.text_desc_src)

        self.btn_translate = ttk.Button(top_frame, text="목록의 전체 언어 번역 시작", command=self.start_translation)
        self.btn_translate.grid(row=2, column=1, sticky="e", padx=10, pady=10)
        
        self.lbl_status = ttk.Label(top_frame, text="대기 중...", foreground="blue", font=("", 10, "bold"))
        self.lbl_status.grid(row=2, column=0, columnspan=2, sticky="w")

    def set_status(self, text, color="blue"):
        self.lbl_status.config(text=text, foreground=color)

    def create_thumbnail_frame(self):
        frame = ttk.LabelFrame(self.root, text="[ 썸네일 자동 등록 ]", padding=(15, 10))
        frame.pack(side="top", fill="x", padx=15, pady=5)

        ttk.Label(frame, text="동영상 주소:").grid(row=0, column=0, sticky="w", pady=3)
        self.entry_video = ttk.Entry(frame, width=80)
        self.entry_video.grid(row=0, column=1, columnspan=2, sticky="we", padx=10, pady=3)
        add_clipboard_support(self.entry_video)

        ttk.Label(frame, text="썸네일 폴더:").grid(row=1, column=0, sticky="w", pady=3)
        self.entry_thumb_folder = ttk.Entry(frame, width=66)
        self.entry_thumb_folder.grid(row=1, column=1, sticky="we", padx=10, pady=3)
        add_clipboard_support(self.entry_thumb_folder)
        ttk.Button(frame, text="📁 폴더 선택", command=self.browse_thumb_folder).grid(row=1, column=2, sticky="e")

        self.var_thumb_overwrite = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="이미 썸네일이 있는 언어도 새 이미지로 바꾸기",
                        variable=self.var_thumb_overwrite).grid(row=2, column=1, sticky="w", padx=10)

        buttons = ttk.Frame(frame)
        buttons.grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Button(buttons, text="① 유튜브 로그인", command=self.thumbs.login).pack(side="left", padx=4)
        ttk.Button(buttons, text="② 시험 실행 (올리지 않음)",
                   command=lambda: self.start_thumbnail_upload(dry_run=True)).pack(side="left", padx=4)
        ttk.Button(buttons, text="🖼️ 썸네일 자동 등록",
                   command=lambda: self.start_thumbnail_upload(dry_run=False)).pack(side="left", padx=4)
        ttk.Button(buttons, text="📜 진행 기록 보기", command=self.thumbs.show_log).pack(side="left", padx=4)
        frame.columnconfigure(1, weight=1)

    def browse_thumb_folder(self):
        folder = filedialog.askdirectory(title="썸네일 이미지가 들어 있는 폴더를 선택하세요")
        if folder:
            self.entry_thumb_folder.delete(0, tk.END)
            self.entry_thumb_folder.insert(0, folder)
            self.load_thumb_folder()

    def load_thumb_folder(self):
        """폴더의 이미지 파일 이름을 보고 각 언어 카드에 썸네일을 채운다."""
        folder = self.entry_thumb_folder.get().strip().strip('"')
        if not folder:
            return False
        try:
            scan = scan_folder(folder, self.thumbs.table)
        except FileNotFoundError as e:
            messagebox.showerror("폴더 오류", str(e))
            return False
        self.folder_thumbs = dict(scan.matched)
        self.last_scan = scan
        for code in self.active_langs:
            path = self.folder_thumbs.get(self.thumbs.code_for(code))
            if path:
                self.set_card_thumb(code, str(path))
        filled = sum(1 for c in self.active_langs if c in self.thumb_paths)
        missing = [self.active_langs[c] for c in self.active_langs if c not in self.thumb_paths]
        msg = f"🖼️ 썸네일 {filled}/{len(self.active_langs)}개 언어에 연결됨"
        if missing:
            msg += f" (없음: {', '.join(missing[:5])}{' 외' if len(missing) > 5 else ''})"
        if scan.unmatched:
            msg += f" / 언어를 알 수 없는 파일 {len(scan.unmatched)}개"
        self.set_status(msg, "blue" if not missing and not scan.unmatched else "red")
        return True

    def set_card_thumb(self, code, path):
        if code not in self.lang_widgets:
            return
        if path:
            self.thumb_paths[code] = path
            self.lang_widgets[code]['thumb'].config(text=f"🖼️ {os.path.basename(path)}", foreground="green")
        else:
            self.thumb_paths.pop(code, None)
            self.lang_widgets[code]['thumb'].config(text="🖼️ 썸네일 없음", foreground="gray")

    def choose_card_thumb(self, code):
        path = filedialog.askopenfilename(
            title=f"[{self.active_langs[code]}] 썸네일 이미지 선택",
            filetypes=[("이미지 파일", "*.jpg *.jpeg *.png *.gif *.bmp"), ("모든 파일", "*.*")])
        if path:
            self.set_card_thumb(code, path)

    def start_thumbnail_upload(self, dry_run):
        video = self.entry_video.get().strip()
        if not video:
            messagebox.showwarning("경고", "썸네일을 넣을 동영상 주소를 입력해주세요.")
            return
        if self.entry_thumb_folder.get().strip():
            self.load_thumb_folder()
        thumbs = {c: p for c, p in self.thumb_paths.items() if c in self.active_langs}
        if not thumbs:
            detail = ""
            if self.last_scan is not None and self.entry_thumb_folder.get().strip():
                detail = "\n\n" + describe_scan(self.last_scan)
                extra = [c for c in self.last_scan.matched
                         if c not in {self.thumbs.code_for(a) for a in self.active_langs}]
                if extra:
                    detail += ("\n아래 목록에 없는 언어의 이미지: "
                               + ", ".join(self.thumbs.table.display_name(c) for c in extra)
                               + "\n  → [새로운 언어 추가]로 해당 언어를 목록에 넣어 주세요.")
            messagebox.showwarning("경고", "연결된 썸네일이 없습니다.\n썸네일 폴더를 선택하거나 언어 카드에서 썸네일을 선택해주세요." + detail)
            return
        if self.thumbs.needs_login():
            messagebox.showinfo("로그인 필요", "처음 사용하시면 먼저 [① 유튜브 로그인]을 해주세요.")
            return
        if not dry_run and not messagebox.askyesno(
                "확인", f"{len(thumbs)}개 언어에 썸네일을 등록할까요?\n\n진행 중에는 크롬 창을 건드리지 마세요."):
            return
        self.thumbs.upload(video, thumbs, overwrite=self.var_thumb_overwrite.get(), dry_run=dry_run)

    def create_language_control_frame(self):
        control_frame = ttk.Frame(self.root)
        control_frame.pack(fill="x", padx=15, pady=5)

        ttk.Label(control_frame, text="➕ 새로운 언어 추가:", font=("", 10, "bold")).pack(side="left")

        combo_values = [f"{name} ({code})" for code, name in ALL_SUPPORTED_LANGS.items()]
        combo_values.sort()
        
        self.combo_langs = ttk.Combobox(control_frame, values=combo_values, width=30, state="readonly")
        self.combo_langs.pack(side="left", padx=10)
        self.combo_langs.set("추가할 언어를 선택하세요")

        btn_add_lang = ttk.Button(control_frame, text="목록에 추가하기", command=self.add_new_language_from_combo)
        btn_add_lang.pack(side="left")

    def create_bottom_frame(self):
        self.bottom_outer_frame = ttk.LabelFrame(self.root, text="[ 번역 결과 및 언어 관리 ]", padding=(10, 10))
        self.bottom_outer_frame.pack(side="top", fill="both", expand=True, padx=15, pady=5)

        self.canvas = tk.Canvas(self.bottom_outer_frame)
        self.scrollbar = ttk.Scrollbar(self.bottom_outer_frame, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        def _on_mousewheel(event):
            self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        self.canvas.bind_all("<MouseWheel>", _on_mousewheel)

    def create_footer_frame(self):
        footer_frame = ttk.Frame(self.root, padding=(10, 10))
        footer_frame.pack(side="bottom", fill="x")

        btn_save_all = ttk.Button(footer_frame, text="💾 엑셀(CSV) 형식으로 현재 목록 전체 저장", command=self.save_all_to_csv)
        btn_save_all.pack(pady=5, ipadx=20, ipady=5)

    def add_language_card(self, code, lang_name):
        if code in self.active_langs:
            return

        self.active_langs[code] = lang_name

        card = ttk.Frame(self.scrollable_frame, borderwidth=1, relief="groove")
        card.pack(fill="x", padx=5, pady=5, ipadx=10, ipady=10)

        left_frame = ttk.Frame(card)
        left_frame.pack(side="left", fill="y", padx=5)

        lbl_lang = ttk.Label(left_frame, text=f"{lang_name}\n({code})", width=12, font=("", 10, "bold"), anchor="center", justify="center")
        lbl_lang.pack(side="top", pady=(5, 5))

        btn_retrans = ttk.Button(left_frame, text="🔄 다시 번역", command=lambda c=code: self.retranslate_single(c), width=10)
        btn_retrans.pack(side="top", pady=2)

        content_frame = ttk.Frame(card)
        content_frame.pack(side="left", fill="both", expand=True, padx=5)

        title_frame = ttk.Frame(content_frame)
        title_frame.pack(fill="x", pady=2)
        
        entry_title = ttk.Entry(title_frame)
        entry_title.pack(side="left", fill="x", expand=True, padx=(0, 5))
        add_clipboard_support(entry_title)
        
        btn_copy_title = ttk.Button(title_frame, text="📋 제목 복사", command=lambda c=code: self.copy_title(c), width=10)
        btn_copy_title.pack(side="right")

        desc_frame = ttk.Frame(content_frame)
        desc_frame.pack(fill="x", pady=2)
        
        text_desc = tk.Text(desc_frame, height=3)
        text_desc.pack(side="left", fill="x", expand=True, padx=(0, 5))
        add_clipboard_support(text_desc)
        
        btn_copy_desc = ttk.Button(desc_frame, text="📋 설명 복사", command=lambda c=code: self.copy_desc(c), width=10)
        btn_copy_desc.pack(side="right")

        thumb_frame = ttk.Frame(content_frame)
        thumb_frame.pack(fill="x", pady=2)

        lbl_thumb = ttk.Label(thumb_frame, text="🖼️ 썸네일 없음", foreground="gray")
        lbl_thumb.pack(side="left", fill="x", expand=True)

        btn_thumb = ttk.Button(thumb_frame, text="🖼️ 썸네일 선택", command=lambda c=code: self.choose_card_thumb(c), width=12)
        btn_thumb.pack(side="right")

        right_frame = ttk.Frame(card)
        right_frame.pack(side="right", fill="y", padx=5)

        btn_remove = ttk.Button(right_frame, text="❌ 삭제", command=lambda c=code: self.remove_language_card(c), width=8)
        btn_remove.pack(side="top", pady=25)

        self.lang_widgets[code] = {
            'card': card,
            'title': entry_title,
            'desc': text_desc,
            'thumb': lbl_thumb
        }

        # 썸네일 폴더를 이미 골라 두었다면 새로 추가한 언어에도 자동으로 연결
        path = self.folder_thumbs.get(self.thumbs.code_for(code))
        if path:
            self.set_card_thumb(code, str(path))

    def add_new_language_from_combo(self):
        selection = self.combo_langs.get()
        if "선택하세요" in selection or not selection:
            return

        match = re.search(r'\((.*?)\)', selection)
        if match:
            code = match.group(1)
            lang_name = ALL_SUPPORTED_LANGS.get(code, "알 수 없음")

            if code in self.active_langs:
                self.lbl_status.config(text=f"ℹ️ {lang_name}은(는) 이미 목록에 있습니다.", foreground="red")
                return

            self.add_language_card(code, lang_name)
            self.root.after(100, lambda: self.canvas.yview_moveto(1))
            self.combo_langs.set("추가할 언어를 선택하세요")
            self.lbl_status.config(text=f"✅ {lang_name}이(가) 하단에 추가되었습니다.", foreground="blue")

    def remove_language_card(self, code):
        if code in self.active_langs:
            lang_name = self.active_langs[code]
            if messagebox.askyesno("삭제 확인", f"목록에서 '{lang_name}'을(를) 제거하시겠습니까?"):
                self.lang_widgets[code]['card'].destroy()
                self.thumb_paths.pop(code, None)
                del self.active_langs[code]
                del self.lang_widgets[code]
                self.lbl_status.config(text=f"🗑️ {lang_name}이(가) 삭제되었습니다.", foreground="red")

    def start_translation(self):
        src_title = self.entry_title_src.get().strip()
        src_desc = self.text_desc_src.get("1.0", tk.END).strip()

        if not src_title and not src_desc:
            messagebox.showwarning("경고", "번역할 제목이나 설명을 입력해주세요.")
            return

        self.btn_translate.config(state="disabled")
        total_langs = len(self.active_langs)
        self.lbl_status.config(text=f"전체 번역 중... (총 {total_langs}개 언어)", foreground="blue")

        threading.Thread(target=self.process_translation, args=(src_title, src_desc), daemon=True).start()

    def _translate_with_retry(self, code, text, max_retries=3):
        if not text:
            return ""
        # 구글 클라우드 공식 번역 API(v2). target 언어 코드는 이 API가 쓰는 표기와
        # 거의 같지만, zh-CN/zh-TW만 zh-CN/zh-TW로 그대로 써도 인식된다.
        target = code
        for attempt in range(max_retries):
            try:
                resp = requests.post(
                    "https://translation.googleapis.com/language/translate/v2",
                    params={"key": GOOGLE_TRANSLATE_API_KEY},
                    data={"q": text, "target": target, "format": "text"},
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
                translated = data["data"]["translations"][0]["translatedText"]
                return html.unescape(translated)
            except Exception as e:
                if attempt == max_retries - 1:
                    raise e
                time.sleep(2 * (attempt + 1))
        return ""

    def process_translation(self, title, desc):
        total = len(self.active_langs)
        count = 0

        for code, name in list(self.active_langs.items()):
            try:
                res_title = self._translate_with_retry(code, title)
                time.sleep(0.2)

                res_desc = self._translate_with_retry(code, desc)

                self.root.after(0, self.update_widget, code, res_title, res_desc)
                count += 1
                self.root.after(0, self.lbl_status.config, {'text': f"번역 진행 중... ({count}/{total})"})

                time.sleep(0.2)

            except Exception as e:
                print(f"[{code}] 번역 오류: {e}")
                self.root.after(0, self.update_widget, code, "번역 실패", f"오류: {e}")
                count += 1
                self.root.after(0, self.lbl_status.config, {'text': f"번역 진행 중... ({count}/{total})"})

                time.sleep(1.0)

        self.root.after(0, self.finish_translation)

    def retranslate_single(self, code):
        src_title = self.entry_title_src.get().strip()
        src_desc = self.text_desc_src.get("1.0", tk.END).strip()

        if not src_title and not src_desc:
            messagebox.showwarning("경고", "원본 입력칸에 번역할 내용을 먼저 입력해주세요.")
            return

        self.lang_widgets[code]['title'].delete(0, tk.END)
        self.lang_widgets[code]['title'].insert(0, "번역 중...")
        self.lbl_status.config(text=f"🔄 {self.active_langs[code]} 다시 번역 중...", foreground="blue")

        threading.Thread(target=self.process_single_translation, args=(code, src_title, src_desc), daemon=True).start()

    def process_single_translation(self, code, title, desc):
        try:
            res_title = self._translate_with_retry(code, title)
            time.sleep(0.2)
            res_desc = self._translate_with_retry(code, desc)

            self.root.after(0, self.update_widget, code, res_title, res_desc)
            self.root.after(0, self.lbl_status.config, {'text': f"✅ {self.active_langs[code]} 개별 번역 완료!", 'foreground': 'blue'})
        except Exception as e:
            self.root.after(0, self.update_widget, code, "번역 실패", f"오류: {e}")
            self.root.after(0, self.lbl_status.config, {'text': f"❌ {self.active_langs[code]} 번역 실패", 'foreground': 'red'})

    def save_all_to_csv(self):
        if not self.active_langs:
            messagebox.showwarning("경고", "저장할 언어 데이터가 없습니다.")
            return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV 엑셀 파일", "*.csv"), ("모든 파일", "*.*")],
            title="번역 결과 저장 위치 선택",
            initialdir=r"C:\Users\lg\Desktop\yt_automation",
            initialfile="youtube_multilingual_data.csv"
        )
        
        if not file_path:
            return

        try:
            with open(file_path, mode='w', encoding='utf-8-sig', newline='') as file:
                writer = csv.writer(file)
                writer.writerow(["언어", "언어코드", "영상 제목", "영상 설명"])
                
                for code, lang_name in self.active_langs.items():
                    title = self.lang_widgets[code]['title'].get().strip()
                    desc = self.lang_widgets[code]['desc'].get("1.0", tk.END).strip()
                    writer.writerow([lang_name, code, title, desc])
                    
            messagebox.showinfo("저장 완료", f"성공적으로 엑셀(CSV) 파일로 저장되었습니다!\n\n저장 위치: {file_path}")
            
        except Exception as e:
            messagebox.showerror("저장 오류", f"파일을 저장하는 중에 문제가 발생했습니다:\n{e}")

    def update_widget(self, code, trans_title, trans_desc):
        if code in self.lang_widgets:
            self.lang_widgets[code]['title'].delete(0, tk.END)
            self.lang_widgets[code]['title'].insert(0, trans_title)
            
            self.lang_widgets[code]['desc'].delete("1.0", tk.END)
            self.lang_widgets[code]['desc'].insert("1.0", trans_desc)

    def finish_translation(self):
        self.btn_translate.config(state="normal")
        self.lbl_status.config(text="✅ 목록의 언어 전체 번역이 완료되었습니다!", foreground="green")

    def copy_title(self, code):
        title = self.lang_widgets[code]['title'].get().strip()
        pyperclip.copy(title)
        lang_name = self.active_langs[code]
        self.lbl_status.config(text=f"📋 [{lang_name}] 제목이 복사되었습니다.", foreground="blue")

    def copy_desc(self, code):
        desc = self.lang_widgets[code]['desc'].get("1.0", tk.END).strip()
        pyperclip.copy(desc)
        lang_name = self.active_langs[code]
        self.lbl_status.config(text=f"📋 [{lang_name}] 설명이 복사되었습니다.", foreground="blue")

if __name__ == "__main__":
    root = tk.Tk()
    app = YouTubeTranslatorApp(root)
    root.mainloop()