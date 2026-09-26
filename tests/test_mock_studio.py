"""가짜 스튜디오 페이지(mock_studio.html)로 업로드 흐름을 시험한다.

실행: python -m pytest tests  (또는 python tests/test_mock_studio.py)
"""

import os
import sys
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from thumb_agent.folder import scan_folder  # noqa: E402
from thumb_agent.languages import LanguageTable  # noqa: E402
from thumb_agent.studio import StudioThumbnailUploader, parse_video_id  # noqa: E402

MOCK_URL = (Path(__file__).parent / "mock_studio.html").as_uri() + "?v={video_id}"


def make_images(folder: Path, names):
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        Image.new("RGB", (1280, 720), (200, 120, 40)).save(folder / name)


def test_filename_matching(tmp_path):
    table = LanguageTable({"스리랑카어": "si"})
    make_images(tmp_path, ["gu.jpg", "그리스어.png", "03_Dutch.jpg", "thumb_ne.jpg",
                           "중국어(간체).jpg", "Chinese (Traditional).jpg", "스리랑카어.jpg",
                           "random.jpg"])
    scan = scan_folder(tmp_path, table)
    assert {c: p.name for c, p in scan.matched.items()} == {
        "gu": "gu.jpg", "el": "그리스어.png", "nl": "03_Dutch.jpg", "ne": "thumb_ne.jpg",
        "zh-Hans": "중국어(간체).jpg", "zh-Hant": "Chinese (Traditional).jpg", "si": "스리랑카어.jpg",
    }
    assert [p.name for p in scan.unmatched] == ["random.jpg"]


def test_translator_language_codes_and_names():
    """번역기(youtube_translator_maker.pyw)의 106개 언어 코드/이름이 모두 같은 언어로 인식되는지."""
    import ast
    src = (ROOT / "youtube_translator_maker.pyw").read_text(encoding="utf-8")
    start = src.index("ALL_SUPPORTED_LANGS = {")
    langs = ast.literal_eval(src[src.index("{", start):src.index("}", start) + 1])
    table = LanguageTable()
    for code, name in langs.items():
        assert table.match_filename(code) is not None, code
        assert table.match_filename(code) == table.match_filename(name), (code, name)
    assert len(langs) >= 100


def test_parse_video_id():
    assert parse_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=3") == "dQw4w9WgXcQ"
    assert parse_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert parse_video_id("https://studio.youtube.com/video/dQw4w9WgXcQ/translations") == "dQw4w9WgXcQ"
    assert parse_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_upload_flow_on_mock(tmp_path):
    table = LanguageTable()
    thumbs_dir = tmp_path / "thumbs"
    # 힌디어는 스튜디오 표에 없음, 네덜란드어는 이미 썸네일 있음
    make_images(thumbs_dir, ["gu.jpg", "el.jpg", "nl.jpg", "zh-Hans.jpg", "ar.jpg", "hi.jpg"])
    scan = scan_folder(thumbs_dir, table)

    with sync_playwright() as pw:
        # 설치된 크로미움 경로를 지정하려면 환경변수 PW_CHROMIUM 사용
        browser = pw.chromium.launch(executable_path=os.environ.get("PW_CHROMIUM") or None)
        page = browser.new_page()
        uploader = StudioThumbnailUploader(
            page, table, log_dir=tmp_path / "logs", progress_dir=tmp_path / "progress",
            step_delay=0.1, studio_url=MOCK_URL)
        summary = uploader.upload_all("abcdefghijk", scan.matched)
        uploaded = page.evaluate("window.uploaded")

        assert sorted(summary["ok"]) == ["ar", "el", "gu", "zh-Hans"]
        assert summary["skipped"] == ["nl"]           # 이미 썸네일 있음
        assert summary["not_in_studio"] == ["hi"]     # 숨겨진 메뉴의 '힌디어'는 무시
        assert summary["no_file"] == ["ne"]
        assert summary["failed"] == []
        assert uploaded == {"구자라트어": "gu.jpg", "그리스어": "el.jpg",
                            "중국어(간체)": "zh-Hans.jpg", "아랍어": "ar.jpg"}

        # 다시 실행하면 완료된 언어는 진행 기록 때문에 건너뛴다
        summary2 = uploader.upload_all("abcdefghijk", scan.matched)
        assert summary2["ok"] == []
        assert sorted(summary2["skipped"]) == ["ar", "el", "gu", "nl", "zh-Hans"]
        browser.close()


if __name__ == "__main__":
    import tempfile
    for test in (test_filename_matching, test_upload_flow_on_mock):
        with tempfile.TemporaryDirectory() as d:
            test(Path(d))
    test_parse_video_id()
    print("모든 테스트 통과")
