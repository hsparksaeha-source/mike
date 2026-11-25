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


def test_original_on_top_on_screen_and_swapped_when_saved_for_video():
    parsed, todo = lrc.parse_lrc("[ti:x]\n[00:12.34]Tu sei la mia canzone\n[00:15.00]Ciao")
    todo[0]["translated_text"], todo[1]["translated_text"] = "너는 나의 노래", "안녕"
    shown = lrc.build_lines(parsed, "x2ko")
    assert shown == ["[ti:x]", "[00:12.34]Tu sei la mia canzone", "[00:12.34]너는 나의 노래",
                     "[00:15.00]Ciao", "[00:15.00]안녕"]
    assert lrc.for_video("\n".join(shown)).split("\n") == [
        "[ti:x]", "[00:12.34]너는 나의 노래", "[00:12.34]Tu sei la mia canzone", "[00:15.00]안녕", "[00:15.00]Ciao"]


def test_claude_prompt_and_answer_for_lyrics():
    parsed, todo = lrc.parse_lrc("[ti:x]\n[00:12.34]Tu sei la mia canzone\n[00:15.00]Ciao amore")
    prompt = lrc.claude_lrc_prompt(todo, "한국어")
    assert "1. Tu sei la mia canzone" in prompt and "2. Ciao amore" in prompt and "한국어" in prompt
    answer = "```\n1. 너는 나의 노래\n2) 안녕 내 사랑\n```"
    assert lrc.apply_claude_answer(todo, answer) == (2, [])
    assert lrc.build_lines(parsed, "x2ko") == [
        "[ti:x]", "[00:12.34]Tu sei la mia canzone", "[00:12.34]너는 나의 노래",
        "[00:15.00]Ciao amore", "[00:15.00]안녕 내 사랑"]
    _, todo2 = lrc.parse_lrc("[00:01.00]a b\n[00:02.00]c d")
    assert lrc.apply_claude_answer(todo2, "1. 하나") == (1, [2])
