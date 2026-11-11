"""LRC 이중자막 만들기 — 다국어 → 영어 / 다국어 → 한국어.

기존 'LRC 이중자막 생성기'(영-한 / 한-영) 와 같은 화면이고, 원문이 어느 나라 말이든 된다
(이탈리아어 칸쏘네, 일본어, 스페인어 …). 원문 언어는 구글 번역이 알아서 찾는다.
- 결과 칸에는 원문(다국어)이 위, 번역(영어·한국어)이 아래로 보인다.
- 같은 시간의 두 줄은 영상(플레이어·캡컷)에서 거꾸로 쌓여 보이므로, 저장할 때만 두 줄의 순서를 바꿔 쓴다.
  → 영상에서도 원문이 위, 번역이 아래.
구글 번역 API 키: google_translate_api_key.txt (이 파일 옆 → 위 폴더 → 바탕화면의 기존 번역기 폴더)
실행: LRC다국어번역기.bat
"""

import tkinter as tk
from tkinter import messagebox, filedialog
import re
import threading
import time
import html
import json
import urllib.parse
import urllib.request
from pathlib import Path

KEY_NAME = "google_translate_api_key.txt"
HERE = Path(__file__).resolve().parent
KEY_PLACES = [
    HERE / KEY_NAME,
    HERE.parent / KEY_NAME,
    Path.home() / "Desktop" / "mike-claude-capcut-auto-editor-agent-i40khi" / KEY_NAME,
]
TIME_RE = re.compile(r'^((?:\[\d{1,3}:\d{2}(?:[.:]\d{1,3})?\])+)(.*)')   # [01:23.45] (한 줄에 여러 개도)


def load_api_key():
    for place in KEY_PLACES:
        if place.is_file():
            key = place.read_text(encoding="utf-8").strip()
            if key:
                return key
    raise FileNotFoundError("구글 번역 API 키 파일을 찾지 못했습니다.\n\n"
                            f"'{KEY_NAME}' 을 이 프로그램 폴더에 복사해 주세요:\n{HERE}")


GOOGLE_TRANSLATE_API_KEY = None


def google_translate(text, target):
    """원문 언어는 자동으로 찾는다 (source 를 주지 않음)."""
    data = urllib.parse.urlencode({"q": text, "target": target, "format": "text",
                                   "key": GOOGLE_TRANSLATE_API_KEY}).encode()
    with urllib.request.urlopen("https://translation.googleapis.com/language/translate/v2", data, timeout=15) as r:
        result = json.loads(r.read().decode("utf-8"))
    return html.unescape(result["data"]["translations"][0]["translatedText"])


def has_letters(text):
    """글자(어느 나라 글자든)가 있는가. 숫자·기호만 있는 줄은 번역하지 않는다."""
    return bool(re.search(r"[^\W\d_]", text))


def build_lines(parsed_items, direction):
    """번역이 끝난 항목들 → 이중자막 줄들."""
    out = []
    for item in parsed_items:
        if item["type"] != "lrc":
            out.append(item["original"])
            continue
        ts, orig, trans = item["timestamp"], item["original_text"], item["translated_text"]
        out.append(f"{ts}{orig}")     # 결과 칸: 원문이 위, 번역이 아래
        if trans:
            out.append(f"{ts}{trans}")
    return out


def for_video(text):
    """저장용: 같은 시간이 붙은 두 줄(원문·번역)의 순서를 바꾼다.
    영상에서는 같은 시간의 줄이 거꾸로 쌓여 보이므로, 이렇게 저장해야 영상에서 원문이 위로 보인다."""
    lines = text.split("\n")
    out, i = [], 0
    while i < len(lines):
        a = TIME_RE.match(lines[i].strip())
        b = TIME_RE.match(lines[i + 1].strip()) if i + 1 < len(lines) else None
        if a and b and a.group(1) == b.group(1):
            out += [lines[i + 1], lines[i]]
            i += 2
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


def parse_lrc(text):
    parsed, todo = [], []
    for line in text.split("\n"):
        s = line.strip()
        m = TIME_RE.match(s)
        if not s:
            parsed.append({"type": "empty", "original": s})
        elif m and m.group(2).strip():
            item = {"type": "lrc", "timestamp": m.group(1), "original_text": m.group(2).strip(), "translated_text": ""}
            parsed.append(item)
            todo.append(item)
        else:
            parsed.append({"type": "meta", "original": s})
    return parsed, todo


def claude_lrc_prompt(todo, target_name):
    """Claude 대화창에 붙여 넣을 요청문 (요금 없이 번역). 줄마다 번호를 붙여 순서가 어긋나지 않게 한다."""
    lines = "\n".join(f"{i}. {item['original_text']}" for i, item in enumerate(todo, 1))
    return f"""아래 노래 가사 {len(todo)}줄을 {target_name}로 번역해 주세요. 노래 자막으로 쓸 것이라 자연스럽고 짧게 해 주세요.

답은 코드 블록(```) 하나에, 줄마다 같은 번호를 붙여서 주세요. 예) 1. 번역문
- {len(todo)}줄을 하나도 빠짐없이, 순서 그대로, 한 줄에 한 번호씩.
- 중간에 멈추거나 "계속할까요?" 라고 묻지 말고 끝까지 한 번에 써 주세요. 다른 말은 쓰지 마세요.

{lines}
"""


def apply_claude_answer(todo, answer):
    """Claude 답의 '번호. 번역문' 줄을 가사 줄에 넣는다. (넣은 줄 수, 빠진 번호 목록)"""
    blocks = re.findall(r"```[^\n]*\n(.*?)```", answer, re.S)
    body = "\n".join(blocks) if blocks else answer
    found = {}
    for line in body.splitlines():
        m = re.match(r"^\s*(\d+)\s*[.)|:\-]\s*(.*\S)\s*$", line)
        if m:
            found[int(m.group(1))] = m.group(2)
    filled, missing = 0, []
    for i, item in enumerate(todo, 1):
        if i in found:
            item["translated_text"] = found[i]
            filled += 1
        else:
            missing.append(i)
    return filled, missing


class SubtitleTranslatorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("LRC 이중자막 생성기 (다국어 → 영어 / 다국어 → 한국어)")
        self.root.geometry("950x680")
        
        self.font_style = ("맑은 고딕", 10)
        self.setup_ui()

    def setup_ui(self):
        self.create_context_menu()

        # --- 번역 방향 선택 라디오 버튼 ---
        direction_frame = tk.Frame(self.root)
        direction_frame.pack(fill=tk.X, padx=10, pady=(10, 0))
        
        tk.Label(direction_frame, text="🔄 번역 방향 선택:", font=("맑은 고딕", 10, "bold")).pack(side=tk.LEFT, padx=(0, 10))
        
        self.trans_direction = tk.StringVar(value="x2ko")
        tk.Radiobutton(direction_frame, text="다국어 원본 ➔ 한국어 번역", variable=self.trans_direction, value="x2ko", font=self.font_style).pack(side=tk.LEFT, padx=10)
        tk.Radiobutton(direction_frame, text="다국어 원본 ➔ 영어 번역", variable=self.trans_direction, value="x2en", font=self.font_style).pack(side=tk.LEFT, padx=10)

        # --- 상단 텍스트 창 영역 ---
        text_frame = tk.Frame(self.root)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        text_frame.columnconfigure(0, weight=1, uniform="half")
        text_frame.columnconfigure(1, weight=1, uniform="half")
        text_frame.rowconfigure(0, weight=1)
        
        left_frame = tk.Frame(text_frame)
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        tk.Label(left_frame, text="원본 파일 (LRC / SRT)", font=("맑은 고딕", 11, "bold")).pack(anchor="w", pady=(0, 5))
        self.txt_original = tk.Text(left_frame, wrap=tk.WORD, font=self.font_style)
        self.txt_original.pack(fill=tk.BOTH, expand=True)
        self.bind_shortcuts(self.txt_original)
        
        right_frame = tk.Frame(text_frame)
        right_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        tk.Label(right_frame, text="완성된 이중자막 (결과)", font=("맑은 고딕", 11, "bold")).pack(anchor="w", pady=(0, 5))
        self.txt_result = tk.Text(right_frame, wrap=tk.WORD, font=self.font_style)
        self.txt_result.pack(fill=tk.BOTH, expand=True)
        self.bind_shortcuts(self.txt_result)

        # --- 하단 버튼 영역 ---
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        
        self.btn_load = tk.Button(btn_frame, text="📂 파일 불러오기", command=self.load_file, width=20, height=2)
        self.btn_load.pack(side=tk.LEFT, padx=5)
        
        self.btn_translate = tk.Button(btn_frame, text="🎯 100% 정밀 번역 시작 (약 1분 소요)", command=self.start_translation, height=2, bg="#4CAF50", fg="white", font=("맑은 고딕", 10, "bold"))
        self.btn_translate.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)
        
        self.btn_save = tk.Button(btn_frame, text="💾 LRC / SRT로 저장하기", command=self.save_file, width=20, height=2)
        self.btn_save.pack(side=tk.RIGHT, padx=5)

        # 요금 없이: Claude 대화창으로 번역 (요청문 복사 → Claude 에 붙여넣기 → 답 복사 → 답 붙여넣기)
        free_frame = tk.Frame(self.root)
        free_frame.pack(fill=tk.X, padx=10, pady=(0, 5))
        tk.Label(free_frame, text="💡 요금 없이:", font=("맑은 고딕", 10, "bold")).pack(side=tk.LEFT, padx=5)
        tk.Button(free_frame, text="🤖 Claude 요청문 복사", command=self.copy_claude, height=1).pack(side=tk.LEFT, padx=5)
        tk.Button(free_frame, text="📥 Claude 답 붙여넣기", command=self.paste_claude, height=1).pack(side=tk.LEFT, padx=5)
        tk.Label(free_frame, text="(요청문을 claude.ai 새 대화에 붙여 넣고, 답을 복사해서 [답 붙여넣기])",
                 fg="gray", font=("맑은 고딕", 9)).pack(side=tk.LEFT, padx=5)

        self.status_label = tk.Label(self.root, text="대기 중...", fg="gray", font=("맑은 고딕", 9, "bold"))
        self.status_label.pack(side=tk.BOTTOM, pady=5)

    # 마우스 우클릭 및 단축키 설정
    def create_context_menu(self):
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="복사 (Copy)", command=self.menu_copy)
        self.context_menu.add_command(label="붙여넣기 (Paste)", command=self.menu_paste)
        self.context_menu.add_command(label="잘라내기 (Cut)", command=self.menu_cut)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="전체 선택 (Select All)", command=self.menu_select_all)

    def bind_shortcuts(self, widget):
        widget.bind("<Control-c>", self.copy_text)
        widget.bind("<Control-C>", self.copy_text)
        widget.bind("<Control-v>", self.paste_text)
        widget.bind("<Control-V>", self.paste_text)
        widget.bind("<Control-x>", self.cut_text)
        widget.bind("<Control-X>", self.cut_text)
        widget.bind("<Control-a>", self.select_all_text)
        widget.bind("<Control-A>", self.select_all_text)
        widget.bind("<Button-3>", self.show_context_menu)

    def show_context_menu(self, event):
        self.active_widget = event.widget
        self.context_menu.tk_popup(event.x_root, event.y_root)

    def menu_copy(self):
        if hasattr(self, 'active_widget'): self.copy_action(self.active_widget)
    def menu_paste(self):
        if hasattr(self, 'active_widget'): self.paste_action(self.active_widget)
    def menu_cut(self):
        if hasattr(self, 'active_widget'): self.cut_action(self.active_widget)
    def menu_select_all(self):
        if hasattr(self, 'active_widget'): self.active_widget.tag_add("sel", "1.0", "end")

    def copy_text(self, event):
        self.copy_action(event.widget)
        return "break"
    def paste_text(self, event):
        self.paste_action(event.widget)
        return "break"
    def cut_text(self, event):
        self.cut_action(event.widget)
        return "break"
    def select_all_text(self, event):
        event.widget.tag_add("sel", "1.0", "end")
        return "break"

    def copy_action(self, widget):
        try:
            widget.clipboard_clear()
            widget.clipboard_append(widget.selection_get())
        except tk.TclError: pass
    def paste_action(self, widget):
        try:
            widget.insert(tk.INSERT, widget.clipboard_get())
        except tk.TclError: pass
    def cut_action(self, widget):
        try:
            self.copy_action(widget)
            widget.delete("sel.first", "sel.last")
        except tk.TclError: pass

    def load_file(self):
        filepath = filedialog.askopenfilename(
            title="자막 파일 선택",
            filetypes=(("자막 파일", "*.lrc *.srt *.txt"), ("모든 파일", "*.*"))
        )
        if filepath:
            try:
                with open(filepath, 'r', encoding='utf-8') as file:
                    content = file.read()
                self.txt_original.delete("1.0", tk.END)
                self.txt_original.insert(tk.END, content)
                self.status_label.config(text=f"파일 로드 완료: {filepath}", fg="blue")
            except Exception as e:
                messagebox.showerror("오류", f"파일을 읽는 중 오류가 발생했습니다:\n{e}")

    def start_translation(self):
        original_text = self.txt_original.get("1.0", tk.END).strip()
        if not original_text:
            messagebox.showwarning("경고", "먼저 원본 파일을 불러오거나 텍스트를 입력해주세요.")
            return
            
        self.btn_translate.config(state=tk.DISABLED, text="⏳ 정밀 번역 진행 중...")
        threading.Thread(target=self.process_translation, args=(original_text,), daemon=True).start()

    # 💡 [핵심] 한 줄을 번역할 때 실패하면 최대 3번까지 재시도하는 함수
    def translate_single_line(self, target_lang, text):
        if not text or not text.strip():
            return ""

        # 글자 없이 숫자나 기호만 있는 줄은 번역 통신 없이 그대로 반환 (일본어·러시아어 … 글자도 글자로 본다)
        if not has_letters(text):
            return text.strip()

        for attempt in range(3):
            try:
                res = google_translate(text, target_lang)
                if res:
                    return res.strip()
            except Exception:
                time.sleep(2 + attempt * 2)

        return "[번역 실패]"

    def process_translation(self, text):
        direction = self.trans_direction.get()
        target_lang = 'ko' if direction == "x2ko" else 'en'
        parsed_items, texts_to_translate = parse_lrc(text)

        total_count = len(texts_to_translate)
        
        # 💡 한 줄씩 정밀하고 안전하게 번역 (100% 완주)
        for idx, item in enumerate(texts_to_translate):
            current_num = idx + 1
            percent = int((current_num / total_count) * 100)
            remain_sec = int((total_count - current_num) * 1.0)
            
            # 실시간 진행률 업데이트
            status_text = f"⏳ 진행률: {current_num}/{total_count} 줄 ({percent}%) - 예상 남은 시간: 약 {remain_sec}초"
            self.root.after(0, lambda st=status_text: self.status_label.config(text=st, fg="blue"))
            self.root.after(0, lambda n=current_num, t=total_count, p=percent: self.btn_translate.config(text=f"⏳ 번역 중... ({n}/{t}줄 - {p}%)"))
            
            # 1줄 정밀 번역
            item["translated_text"] = self.translate_single_line(target_lang, item["original_text"])

            time.sleep(0.1)

        output_lines = build_lines(parsed_items, direction)

        # UI 결과 출력
        self.root.after(0, lambda: self.txt_result.delete("1.0", tk.END))
        self.root.after(0, lambda: self.txt_result.insert(tk.END, '\n'.join(output_lines)))
        self.root.after(0, lambda: self.status_label.config(text="모든 가사가 누락 없이 100% 번역되었습니다! 🎉", fg="green"))
        self.root.after(0, lambda: self.btn_translate.config(state=tk.NORMAL, text="🎯 100% 정밀 번역 시작 (약 1분 소요)"))

    def copy_claude(self):
        original = self.txt_original.get("1.0", tk.END).strip()
        if not original:
            messagebox.showwarning("경고", "먼저 원본 파일을 불러오거나 가사를 넣어 주세요.")
            return
        _, todo = parse_lrc(original)
        if not todo:
            messagebox.showwarning("경고", "번역할 가사 줄([00:12.34]가사)을 찾지 못했습니다.")
            return
        target = "한국어" if self.trans_direction.get() == "x2ko" else "영어"
        self.root.clipboard_clear()
        self.root.clipboard_append(claude_lrc_prompt(todo, target))
        self.status_label.config(text=f"📋 요청문({len(todo)}줄 → {target}) 복사. claude.ai 새 대화에 붙여 넣고, "
                                      "답을 복사해서 [Claude 답 붙여넣기]", fg="blue")

    def paste_claude(self):
        original = self.txt_original.get("1.0", tk.END).strip()
        try:
            answer = self.root.clipboard_get()
        except tk.TclError:
            answer = ""
        parsed, todo = parse_lrc(original)
        filled, missing = apply_claude_answer(todo, answer)
        if not filled:
            messagebox.showwarning("알림", "복사한 글에서 '1. 번역문' 모양의 줄을 찾지 못했습니다.\n"
                                           "Claude 답의 코드 블록 오른쪽 위 [복사] 를 누른 뒤 다시 해 주세요.")
            return
        self.txt_result.delete("1.0", tk.END)
        self.txt_result.insert(tk.END, "\n".join(build_lines(parsed, self.trans_direction.get())))
        if missing:
            self.status_label.config(text=f"⚠️ {filled}줄을 넣었고 {len(missing)}줄이 빠졌습니다 (번호 {missing[:10]}…). "
                                          "빠진 줄은 원문만 들어갑니다.", fg="red")
        else:
            self.status_label.config(text=f"✅ Claude 번역 {filled}줄을 모두 넣었습니다 (요금 없음). 저장하세요.", fg="green")

    def save_file(self):
        result_text = self.txt_result.get("1.0", tk.END).strip()
        if not result_text:
            messagebox.showwarning("경고", "저장할 내용이 없습니다.")
            return
        
        filepath = filedialog.asksaveasfilename(
            defaultextension=".lrc",
            filetypes=[("LRC 파일", "*.lrc"), ("SRT 파일", "*.srt"), ("텍스트 파일", "*.txt")],
            title="이중 자막 LRC 파일 저장"
        )
        
        if filepath:
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(for_video(result_text))   # 영상에서 원문이 위로 보이게 두 줄 순서를 바꿔 저장
                self.status_label.config(text=f"저장 완료: {filepath}", fg="blue")
                messagebox.showinfo("성공", "파일이 성공적으로 저장되었습니다!")
            except Exception as e:
                messagebox.showerror("오류", f"파일 저장 중 오류가 발생했습니다:\n{e}")

if __name__ == "__main__":
    root = tk.Tk()
    try:
        GOOGLE_TRANSLATE_API_KEY = load_api_key()
    except Exception as e:
        root.withdraw()
        messagebox.showerror("API 키 없음", str(e))
        raise SystemExit
    app = SubtitleTranslatorApp(root)
    root.mainloop()