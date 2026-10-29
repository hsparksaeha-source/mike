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
def test_flow_two_tracks(tmp_path, zip_mode, monkeypatch):
    monkeypatch.setattr(flow_maker, "DOWNLOADS_DIR", tmp_path / "Downloads")   # 실제 다운로드 폴더는 안 봄
    md = tmp_path / "낭만오케스트라3집.md"
    md.write_text(TWO_TRACKS, encoding="utf-8")
    out = tmp_path / "out"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("PW_CHROMIUM") or None)
        context = browser.new_context(viewport={"width": 1700, "height": 1000}, accept_downloads=True)
        page = context.new_page()
        page.goto(f"{MOCK}?delay=300&zip={zip_mode}&newthread={1 - int(zip_mode)}")   # zip=0 쪽은 영상마다 새 대화
        flow_maker.run(md, out, page=page, confirm=False, n_images=15)
        requests = page.evaluate("window.requests")
        collections = page.evaluate("window.collections")
        approved = page.evaluate("[window.approved, window.alwaysClicked || false]")
        wrong = page.evaluate("window.wrongMenu || null")
        browser.close()

    assert approved == [2, False]   # 영상마다 [승인]을 누름 ([항상 승인]은 안 누름)
    assert wrong is None            # '새 세션'·'캐릭터 만들기'는 누르지 않음
    album = out / "낭만오케스트라3집"
    folder1, folder2 = album / "이미지" / "1번", album / "이미지" / "2번"
    for folder in (folder1, folder2):
        names = sorted(p.name for p in folder.iterdir())
        assert len(names) == 15 and all(n.endswith(".jpg") for n in names), names   # 이미지만
    # 영상은 따로 장면 폴더에
    assert sorted(p.name for p in (album / "장면").iterdir()) == ["1.mp4", "2.mp4"]

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
    assert (folder1 / "Frozen_lake_3_abc003.jpg").read_bytes().endswith(b"image 3")   # 실제처럼 '제목_번호.jpg'
    assert (album / "장면" / "1.mp4").read_bytes()[4:8] == b"ftyp"   # 진짜 영상 파일

    # 다시 실행하면 이미 끝난 트랙은 건너뜀
    flow_maker.run(md, out, page=None, confirm=False, dry_run=True)


def test_reuse_existing_images(tmp_path, monkeypatch):
    monkeypatch.setattr(flow_maker, "DOWNLOADS_DIR", tmp_path / "Downloads")
    """이미지 15장이 이미 Flow 맨 앞에 있으면, 새로 만들지 않고 그 이미지로 영상·컬렉션만 한다."""
    from md_parser import parse_md
    [track] = parse_md(EASY_MD)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("PW_CHROMIUM") or None)
        context = browser.new_context(viewport={"width": 1700, "height": 1000}, accept_downloads=True)
        page = context.new_page()
        page.goto(f"{MOCK}?delay=300&plusbroken=1")   # 위쪽 [+] 가 안 되면 라이브러리 [+] 로
        # 지난번에 이미지만 만들어 둔 상태를 흉내: 이미지 15장 요청
        flow = flow_maker.Flow(page)
        flow.send_prompt("photorealistic test 15장")
        flow.wait_new("image", set(), 16, 30, settle=2)
        flow_maker.make_track(flow, track, tmp_path / "이미지" / "1번", tmp_path / "장면", 15, reuse=True)
        requests = page.evaluate("window.requests")
        collections = page.evaluate("window.collections")
        browser.close()
    assert [bool(r["attachment"]) for r in requests] == [False, True]   # 이미지 요청은 처음 1번뿐
    assert requests[1]["attachment"] == 3                              # 그 15장(3~17) 중 제일 처음 것
    assert sorted(collections[0]) == list(range(3, 18))
    assert len(list((tmp_path / "이미지" / "1번").iterdir())) == 15
    assert [p.name for p in (tmp_path / "장면").iterdir()] == ["1.mp4"]


def test_collection_files_from_downloads_folder(tmp_path):
    """크롬이 '다운로드' 폴더에 직접 저장한 파일을 찾는지 (확장자 없는 zip 포함)."""
    import os as _os
    import time
    import zipfile
    dl = tmp_path / "Downloads"
    dl.mkdir()
    start = time.time()
    (dl / "old.jpg").write_bytes(b"\xff\xd8\xff old")
    _os.utime(dl / "old.jpg", (start - 100, start - 100))        # 예전 파일은 무시
    with zipfile.ZipFile(dl / "32035c07-e744-4005-ae93-c0c389a45cd5", "w") as z:   # 확장자 없는 zip
        for i in range(15):
            z.writestr(f"img_{i}.jpg", b"\xff\xd8\xff" + bytes([i]))
    (dl / "b.png").write_bytes(b"\x89PNG data")
    (dl / "c.jpg.crdownload").write_bytes(b"\xff\xd8\xff")       # 받는 중인 파일은 무시
    (dl / "memo.txt").write_text("hello")                        # 이미지·zip 이 아니면 무시
    found = sorted(f.name for f in flow_maker.new_files_in(dl, start))
    assert found == ["32035c07-e744-4005-ae93-c0c389a45cd5", "b.png"]
    assert flow_maker.sniff_ext(dl / "32035c07-e744-4005-ae93-c0c389a45cd5") == ".zip"
    out = tmp_path / "out"
    out.mkdir()
    assert flow_maker.extract_images(dl / "32035c07-e744-4005-ae93-c0c389a45cd5", out) == 15


def test_image_folder_names(tmp_path):
    """이미지 폴더는 '1번', '2번' …. 예전 이름 '3' 폴더는 '3번'으로 바꿔서 이어 쓴다."""
    (tmp_path / "3").mkdir()
    (tmp_path / "3" / "a.jpg").write_text("a")
    assert flow_maker.image_folder(tmp_path, 1) == tmp_path / "1번"
    assert flow_maker.image_folder(tmp_path, 3) == tmp_path / "3번"
    assert (tmp_path / "3번" / "a.jpg").exists() and not (tmp_path / "3").exists()


def test_rerun_after_failure_reuses_made_images_and_video(tmp_path, monkeypatch):
    """이미지·영상을 다 만든 뒤 컬렉션에서 실패해도, 다시 실행하면 새로 만들지 않고 그것을 받는다.
    (실패한 트랙을 다시 돌릴 때마다 이미지·영상이 또 만들어져 크레딧이 들던 문제)"""
    monkeypatch.setattr(flow_maker, "DOWNLOADS_DIR", tmp_path / "Downloads")
    from md_parser import parse_md
    [track] = parse_md(EASY_MD)
    folder, scenes = tmp_path / "이미지" / "1번", tmp_path / "장면"
    real_collect = flow_maker.collect_images
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("PW_CHROMIUM") or None)
        context = browser.new_context(viewport={"width": 1700, "height": 1000}, accept_downloads=True)
        page = context.new_page()
        page.goto(f"{MOCK}?delay=300")
        flow = flow_maker.Flow(page)

        def broken(*a, **k):
            raise RuntimeError("컬렉션 실패")
        monkeypatch.setattr(flow_maker, "collect_images", broken)
        with pytest.raises(RuntimeError):
            flow_maker.make_track(flow, track, folder, scenes, 15)
        assert [p.name for p in scenes.iterdir()] == ["1.mp4"]       # 영상은 먼저 받아 둠
        monkeypatch.setattr(flow_maker, "collect_images", real_collect)
        flow_maker.make_track(flow, track, folder, scenes, 15)       # 다시 실행
        requests = page.evaluate("window.requests")
        browser.close()
    assert [bool(r["attachment"]) for r in requests] == [False, True]   # 이미지·영상 요청은 처음 한 번씩뿐
    assert len([p for p in folder.iterdir() if p.suffix == ".jpg"]) == 15
    assert not (folder / flow_maker.STATE_NAME).exists()


def test_retry_button_and_failed_images(tmp_path, monkeypatch):
    """Flow 오류 때 대화 창의 [다시 시도]를 누르고, 일부가 '실패'로 끝나면 만들어진 것만 받는다.
    받은 뒤에는 15장보다 적어도 끝난 트랙으로 친다 (다시 실행해도 그 트랙을 또 만들지 않음)."""
    monkeypatch.setattr(flow_maker, "DOWNLOADS_DIR", tmp_path / "Downloads")
    monkeypatch.setattr(flow_maker, "FAIL_SETTLE_SEC", 3)
    from md_parser import parse_md
    [track] = parse_md(EASY_MD)
    folder, scenes = tmp_path / "이미지" / "1번", tmp_path / "장면"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("PW_CHROMIUM") or None)
        context = browser.new_context(viewport={"width": 1700, "height": 1000}, accept_downloads=True)
        page = context.new_page()
        page.goto(f"{MOCK}?delay=300&retry=1&fail=4")
        flow_maker.make_track(flow_maker.Flow(page), track, folder, scenes, 15)
        clicked = page.evaluate("[window.retryClicked || 0, window.gridRetry || 0]")
        browser.close()
    assert clicked == [1, 0]          # 대화 창의 [다시 시도]만 한 번 누름 (실패 칸의 아이콘은 안 누름)
    assert len([p for p in folder.iterdir() if p.suffix == ".jpg"]) == 11
    assert flow_maker.track_done(folder, scenes, 1, 15)


def test_pop_tracks_with_characters(tmp_path, monkeypatch):
    """가요·칸쏘네: [+] → 캐릭터 → '캐릭터목록' 프로젝트 → 이름 → [프롬프트에 추가] 로 주인공을 올리고,
    곡 제목 + 가사 + '캐릭터(…)를 주인공으로 가사에 맞게 이미지 15장' 을 보낸다. 영상도 가사에 맞게."""
    monkeypatch.setattr(flow_maker, "DOWNLOADS_DIR", tmp_path / "Downloads")
    from test_cavn_maker import POP_MD, TEST_CAST
    import cast
    (tmp_path / "캐릭터목록.txt").write_text(TEST_CAST, encoding="utf-8")
    monkeypatch.setattr(cast, "CAST_FILE", tmp_path / "캐릭터목록.txt")
    md = tmp_path / "칸쏘네1집.md"
    md.write_text(POP_MD, encoding="utf-8")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("PW_CHROMIUM") or None)
        context = browser.new_context(viewport={"width": 1700, "height": 1000}, accept_downloads=True)
        page = context.new_page()
        page.goto(f"{MOCK}?delay=300")
        # 1번은 기본값(남자 노래 → 첫 남자 '마태오'), 2번은 직접 고른 두 사람
        flow_maker.run(md, tmp_path / "out", page=page, confirm=False, n_images=15,
                       cast_group="칸쏘네", cast={2: ["안나", "브루노"]})
        requests = page.evaluate("window.requests")
        played = page.evaluate("window.videoPlayed || 0")
        browser.close()
    assert played == 0          # 캐릭터 창 밖 격자의 영상 재생 단추는 누르지 않음
    images = [r for r in requests if not r["attachment"]]
    videos = [r for r in requests if r["attachment"]]
    assert [r["chars"] for r in images] == [["마태오"], ["안나", "브루노"]]
    assert images[0]["text"].startswith("You Were Already There\n\n")
    assert "캐릭터(마태오)를 주인공으로 가사에 맞게 16:9 이미지 15장" in images[0]["text"]
    assert "캐릭터(안나와 브루노)를 주인공으로" in images[1]["text"]
    assert all(v["text"].endswith("이 이미지로 가사에 맞게 영상을 만들어 주세요.") for v in videos) and len(videos) == 2
    album = tmp_path / "out" / "칸쏘네1집"
    assert len(list((album / "이미지" / "2번").glob("*.jpg"))) == 15
    assert sorted(p.name for p in (album / "장면").iterdir()) == ["1.mp4", "2.mp4"]


@pytest.mark.parametrize("direct", ["0", "1"])
def test_add_character_both_ways(direct):
    """[프롬프트에 추가] 를 눌러야 올라가는 경우와, 이름만 눌러도 바로 올라가는 경우 모두."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("PW_CHROMIUM") or None)
        page = browser.new_context(viewport={"width": 1700, "height": 1000}).new_page()
        page.goto(f"{MOCK}?delay=300&directadd={direct}")
        flow = flow_maker.Flow(page)
        flow.add_character("쥴리", "캐릭터목록")
        flow.add_character("마태오", "캐릭터목록")
        chars = page.evaluate("window.attachedChars")
        browser.close()
    assert chars == ["쥴리", "마태오"]


def test_video_refused_keeps_images(tmp_path, monkeypatch):
    """Flow 가 영상을 거절하면(정책·유명인) 기다리지 않고 영상만 건너뛰고 이미지는 받는다. 다시 돌려도 끝난 트랙."""
    monkeypatch.setattr(flow_maker, "DOWNLOADS_DIR", tmp_path / "Downloads")
    from md_parser import parse_md
    [track] = parse_md(EASY_MD)
    folder, scenes = tmp_path / "이미지" / "1번", tmp_path / "장면"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("PW_CHROMIUM") or None)
        context = browser.new_context(viewport={"width": 1700, "height": 1000}, accept_downloads=True)
        page = context.new_page()
        page.goto(f"{MOCK}?delay=300&videorefuse=1")
        flow_maker.make_track(flow_maker.Flow(page), track, folder, scenes, 15)
        browser.close()
    assert len(list(folder.glob("*.jpg"))) == 15
    assert not scenes.exists() or not list(scenes.iterdir())
    assert flow_maker.track_done(folder, scenes, 1, 15)


def test_add_character_slow_picker_and_many_projects():
    """애셋 창의 프로젝트 칸이 늦게 그려지고, 프로젝트가 많아 '캐릭터목록' 이 아래쪽에 있어도 찾는다."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("PW_CHROMIUM") or None)
        page = browser.new_context(viewport={"width": 1700, "height": 1000}).new_page()
        page.goto(f"{MOCK}?delay=300&slowpicker=1&manyprojects=1")
        flow = flow_maker.Flow(page)
        flow.add_character("마태오", "캐릭터목록")
        chars = page.evaluate("window.attachedChars")
        browser.close()
    assert chars == ["마태오"]


def test_image_urls_change_after_generation(tmp_path, monkeypatch):
    """다 만든 직후 Flow 가 그림 주소를 바꿔도 이미지를 찾아 컬렉션에 넣는다 (썸네일 배경 싱글1·2 실패 문제)."""
    monkeypatch.setattr(flow_maker, "DOWNLOADS_DIR", tmp_path / "Downloads")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("PW_CHROMIUM") or None)
        context = browser.new_context(viewport={"width": 1700, "height": 1000}, accept_downloads=True)
        page = context.new_page()
        page.goto(f"{MOCK}?delay=300&rekey=1")
        flow = flow_maker.Flow(page)
        images = flow_maker.request_images(flow, "photorealistic test", 4)
        count = flow_maker.collect_images(flow, images, tmp_path / "배경")
        browser.close()
    assert count == 4


def test_add_character_search_in_wrapper_and_picker_stays_open():
    """검색칸이 종류 칸이 빠진 큰 상자 안에 있어도 왼쪽 '캐릭터' 를 누르고,
    올린 뒤 창이 열린 채로 남으면 닫아서 격자를 훑을 수 있게 한다."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("PW_CHROMIUM") or None)
        page = browser.new_context(viewport={"width": 1700, "height": 1000}).new_page()
        page.goto(f"{MOCK}?delay=300&wrapsearch=1&stickypicker=1")
        flow = flow_maker.Flow(page)
        flow.add_character("소라", "캐릭터목록")
        flow.add_character("서준", "캐릭터목록")
        chars = page.evaluate("window.attachedChars")
        still_open = page.evaluate("!!document.getElementById('picker')")
        browser.close()
    assert chars == ["소라", "서준"]
    assert not still_open


def test_two_tracks_when_addresses_keep_changing(tmp_path, monkeypatch):
    """그림 주소가 만든 뒤에도, 컬렉션에 넣을 때마다 바뀌고, 예전 영상 주소도 바뀌고, [승인] 칸이 안 보여도:
    - 이미지는 제목으로 찾아 트랙마다 자기 그림 15장만 넣는다 (다른 트랙 그림·같은 그림 두 번 없음)
    - 예전 영상을 새 영상으로 착각하지 않는다 (7번에 3번 영상이 들어가던 문제)
    - [승인] 칸이 안 보이면 보내기(→) 화살표로 승인한다"""
    monkeypatch.setattr(flow_maker, "DOWNLOADS_DIR", tmp_path / "Downloads")
    md = tmp_path / "앨범.md"
    md.write_text(TWO_TRACKS, encoding="utf-8")
    out = tmp_path / "out"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("PW_CHROMIUM") or None)
        context = browser.new_context(viewport={"width": 1700, "height": 1000}, accept_downloads=True)
        page = context.new_page()
        page.goto(f"{MOCK}?delay=300&zip=1&rekey=1&rekeydrag=1&videorekey=1&hideapprove=1")
        flow_maker.run(md, out, page=page, confirm=False, n_images=15)
        collections = page.evaluate("window.collections")
        send_ok = page.evaluate("window.sendApproved || false")
        videos = page.evaluate("items.filter(i => i.kind === 'video').map(i => i.id)")
        browser.close()
    assert send_ok
    track2, track1 = collections[0], collections[1]
    assert len(set(track1)) == 15 and len(set(track2)) == 15
    assert max(track1) < min(track2)          # 트랙 1 그림은 트랙 1 컬렉션에만
    album = out / "앨범"
    for n in (1, 2):
        assert len(list((album / "이미지" / f"{n}번").glob("*.jpg"))) == 15
    v1 = (album / "장면" / "1.mp4").read_bytes()
    v2 = (album / "장면" / "2.mp4").read_bytes()
    assert v1 != v2 and v2.endswith(f"video {max(videos)}".encode())


def test_video_only_when_images_already_saved(tmp_path, monkeypatch):
    """이미지는 다 받아 두었는데 영상만 없으면(지운 경우 등) 이미지를 또 만들지 않고, 받아 둔 그림과 같은 제목의
    Flow 그림으로 영상만 만든다."""
    monkeypatch.setattr(flow_maker, "DOWNLOADS_DIR", tmp_path / "Downloads")
    md = tmp_path / "앨범.md"
    md.write_text(EASY_MD, encoding="utf-8")
    out = tmp_path / "out"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("PW_CHROMIUM") or None)
        context = browser.new_context(viewport={"width": 1700, "height": 1000}, accept_downloads=True)
        page = context.new_page()
        page.goto(f"{MOCK}?delay=300&zip=1")
        flow_maker.run(md, out, page=page, confirm=False, n_images=15)
        (out / "앨범" / "장면" / "1.mp4").unlink()
        flow_maker.run(md, out, page=page, confirm=False, n_images=15)
        requests = page.evaluate("window.requests")
        browser.close()
    assert [bool(r["attachment"]) for r in requests] == [False, True, True]   # 두 번째는 영상만
    assert len(list((out / "앨범" / "이미지" / "1번").glob("*.jpg"))) == 15
    assert (out / "앨범" / "장면" / "1.mp4").exists()
