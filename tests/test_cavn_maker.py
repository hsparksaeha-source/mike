"""CAVN 자동 곡 생성 프로그램 시험 (md 읽기 + 가짜 CAVN 페이지 mock_cavn.html).

실행: python -m pytest tests/test_cavn_maker.py
"""

import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "cavn_music"))

import cavn_maker  # noqa: E402
from md_parser import parse_md  # noqa: E402

MOCK = (Path(__file__).parent / "mock_cavn.html").as_uri()

POP_MD = """# 「Café Sonnet 5」— 정규 앨범

**공통 Exclude Styles:** `rap, edm, korean lyrics`

---

# Track 1. You Were Already There

## 제목
```
You Were Already There (당신은 이미 거기 있었어요)
```

## 장르 → 텍스트 박스
```
Classic 1960s pop, light swing ballad
```

## 스타일 → 텍스트 박스
```
male vocal, smooth crooner tone, English
lyrics, mid tempo 92 bpm
```

## 간단한 곡 설명 → 텍스트 박스
```
설명
```

## 가사 → 텍스트 박스
```
[Verse 1 - male lead]
I came an hour early

[Chorus]
You were already there
```

## 한국어 번역 (전곡, 자막 수정 참고용 · Suno 입력 X) → 텍스트 박스
```
나는 한 시간 일찍 왔어요
```

# Track 2. Un'Estate Soltanto

## 제목
```
Un'Estate Soltanto (단 한 번의 여름)
```

## 장르 → 텍스트 박스
```
Italian canzone
```

## 스타일 → 텍스트 박스
```
male vocal, Italian lyrics
```

## 가사 → 텍스트 박스
```
[Verse 1]
Un'estate soltanto
```

# 업로드 메모
## 제목
```
이건 곡이 아님
```
"""

CLASSICAL_MD = """# 바흐풍 바로크 실내악 (앨범명: Slow Winter Days)

## 곡별 예상 길이
| 1 | Warm Socks, Slow Morning (따뜻한 양말, 느린 아침) | 바이올린 |

## 트랙 1: Warm Socks, Slow Morning (따뜻한 양말, 느린 아침)

### 제목 → 텍스트 박스
```
Warm Socks, Slow Morning
```

### 장르 → 텍스트 박스
```
Classical, Baroque, Chamber Music, Instrumental
```

### 스타일 → 텍스트 박스 (492자)
```
baroque chamber music, violin plays the sole lead melody, 66 BPM
```

### Exclude Styles → 텍스트 박스
```
drum kit, vocal, harpsichord
```

### 가사(구조 태그) → 텍스트 박스 (332자, 스타일+구조 합계 824자)
```
[Intro] (calm opening)
[A] (violin enters with the main theme)
[Outro] (gentle cadence, slowly fading)
```

### 이미지 프롬프트 → 텍스트 박스
```
Aerial drone photograph
```

---

## 유튜브 업로드용
### 태그 → 텍스트 박스
```
바흐풍 클래식
```
"""


def test_parse_pop():
    tracks = parse_md(POP_MD)
    assert [(t.number, t.title) for t in tracks] == [(1, "You Were Already There"), (2, "Un'Estate Soltanto")]
    t = tracks[0]
    assert not t.classical
    assert t.style_box() == ("Classic 1960s pop, light swing ballad, "
                             "male vocal, smooth crooner tone, English lyrics, mid tempo 92 bpm")
    assert t.style_box(include_genre=False) == "male vocal, smooth crooner tone, English lyrics, mid tempo 92 bpm"
    assert t.lyrics_box() == "[Verse 1 - male lead]\nI came an hour early\n\n[Chorus]\nYou were already there"
    assert t.exclude == "rap, edm, korean lyrics"   # 머리말의 공통 Exclude


def test_parse_classical():
    [t] = parse_md(CLASSICAL_MD)
    assert t.classical and t.title == "Warm Socks, Slow Morning"
    assert t.lyrics_box() == ""
    # 스타일 + 구조 태그를 음악 스타일 칸에 한꺼번에 (장르는 넣지 않음)
    assert t.style_box() == ("baroque chamber music, violin plays the sole lead melody, 66 BPM\n"
                             "[Intro] (calm opening)\n[A] (violin enters with the main theme)\n"
                             "[Outro] (gentle cadence, slowly fading)")
    assert t.exclude == "drum kit, vocal, harpsichord"


def run_mock(tmp_path, md_text, md_name, lengths):
    md = tmp_path / md_name
    md.write_text(md_text, encoding="utf-8")
    out = tmp_path / "out"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("PW_CHROMIUM") or None)
        context = browser.new_context(viewport={"width": 1600, "height": 1000}, accept_downloads=True)
        page = context.new_page()
        cavn_maker.run(md, out, page=page, confirm=False,
                       create_url=f"{MOCK}?page=create&delay=1500&lengths={lengths}",
                       albums_url=f"{MOCK}?page=albums")
        created = page.evaluate("window.created")
        bad = page.evaluate("window.badClick || null")
        browser.close()
    return out / md.stem / "노래", created, bad


def test_pop_flow_on_mock(tmp_path):
    songs, created, bad = run_mock(tmp_path, POP_MD, "카페소네트5_2장.md", "150,200")
    assert bad is None   # 가사 비디오·창작 증명서는 누르지 않음
    assert [c["title"] for c in created] == ["You Were Already There", "Un'Estate Soltanto"]
    first = created[0]
    assert first["album"] == "카페소네트5_2장" and not first["instrumental"]
    assert first["lyrics"].startswith("[Verse 1 - male lead]")
    assert first["style"].startswith("Classic 1960s pop")
    assert first["exclude"] == "rap, edm, korean lyrics"

    names = sorted(p.name for p in songs.iterdir())
    for title in ("You Were Already There", "Un'Estate Soltanto"):
        assert {f"{title}.mp3", f"{title}.wav", f"{title}.lrc", f"{title}.jpeg",
                f"{title}_구간라벨.txt", f"{title}_가사본문.txt",
                f"{title} (1).mp3", f"{title} (1).wav", f"{title} (1).lrc", f"{title} (1).jpeg"} <= set(names)
    assert len(names) == 20
    # 긴 곡(200초)이 '제목', 짧은 곡(150초)이 '제목 (1)'
    long_wav = (songs / "You Were Already There.wav").read_text()
    short_wav = (songs / "You Were Already There (1).wav").read_text()
    assert len(long_wav) > len(short_wav)
    long_id = long_wav.split("#")[-1]
    assert (songs / "You Were Already There.lrc").read_text().endswith("#" + long_id)
    assert (songs / "You Were Already There_구간라벨.txt").read_text().startswith("구간 라벨 유지")
    assert (songs / "You Were Already There_가사본문.txt").read_text().startswith("가사 본문만")
    # 긴 곡을 먼저 받음
    assert (songs / "You Were Already There.wav").stat().st_mtime < \
        (songs / "You Were Already There (1).wav").stat().st_mtime


def test_classical_flow_and_resume(tmp_path):
    songs, created, _ = run_mock(tmp_path, CLASSICAL_MD, "바흐풍_겨울마을.md", "190,170")
    [c] = created
    assert c["instrumental"] and c["lyrics"] == ""
    assert c["style"].endswith("[Outro] (gentle cadence, slowly fading)")
    assert len(list(songs.iterdir())) == 10
    # 다시 실행하면 이미 받은 곡은 건너뜀
    _, created2, _ = run_mock(tmp_path, CLASSICAL_MD, "바흐풍_겨울마을.md", "190,170")
    assert not created2   # 곡 만들기를 누르지 않음
