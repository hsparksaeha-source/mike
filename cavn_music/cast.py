"""가요·칸쏘네 이미지의 주인공 캐릭터 고르기.

캐릭터목록.txt (이 폴더) 에 Flow 캐릭터 이름을 묶음별로 적어 둔다.
  프로젝트: 캐릭터목록
  [칸쏘네]
  여: 쥴리, 안나
  남: 마태오, 브루노
[인물 설명] 칸에 '이름: 설명' 을 적어 두면 (예: 쥴리: 키 185cm 의 큰 키)
이미지·영상 요청 글에 붙여서 Flow 가 꼭 그대로 그리게 한다.
곡마다 주인공은
  1) md 의 '## 주인공 캐릭터' 칸
  2) 없으면 곡의 남·여 가수 표시 (여성 → 첫 여자, 남성 → 첫 남자, 둘 다/모름 → 첫 여자 + 첫 남자)
실행할 때 곡마다 '여' / '남' / '둘' 이나 이름(띄어 쓰기)으로 바꿀 수 있다.
"""

import re
from pathlib import Path

CAST_FILE = Path(__file__).resolve().parent / "캐릭터목록.txt"
DEFAULT_PROJECT = "캐릭터목록"
TRAITS_SECTION = re.compile(r"^(인물\s*설명|설명|키)$")


def load_cast(path=None):
    """(Flow 프로젝트 이름, {묶음: {'여': [...], '남': [...]}})"""
    path = path or CAST_FILE
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
            if TRAITS_SECTION.match(cur):   # [인물 설명] 은 묶음이 아님
                cur = None
                continue
            groups[cur] = {"여": [], "남": []}
            continue
        m = re.match(r"^(여|남)\s*[:：]\s*(.*)$", line)
        if m and cur:
            groups[cur][m.group(1)] += [n.strip() for n in re.split(r"[,，、]", m.group(2)) if n.strip()]
    return project, groups


def load_traits(path=None):
    """[인물 설명] 칸 → {이름: 설명}. 예) 쥴리: 키 185cm 의 큰 키"""
    path = path or CAST_FILE
    traits, inside = {}, False
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError:
        return traits
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^\[(.+)\]$", line)
        if m:
            inside = bool(TRAITS_SECTION.match(m.group(1).strip()))
            continue
        m = re.match(r"^([^:：]+?)\s*[:：]\s*(.+)$", line)
        if inside and m:
            traits[m.group(1).strip()] = m.group(2).strip()
    return traits


def _topic(name):
    """'쥴리' → '쥴리는', '서준' → '서준은'."""
    last = name[-1]
    batchim = "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 != 0
    return name + ("은" if batchim else "는")


def traits_text(names, traits=None, what="이미지"):
    """주인공들의 [인물 설명] → 요청 글에 붙일 문장. 설명이 없으면 ''.
    Flow 캐릭터 설명만으로는 키를 무시할 때가 많아서, 사용자가 직접 쓰던 말 그대로 프롬프트에 넣는다:
    '안나 키 185센티미터의 큰 키, 브루노 키 195센티미터의 큰 키, 이 키를 그대로 반영해서 가사에 맞게 이미지 15장 만들어 주세요.'"""
    traits = load_traits() if traits is None else traits
    parts = [f"{n} {traits[n]}" for n in names if traits.get(n)]
    if not parts:
        return ""
    last = what[-1]
    obj = "을" if "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 != 0 else "를"
    if re.search(r"\d+장$", what):   # '이미지 15장 만들어 주세요' (사용자가 쓰던 말 그대로)
        return ", ".join(parts) + f", 이 키를 그대로 반영해서 가사에 맞게 {what} 만들어 주세요."
    return ", ".join(parts) + f", 이 키를 그대로 반영해서 가사에 맞게 {what}{obj} 만들어 주세요."


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
    # 철자가 조금 달라도(줄리 → 쥴리) 목록에서 하나로 정해지면 그 이름으로 본다
    import difflib
    fixed = []
    for n in names:
        if n in known:
            fixed.append(n)
            continue
        close = [k for k in known if _similar(n, k)] or difflib.get_close_matches(n, known, n=2, cutoff=0.5)
        fixed.append(close[0] if len(close) == 1 else n)
    names = fixed
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


def _jamo(text):
    """한글을 자모로 풀되, 헷갈리기 쉬운 모음은 같은 것으로 (ㅠ·ㅜ, ㅕ·ㅓ, ㅛ·ㅗ, ㅑ·ㅏ, ㅖ·ㅔ·ㅐ·ㅒ)."""
    same = {"ㅠ": "ㅜ", "ㅕ": "ㅓ", "ㅛ": "ㅗ", "ㅑ": "ㅏ", "ㅖ": "ㅔ", "ㅐ": "ㅔ", "ㅒ": "ㅔ"}
    vowels = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
    out = []
    for ch in text:
        code = ord(ch) - 0xAC00
        if 0 <= code < 11172:
            out.append(str(code // 588))
            v = vowels[(code % 588) // 28]
            out.append(same.get(v, v))
            out.append(str(code % 28))
        else:
            out.append(ch)
    return "".join(out)


def _similar(a, b):
    return len(a) == len(b) and _jamo(a) == _jamo(b)
