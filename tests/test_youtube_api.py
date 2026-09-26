"""YouTube API 제목·설명 등록 로직을 가짜 API 객체로 시험한다 (실제 유튜브에는 접속하지 않음)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from thumb_agent.languages import LanguageTable  # noqa: E402
from thumb_agent.youtube_api import apply_localizations  # noqa: E402


class _Call:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


class FakeYouTube:
    def __init__(self, snippet, localizations):
        self.video = {"id": "abcdefghijk", "snippet": snippet, "localizations": localizations}
        self.updates = []
        codes = ["en", "ja", "zh-Hans", "zh-Hant", "iw", "fil", "gu", "el", "ko", "fr"]
        self.langs = {"items": [{"snippet": {"hl": c, "name": c}} for c in codes]}

    def videos(self):
        return self

    def i18nLanguages(self):
        outer = self

        class _L:
            def list(self, **kw):
                return _Call(outer.langs)
        return _L()

    def list(self, **kw):
        return _Call({"items": [self.video]})

    def update(self, part, body):
        self.updates.append((part, body))
        return _Call(body)


def test_adds_only_missing_languages_and_keeps_existing():
    yt = FakeYouTube({"title": "원제목", "description": "원설명", "categoryId": "10", "defaultLanguage": "ko"},
                     {"en": {"title": "Existing EN", "description": "keep me"}})
    items = {
        "en": ("New EN", "should not overwrite"),
        "zh-CN": ("中文标题", "描述"),
        "he": ("כותרת", "תיאור"),
        "tl": ("Pamagat", "Paglalarawan"),
        "gu": ("번역 실패", "오류: 429"),
        "el": ("<Τίτλος>", "x" * 6000),
        "xx": ("?", "?"),
        "ko": ("한국어", "원래 언어"),
    }
    summary = apply_localizations(yt, "abcdefghijk", items, table=LanguageTable(), log=lambda *_: None)
    assert summary["existing"] == ["en"]
    assert sorted(summary["added"]) == ["el", "he", "tl", "zh-CN"]
    assert summary["bad"] == ["gu"] and summary["unknown"] == ["xx"] and summary["main"] == ["ko"]

    part, body = yt.updates[0]
    assert part == "localizations"            # 기본 언어가 있으면 snippet 은 건드리지 않음
    locs = body["localizations"]
    assert locs["en"] == {"title": "Existing EN", "description": "keep me"}
    assert locs["zh-Hans"]["title"] == "中文标题"
    assert locs["iw"]["title"] == "כותרת" and locs["fil"]["title"] == "Pamagat"
    assert locs["el"]["title"] == "‹Τίτλος›" and len(locs["el"]["description"]) == 5000


def test_overwrite_and_default_language_and_dry_run():
    yt = FakeYouTube({"title": "원제목", "description": "원설명", "categoryId": "10", "tags": ["a"]},
                     {"en": {"title": "Old", "description": "old"}})
    apply_localizations(yt, "abcdefghijk", {"en": ("New", "new")}, table=LanguageTable(),
                        dry_run=True, overwrite=True, log=lambda *_: None)
    assert yt.updates == []                   # 시험 실행은 등록하지 않음

    summary = apply_localizations(yt, "abcdefghijk", {"en": ("New", "new")}, table=LanguageTable(),
                                  overwrite=True, log=lambda *_: None)
    assert summary["updated"] == ["en"]
    part, body = yt.updates[0]
    assert part == "localizations,snippet"
    assert body["snippet"] == {"title": "원제목", "description": "원설명", "categoryId": "10",
                               "tags": ["a"], "defaultLanguage": "ko"}
    assert body["localizations"]["en"]["title"] == "New"
