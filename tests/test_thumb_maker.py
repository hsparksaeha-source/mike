"""썸네일 만들기 시험: md 썸네일 문구 읽기 + 완성 그림 + 캡컷 초안.

실행: python -m pytest tests/test_thumb_maker.py
"""

import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "cavn_music"))

import thumb_maker  # noqa: E402

EASY = """# Snowlight Serenade

## Track 1. Snow Falling on the Quiet Street

### 스타일 → 텍스트 박스
```
piano
```

### 구조 태그 (가사 칸 대신 → 텍스트 박스)
```
[Intro]
```

### 썸네일 이미지 생성 프롬프트
```
photorealistic quiet snowy street
```

### 썸네일 문구
```
트랙 문구는 쓰지 않음
```

# PART B. 전곡 듣기 영상 — 유튜브 SEO 세트

## 유튜브 설명

```text
설명
#겨울음악 #경음악
```

## 썸네일 문구

```text
한글 1: 눈 오는 날 / 낭만 경음악 10곡
한글 2: 포근한 겨울밤 / 솔로 악기와 현악의 슬로우 발라드
영문: Snowlight Serenade / Winter Easy Listening Orchestra
```

## 썸네일 이미지 생성 프롬프트 (배경 이미지용, 문구는 별도로 얹을 것)

```text
photorealistic snowy street at
night, warm lamps
```

# PART C. 엄선 싱글 3곡 + 유튜브 SEO 세트

## Single 1. Snow Falling on the Quiet Street

### 유튜브 설명

```text
#피아노연주곡
```

### 썸네일 문구

```text
한글 1: 조용한 거리에 내리는 눈
영문: Snow Falling / Piano & Strings
```

### 썸네일 이미지 생성 프롬프트

```text
photorealistic quiet snowy street
```
"""

SACRED = """# 사크리드 5집

## 트랙 1: 사랑이 머무는 저녁 식탁

**썸네일 문구** (메인+서브 두 줄 구성)
```
메인: 트랙 문구
서브: 쓰지 않음
```

## PART A: 앨범 대표 썸네일 (3종)

**대표 이미지 1 — 저녁 식탁 (가장 상징적)**
```
A long rustic wooden table
```

**대표 이미지 2 — 스테인드글라스**
```
The nave of a stone chapel
```

**대표 썸네일 문구**
```
메인: 저녁 종소리의 기도
서브: 라틴어 성가 · 메조소프라노
```

## PART B: 유튜브 SEO 패키지

**썸네일 문구** (전체 패키지용, 2안)
```
[1안]
메인: 가을 저녁, 종소리가 닿는 곳에서
서브: 첼로와 클라리넷이 번갈아 전하는 사크리드 뉴에이지 보컬 5집

[2안]
메인: 노을에서 별빛까지
서브: 라틴어로 부르는 저녁 종소리의 기도
```

**썸네일 문구 (English, 전체 패키지용 2안)**
```
[Option 1]
Main: Where the Evening Bell Reaches
Sub: Sacred New Age Vocal Album 5
```
"""


def test_parse_easy_main_and_singles():
    main, single = thumb_maker.parse_thumbnails(EASY)
    assert main.name == "메인" and main.prompt == "photorealistic snowy street at night, warm lamps"
    assert [(o.label, o.lines) for o in main.options] == [
        ("한글1", ["눈 오는 날", "낭만 경음악 10곡"]),
        ("한글2", ["포근한 겨울밤", "솔로 악기와 현악의 슬로우 발라드"])]
    assert main.english == ["Snowlight Serenade", "Winter Easy Listening Orchestra"]
    assert (single.name, single.title) == ("싱글1", "Snow Falling on the Quiet Street")
    assert [o.lines for o in single.options] == [["조용한 거리에 내리는 눈"]]
    assert single.english == ["Snow Falling", "Piano & Strings"]
    assert single.prompt == "photorealistic quiet snowy street"


def test_parse_sacred_main_only():
    [main] = thumb_maker.parse_thumbnails(SACRED)
    assert main.prompt == "A long rustic wooden table"          # 대표 이미지 1
    assert [(o.label, o.lines[0]) for o in main.options] == [
        ("문구", "저녁 종소리의 기도"), ("1안", "가을 저녁, 종소리가 닿는 곳에서"), ("2안", "노을에서 별빛까지")]
    assert main.english == ["Where the Evening Bell Reaches", "Sacred New Age Vocal Album 5"]
    assert [(o.label, o.lines) for o in main.en_options] == [
        ("영문", ["Where the Evening Bell Reaches", "Sacred New Age Vocal Album 5"])]


def test_run_makes_jpg_and_capcut(tmp_path):
    md = tmp_path / "Snowlight.md"
    md.write_text(EASY, encoding="utf-8")
    out = tmp_path / "out"
    album = out / "Snowlight"
    # 메인 배경은 Flow 에서 받아 둔 것, 싱글1 은 곡 이미지(프롬프트 같음)를 다시 씀
    (album / "썸네일" / "배경" / "메인").mkdir(parents=True)
    Image.new("RGB", (1376, 768), (40, 60, 90)).save(album / "썸네일" / "배경" / "메인" / "a.jpg")
    (album / "이미지" / "1번").mkdir(parents=True)
    Image.new("RGB", (1376, 768), (90, 60, 40)).save(album / "이미지" / "1번" / "img.jpg")

    made = thumb_maker.run(md, out, use_flow=False, capcut_dir=tmp_path / "drafts", confirm=False)
    assert sorted(p.name for p in made) == ["메인_영문.jpg", "메인_한글1.jpg", "메인_한글2.jpg",
                                            "싱글1_영문.jpg", "싱글1_한글1.jpg"]   # 영문 썸네일도
    img = Image.open(made[0])
    assert img.size == (1920, 1080) and made[0].stat().st_size < 2 * 1024 * 1024
    assert (album / "썸네일" / "배경" / "싱글1" / "img.jpg").exists()

    drafts = sorted(p.name for p in (tmp_path / "drafts").iterdir() if p.is_dir())
    assert drafts == ["Snowlight 썸네일 메인_영문", "Snowlight 썸네일 메인_한글1", "Snowlight 썸네일 메인_한글2",
                      "Snowlight 썸네일 싱글1_영문", "Snowlight 썸네일 싱글1_한글1"]
    en = json.loads((tmp_path / "drafts" / drafts[0] / "draft_content.json").read_text(encoding="utf-8"))
    assert [json.loads(m["content"])["text"] for m in en["materials"]["texts"]] == [
        "Snowlight Serenade", "Winter Easy", "Listening Orchestra"]   # 영문 썸네일: 영어 문구만 크게 (긴 줄은 둘로)
    content = json.loads((tmp_path / "drafts" / drafts[1] / "draft_content.json").read_text(encoding="utf-8"))
    texts = [json.loads(m["content"])["text"] for m in content["materials"]["texts"]]
    assert texts == ["눈 오는 날", "낭만 경음악 10곡", "Snowlight Serenade", "Winter Easy Listening Orchestra"]
    styles = json.loads(content["materials"]["texts"][1]["content"])["styles"]
    assert [s["range"] for s in styles] == [[0, 7], [7, 9], [9, 10]]     # '낭만 경음악 ' / '10' / '곡' 글꼴 따로


def test_runs_split_by_script():
    assert thumb_maker.runs("2장 · 사랑 10곡") == [("2", False), ("장 · 사랑 ", True), ("10", False), ("곡", True)]
    assert thumb_maker.runs("Gettone · Jeton") == [("Gettone · Jeton", False)]


def test_background_from_track_images_when_no_prompt(tmp_path):
    """썸네일 이미지 프롬프트가 없는 md: 싱글은 같은 제목 곡의 이미지, 메인은 1번 곡 이미지를 배경으로."""
    from md_parser import Track
    tracks = [Track(1, "하얀 숨결"), Track(2, "첫눈")]
    album = tmp_path / "앨범"
    for n in (1, 2):
        (album / "이미지" / f"{n}번").mkdir(parents=True)
        Image.new("RGB", (100, 60)).save(album / "이미지" / f"{n}번" / f"img{n}.jpg")
    single = thumb_maker.Thumb("싱글2", title="첫눈")
    main = thumb_maker.Thumb("메인")
    assert thumb_maker.reuse_track_images(single, tracks, album, tmp_path / "배경" / "싱글2")
    assert thumb_maker.reuse_track_images(main, tracks, album, tmp_path / "배경" / "메인")
    assert [p.name for p in (tmp_path / "배경" / "싱글2").iterdir()] == ["img2.jpg"]
    assert [p.name for p in (tmp_path / "배경" / "메인").iterdir()] == ["img1.jpg"]
