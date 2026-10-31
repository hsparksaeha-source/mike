"""LRC 이중자막 (다국어 → 영어 / 한국어) 시험. 화면·구글 번역 없이 줄 나누기와 순서만."""

import importlib.machinery
import importlib.util
import sys
import types
from pathlib import Path

for _name in ("tkinter", "tkinter.filedialog", "tkinter.messagebox"):
    sys.modules.setdefault(_name, types.ModuleType(_name))
sys.modules["tkinter"].messagebox = sys.modules["tkinter.messagebox"]
sys.modules["tkinter"].filedialog = sys.modules["tkinter.filedialog"]

ROOT = Path(__file__).resolve().parent.parent
_loader = importlib.machinery.SourceFileLoader("lrc_multi", str(ROOT / "cavn_music" / "lrc_translate_multi.pyw"))
lrc = importlib.util.module_from_spec(importlib.util.spec_from_loader("lrc_multi", _loader))
_loader.exec_module(lrc)

SAMPLE = "[ti:Gettone]\n[00:12.34]Tu sei la mia canzone\n[00:15.00]\n\n[00:16.50][00:40.10]雪が降る\n[00:20.00]♪ 123"


def test_parse_and_letters():
    parsed, todo = lrc.parse_lrc(SAMPLE)
    assert [t["original_text"] for t in todo] == ["Tu sei la mia canzone", "雪が降る", "♪ 123"]
    assert todo[1]["timestamp"] == "[00:16.50][00:40.10]"
    assert lrc.has_letters("雪が降る") and lrc.has_letters("Привет") and not lrc.has_letters("♪ 123 !")


def test_order_korean_on_top_english_below():
    parsed, todo = lrc.parse_lrc("[00:12.34]Tu sei la mia canzone")
    todo[0]["translated_text"] = "너는 나의 노래"
    assert lrc.build_lines(parsed, "x2ko") == ["[00:12.34]너는 나의 노래", "[00:12.34]Tu sei la mia canzone"]
    todo[0]["translated_text"] = "You are my song"
    assert lrc.build_lines(parsed, "x2en") == ["[00:12.34]Tu sei la mia canzone", "[00:12.34]You are my song"]
