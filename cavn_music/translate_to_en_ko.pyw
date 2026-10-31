"""다국어 → 영어·한국어 번역기.

어느 나라 말이든 제목·설명을 넣으면 언어를 알아서 찾아 영어와 한국어로 번역한다.
(기존 '유튜브 다국어 자동 번역기' 는 한 언어 → 50개 언어. 이것은 거꾸로 여러 언어 → 영어·한국어)

- 구글 번역 API 키: 기존 번역기와 같은 google_translate_api_key.txt 를 쓴다.
  이 파일 옆 → 위 폴더 → 바탕화면의 기존 번역기 폴더 순서로 찾는다.
- 실행: 다국어번역기.bat 더블클릭
"""

import html
import json
import threading
import tkinter as tk
import urllib.parse
import urllib.request
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

KEY_NAME = "google_translate_api_key.txt"
HERE = Path(__file__).resolve().parent
KEY_PLACES = [
    HERE / KEY_NAME,
    HERE.parent / KEY_NAME,
    Path.home() / "Desktop" / "mike-claude-capcut-auto-editor-agent-i40khi" / KEY_NAME,
]
TARGETS = [("en", "영어"), ("ko", "한국어")]
LANG_NAMES = {
    "en": "영어", "ko": "한국어", "ja": "일본어", "zh-CN": "중국어(간체)", "zh-TW": "중국어(번체)", "zh": "중국어",
    "es": "스페인어", "fr": "프랑스어", "de": "독일어", "ru": "러시아어", "pt": "포르투갈어", "it": "이탈리아어",
    "vi": "베트남어", "th": "태국어", "id": "인도네시아어", "ar": "아랍어", "hi": "힌디어", "tr": "튀르키예어",
    "pl": "폴란드어", "uk": "우크라이나어", "nl": "네덜란드어", "el": "그리스어", "sv": "스웨덴어",
    "ms": "말레이어", "tl": "필리핀어", "fa": "페르시아어", "he": "히브리어", "iw": "히브리어",
}


def find_key():
    for place in KEY_PLACES:
        if place.is_file():
            key = place.read_text(encoding="utf-8").strip()
            if key:
                return key
    raise FileNotFoundError("구글 번역 API 키 파일을 찾지 못했습니다.\n\n"
                            f"'{KEY_NAME}' 을 이 프로그램 폴더에 복사해 주세요:\n{HERE}\n\n"
                            "(기존 유튜브 번역기 폴더에 있는 같은 파일을 복사하면 됩니다)")


def translate(key, text, target):
    """구글 번역. 원문 언어는 자동으로 찾는다. (번역문, 원문 언어 코드)"""
    if not text.strip():
        return "", ""
    data = urllib.parse.urlencode({"q": text, "target": target, "format": "text", "key": key}).encode()
    last = None
    for _ in range(3):
        try:
            with urllib.request.urlopen("https://translation.googleapis.com/language/translate/v2", data, timeout=30) as r:
                result = json.loads(r.read().decode("utf-8"))["data"]["translations"][0]
            return html.unescape(result["translatedText"]), result.get("detectedSourceLanguage", "")
        except Exception as e:   # 잠깐 끊겨도 두 번 더 해 본다
            last = e
    raise RuntimeError(f"번역 실패: {last}")


def add_clipboard_support(widget):
    menu = tk.Menu(widget, tearoff=0)
    menu.add_command(label="잘라내기 (Ctrl+X)", command=lambda: widget.event_generate("<<Cut>>"))
    menu.add_command(label="복사 (Ctrl+C)", command=lambda: widget.event_generate("<<Copy>>"))
    menu.add_command(label="붙여넣기 (Ctrl+V)", command=lambda: widget.event_generate("<<Paste>>"))
    widget.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))

    def force_paste(event):
        widget.event_generate("<<Paste>>")
        return "break"
    widget.bind("<Control-v>", force_paste)
    widget.bind("<Control-V>", force_paste)


class App:
    def __init__(self, root, key):
        self.root, self.key = root, key
        root.title("다국어 → 영어·한국어 번역기")
        root.geometry("1100x820")

        top = ttk.LabelFrame(root, text="[ 원문 입력 — 어느 나라 말이든 ]", padding=(15, 10))
        top.pack(fill="x", padx=15, pady=5)
        ttk.Label(top, text="제목:").grid(row=0, column=0, sticky="w", pady=5)
        self.title_src = ttk.Entry(top, width=90)
        self.title_src.grid(row=0, column=1, sticky="w", padx=10, pady=5)
        add_clipboard_support(self.title_src)
        ttk.Label(top, text="설명:").grid(row=1, column=0, sticky="nw", pady=5)
        self.desc_src = tk.Text(top, width=90, height=8, wrap="word")
        self.desc_src.grid(row=1, column=1, sticky="w", padx=10, pady=5)
        add_clipboard_support(self.desc_src)

        bar = ttk.Frame(top)
        bar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=5)
        self.status = ttk.Label(bar, text="원문을 넣고 [번역]을 누르세요.", foreground="blue", font=("", 10, "bold"))
        self.status.pack(side="left")
        ttk.Button(bar, text="지우기", command=self.clear).pack(side="right", padx=5)
        ttk.Button(bar, text="결과 저장 (txt)", command=self.save).pack(side="right", padx=5)
        self.btn = ttk.Button(bar, text="번역", command=self.start)
        self.btn.pack(side="right", padx=5)

        # 아래: 왼쪽 영어 칸, 오른쪽 한국어 칸
        both = ttk.Frame(root)
        both.pack(fill="both", expand=True, padx=15, pady=5)
        both.columnconfigure(0, weight=1, uniform="half")
        both.columnconfigure(1, weight=1, uniform="half")
        both.rowconfigure(0, weight=1)
        self.out = {}
        for col, (code, name) in enumerate(TARGETS):
            box = ttk.LabelFrame(both, text=f"[ {name} ]", padding=(10, 8))
            box.grid(row=0, column=col, sticky="nsew", padx=(0, 5) if col == 0 else (5, 0))
            ttk.Label(box, text="제목:").pack(anchor="w")
            title = ttk.Entry(box)
            title.pack(fill="x", pady=(2, 4))
            ttk.Button(box, text="제목 복사", command=lambda w=title: self.copy(w.get())).pack(anchor="e")
            ttk.Label(box, text="설명:").pack(anchor="w")
            desc = tk.Text(box, height=16, wrap="word")
            desc.pack(fill="both", expand=True, pady=(2, 4))
            ttk.Button(box, text="설명 복사", command=lambda w=desc: self.copy(w.get("1.0", "end-1c"))).pack(anchor="e")
            for w in (title, desc):
                add_clipboard_support(w)
            self.out[code] = (title, desc)

    def start(self):
        title = self.title_src.get().strip()
        desc = self.desc_src.get("1.0", "end-1c").strip()
        if not title and not desc:
            messagebox.showinfo("알림", "번역할 제목이나 설명을 넣어 주세요.")
            return
        self.btn.config(state="disabled")
        self.status.config(text="번역 중...")
        threading.Thread(target=self.work, args=(title, desc), daemon=True).start()

    def work(self, title, desc):
        try:
            results, detected = {}, ""
            for code, _ in TARGETS:
                t, d1 = translate(self.key, title, code)
                d, d2 = translate(self.key, desc, code)
                results[code] = (t, d)
                detected = detected or d1 or d2
            self.root.after(0, self.show, results, detected)
        except Exception as e:
            self.root.after(0, self.fail, str(e))

    def show(self, results, detected):
        for code, (t, d) in results.items():
            title, desc = self.out[code]
            title.delete(0, "end")
            title.insert(0, t)
            desc.delete("1.0", "end")
            desc.insert("1.0", d)
        name = LANG_NAMES.get(detected, detected or "알 수 없음")
        self.status.config(text=f"끝. 원문 언어: {name}")
        self.btn.config(state="normal")

    def fail(self, msg):
        self.status.config(text="번역 실패")
        self.btn.config(state="normal")
        messagebox.showerror("번역 실패", msg)

    def copy(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status.config(text="복사했습니다.")

    def clear(self):
        self.title_src.delete(0, "end")
        self.desc_src.delete("1.0", "end")
        for title, desc in self.out.values():
            title.delete(0, "end")
            desc.delete("1.0", "end")
        self.status.config(text="원문을 넣고 [번역]을 누르세요.")

    def save(self):
        path = filedialog.asksaveasfilename(defaultextension=".txt", initialfile="번역결과.txt",
                                            filetypes=[("텍스트", "*.txt")])
        if not path:
            return
        parts = ["[원문]", self.title_src.get(), self.desc_src.get("1.0", "end-1c"), ""]
        for code, name in TARGETS:
            title, desc = self.out[code]
            parts += [f"[{name}]", title.get(), desc.get("1.0", "end-1c"), ""]
        Path(path).write_text("\n".join(parts), encoding="utf-8")
        self.status.config(text=f"저장했습니다: {path}")


def main():
    root = tk.Tk()
    try:
        key = find_key()
    except Exception as e:
        root.withdraw()
        messagebox.showerror("API 키 없음", str(e))
        return
    App(root, key)
    root.mainloop()


if __name__ == "__main__":
    main()
