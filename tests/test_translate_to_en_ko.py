"""다국어 → 영어·한국어 번역기 시험 (구글 번역 API 는 가짜로 바꿔서)."""

import importlib.machinery
import importlib.util
import io
import json
import sys
import types
from pathlib import Path

# 시험 컴퓨터에 tkinter(화면 그리기)가 없어도 번역 부분만 시험한다
for _name in ("tkinter", "tkinter.filedialog", "tkinter.messagebox", "tkinter.ttk"):
    sys.modules.setdefault(_name, types.ModuleType(_name))

ROOT = Path(__file__).resolve().parent.parent
_loader = importlib.machinery.SourceFileLoader("translate_to_en_ko", str(ROOT / "cavn_music" / "translate_to_en_ko.pyw"))
spec = importlib.util.spec_from_loader("translate_to_en_ko", _loader)
tr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tr)


class Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_translate_detects_language_and_keeps_lines(monkeypatch):
    sent = []

    def fake_urlopen(url, data, timeout):
        sent.append(dict(p.split("=", 1) for p in data.decode().split("&")))
        body = {"data": {"translations": [{"translatedText": "Snow &amp; Love\nline 2", "detectedSourceLanguage": "ja"}]}}
        return Reply(json.dumps(body).encode())
    monkeypatch.setattr(tr.urllib.request, "urlopen", fake_urlopen)
    text, lang = tr.translate("KEY", "雪と愛\n二行目", "en")
    assert text == "Snow & Love\nline 2" and lang == "ja"
    assert sent[0]["target"] == "en" and sent[0]["format"] == "text" and "source" not in sent[0]
    assert tr.translate("KEY", "   ", "ko") == ("", "")


def test_key_found_next_to_program_or_old_translator(tmp_path, monkeypatch):
    key = tmp_path / tr.KEY_NAME
    key.write_text(" abc \n", encoding="utf-8")
    monkeypatch.setattr(tr, "KEY_PLACES", [tmp_path / "없음.txt", key])
    assert tr.find_key() == "abc"
