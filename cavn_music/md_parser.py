"""Claude가 만든 음악 md 파일에서 곡별 제목·장르·스타일·Exclude·가사를 뽑는다.

두 가지 형식을 모두 읽는다.
  가요/팝:  "# Track 1. 제목"   아래에 "## 제목", "## 장르 → 텍스트 박스", "## 스타일 → ...", "## 가사 → ..."
  클래식:   "## 트랙 1: 제목"   아래에 "### 제목 → ...", "### 스타일 → ...", "### Exclude Styles → ...",
            "### 가사(구조 태그) → ..."
각 항목의 내용은 그 제목 바로 아래 ``` 코드 블록이다.

CAVN 입력 규칙
  가요/팝:  연주곡 끔, 가사 칸 = 가사, 음악 스타일 칸 = (장르 + ) 스타일
  클래식:   연주곡 켬, 음악 스타일 칸 = 스타일 + 줄바꿈 + 구조 태그 (가사 칸 없음)
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

STYLE_MAX_LEN = 1000  # CAVN 음악 스타일 칸 글자 제한

HEADING_RE = re.compile(r"^(#{1,6})\s*(.+?)\s*$", re.M)
TRACK_RE = re.compile(r"^(?:Track|트랙)\s*(\d+)\s*[.:]\s*(.+)$", re.I)
CODE_RE = re.compile(r"```[^\n]*\n(.*?)\n?```", re.S)
COMMON_EXCLUDE_RE = re.compile(r"공통\s*Exclude\s*Styles?\s*:?\**\s*:?\s*`([^`]+)`", re.I)
HANGUL_PAREN_RE = re.compile(r"\s*\([^()]*[가-힣][^()]*\)\s*$")


@dataclass
class Track:
    number: int
    title: str              # CAVN 제목 칸에 넣을 제목 (한글 괄호 설명은 뺌)
    genre: str = ""
    style: str = ""
    exclude: str = ""
    lyrics: str = ""
    classical: bool = False  # True면 연주곡 (가사 칸 = 구조 태그)
    warnings: list = field(default_factory=list)

    def style_box(self, include_genre=True):
        """CAVN '음악 스타일' 칸에 넣을 글."""
        if self.classical:
            return f"{self.style}\n{self.lyrics}".strip()
        parts = [self.genre, self.style] if include_genre else [self.style]
        return ", ".join(p.strip().rstrip(",") for p in parts if p.strip())

    def lyrics_box(self):
        """CAVN '가사' 칸에 넣을 글 (클래식은 없음)."""
        return "" if self.classical else self.lyrics


def _section_key(heading):
    name = re.split(r"→|\(", heading, maxsplit=1)[0].strip()
    if name.startswith("제목"):
        return "title"
    if name.startswith("장르"):
        return "genre"
    if name.startswith("스타일"):
        return "style"
    if name.lower().startswith("exclude"):
        return "exclude"
    if name.startswith("가사"):
        return "structure" if "구조" in heading else "lyrics"
    return None


def _one_line(text):
    """여러 줄로 끊어 쓴 스타일 글을 한 줄로 잇는다."""
    return re.sub(r"\s*\n\s*", " ", text).strip()


def clean_title(title):
    """'You Were Already There (당신은 이미 거기 있었어요)' -> 'You Were Already There'"""
    return HANGUL_PAREN_RE.sub("", title).strip()


def parse_md(text):
    headings = [(m.start(), m.end(), len(m.group(1)), m.group(2)) for m in HEADING_RE.finditer(text)]
    common_exclude = ""
    m = COMMON_EXCLUDE_RE.search(text)
    if m:
        common_exclude = m.group(1).strip()

    tracks = []
    for i, (start, end, level, heading) in enumerate(headings):
        tm = TRACK_RE.match(heading)
        if not tm:
            continue
        # 트랙 범위: 같은 단계 이상의 다음 제목 전까지
        stop = len(text)
        for nstart, _, nlevel, _ in headings[i + 1:]:
            if nlevel <= level:
                stop = nstart
                break
        values = {}
        sub = [h for h in headings[i + 1:] if start < h[0] < stop]
        for j, (sstart, send, _, sheading) in enumerate(sub):
            key = _section_key(sheading)
            if not key or key in values:
                continue
            block_end = sub[j + 1][0] if j + 1 < len(sub) else stop
            cm = CODE_RE.search(text, send, block_end)
            if cm:
                values[key] = cm.group(1).strip()

        classical = "structure" in values
        track = Track(
            number=int(tm.group(1)),
            title=clean_title(values.get("title") or tm.group(2)),
            genre=_one_line(values.get("genre", "")),
            style=_one_line(values.get("style", "")),
            exclude=_one_line(values.get("exclude", common_exclude)),
            lyrics=values.get("structure" if classical else "lyrics", ""),
            classical=classical,
        )
        if not track.style:
            track.warnings.append("스타일 칸이 비어 있음")
        if not track.classical and not track.lyrics:
            track.warnings.append("가사가 비어 있음")
        tracks.append(track)
    return tracks


def parse_md_file(path):
    return parse_md(Path(path).read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    import sys
    for t in parse_md_file(sys.argv[1]):
        kind = "클래식" if t.classical else "가요/팝"
        print(f"[{t.number}] {t.title}  ({kind}, 스타일 {len(t.style_box())}자, 가사 {len(t.lyrics_box())}자)")
        for w in t.warnings:
            print("    !!", w)
