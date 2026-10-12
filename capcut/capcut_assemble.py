"""
캡컷 초안 자동 조립 프로그램

노래 파일 + 가사 자막(.srt 또는 .lrc) + 이미지 폴더를 주면,
캡컷에서 바로 열리는 초안(draft)을 자동으로 만들어줍니다.
(오디오 트랙 + 이미지 트랙(자막 바뀌는 시점에 맞춰 전환) + 자막 트랙)
그 다음 세부 편집은 캡컷에서 직접 하시면 됩니다.

사용법:
  python capcut_assemble.py <노래파일> <자막.srt 또는 .lrc> <이미지폴더> <프로젝트이름> <CapCut_Drafts_폴더>

<CapCut_Drafts_폴더> 예시:
  "C:\\Users\\lg\\Documents\\Claude Newage Music Channel\\Newage Flute & Bassoon\\CapCut Drafts"
  (그 곡 프로젝트 폴더 안의 "CapCut Drafts" 폴더 경로. 캡컷에서 그 프로젝트를 열 때
   쓰던 초안 저장 위치와 동일해야 캡컷에서 바로 보입니다.)
"""

import os
import re
import sys

import pycapcut as cc
from pycapcut import trange

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")

TIME_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)


def parse_srt(path):
    with open(path, encoding="utf-8-sig") as f:
        content = f.read()

    blocks = re.split(r"\n\s*\n", content.strip())
    captions = []
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 2:
            continue
        match = None
        text_start = None
        for i, line in enumerate(lines):
            match = TIME_RE.search(line)
            if match:
                text_start = i + 1
                break
        if not match:
            continue
        h1, m1, s1, ms1, h2, m2, s2, ms2 = map(int, match.groups())
        start = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000
        end = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000
        text = "\n".join(lines[text_start:]).strip()
        if text:
            captions.append((start, end - start, text))
    return captions


LRC_TIME_RE = re.compile(r"\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\]")
HANGUL_RE = re.compile(r"[가-힣]")


def _is_korean(text):
    return bool(HANGUL_RE.search(text))


def parse_lrc_tracks(path, total_sec):
    """LRC 가사 파일을 읽는다. 같은 타임코드에 여러 줄(예: 한국어+영어 번역)이 있으면
    합치지 않고, 줄마다 원래 그대로 각각 별도 트랙으로 나눠 반환한다 (겹침 없이,
    각 줄이 독립된 자막으로 남아 나중에 캡컷에서 개별 수정 가능).
    반환값: [(트랙이름, [(시작초,길이초,텍스트), ...]), ...]"""
    with open(path, encoding="utf-8-sig") as f:
        lines = f.readlines()

    raw = []  # (start_sec, text)
    for line in lines:
        matches = list(LRC_TIME_RE.finditer(line))
        if not matches:
            continue
        text = LRC_TIME_RE.sub("", line).strip()
        if not text:
            continue
        for m in matches:
            mm, ss, frac = m.group(1), m.group(2), m.group(3)
            frac_val = 0.0
            if frac:
                frac_val = int(frac) / (10 ** len(frac))
            start = int(mm) * 60 + int(ss) + frac_val
            raw.append((start, text))

    raw.sort(key=lambda t: t[0])

    # 같은 타임코드 줄들을 그룹으로 묶는다 (합치지 않고, 등장 순서만 기억)
    groups = []
    for start, text in raw:
        if groups and abs(groups[-1][0][0] - start) < 0.001:
            groups[-1].append((start, text))
        else:
            groups.append([(start, text)])

    max_lines = max((len(g) for g in groups), default=0)
    tracks_raw = [[] for _ in range(max_lines)]
    for g in groups:
        for idx, (start, text) in enumerate(g):
            tracks_raw[idx].append((start, text))

    tracks = []
    for track_raw in tracks_raw:
        if not track_raw:
            continue
        caps = []
        for i, (start, text) in enumerate(track_raw):
            end = track_raw[i + 1][0] if i + 1 < len(track_raw) else total_sec
            dur = end - start
            if dur > 0:
                caps.append((start, dur, text))
        if caps:
            is_ko = _is_korean(caps[0][2])
            name = "자막-한글" if is_ko else "자막-영어"
            tracks.append((name, is_ko, caps))
    return tracks


def parse_captions_tracks(path, total_sec):
    """확장자에 따라 .srt 또는 .lrc 가사 파일을 파싱해서 트랙 목록으로 반환한다.
    반환값: [(트랙이름, is_korean, [(시작초,길이초,텍스트), ...]), ...]"""
    if path.lower().endswith(".lrc"):
        return parse_lrc_tracks(path, total_sec)
    return [("자막", True, parse_srt(path))]


def load_images(folder):
    files = [
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if f.lower().endswith(IMAGE_EXTS)
    ]
    files.sort()
    return files


def build_image_slots(captions_us, total_us):
    """자막 구간(및 자막 사이 빈 구간)마다 하나씩, [시작,길이] 슬롯 목록을 만든다.
    -> 이미지가 자막 바뀌는 시점에 맞춰 같이 바뀌게 된다."""
    slots = []
    pos = 0
    for start_us, dur_us, _text in captions_us:
        if start_us > pos:
            slots.append((pos, start_us - pos))  # 자막 시작 전 빈 구간
        slots.append((start_us, dur_us))  # 자막 구간 자체
        pos = start_us + dur_us
    if pos < total_us:
        slots.append((pos, total_us - pos))  # 마지막 자막 이후 남는 구간
    if not slots:
        slots = [(0, total_us)]
    return slots


def add_song_to_script(script, song_path, srt_path, images_dir, cursor=0, images=None, text_tracks_created=None):
    """이미 만들어진 script(오디오/이미지 트랙이 있어야 함)에 노래 1곡 분량을
    cursor 시각부터 이어붙인다. 다음 곡을 위한 새 cursor(끝난 시각, 마이크로초)를 반환한다.
    이미지는 자막이 바뀌는 시점에 맞춰 같이 바뀐다. 자막은 (한국어 줄 + 영어 줄처럼) 같은
    타임코드에 여러 줄이 있으면 합치지 않고 각각 별도 트랙에 넣어 나중에 개별 수정이 가능하다.
    images를 직접 넘기면 images_dir 스캔 대신 그 목록을 그대로 사용한다."""
    if images is None:
        images = load_images(images_dir)
    if not images:
        raise ValueError(f"이미지가 없습니다: {images_dir}")
    if text_tracks_created is None:
        text_tracks_created = set()

    audio_material = cc.AudioMaterial(song_path)
    total_us = audio_material.duration
    script.add_segment(cc.AudioSegment(audio_material, trange(cursor, total_us)))

    tracks = parse_captions_tracks(srt_path, total_us / 1_000_000)

    # 이미지 전환 타이밍은 첫 번째 자막 트랙 기준
    ref_captions_us = [
        (round(start * 1_000_000), round(dur * 1_000_000), text)
        for start, dur, text in (tracks[0][2] if tracks else [])
    ]
    slots = build_image_slots(ref_captions_us, total_us)
    n_images = len(images)
    for i, (slot_start, slot_dur) in enumerate(slots):
        if slot_dur <= 0:
            continue
        img = images[i % n_images]
        script.add_segment(
            cc.VideoSegment(img, trange(cursor + slot_start, slot_dur)), "이미지"
        )

    total_caption_count = 0
    for track_name, is_ko, caps in tracks:
        if track_name not in text_tracks_created:
            script.add_track(cc.TrackType.text, track_name)
            text_tracks_created.add(track_name)
        y = -0.85 if is_ko else -0.68  # 한글 아래, 영어 위 (둘 다 화면 하단)
        for start, dur, text in caps:
            start_us = round(start * 1_000_000)
            dur_us = round(dur * 1_000_000)
            script.add_segment(
                cc.TextSegment(
                    text,
                    trange(cursor + start_us, dur_us),
                    style=cc.TextStyle(size=5.0, color=(1.0, 1.0, 1.0), align=1),
                    clip_settings=cc.ClipSettings(transform_y=y),
                ),
                track_name,
            )
            total_caption_count += 1

    print(
        f"  자막 {total_caption_count}개({len(tracks)}개 트랙), 이미지슬롯 {len(slots)}개(보유 이미지 {n_images}장 순환), "
        f"노래 길이 {total_us/1_000_000:.1f}초"
    )
    return cursor + total_us


def build_pop_draft(song_path, srt_path, images_dir, project_name, draft_folder_path, images=None):
    """노래 1곡 + 자막(.srt/.lrc) + 이미지로 캡컷 초안 1개를 만든다.
    images(경로 리스트)를 넘기면 images_dir 스캔 대신 그 목록을 그대로 사용한다."""
    draft_folder = cc.DraftFolder(draft_folder_path)
    script = draft_folder.create_draft(project_name, 1920, 1080, fps=30, allow_replace=True)

    script.add_track(cc.TrackType.audio)
    script.add_track(cc.TrackType.video, "이미지")
    # 자막 트랙은 add_song_to_script 안에서 필요한 만큼 동적으로 생성됨

    try:
        add_song_to_script(script, song_path, srt_path, images_dir, 0, images=images)
    except ValueError as e:
        print(f"!! {e}")
        return False

    script.save()
    print(f"완료! 캡컷을 열면 '{project_name}' 초안이 보입니다.")
    return True


def main():
    if len(sys.argv) < 6:
        print("사용법: python capcut_assemble.py <노래파일> <자막.srt> <이미지폴더> <프로젝트이름> <CapCut_Drafts_폴더>")
        sys.exit(1)

    song_path, srt_path, images_dir, project_name, draft_folder_path = sys.argv[1:6]

    if not os.path.isdir(draft_folder_path):
        print(f"!! CapCut Drafts 폴더를 찾을 수 없습니다: {draft_folder_path}")
        sys.exit(1)

    build_pop_draft(song_path, srt_path, images_dir, project_name, draft_folder_path)


if __name__ == "__main__":
    main()
