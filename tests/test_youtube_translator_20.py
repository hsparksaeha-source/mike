"""요금 절약 유튜브 번역기: 기억해 둔 번역, 예상 요금, Claude 요청문·답 읽기 (화면·구글 없이)."""

import importlib.machinery
import importlib.util
import sys
import types
from pathlib import Path

for _name in ("tkinter", "tkinter.filedialog", "tkinter.messagebox", "tkinter.ttk"):
    sys.modules.setdefault(_name, types.ModuleType(_name))

ROOT = Path(__file__).resolve().parent.parent
_loader = importlib.machinery.SourceFileLoader("yt20", str(ROOT / "youtube_translator_20.pyw"))
yt = importlib.util.module_from_spec(importlib.util.spec_from_loader("yt20", _loader))
_loader.exec_module(yt)


def test_lists():
    assert len(yt.DEFAULT_LANGS) == 20 and "ko" not in yt.DEFAULT_LANGS
    assert len(yt.FREE_80) == 80 and len(set(yt.FREE_80)) == 80
    assert all(c in yt.ALL_SUPPORTED_LANGS for c in yt.FREE_80)


def test_cache_skips_already_translated_text(tmp_path):
    cache = {yt.cache_key("en", "제목"): "Title"}
    assert yt.chars_to_translate(["en", "ja"], ["제목", "설명입니다"], cache) == len("제목") + 2 * len("설명입니다")
    assert yt.won(1_000_000) == 28_000
    f = tmp_path / "c.json"
    yt.save_cache(cache, f)
    assert yt.load_cache(f) == cache


def test_claude_prompt_and_answer_roundtrip(tmp_path):
    prompt = yt.claude_prompt("겨울밤", "잔잔한 피아노\n#수면음악", [("en", "영어"), ("ja", "일본어")])
    assert "영어,en" in prompt and "일본어,ja" in prompt and "[제목]\n겨울밤" in prompt
    answer = '''네, 번역했습니다.
```csv
언어,언어코드,영상 제목,영상 설명
영어,en,"Winter Night","Calm piano
#수면음악"
일본어,ja,"冬の夜","静かなピアノ ""夜""
#수면음악"
```'''
    rows = yt.parse_claude_csv(answer)
    assert rows["en"] == ("영어", "Winter Night", "Calm piano\n#수면음악")
    assert rows["ja"][2] == '静かなピアノ "夜"\n#수면음악'
    out = tmp_path / "out.csv"
    yt.write_csv(out, [(n, c, t, d) for c, (n, t, d) in rows.items()])
    assert out.read_text(encoding="utf-8-sig").splitlines()[0] == "언어,언어코드,영상 제목,영상 설명"


def test_claude_answer_in_several_blocks_and_without_quotes():
    answer = '''```csv
언어,언어코드,영상 제목,영상 설명
영어,en,Winter Night,Calm piano, soft cello
#수면음악
```
다음은 나머지입니다.
```csv
일본어,ja,"冬の夜","静かな
ピアノ"
스페인어,es,Noche de invierno,"Piano tranquilo, chelo"
```'''
    rows = yt.parse_claude_csv(answer)
    assert set(rows) == {"en", "ja", "es"}
    assert rows["en"] == ("영어", "Winter Night", "Calm piano, soft cello\n#수면음악")
    assert rows["ja"][2] == "静かな\nピアノ"
    assert rows["es"][2] == "Piano tranquilo, chelo"
