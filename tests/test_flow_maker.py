"""Flow 이미지·영상 자동 만들기 시험 (가짜 Flow 페이지 mock_flow.html).

실행: python -m pytest tests/test_flow_maker.py
"""

import os
import sys
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "cavn_music"))
sys.path.insert(0, str(ROOT / "tests"))

import flow_maker  # noqa: E402
from test_cavn_maker import EASY_MD  # noqa: E402

MOCK = (Path(__file__).parent / "mock_flow.html").as_uri()
TWO_TRACKS = EASY_MD.replace("# PART B.", EASY_MD[EASY_MD.index("## Track 1."):EASY_MD.index("# PART B.")]
                             .replace("Track 1.", "Track 2.").replace("Quiet Street", "Second Street") + "# PART B.")


@pytest.mark.parametrize("zip_mode", ["1", "0"])
def test_flow_two_tracks(tmp_path, zip_mode):
    md = tmp_path / "낭만오케스트라3집.md"
    md.write_text(TWO_TRACKS, encoding="utf-8")
    out = tmp_path / "out"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("PW_CHROMIUM") or None)
        context = browser.new_context(viewport={"width": 1700, "height": 1000}, accept_downloads=True)
        page = context.new_page()
        page.goto(f"{MOCK}?delay=300&zip={zip_mode}")
        flow_maker.run(md, out, page=page, confirm=False, n_images=15)
        requests = page.evaluate("window.requests")
        collections = page.evaluate("window.collections")
        browser.close()

    folder1, folder2 = out / "낭만오케스트라3집" / "이미지" / "1", out / "낭만오케스트라3집" / "이미지" / "2"
    for folder in (folder1, folder2):
        names = sorted(p.name for p in folder.iterdir())
        assert len([n for n in names if n.endswith(".jpg")]) == 15, names
        assert [n for n in names if n.endswith(".mp4")] == [f"{folder.name}_영상.mp4"]
        assert not [n for n in names if n.endswith(".zip")]

    # 요청: 이미지 → (첫 이미지 첨부) 영상 → 이미지 → 영상
    assert [bool(r["attachment"]) for r in requests] == [False, True, False, True]
    assert requests[0]["text"].startswith("photorealistic photograph of a quiet snow-covered street")
    assert "15장" in requests[0]["text"]
    assert requests[1]["text"].startswith("가로등이 켜진 눈 덮인 밤거리")
    # 트랙 1 이미지는 id 3~17 → 영상은 제일 처음 만든 3번으로
    assert requests[1]["attachment"] == 3
    # 새 컬렉션 2개 (새 것이 앞), 각각 그 트랙의 이미지 15장, 처음 있던 컬렉션은 그대로
    assert sorted(collections[1]) == list(range(3, 18))
    assert len(collections[0]) == 15 and collections[2] == [1]
    assert (folder1 / "image_3.jpg").read_text() == "image 3"

    # 다시 실행하면 이미 끝난 트랙은 건너뜀
    flow_maker.run(md, out, page=None, confirm=False, dry_run=True)
