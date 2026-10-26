"""md 파일의 썸네일 문구 + 썸네일 이미지 프롬프트로 유튜브 썸네일 만들기.

1. md 맨 아래(유튜브 SEO)에서 메인(전곡) 1개 + 싱글 썸네일(보통 3개)의 문구와 이미지 프롬프트를 읽는다.
2. 배경 그림: Google Flow 에서 그 프롬프트로 이미지를 만들어 받는다.
   (싱글 프롬프트가 곡 이미지 프롬프트와 같고 그 곡 이미지를 이미 받아 두었으면 그것을 씀 → 크레딧 안 씀)
3. 문구마다 썸네일 한 장:
   - 완성 그림  F:\\음악생성\\<md>\\썸네일\\메인_한글1.jpg  (1920×1080)
   - 캡컷 초안  같은 이름의 초안 (글씨를 캡컷에서 고칠 수 있음)
   큰 한글 문구는 가운데 조금 위 (흰 글씨 + 굵은 검정 테두리),
   영어 문구는 왼쪽 위에 작게 (Times New Roman Bold).

실행:  python thumb_maker.py "앨범.md"            (Flow 로 배경 만들기 + 썸네일)
       python thumb_maker.py "앨범.md" --no-flow  (받아 둔 배경으로 썸네일만 다시)
"""

import argparse
import os
import re
import shutil
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from md_parser import BOLD_LABEL_RE, CODE_RE, HEADING_RE, TRACK_RE, ask_md_path, parse_md

DEFAULT_OUT = r"F:\음악생성"
BG_IMAGES = 4               # 썸네일마다 Flow 에서 만들 배경 그림 수 (고를 수 있게)
WIDTH, HEIGHT = 1920, 1080

# 글꼴: 한글 = 휴먼둥근헤드라인, 영어·숫자 = Times New Roman Bold
FONT_DIRS = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
             Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "Microsoft" / "Windows" / "Fonts",
             Path("/usr/share/fonts")]
KO_FONT_NAMES = ["휴먼둥근헤드라인", "HumanRoundHeadline", "HYHeadLine"]
KO_FONT_FILES = ["HMKMRHD.TTF"]
KO_FALLBACK = ["malgunbd.ttf", "NanumSquareRoundEB.ttf", "NanumSquareRoundB.ttf"]
EN_FONT_FILES = ["timesbd.ttf", "LiberationSerif-Bold.ttf"]

# 글씨 배치 (예시 썸네일에 맞춤, 1920×1080 기준 픽셀)
BIG_MAX_PX = 175            # 큰 문구 글자 크기 (최대)
BIG_MAX_WIDTH = 1780        # 큰 문구 한 줄 최대 폭
BIG_MAX_HEIGHT = 760        # 큰 문구 덩어리 최대 높이 (왼쪽 위 영어와 안 겹치게)
BIG_CENTER_Y = 505          # 큰 문구 덩어리의 세로 가운데 (가운데 조금 위)
BIG_LINE_GAP = 1.22         # 줄 간격 (글자 크기의 배수)
BIG_WORD_GAP = 0.45         # 낱말 사이를 더 띄움 (글자 크기의 배수)
BIG_STROKE = 0.09           # 테두리 두께 (글자 크기의 배수)
SMALL_PX = 50               # 왼쪽 위 영어 글자 크기
SMALL_MARGIN = (40, 28)
CAPCUT_STROKE = 60.0        # 캡컷 '사전 설정 스타일' 첫 번째(흰 글씨 + 검정 테두리), 테두리 두께 60 — 모든 글씨
CAPCUT_PX_PER_SIZE = 12.6   # 캡컷 글자 크기 1 ≈ 12.6px (1080p 화면, 실제 캡컷 화면에서 잰 값)


def log(msg):
    print(msg, flush=True)


def safe_filename(name):
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip().rstrip(".") or "untitled"


def has_hangul(text):
    return bool(re.search(r"[가-힣]", text))


# ---------------------------------------------------------------- md 에서 썸네일 읽기

@dataclass
class Option:
    label: str              # '한글1', '1안', '메인문구' …
    lines: list             # 썸네일에 쓸 줄들


@dataclass
class Thumb:
    name: str               # '메인', '싱글1' …
    title: str = ""         # 싱글이면 곡 제목
    prompt: str = ""        # 배경 이미지 프롬프트
    options: list = field(default_factory=list)   # 한글 문구들 (한 개 = 썸네일 한 장)
    english: list = field(default_factory=list)   # 왼쪽 위 영어 문구 (줄들)


SINGLE_RE = re.compile(r"^Single\s*(\d+)\s*[.:]\s*(.+)$", re.I)
KV_RE = re.compile(r"^\s*\[?([^:\]\[]{1,14}?)\]?\s*:\s*(.+)$")
MAIN_SUB_RE = re.compile(r"^(메인|서브|main|sub)$", re.I)
GROUP_RE = re.compile(r"^\s*\[([^\]]{1,20})\]\s*$")


def _split_lines(value):
    return [p.strip() for p in re.split(r"\s+/\s+", value) if p.strip()]


def parse_options(block, label=""):
    """썸네일 문구 코드 블록 하나 → Option 목록.
    '한글 1: A / B' (줄마다 한 안), '메인: A' + '서브: B' (두 줄이 한 안), '[1안]' 묶음, 그냥 두 줄 모두 읽는다."""
    groups, cur_label, cur = [], label, []
    for raw in block.splitlines():
        line = raw.strip()
        if not line:
            continue
        g = GROUP_RE.match(line)
        if g:
            if cur:
                groups.append((cur_label, cur))
            cur_label, cur = g.group(1).strip(), []
            continue
        cur.append(line)
    if cur:
        groups.append((cur_label, cur))

    options = []
    for glabel, lines in groups:
        kv = [KV_RE.match(line) for line in lines]
        if all(kv) and all(MAIN_SUB_RE.match(m.group(1).strip()) for m in kv):
            options.append(Option(glabel, [m.group(2).strip() for m in kv]))      # 메인 + 서브 = 한 안
        elif all(kv):
            for m in kv:                                                         # '한글 1: A / B' = 줄마다 한 안
                options.append(Option(m.group(1).strip(), _split_lines(m.group(2))))
        else:
            out = []
            for line in lines:
                m = KV_RE.match(line)
                out += _split_lines(m.group(2) if m else line)
            options.append(Option(glabel, out))
    return [o for o in options if o.lines]


def _sections(text):
    """(시작, 끝, 단계, 제목) 목록. '**굵은 글씨**' 항목은 7단계."""
    heads = [(m.start(), m.end(), len(m.group(1)), m.group(2)) for m in HEADING_RE.finditer(text)]
    heads += [(m.start(), m.end(), 7, m.group(1).strip()) for m in BOLD_LABEL_RE.finditer(text)]
    # 코드 블록 안의 '#해시태그' 줄은 제목이 아님
    spans = [(m.start(), m.end()) for m in CODE_RE.finditer(text)]
    heads = [h for h in heads if not any(a <= h[0] < b for a, b in spans)]
    heads.sort()
    return heads


def parse_thumbnails(text):
    """md 글 → [Thumb(메인), Thumb(싱글1), …]. 곡(트랙)마다 있는 썸네일 문구는 쓰지 않는다."""
    heads = _sections(text)
    thumbs = {"메인": Thumb("메인")}
    order = ["메인"]
    owner = "메인"          # 지금 읽는 부분이 누구 것인지 (트랙 안이면 None)
    owner_level = 0
    for i, (start, end, level, heading) in enumerate(heads):
        title = heading.strip().strip("*").strip()
        name_part = re.split(r"\(|→", title)[0]   # '썸네일 이미지 생성 프롬프트 (…문구는 별도로…)' → 앞부분만
        if level <= owner_level:   # 트랙·싱글 부분이 끝남
            owner, owner_level = "메인", 0
        if TRACK_RE.match(title) or re.match(r"^Track\s*\d+", title, re.I):
            owner, owner_level = None, level
            continue
        sm = SINGLE_RE.match(title)
        if sm:
            name = f"싱글{sm.group(1)}"
            if name not in thumbs:
                thumbs[name] = Thumb(name, title=re.sub(r"\s*\(.*\)\s*$", "", sm.group(2)).strip())
                order.append(name)
            owner, owner_level = name, level
            continue
        if owner is None:
            continue
        stop = heads[i + 1][0] if i + 1 < len(heads) else len(text)
        body = text[end:stop]
        thumb = thumbs[owner]
        if "썸네일" in name_part and "문구" in name_part:
            for cm in CODE_RE.finditer(body):
                # 코드 블록 바로 위 글줄을 이름표로 ('한글 버전 1 (메인+서브)' → '한글 버전 1')
                before = body[:cm.start()].rstrip().splitlines()
                label = re.sub(r"\s*\(.*$", "", before[-1]).strip() if before and not before[-1].strip().startswith("```") else ""
                for opt in parse_options(cm.group(1), label):
                    text_all = " ".join(opt.lines)
                    if has_hangul(text_all):
                        thumb.options.append(opt)
                    elif not thumb.english:
                        thumb.english = opt.lines
        elif not thumb.prompt and (("썸네일" in name_part and "이미지" in name_part)
                                   or re.match(r"^대표 이미지", name_part)):
            cm = CODE_RE.search(body)
            if cm:
                # '[1 눈 덮인 마을] …' 처럼 여러 안이 한 블록에 있으면 첫 번째 것만
                first = re.split(r"\n\s*\n|\n(?=\s*\[)", cm.group(1).strip())[0]
                thumb.prompt = re.sub(r"^\s*\[[^\]]*\]\s*", "", re.sub(r"\s*\n\s*", " ", first)).strip()

    result = [thumbs[n] for n in order if thumbs[n].options]
    for t in result:
        labels = {}
        for k, o in enumerate(t.options, 1):
            base = safe_filename(re.sub(r"\s+", "", o.label)) if o.label else "문구"
            labels[base] = labels.get(base, 0) + 1
            o.label = base if labels[base] == 1 else f"{base}_{labels[base]}"
        if not t.english and result[0].english:
            t.english = result[0].english
    return result


# ---------------------------------------------------------------- 글꼴 찾기

def _font_names(path):
    """TTF/OTF/TTC 파일의 글꼴 이름들 (name 표)."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return []
    offsets = [0]
    if data[:4] == b"ttcf":
        n = struct.unpack(">I", data[8:12])[0]
        offsets = list(struct.unpack(f">{n}I", data[12:12 + 4 * n]))
    names = []
    for off in offsets:
        try:
            num = struct.unpack(">H", data[off + 4:off + 6])[0]
            for k in range(num):
                tag, _, toff, _ = struct.unpack(">4sIII", data[off + 12 + 16 * k:off + 28 + 16 * k])
                if tag != b"name":
                    continue
                _, count, soff = struct.unpack(">HHH", data[toff:toff + 6])
                for r in range(count):
                    pid, _, _, nid, length, noff = struct.unpack(">HHHHHH", data[toff + 6 + 12 * r:toff + 18 + 12 * r])
                    if nid not in (1, 4):
                        continue
                    raw = data[toff + soff + noff:toff + soff + noff + length]
                    names.append(raw.decode("utf-16-be" if pid in (0, 3) else "latin-1", "ignore"))
        except struct.error:
            continue
    return names


def _font_files():
    for d in FONT_DIRS:
        if d.is_dir():
            yield from (p for p in d.rglob("*") if p.suffix.lower() in (".ttf", ".otf", ".ttc"))


def find_font(files, names=(), fallback=()):
    files_l = {f.lower() for f in files}
    all_files = list(_font_files())
    for p in all_files:
        if p.name.lower() in files_l:
            return p
    if names:
        want = [n.replace(" ", "").lower() for n in names]
        for p in all_files:
            if any(w in n.replace(" ", "").lower() for n in _font_names(p) for w in want):
                return p
    fb = {f.lower() for f in fallback}
    for p in all_files:
        if p.name.lower() in fb:
            log(f"  (글꼴 '{names[0] if names else files[0]}' 이 없어서 '{p.name}' 로 대신합니다)")
            return p
    return None


@dataclass
class Fonts:
    ko: Path
    en: Path


def load_fonts():
    ko = find_font(KO_FONT_FILES, KO_FONT_NAMES, KO_FALLBACK)
    en = find_font(EN_FONT_FILES, ("Times New Roman Bold",), ())
    if not ko or not en:
        raise SystemExit("!! 글꼴을 찾지 못했습니다: " + ("휴먼둥근헤드라인 " if not ko else "") + ("Times New Roman Bold" if not en else ""))
    log(f"글꼴: 한글 {ko.name}, 영어 {en.name}")
    return Fonts(ko, en)


def runs(text):
    """글을 한글 부분 / 그 밖(영어·숫자·기호) 부분으로 나눈다. [(글, 한글인가)]"""
    out = []
    for ch in text:
        if out and not re.match(r"[가-힣ㄱ-ㅎㅏ-ㅣA-Za-z0-9À-ɏ]", ch):
            out[-1][0] += ch          # 띄어쓰기·문장부호(·, ', 등)는 앞 글자 글꼴을 따름
            continue
        ko = bool(re.match(r"[가-힣ㄱ-ㅎㅏ-ㅣ]", ch))
        if out and out[-1][1] == ko:
            out[-1][0] += ch
        else:
            out.append([ch, ko])
    return [(t, k) for t, k in out]


# ---------------------------------------------------------------- 완성 그림 (jpg)

def cover(img, w=WIDTH, h=HEIGHT):
    """화면을 꽉 채우게 키우고 가운데를 잘라낸다."""
    scale = max(w / img.width, h / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    left, top = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


def _measure(text, px, fonts, word_gap=0.0):
    fk = ImageFont.truetype(str(fonts.ko), px)
    fe = ImageFont.truetype(str(fonts.en), px)
    width = 0
    for t, ko in runs(text):
        width += (fk if ko else fe).getlength(t) + t.count(" ") * px * word_gap
    return width, fk, fe


def _draw_line(draw, x, y, text, px, fonts, stroke, word_gap=0.0):
    _, fk, fe = _measure(text, px, fonts, word_gap)
    for t, ko in runs(text):
        for k, word in enumerate(t.split(" ")):
            if k:
                x += (fk if ko else fe).getlength(" ") + px * word_gap
            if word:
                f = fk if ko else fe
                draw.text((x, y), word, font=f, fill="white", stroke_width=stroke, stroke_fill="black", anchor="ls")
                x += f.getlength(word)


def _fit_px(line, fonts, max_px=BIG_MAX_PX):
    """그 줄이 한 줄 폭에 들어가는 가장 큰 글자 크기와 그때의 폭."""
    px = max_px
    while True:
        w = _measure(line, px, fonts, BIG_WORD_GAP)[0] + 2 * px * BIG_STROKE
        if w <= BIG_MAX_WIDTH or px <= 40:
            return px, w
        px -= 5


def big_layout(lines, fonts):
    """큰 문구를 [(줄, 글자 크기, 폭, 기준선 y)] 로 배치한다.
    줄마다 화면 폭에 맞춰 최대한 크게. 너무 긴 줄(작아질 줄)은 가운데 띄어쓰기에서 두 줄로 나눈다."""
    out_lines = []
    for line in lines:
        px, _ = _fit_px(line, fonts)
        words = line.split(" ")
        cut = None
        if px < BIG_MAX_PX * 0.72 and len(words) >= 2:
            half = len(line) / 2
            cut = min(range(1, len(words)), key=lambda k: abs(len(" ".join(words[:k])) - half))
            short = min(len(" ".join(words[:cut])), len(" ".join(words[cut:])))
            if short < len(line) * 0.3:   # '16곡' 처럼 한쪽이 너무 짧게 남으면 나누지 않음
                cut = None
        if cut:
            out_lines += [" ".join(words[:cut]), " ".join(words[cut:])]
        else:
            out_lines.append(line)
    max_px = BIG_MAX_PX
    while True:
        sized = [(line, *_fit_px(line, fonts, max_px)) for line in out_lines]
        # 첫 줄 가운데 ~ 마지막 줄 가운데 거리 → 덩어리 전체의 가운데를 BIG_CENTER_Y 에
        total = sum((sized[k - 1][1] + sized[k][1]) / 2 * BIG_LINE_GAP for k in range(1, len(sized)))
        height = total + (sized[0][1] + sized[-1][1]) / 2
        if height <= BIG_MAX_HEIGHT or max_px <= 60:
            break
        max_px -= 5   # 줄이 많아 위쪽 영어 문구와 겹치면 전체를 조금씩 줄임
    y = BIG_CENTER_Y - total / 2
    result = []
    for k, (line, px, w) in enumerate(sized):
        if k:
            y += (sized[k - 1][1] + px) / 2 * BIG_LINE_GAP
        result.append((line, px, w, y + px * 0.36))   # 기준선은 글자 가운데에서 0.36em 아래 쯤
    return result


def render_jpg(bg_path, option, english, fonts, out_path):
    img = cover(Image.open(bg_path).convert("RGB"))
    draw = ImageDraw.Draw(img)
    for line, px, w, base in big_layout(option.lines, fonts):
        stroke = max(4, round(px * BIG_STROKE))
        _draw_line(draw, (WIDTH - w) / 2 + stroke, base, line, px, fonts, stroke, BIG_WORD_GAP)
    x, y = SMALL_MARGIN
    for line in english:
        _draw_line(draw, x, y + SMALL_PX * 0.85, line, SMALL_PX, fonts, max(3, round(SMALL_PX * BIG_STROKE)))
        y += SMALL_PX * 1.15
    out_path.parent.mkdir(parents=True, exist_ok=True)
    quality = 92
    while True:   # 유튜브 썸네일은 2MB 이하
        img.save(out_path, "JPEG", quality=quality)
        if out_path.stat().st_size <= 2 * 1024 * 1024 or quality <= 60:
            break
        quality -= 8
    return out_path


# ---------------------------------------------------------------- 캡컷 초안 (글씨를 고칠 수 있게)

def _capcut():
    try:
        import pycapcut
        return pycapcut
    except ImportError:
        import subprocess
        log("  (캡컷 초안용 pycapcut 을 설치합니다)")
        subprocess.call([sys.executable, "-m", "pip", "install", "-q", "pycapcut"])
        import pycapcut
        return pycapcut


def _text_segment(cc, text, timerange, size, fonts, border_width, transform, align):
    """한글·영어 부분마다 글꼴을 달리 넣은 캡컷 글 상자."""
    seg = cc.TextSegment(text, timerange,
                         style=cc.TextStyle(size=size, color=(1.0, 1.0, 1.0), align=align,
                                            auto_wrapping=False, max_line_width=1.0),
                         border=cc.TextBorder(color=(0.0, 0.0, 0.0), width=border_width),
                         clip_settings=cc.ClipSettings(transform_x=transform[0], transform_y=transform[1]))
    original = seg.export_material

    def export_material():
        import json
        mat = original()
        content = json.loads(mat["content"])
        base = content["styles"][0]
        styles, pos = [], 0
        for t, ko in runs(text):
            style = json.loads(json.dumps(base))
            style["range"] = [pos, pos + len(t)]
            style["font"] = {"id": "", "path": str(fonts.ko if ko else fonts.en)}
            styles.append(style)
            pos += len(t)
        content["styles"] = styles
        mat["content"] = json.dumps(content, ensure_ascii=False)
        main_font = fonts.ko if has_hangul(text) else fonts.en
        mat.update({"font_path": str(main_font), "font_name": main_font.stem,
                    "font_id": "", "font_resource_id": "", "fonts": []})
        return mat

    seg.export_material = export_material
    return seg


def build_capcut(draft_dir, name, bg_path, option, english, fonts):
    cc = _capcut()
    from pycapcut import trange
    Path(draft_dir).mkdir(parents=True, exist_ok=True)
    folder = cc.DraftFolder(str(draft_dir))
    script = folder.create_draft(name, WIDTH, HEIGHT, fps=30, allow_replace=True)
    script.add_track(cc.TrackType.video, "배경")
    length = trange(0, 5_000_000)   # 5초짜리 한 장면
    script.add_segment(cc.VideoSegment(cc.VideoMaterial(str(bg_path)), length), "배경")

    # 줄마다 글 상자 하나 (같은 시간에 겹치므로 줄마다 트랙 하나)
    for k, (line, px, _, base) in enumerate(big_layout(option.lines, fonts), 1):
        center_y = base - px * 0.36
        script.add_track(cc.TrackType.text, f"큰 문구 {k}")
        script.add_segment(_text_segment(cc, line, length, px / CAPCUT_PX_PER_SIZE, fonts, CAPCUT_STROKE,
                                         (0.0, (HEIGHT / 2 - center_y) / (HEIGHT / 2)), 1), f"큰 문구 {k}")
    x, y = SMALL_MARGIN
    for k, line in enumerate(english, 1):
        script.add_track(cc.TrackType.text, f"영어 {k}")
        w = _measure(line, SMALL_PX, fonts)[0]
        cx, cy = x + w / 2, y + SMALL_PX * 0.55
        script.add_segment(_text_segment(cc, line, length, SMALL_PX / CAPCUT_PX_PER_SIZE, fonts, CAPCUT_STROKE,
                                         ((cx - WIDTH / 2) / (WIDTH / 2), (HEIGHT / 2 - cy) / (HEIGHT / 2)), 0), f"영어 {k}")
        y += SMALL_PX * 1.15
    script.save()


# ---------------------------------------------------------------- 배경 그림

def _norm(text):
    return re.sub(r"\W+", " ", text or "").strip().lower()


def backgrounds(folder):
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))


def reuse_track_images(thumb, tracks, album_dir, bg_dir):
    """싱글 프롬프트가 그 곡 이미지 프롬프트와 같고 곡 이미지를 이미 받아 두었으면 그것을 배경으로 복사."""
    want = _norm(thumb.prompt)
    for t in tracks:
        if want and _norm(t.image_prompt) == want:
            src = backgrounds(album_dir / "이미지" / f"{t.number}번")
            if src:
                bg_dir.mkdir(parents=True, exist_ok=True)
                for p in src[:BG_IMAGES]:
                    shutil.copy2(p, bg_dir / p.name)
                log(f"  {t.number}번 곡 이미지와 프롬프트가 같아서 그 이미지를 씁니다 (크레딧 안 씀)")
                return True
    return False


# ---------------------------------------------------------------- 실행

def run(md_path, out_root, use_flow=True, capcut_dir=None, page=None, confirm=True, n_images=BG_IMAGES):
    md_path = Path(md_path)
    text = md_path.read_text(encoding="utf-8-sig")
    thumbs = parse_thumbnails(text)
    tracks = parse_md(text)
    album_dir = Path(out_root) / safe_filename(md_path.stem)
    out_dir = album_dir / "썸네일"
    # 캡컷 초안도 썸네일 폴더 안에 (음악·이미지와 같은 F:\음악생성\<md>\ 아래에서 관리)
    capcut_dir = Path(capcut_dir) if capcut_dir else out_dir / "CapCut Drafts"

    print(f"\nmd 파일 : {md_path.name}\n썸네일  : {out_dir}\n캡컷 초안: {capcut_dir}\n")
    if not thumbs:
        print("이 md 파일에서 썸네일 문구를 찾지 못했습니다.")
        return []
    todo_bg = []
    for t in thumbs:
        bg_dir = out_dir / "배경" / t.name
        have = len(backgrounds(bg_dir))
        print(f"  [{t.name}] {t.title}  배경 {'있음' if have else '만들 것'}" + ("" if t.prompt else "  !! 이미지 프롬프트 없음"))
        for o in t.options:
            print(f"      {o.label}: {' / '.join(o.lines)}")
        if t.english:
            print(f"      (왼쪽 위) {' / '.join(t.english)}")
        if not have and t.prompt:
            todo_bg.append(t)
    if confirm and input("\n시작할까요? (y/n): ").strip().lower() not in ("y", "yes", "ㅛ"):
        return []

    # 1. 배경 그림
    need_flow = [t for t in todo_bg if not reuse_track_images(t, tracks, album_dir, out_dir / "배경" / t.name)]
    if need_flow and use_flow:
        import flow_maker

        def work(pg):
            flow = flow_maker.Flow(pg)
            for t in need_flow:
                log(f"[배경] {t.name} {t.title}")
                try:
                    images = flow_maker.request_images(flow, t.prompt, n_images)
                    flow_maker.collect_images(flow, images, out_dir / "배경" / t.name)
                except Exception as e:   # 하나가 실패해도 다음 것은 계속
                    log(f"  !! 실패: {e}")
                    try:
                        pg.keyboard.press("Escape")
                    except Exception:
                        pass

        if page is not None:
            work(page)
        else:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                work(flow_maker.connect(pw))

    # 2. 썸네일 (jpg + 캡컷 초안)
    fonts = load_fonts()
    made = []
    album = md_path.stem
    for t in thumbs:
        bgs = backgrounds(out_dir / "배경" / t.name)
        if not bgs:
            log(f"!! [{t.name}] 배경 그림이 없어서 건너뜁니다")
            continue
        for o in t.options:
            name = f"{t.name}_{o.label}"
            jpg = render_jpg(bgs[0], o, t.english, fonts, out_dir / f"{name}.jpg")
            made.append(jpg)
            try:
                build_capcut(capcut_dir, f"{album} 썸네일 {name}", bgs[0], o, t.english, fonts)
                log(f"  {jpg.name}  + 캡컷 초안 '{album} 썸네일 {name}'")
            except Exception as e:
                log(f"  {jpg.name}  (!! 캡컷 초안 실패: {e})")
    log(f"끝. 썸네일 {len(made)}장 → {out_dir}")
    return made


def main():
    ap = argparse.ArgumentParser(description="md 썸네일 문구로 유튜브 썸네일 만들기 (Flow 배경 + 캡컷 초안)")
    ap.add_argument("md", nargs="?", help="음악 md 파일 (없으면 실행할 때 물어봄)")
    ap.add_argument("--out", default=DEFAULT_OUT, help=f"저장 폴더 (기본 {DEFAULT_OUT})")
    ap.add_argument("--no-flow", action="store_true", help="Flow 로 배경을 만들지 않음 (받아 둔 배경만 씀)")
    ap.add_argument("--images", type=int, default=BG_IMAGES, help=f"썸네일마다 배경 그림 수 (기본 {BG_IMAGES})")
    ap.add_argument("--capcut", help="캡컷 초안 저장 폴더 (기본: 썸네일\\CapCut Drafts)")
    args = ap.parse_args()
    md = ask_md_path(args.md)
    run(md, args.out, use_flow=not args.no_flow, capcut_dir=args.capcut, n_images=args.images)


if __name__ == "__main__":
    main()
