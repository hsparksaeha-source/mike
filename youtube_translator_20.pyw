"""유튜브 제목·설명 번역기 (20개국 + 추가, 요금 절약판).

기존 '유튜브 다국어 자동 번역기' 와 같은 화면·같은 CSV(언어, 언어코드, 영상 제목, 영상 설명).
다른 점:
- 처음 목록은 인터넷·유튜브 이용자가 많은 20개국. 필요하면 [목록에 추가하기] 로 더한다.
- 번역 전에 몇 글자를 번역하는지, 대략 얼마인지 보여 주고 묻는다 (구글 번역은 글자 수만큼 요금).
- 한 번 번역한 글은 기억해 두고(translate_cache.json), 같은 글이면 다시 번역하지 않는다 (요금 0).
- [Claude 요청문 복사] → Claude 대화창에 붙여 넣기 → 받은 답을 [Claude 답 붙여넣기]:
  구글 요금 없이 Claude 로 번역한다. [80개국으로] 를 체크하면 80개 언어 (괜찮은 영상만 많은 나라로 할 때).
  답이 너무 길면 잘리므로 20개 언어씩 나눠서 부탁한다 (80개국이면 4번).

실행: 유튜브번역기_20개국.bat
"""

import csv
import hashlib
import html
import io
import json
import re
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import requests

HERE = Path(__file__).resolve().parent
KEY_NAME = "google_translate_api_key.txt"
KEY_PLACES = [
    HERE / KEY_NAME,
    Path.home() / "Desktop" / "mike-claude-capcut-auto-editor-agent-i40khi" / KEY_NAME,
]
CACHE_FILE = HERE / "translate_cache.json"
WON_PER_MILLION_CHARS = 28_000   # 구글 번역 100만 자에 약 20달러 (환율 1,400원으로 어림)
CLAUDE_BATCH = 20                # Claude 에 한 번에 부탁할 언어 수 (답이 너무 길면 잘리므로)

# 구글 번역이 지원하는 언어 (한국어 원문은 번역 대상에서 뺀다)
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
    'ja': '일본어', 'jw': '자바어', 'kn': '칸나다어', 'kk': '카자흐어', 'km': '크메르어',
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

# 처음 목록: 인터넷·유튜브 이용자가 많은 20개 언어
DEFAULT_LANGS = {
    'en': '영어', 'ja': '일본어', 'zh-TW': '중국어(번체)', 'zh-CN': '중국어(간체)', 'es': '스페인어',
    'pt': '포르투갈어', 'hi': '힌디어', 'id': '인도네시아어', 'vi': '베트남어', 'th': '태국어',
    'fr': '프랑스어', 'de': '독일어', 'ru': '러시아어', 'ar': '아랍어', 'tr': '튀르키예어',
    'it': '이탈리아어', 'pl': '폴란드어', 'nl': '네덜란드어', 'tl': '필리핀어', 'ms': '말레이어',
}


# 요금 없이(Claude 로) 번역할 때 쓰는 80개 언어: 예전 번역기의 기본 50개 + 30개
FREE_80 = ['en', 'ja', 'zh-CN', 'zh-TW', 'es', 'fr', 'de', 'ru', 'pt', 'it', 'vi', 'th', 'id', 'ar', 'hi', 'bn', 'ms', 'tr', 'fa', 'ur', 'pl', 'uk', 'nl', 'el', 'sv', 'ro', 'hu', 'cs', 'da', 'fi', 'sk', 'no', 'bg', 'hr', 'lt', 'sl', 'lv', 'et', 'sr', 'ca', 'he', 'af', 'sw', 'tl', 'ta', 'te', 'ml', 'mr', 'gu', 'kn', 'az', 'be', 'bs', 'eu', 'gl', 'hy', 'is', 'ka', 'kk', 'km', 'ky', 'lo', 'mk', 'mn', 'my', 'ne', 'pa', 'si', 'sq', 'uz', 'am', 'ha', 'ig', 'yo', 'zu', 'so', 'ps', 'ku', 'mt', 'ga']


# ---------------------------------------------------------------- 화면과 상관없는 부분 (시험하기 쉽게)

def load_api_key():
    for place in KEY_PLACES:
        if place.is_file():
            key = place.read_text(encoding="utf-8").strip()
            if key:
                return key
    return None


def load_cache(path=CACHE_FILE):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_cache(cache, path=CACHE_FILE):
    try:
        Path(path).write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def cache_key(code, text):
    return hashlib.md5(f"{code}\n{text}".encode("utf-8")).hexdigest()


def chars_to_translate(codes, texts, cache):
    """기억해 둔 번역을 빼고 실제로 구글에 보낼 글자 수."""
    return sum(len(t) for c in codes for t in texts if t and cache_key(c, t) not in cache)


def won(chars):
    return round(chars * WON_PER_MILLION_CHARS / 1_000_000)


def claude_prompt(title, desc, langs):
    """Claude 대화창에 붙여 넣을 요청문. langs: [(코드, 이름), ...]"""
    lines = "\n".join(f"{name},{code}" for code, name in langs)
    return f"""아래 유튜브 영상 제목과 설명을 다음 {len(langs)}개 언어로 번역해 주세요.

아래 {len(langs)}개 언어를 하나도 빠짐없이 모두 번역해서, CSV 하나만 코드 블록(```csv) 하나에 담아 주세요.
중간에 멈추거나 "계속할까요?" 라고 묻지 말고 끝까지 한 번에 써 주세요. 다른 말은 쓰지 마세요.
- 첫 줄은 정확히: 언어,언어코드,영상 제목,영상 설명
- 언어마다 한 줄. 언어와 언어코드는 아래 목록 그대로.
- 제목과 설명은 큰따옴표로 감싸고, 설명 안의 줄바꿈은 그대로 둡니다. 글 안의 큰따옴표는 두 개("")로 씁니다.
- 해시태그(#…)와 이모지는 바꾸지 말고 그대로 둡니다.
- 유튜브 제목은 100자, 설명은 5000자를 넘지 않게 합니다.

[번역할 언어 (언어,언어코드)]
{lines}

[제목]
{title}

[설명]
{desc}
"""


CODE_ALIASES = {"iw": "he", "jv": "jw", "fil": "tl", "nb": "no", "zh": "zh-CN", "zh-hans": "zh-CN",
                "zh-cn": "zh-CN", "zh-hant": "zh-TW", "zh-tw": "zh-TW", "pt-br": "pt", "pt-pt": "pt"}


def normalize_code(code, name="", asked=()):
    """Claude 가 언어코드를 조금 다르게 쓴 경우(zh-Hans, fil, jv …)에도 목록의 코드로 맞춘다."""
    c = code.strip()
    if c in ALL_SUPPORTED_LANGS:
        return c
    low = c.lower()
    if low in CODE_ALIASES:
        return CODE_ALIASES[low]
    for ac, an in asked:   # 언어 이름(한국어)으로 찾기
        if name.strip() == an:
            return ac
    return None


def parse_claude_csv(text, known=None, asked=()):
    """Claude 답 → {코드: (이름, 제목, 설명)}.
    Claude 가 표를 코드 블록 여러 개로 나누거나, 설명을 큰따옴표로 감싸지 않거나(쉼표·줄바꿈이 섞임)
    해도 읽도록, '언어,언어코드,' 로 시작하는 줄마다 한 언어로 나눠서 읽는다."""
    blocks = re.findall(r"```(?:csv)?[^\n]*\n(.*?)```", text, re.S)
    body = "\n".join(blocks) if blocks else text
    start = re.compile(r"^\s*\"?([^,\n\"]{1,30})\"?,\s*\"?([A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,4})?)\"?\s*,")
    records, cur = [], None
    for line in body.splitlines():
        m = start.match(line)
        if m and normalize_code(m.group(2), m.group(1), asked):
            cur = [line]
            records.append(cur)
        elif cur is not None:
            cur.append(line)
    out = {}
    for rec in records:
        joined = "\n".join(rec).strip()
        try:
            parsed = list(csv.reader(io.StringIO(joined)))
        except csv.Error:
            parsed = []
        # 한 줄(따옴표 안 줄바꿈 포함)로 읽혀야 정상. 아니면 따옴표 없이 줄바꿈이 섞인 것 → 앞의 쉼표 세 개로만 나눈다
        row = parsed[0] if len(parsed) == 1 else []
        if len(row) < 4:
            row = [c.strip().strip('"') for c in joined.split(",", 3)]
        if len(row) < 4:
            continue
        name, code, title = (c.strip() for c in row[:3])
        code = normalize_code(code, name, asked)
        if not code:
            continue
        desc = ",".join(row[3:]).strip()   # 설명 안의 쉼표 때문에 칸이 더 생겼으면 다시 붙인다
        out[code] = (name, title.strip('"'), desc.strip('"'))
    return out


def write_csv(path, rows):
    """rows: [(이름, 코드, 제목, 설명)] → 스튜디오 자동 입력이 읽는 CSV"""
    with open(path, mode="w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["언어", "언어코드", "영상 제목", "영상 설명"])
        writer.writerows(rows)


# ---------------------------------------------------------------- 화면

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
    def __init__(self, root):
        self.root = root
        self.root.title("유튜브 번역기 (20개국 + 추가 · 요금 절약판)")
        self.root.geometry("950x980")
        self.key = load_api_key()
        self.cache = load_cache()
        self.active_langs, self.lang_widgets = {}, {}
        self.claude_parts, self.claude_next, self.claude_missing, self.claude_asked = None, 0, [], []
        self.create_top()
        self.create_lang_control()
        self.create_list()
        self.create_footer()
        for code, name in DEFAULT_LANGS.items():
            self.add_card(code, name)

    # -- 위: 원본 입력
    def create_top(self):
        f = ttk.LabelFrame(self.root, text="[ 원본 입력 ]", padding=(15, 10))
        f.pack(side="top", fill="x", padx=15, pady=5)
        ttk.Label(f, text="영상 제목:").grid(row=0, column=0, sticky="w", pady=5)
        self.title_src = ttk.Entry(f, width=85)
        self.title_src.grid(row=0, column=1, sticky="w", padx=10, pady=5)
        add_clipboard_support(self.title_src)
        ttk.Label(f, text="영상 설명:").grid(row=1, column=0, sticky="nw", pady=5)
        self.desc_src = tk.Text(f, width=85, height=5)
        self.desc_src.grid(row=1, column=1, sticky="w", padx=10, pady=5)
        add_clipboard_support(self.desc_src)

        bar = ttk.Frame(f)
        bar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=5)
        self.status = ttk.Label(bar, text="대기 중...", foreground="blue", font=("", 10, "bold"))
        self.status.pack(side="left")
        self.btn_translate = ttk.Button(bar, text="구글로 목록 전체 번역 (요금)", command=self.start_translation)
        self.btn_translate.pack(side="right", padx=5)

        free = ttk.LabelFrame(f, text="[ 요금 없이: Claude 로 번역 ]", padding=(10, 6))
        free.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(5, 0))
        self.claude_all = tk.BooleanVar(value=False)
        ttk.Checkbutton(free, text="80개국으로 (괜찮은 영상용, 체크 안 하면 지금 목록)",
                        variable=self.claude_all, command=self.reset_claude).pack(side="left")
        ttk.Button(free, text="📥 Claude 답 붙여넣기", command=self.paste_claude).pack(side="right", padx=5)
        self.btn_claude = ttk.Button(free, text="🤖 Claude 요청문 복사", command=self.copy_claude)
        self.btn_claude.pack(side="right", padx=5)

    def create_lang_control(self):
        f = ttk.Frame(self.root)
        f.pack(fill="x", padx=15, pady=5)
        ttk.Label(f, text="➕ 언어 추가:", font=("", 10, "bold")).pack(side="left")
        values = sorted(f"{name} ({code})" for code, name in ALL_SUPPORTED_LANGS.items())
        self.combo = ttk.Combobox(f, values=values, width=30, state="readonly")
        self.combo.pack(side="left", padx=10)
        self.combo.set("추가할 언어를 선택하세요")
        ttk.Button(f, text="목록에 추가하기", command=self.add_from_combo).pack(side="left")

    def create_list(self):
        outer = ttk.LabelFrame(self.root, text="[ 번역 결과 및 언어 관리 ]", padding=(10, 10))
        outer.pack(side="top", fill="both", expand=True, padx=15, pady=5)
        self.canvas = tk.Canvas(outer)
        bar = ttk.Scrollbar(outer, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

    def create_footer(self):
        f = ttk.Frame(self.root, padding=(10, 10))
        f.pack(side="bottom", fill="x")
        ttk.Button(f, text="💾 엑셀(CSV) 형식으로 현재 목록 전체 저장", command=self.save_csv).pack(pady=5, ipadx=20, ipady=5)

    # -- 언어 카드
    def add_card(self, code, name):
        if code in self.active_langs:
            return
        self.active_langs[code] = name
        card = ttk.Frame(self.inner, borderwidth=1, relief="groove")
        card.pack(fill="x", padx=5, pady=5, ipadx=10, ipady=10)
        left = ttk.Frame(card)
        left.pack(side="left", fill="y", padx=5)
        ttk.Label(left, text=f"{name}\n({code})", width=12, font=("", 10, "bold"), anchor="center",
                  justify="center").pack(side="top", pady=5)
        ttk.Button(left, text="🔄 다시 번역", width=10, command=lambda c=code: self.retranslate(c)).pack(side="top", pady=2)
        content = ttk.Frame(card)
        content.pack(side="left", fill="both", expand=True, padx=5)
        tf = ttk.Frame(content)
        tf.pack(fill="x", pady=2)
        title = ttk.Entry(tf)
        title.pack(side="left", fill="x", expand=True, padx=(0, 5))
        add_clipboard_support(title)
        ttk.Button(tf, text="📋 제목 복사", width=10, command=lambda w=title: self.copy(w.get().strip())).pack(side="right")
        df = ttk.Frame(content)
        df.pack(fill="x", pady=2)
        desc = tk.Text(df, height=3)
        desc.pack(side="left", fill="x", expand=True, padx=(0, 5))
        add_clipboard_support(desc)
        ttk.Button(df, text="📋 설명 복사", width=10,
                   command=lambda w=desc: self.copy(w.get("1.0", tk.END).strip())).pack(side="right")
        right = ttk.Frame(card)
        right.pack(side="right", fill="y", padx=5)
        ttk.Button(right, text="❌ 삭제", width=8, command=lambda c=code: self.remove_card(c)).pack(side="top", pady=25)
        self.lang_widgets[code] = {"card": card, "title": title, "desc": desc}

    def add_from_combo(self):
        m = re.search(r"\((.*?)\)$", self.combo.get())
        if not m:
            return
        code = m.group(1)
        name = ALL_SUPPORTED_LANGS.get(code, code)
        if code in self.active_langs:
            self.status.config(text=f"ℹ️ {name}은(는) 이미 목록에 있습니다.", foreground="red")
            return
        self.add_card(code, name)
        self.root.after(100, lambda: self.canvas.yview_moveto(1))
        self.combo.set("추가할 언어를 선택하세요")
        self.status.config(text=f"✅ {name}을(를) 목록 아래에 추가했습니다.", foreground="blue")

    def remove_card(self, code):
        name = self.active_langs.get(code)
        if name and messagebox.askyesno("삭제 확인", f"목록에서 '{name}'을(를) 뺄까요?"):
            self.lang_widgets.pop(code)["card"].destroy()
            del self.active_langs[code]
            self.status.config(text=f"🗑️ {name}을(를) 뺐습니다.", foreground="red")

    def set_card(self, code, title, desc):
        w = self.lang_widgets.get(code)
        if w:
            w["title"].delete(0, tk.END)
            w["title"].insert(0, title)
            w["desc"].delete("1.0", tk.END)
            w["desc"].insert("1.0", desc)

    # -- 구글 번역 (요금)
    def source(self):
        return self.title_src.get().strip(), self.desc_src.get("1.0", tk.END).strip()

    def confirm_cost(self, codes, texts):
        chars = chars_to_translate(codes, texts, self.cache)
        if chars == 0:
            return True   # 전부 기억해 둔 번역 → 요금 없음
        return messagebox.askyesno(
            "요금 확인",
            f"구글 번역으로 {len(codes)}개 언어, 약 {chars:,}자를 번역합니다.\n"
            f"요금은 약 {won(chars):,}원입니다 (한 달 무료 50만 자를 넘은 뒤 기준).\n\n"
            "한 번 번역한 글은 기억해 두어서, 같은 글은 다시 요금이 들지 않습니다.\n진행할까요?")

    def translate(self, code, text):
        if not text:
            return ""
        k = cache_key(code, text)
        if k in self.cache:
            return self.cache[k]
        if not self.key:
            raise RuntimeError(f"구글 번역 API 키 파일({KEY_NAME})을 찾지 못했습니다. 이 프로그램 폴더에 복사해 주세요.")
        last = None
        for attempt in range(3):
            try:
                r = requests.post("https://translation.googleapis.com/language/translate/v2",
                                  params={"key": self.key}, data={"q": text, "target": code, "format": "text"},
                                  timeout=15)
                r.raise_for_status()
                result = html.unescape(r.json()["data"]["translations"][0]["translatedText"])
                self.cache[k] = result
                return result
            except Exception as e:
                last = e
                time.sleep(2 * (attempt + 1))
        raise last

    def start_translation(self):
        title, desc = self.source()
        if not title and not desc:
            messagebox.showwarning("경고", "번역할 제목이나 설명을 넣어 주세요.")
            return
        codes = list(self.active_langs)
        if not self.confirm_cost(codes, [title, desc]):
            return
        self.btn_translate.config(state="disabled")
        threading.Thread(target=self.work, args=(codes, title, desc), daemon=True).start()

    def work(self, codes, title, desc):
        for i, code in enumerate(codes, 1):
            try:
                t, d = self.translate(code, title), self.translate(code, desc)
            except Exception as e:
                t, d = "번역 실패", f"오류: {e}"
            self.root.after(0, self.set_card, code, t, d)
            self.root.after(0, lambda i=i: self.status.config(text=f"번역 중... ({i}/{len(codes)})", foreground="blue"))
        save_cache(self.cache)
        self.root.after(0, lambda: (self.btn_translate.config(state="normal"),
                                    self.status.config(text="✅ 번역이 끝났습니다.", foreground="green")))

    def retranslate(self, code):
        title, desc = self.source()
        if not title and not desc:
            messagebox.showwarning("경고", "원본 입력칸에 번역할 내용을 먼저 넣어 주세요.")
            return
        # [다시 번역] 은 기억해 둔 번역을 버리고 새로 받는다
        for t in (title, desc):
            self.cache.pop(cache_key(code, t), None)
        if not self.confirm_cost([code], [title, desc]):
            return
        threading.Thread(target=self.work, args=([code], title, desc), daemon=True).start()

    # -- Claude 로 번역 (요금 없음)
    def claude_langs(self):
        if self.claude_all.get():
            return [(c, ALL_SUPPORTED_LANGS[c]) for c in FREE_80]
        return list(self.active_langs.items())

    def reset_claude(self):
        """[80개국으로] 를 바꾸면 처음 묶음부터 다시."""
        self.claude_parts = None   # [[(코드, 이름) …], …] 처음 복사할 때 정해서 끝까지 그대로 쓴다
        self.claude_next = 0       # 다음에 복사할 묶음 번호 (0부터)
        self.claude_missing = []
        self.claude_asked = []
        self.btn_claude.config(text="🤖 Claude 요청문 복사")

    def _claude_label(self):
        total = len(self.claude_parts or [1])
        if self.claude_missing:
            return f"🤖 빠진 {len(self.claude_missing)}개 다시 부탁"
        if self.claude_next >= total:
            return f"🤖 Claude 요청문 복사 (끝 {total}/{total})"
        return f"🤖 Claude 요청문 복사 ({self.claude_next + 1}/{total})"

    def copy_claude(self):
        title, desc = self.source()
        if not title and not desc:
            messagebox.showwarning("경고", "번역할 제목이나 설명을 먼저 넣어 주세요.")
            return
        if not getattr(self, "claude_parts", None):
            langs = self.claude_langs()
            self.claude_parts = [langs[i:i + CLAUDE_BATCH] for i in range(0, len(langs), CLAUDE_BATCH)]
            self.claude_next, self.claude_missing = 0, []
        total = len(self.claude_parts)
        if self.claude_missing:   # 지난번 답에서 빠진 언어만 한 번 다시 부탁한다
            self.claude_asked, self.claude_missing = self.claude_missing, []
            self.copy(claude_prompt(title, desc, self.claude_asked))
            self.status.config(text=f"📋 빠진 {len(self.claude_asked)}개 언어 요청문 복사 → Claude 에 붙여 넣고 "
                                    "답을 [Claude 답 붙여넣기]", foreground="blue")
        else:
            if self.claude_next >= total:
                if not messagebox.askyesno("알림", f"{total}개 묶음을 모두 부탁했습니다. 처음 묶음부터 다시 할까요?"):
                    return
                self.claude_next = 0
            k = self.claude_next
            self.claude_asked = self.claude_parts[k]
            self.copy(claude_prompt(title, desc, self.claude_asked))
            self.claude_next = k + 1
            self.status.config(text=f"📋 묶음 {k + 1}/{total} ({len(self.claude_asked)}개 언어) 요청문 복사 → "
                                    "Claude 에 붙여 넣고 답을 [Claude 답 붙여넣기]", foreground="blue")
        self.btn_claude.config(text=self._claude_label())

    def paste_claude(self):
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            text = ""
        asked = getattr(self, "claude_asked", [])
        rows = parse_claude_csv(text, asked=asked)
        if not rows:
            messagebox.showwarning("알림", "복사한 글에서 번역 표를 찾지 못했습니다.\n"
                                           "Claude 답 전체를 드래그해서 복사하거나, 표 오른쪽 위 [복사] 를 누른 뒤 다시 해 주세요.")
            return
        for code, (name, title, desc) in rows.items():
            if code not in self.active_langs:
                self.add_card(code, ALL_SUPPORTED_LANGS.get(code, name))
            self.set_card(code, title, desc)
        self.claude_missing = [(c, n) for c, n in asked if c not in rows]
        total = len(getattr(self, "claude_parts", None) or [1])
        done = min(getattr(self, "claude_next", 1), total)
        if self.claude_missing:
            names = ", ".join(n for _, n in self.claude_missing)
            self.status.config(text=f"⚠️ 묶음 {done}/{total}: {len(rows)}개 넣음, {len(self.claude_missing)}개 빠짐 ({names}). "
                                    "단추를 누르면 빠진 언어만 다시 부탁합니다.", foreground="red")
        elif done < total:
            self.status.config(text=f"✅ 묶음 {done}/{total}: {len(rows)}개 언어를 넣었습니다. "
                                    f"다음은 묶음 {done + 1}/{total} — [Claude 요청문 복사]", foreground="green")
        else:
            self.status.config(text=f"✅ 마지막 묶음까지 넣었습니다 ({len(rows)}개). 이제 [💾 CSV 저장] 을 누르세요.",
                               foreground="green")
        self.btn_claude.config(text=self._claude_label())

    # -- 저장·복사
    def save_csv(self):
        if not self.active_langs:
            messagebox.showwarning("경고", "저장할 언어가 없습니다.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV 엑셀 파일", "*.csv")],
                                            title="번역 결과 저장", initialdir=r"C:\Users\lg\Desktop\yt_automation",
                                            initialfile="youtube_multilingual_data.csv")
        if not path:
            return
        rows = [(name, code, self.lang_widgets[code]["title"].get().strip(),
                 self.lang_widgets[code]["desc"].get("1.0", tk.END).strip())
                for code, name in self.active_langs.items()]
        try:
            write_csv(path, rows)
            messagebox.showinfo("저장 완료", f"CSV 로 저장했습니다.\n\n{path}")
        except Exception as e:
            messagebox.showerror("저장 오류", f"저장하지 못했습니다:\n{e}")

    def copy(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        if not text.startswith("아래 유튜브"):
            self.status.config(text="📋 복사했습니다.", foreground="blue")


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
