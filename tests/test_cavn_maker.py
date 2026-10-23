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


def run_mock(tmp_path, md_text, md_name, lengths, masters=(0,), between=None):
    """같은 브라우저(=같은 가짜 사이트 기록)에서 masters 개수만큼 이어서 실행한다."""
    md = tmp_path / md_name
    md.write_text(md_text, encoding="utf-8")
    out = tmp_path / "out"
    states = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("PW_CHROMIUM") or None)
        context = browser.new_context(viewport={"width": 1600, "height": 1000}, accept_downloads=True)
        page = context.new_page()
        for n, master in enumerate(masters):
            if n and between:
                between(out / md.stem / "노래")
            cavn_maker.run(md, out, page=page, confirm=False, master=master,
                           create_url=f"{MOCK}?page=create&delay=1500&lengths={lengths}",
                           albums_url=f"{MOCK}?page=albums")
            page.goto(MOCK)
            states.append(page.evaluate("""() => ({
                created: JSON.parse(localStorage.getItem('created') || '[]'),
                mastered: JSON.parse(localStorage.getItem('mastered') || '[]'),
                bad: localStorage.getItem('badClick')})"""))
        browser.close()
    return out / md.stem / "노래", states if len(states) > 1 else states[0]


def test_pop_flow_on_mock(tmp_path):
    songs, state = run_mock(tmp_path, POP_MD, "카페소네트5_2장.md", "150,200")
    created = state["created"]
    assert state["bad"] is None
    assert state["mastered"] == []   # 가사 비디오·창작 증명서는 누르지 않음
    assert [c["title"] for c in created] == ["You Were Already There", "Un'Estate Soltanto"]
    first = created[0]
    assert first["album"] == "카페소네트5_2장" and not first["instrumental"]
    assert first["lyrics"].startswith("[Verse 1 - male lead]")
    assert first["style"].startswith("Classic 1960s pop")
    assert first["exclude"] == "rap, edm, korean lyrics"
    assert first["gender"] == "남성"   # 'male vocal'

    names = sorted(p.name for p in songs.iterdir() if not p.name.startswith("."))
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



def test_classical_flow_and_resume(tmp_path):
    songs, state = run_mock(tmp_path, CLASSICAL_MD, "바흐풍_겨울마을.md", "190,170")
    [c] = state["created"]
    assert c["instrumental"] and c["lyrics"] == ""
    assert c["title"] == "Warm Socks, Slow Morning" and c["gender"] == "여성"   # 클래식은 무조건 여성
    assert c["style"].endswith("[Outro] (gentle cadence, slowly fading)")
    assert len([p for p in songs.iterdir() if not p.name.startswith(".")]) == 10
    # 다시 실행하면 이미 받은 곡은 건너뜀
    _, state2 = run_mock(tmp_path, CLASSICAL_MD, "바흐풍_겨울마을.md", "190,170")
    assert state2["created"] == []   # 곡 만들기를 누르지 않음


def test_mastering_long_take_only(tmp_path):
    one_song = POP_MD.split("# Track 2.")[0]
    title = "You Were Already There"
    # 1회차: 마스터링 안 함, 2회차: 마스터링 함 → 곡은 새로 만들지 않고 긴 곡만 마스터링
    songs, (first, second) = run_mock(tmp_path, one_song, "칸쏘네.md", "160,210", masters=(0, 1))
    assert first["mastered"] == []
    assert second["created"] == first["created"] and len(first["created"]) == 1
    # 긴 곡(210초) = 목록 둘째 줄 = id 2 만 '밝고 선명한'으로
    assert second["mastered"] == [{"id": 2, "style": "밝고 선명한"}]
    assert (songs / f"{title}_mastered.wav").read_text() == f"mastered 밝고 선명한 {title}#2"
    assert not (songs / f"{title} (1)_mastered.wav").exists()
    assert len([p for p in songs.iterdir() if not p.name.startswith(".")]) == 11

    # 처음부터 마스터링 함: 11개, 긴 곡(210초, 2번째 줄 = id 4)만 마스터링
    (tmp_path / "b").mkdir()
    songs2, state = run_mock(tmp_path / "b", one_song, "칸쏘네2.md", "160,210", masters=(1,))
    assert len([p for p in songs2.iterdir() if not p.name.startswith(".")]) == 11
    assert state["mastered"] == [{"id": 2, "style": "밝고 선명한"}]


def test_reuse_songs_already_made(tmp_path):
    """곡은 만들어졌는데 파일을 못 받은 경우, 다시 실행하면 새로 만들지 않고 그 2곡을 받는다."""
    one_song = POP_MD.split("# Track 2.")[0]
    songs, (first, second) = run_mock(tmp_path, one_song, "칸쏘네.md", "150,200", masters=(0, 0),
                                      between=lambda out: [p.unlink() for p in out.iterdir()])
    assert len(first["created"]) == 1 and second["created"] == first["created"]
    assert len([p for p in songs.iterdir() if not p.name.startswith(".")]) == 10


def test_resume_missing_lyrics_and_mastering(tmp_path):
    """wav 는 받았는데 텍스트 가사·마스터링이 빠진 곡은, 다시 실행하면 빠진 것만 받는다."""
    one_song = POP_MD.split("# Track 2.")[0]
    title = "You Were Already There"

    def drop(out):
        (out / f"{title}_가사본문.txt").unlink()
        (out / f"{title}_mastered.wav").unlink()
    songs, (first, second) = run_mock(tmp_path, one_song, "칸쏘네.md", "150,200", masters=(1, 1), between=drop)
    assert len(second["created"]) == 1                      # 새로 만들지 않음
    assert len(second["mastered"]) == 2 and second["mastered"][1] == second["mastered"][0]   # 같은 긴 곡
    assert (songs / f"{title}_가사본문.txt").read_text().startswith("가사 본문만")
    assert len(list(p for p in songs.iterdir() if not p.name.startswith("."))) == 11
