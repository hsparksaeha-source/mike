"""가요·칸쏘네 이미지의 주인공 캐릭터 고르기.

캐릭터목록.txt (이 폴더) 에 Flow 캐릭터 이름을 묶음별로 적어 둔다.
  프로젝트: 캐릭터목록
  [칸쏘네]
  여: 쥴리, 안나
  남: 마태오, 브루노
곡마다 주인공은
  1) md 의 '## 주인공 캐릭터' 칸
  2) 없으면 곡의 남·여 가수 표시 (여성 → 첫 여자, 남성 → 첫 남자, 둘 다/모름 → 첫 여자 + 첫 남자)
실행할 때 곡마다 '여' / '남' / '둘' 이나 이름(띄어 쓰기)으로 바꿀 수 있다.
"""

import re
from pathlib import Path

CAST_FILE = Path(__file__).resolve().parent / "캐릭터목록.txt"
DEFAULT_PROJECT = "캐릭터목록"


def load_cast(path=CAST_FILE):
    """(Flow 프로젝트 이름, {묶음: {'여': [...], '남': [...]}})"""
    project, groups, cur = DEFAULT_PROJECT, {}, None
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError:
        return project, groups
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^프로젝트\s*[:：]\s*(.+)$", line)
        if m:
            project = m.group(1).strip()
            continue
        m = re.match(r"^\[(.+)\]$", line)
        if m:
            cur = m.group(1).strip()
            groups[cur] = {"여": [], "남": []}
            continue
        m = re.match(r"^(여|남)\s*[:：]\s*(.*)$", line)
        if m and cur:
            groups[cur][m.group(1)] += [n.strip() for n in re.split(r"[,，、]", m.group(2)) if n.strip()]
    return project, groups


def lead_kind(track):
    """곡의 가수 표시로 '여' / '남' / '둘'."""
    text = f"{track.genre} {track.style}".lower()
    female = re.search(r"female|woman|women|soprano|mezzo|여성|여자", text)
    male = re.search(r"(?<!fe)\bmale\b|\bman\b|\bmen\b|baritone|tenor|crooner|남성|남자", text)
    if female and male or re.search(r"duet|듀엣", text):
        return "둘"
    return "여" if female else "남" if male else "둘"


def names_for(kind, group):
    f, m = group["여"][:1], group["남"][:1]
    return {"여": f or m, "남": m or f, "둘": f + m}[kind]


def default_names(track, group):
    if getattr(track, "cast", ""):
        try:
            return parse_names(track.cast, group)
        except ValueError:
            pass
    return names_for(lead_kind(track), group)


def parse_names(text, group):
    """'여' / '남' / '둘' 또는 '쥴리 마태오', '쥴리와 마태오' → 이름 목록. 목록에 없는 이름이면 ValueError."""
    text = text.strip()
    if text in ("여", "남", "둘"):
        return names_for(text, group)
    known = group["여"] + group["남"]
    names = [n for n in re.split(r"[\s,，、/+]+|(?<=\S)(?:와|과)(?=\s|$)", text) if n]
    names = [re.sub(r"(와|과)$", "", n) if n not in known else n for n in names]
    bad = [n for n in names if n not in known]
    if bad or not names:
        raise ValueError(f"캐릭터목록에 없는 이름: {', '.join(bad) or text}")
    return names


def join_names(names):
    """['쥴리', '마태오'] → '쥴리와 마태오' (받침이 있으면 '과')."""
    out = names[0]
    for n in names[1:]:
        last = out[-1]
        batchim = "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 != 0
        out += ("과 " if batchim else "와 ") + n
    return out


def ask_group(groups):
    names = list(groups)
    print("\n이 앨범에 쓸 캐릭터 묶음을 고르세요 (캐릭터목록.txt):")
    for i, g in enumerate(names, 1):
        print(f"  {i} = {g}  (여: {', '.join(groups[g]['여'])} / 남: {', '.join(groups[g]['남'])})")
    while True:
        ans = input("번호: ").strip()
        if ans.isdigit() and 1 <= int(ans) <= len(names):
            return names[int(ans) - 1]
        if ans in groups:
            return ans


def ask_cast(tracks, group):
    """곡마다 주인공을 묻는다. Enter = 기본값."""
    print("\n곡마다 주인공을 정하세요.  여 / 남 / 둘  또는 이름 (예: 쥴리 마태오).  Enter = [ ] 안의 기본값")
    cast = {}
    for t in tracks:
        default = default_names(t, group)
        while True:
            ans = input(f"  {t.number:>2}. {t.title}  [{' '.join(default)}]: ").strip()
            if not ans:
                cast[t.number] = default
                break
            try:
                cast[t.number] = parse_names(ans, group)
                break
            except ValueError as e:
                print(f"    !! {e}")
    return cast
