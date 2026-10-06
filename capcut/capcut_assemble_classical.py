"""
캡컷 초안 자동 조립 - 클래식(뉴에이지) 버전

폴더 하나에 아래처럼 들어있다고 가정합니다:
  <입력폴더>/노래/    -- 여러 곡의 wav 파일들 (제목.wav, 제목 (1).wav 형태로 곡마다 2개씩,
                         날짜순으로 나열하면 자연스럽게 곡 쌍이 만들어짐. 하나만 있으면 한 곡으로
                         주제를 만든다. mp3는 무시)
  <입력폴더>/이미지/  -- 여러 주제의 이미지들 (주제마다 장수가 다를 수 있음)
                         * 주제 번호 폴더(추천): 이미지/1/, 이미지/2/, ... 처럼 번호 폴더마다 그 주제의
                           이미지를 넣으면, N번 폴더 = N번째 주제(노래 만든 날짜 순)로 그대로 짝짓는다.
                           파일 이름·만든 날짜·시간 간격은 상관없다.
                         * 번호 폴더가 없으면 아래처럼 시간 간격으로 자동 그룹 분리

만든 날짜(다운로드/생성된 시각) 오름차순으로:
  - 노래 폴더의 wav 파일을 2개씩 묶어 "주제"의 노래 2곡으로 사용
  - 이미지 폴더는 "생성 시간 간격"으로 자동 그룹 분리
    (같은 주제 이미지는 몇 초~몇십 초 간격, 주제가 바뀌면 간격이 훨씬 크게 벌어지는
    패턴을 이용합니다. 장수가 주제마다 달라도 됩니다.)
  (주제 개수는 노래 쌍 개수와 이미지 그룹 개수 중 작은 쪽에 맞춥니다)

각 주제마다:
  - 노래 2곡을 이어붙여 하나의 오디오로 만들고
  - 그 주제의 이미지들을 (반복 순환하며) 5초씩 전환 효과로 계속 연결해서
    두 곡 합친 길이를 끝까지 채웁니다.
  - <입력폴더>/CapCut Drafts/ 안에 초안을 저장합니다 (초안 이름 = 첫 곡 제목).

사용법:
  python capcut_assemble_classical.py <입력폴더> [출력폴더] [초당 이미지길이=5] [그룹경계 간격(초)=120]
"""

import os
import re
import sys
from types import SimpleNamespace

import pycapcut as cc
from pycapcut import trange
from pycapcut.metadata.effect_meta import TransitionMeta

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
DEFAULT_IMAGE_SEC = 5
DEFAULT_GAP_THRESHOLD_SEC = 120  # 이 간격(초)보다 크게 벌어지면 새 주제로 판단

# "사선 페이드" - pycapcut 기본 목록에 없어서, 실제 캡컷에서 추출한 값으로 직접 등록
_DIAGONAL_FADE_META = TransitionMeta(
    "사선 페이드", False,
    "7626594802607394055", "7626594802607394055",
    "fb69ae6695a9dfedbb9c9d93b33a6fb7",
    1.933333, True,
)
TRANSITION = SimpleNamespace(value=_DIAGONAL_FADE_META)
TRANSITION_DUR_US = None  # None이면 전환 자체의 기본 길이(1.93초) 사용
_DIAGONAL_FADE_CACHE_PATH = (
    r"C:\Users\lg\AppData\Local\CapCut\User Data\Cache\effect"
    r"\7626594802607394055\fb69ae6695a9dfedbb9c9d93b33a6fb7"
)


def patch_transition_paths(draft_content_path):
    """pycapcut가 export_json에서 빼버리는 'path' 필드를, 사선 페이드 전환에 한해
    실제 캐시 파일 경로로 채워 넣는다 (없으면 캡컷이 효과를 못 찾을 수 있음)."""
    import json

    with open(draft_content_path, encoding="utf-8") as f:
        data = json.load(f)

    patched = 0
    for t in data.get("materials", {}).get("transitions", []):
        if t.get("effect_id") == _DIAGONAL_FADE_META.effect_id:
            t["path"] = _DIAGONAL_FADE_CACHE_PATH.replace("\\", "/")
            patched += 1

    if patched:
        with open(draft_content_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)


def base_title(filename):
    base = os.path.splitext(os.path.basename(filename))[0]
    return re.sub(r"\s*\(\d+\)\s*$", "", base).strip()


def group_songs_by_title(songs):
    """같은 제목(뒤에 붙는 (N)만 다름)의 wav들을 묶는다. 각 제목에서는
    '제목.wav'와 '제목 (1).wav' 두 개를 사용하고, (2)/(3) 등 나머지는 무시한다.
    둘 중 하나만 있으면 그 한 곡으로 주제를 만든다.
    (제목, [곡...], 주제번호) 리스트로 반환하며, 제목이 처음 등장한 순서를 유지한다.
    "(2)", "(3)" 처럼 쓰지 않는 파일만 있는 제목은 주제로 치지 않는다(번호도 차지하지 않음).
    주제번호는 1부터 센 번호로, 이미지 번호 폴더(이미지\\N)와 짝짓는 데 쓴다."""
    by_title = {}
    order = []
    for path in songs:
        title = base_title(path)
        if title not in by_title:
            by_title[title] = {}
            order.append(title)
        name = os.path.splitext(os.path.basename(path))[0]
        suffix = name[len(title):].strip()  # "" 또는 "(1)", "(2)", ...
        by_title[title][suffix] = path

    result = []
    number = 0
    for title in order:
        variants = by_title[title]
        songs = [p for p in (variants.get(""), variants.get("(1)")) if p]
        if not songs:
            print(f"[무시] '{title}': {sorted(variants)} 파일만 있어서 쓰지 않습니다.")
            continue
        number += 1
        if len(songs) == 1:
            print(f"[안내] {number}번 '{title}': wav가 하나뿐이라 한 곡으로 만듭니다.")
        extras = [k for k in variants if k not in ("", "(1)")]
        if extras:
            print(f"[안내] '{title}': {extras} 파일은 무시하고 기본 파일만 사용합니다.")
        result.append((title, songs, number))
    return result


def list_wav_sorted_by_ctime(folder):
    items = [
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if f.lower().endswith(".wav")
    ]
    items.sort(key=lambda p: os.path.getctime(p))
    return items


def cluster_images_by_time_gap(images_with_ctime, gap_threshold_sec):
    """(경로, 만든 시각) 목록을 시간 간격이 크게 벌어지는 지점마다 새 그룹으로 나눈다."""
    if not images_with_ctime:
        return []
    clusters = [[images_with_ctime[0]]]
    for prev, cur in zip(images_with_ctime, images_with_ctime[1:]):
        gap = cur[1] - prev[1]
        if gap > gap_threshold_sec:
            clusters.append([])
        clusters[-1].append(cur)
    return [[p for p, _ in cluster] for cluster in clusters]


def list_images_with_ctime_sorted(folder):
    items = [
        (os.path.join(folder, f), os.path.getctime(os.path.join(folder, f)))
        for f in os.listdir(folder)
        if f.lower().endswith(IMAGE_EXTS)
    ]
    items.sort(key=lambda t: t[1])
    return items


def numbered_image_folders(image_dir):
    """이미지 폴더 안의 주제 번호 폴더들 {번호: 폴더경로}. ("1", "01", "1번" 처럼 숫자로 시작하는 폴더)"""
    folders = {}
    for d in os.listdir(image_dir):
        path = os.path.join(image_dir, d)
        m = re.match(r"\s*(\d+)", d)
        if os.path.isdir(path) and m:
            folders.setdefault(int(m.group(1)), path)
    return folders


def pair_with_numbered_folders(song_groups, track_folders):
    """N번째 주제에 이미지/N 폴더의 이미지를 짝짓는다. 폴더가 없거나 비어 있는 주제는 뺀다."""
    paired_songs, paired_images = [], []
    for group in song_groups:
        title, _, i = group
        folder = track_folders.get(i)
        if folder is None:
            print(f"[건너뜀] {i}번 '{title}': 이미지\\{i} 폴더가 없습니다.")
            continue
        images = [p for p, _ in list_images_with_ctime_sorted(folder)]
        if not images:
            print(f"[건너뜀] {i}번 '{title}': 이미지\\{os.path.basename(folder)} 폴더에 이미지가 없습니다.")
            continue
        print(f"  {i}번 폴더({len(images)}장) → {title}")
        paired_songs.append(group)
        paired_images.append(images)
    max_number = max((g[2] for g in song_groups), default=0)
    extra = sorted(n for n in track_folders if n > max_number)
    if extra:
        print(f"!! 주의: 노래 주제보다 이미지 번호 폴더가 많습니다 (사용 안 함: {', '.join(map(str, extra))}번)")
    return paired_songs, paired_images


def normalize_output_folder(path, input_folder):
    """출력 폴더를 캡컷이 읽는 "<앨범 폴더>\\CapCut Drafts" 형태로 맞춘다.

    - "CapCut Drafts" 폴더를 넣으면 그대로 사용
    - 앨범 폴더(입력 폴더와 이름이 같은 폴더)를 넣으면 그 안의 "CapCut Drafts"
    - 그 밖의 폴더(채널 폴더)를 넣으면 그 아래에 입력 폴더와 같은 이름의 앨범 폴더를 만들고
      그 안의 "CapCut Drafts"  (예: C:\\...\\Claude Classic Music -> ...\\Claude Classic Music\\앨범명\\CapCut Drafts)
    비어 있으면 None (기본 위치 사용)."""
    if not path:
        return None
    path = path.strip().strip('"').strip()
    if not path:
        return None
    name = os.path.basename(os.path.normpath(path))
    if name.lower() == "capcut drafts":
        return path
    album = os.path.basename(os.path.normpath(input_folder.strip().strip('"')))
    if album and name != album:
        path = os.path.join(path, album)
    return os.path.join(path, "CapCut Drafts")


def default_output_folder(input_folder):
    """출력 폴더를 안 넘기면, F드라이브 등 외장하드의 원본 폴더 대신 캡컷이 실제로
    읽는 Documents 쪽 폴더를 자동으로 찾아서 사용한다.
    (F:\\Claude Newage Music Channel\\<앨범> -> C:\\Users\\lg\\Documents\\Claude Newage Music Channel\\<앨범>\\CapCut Drafts)
    이 규칙에 안 맞으면 예전처럼 <입력폴더>\\CapCut Drafts를 사용한다."""
    marker = "Claude Newage Music Channel"
    parts = os.path.normpath(input_folder).split(os.sep)
    if marker in parts:
        idx = parts.index(marker)
        if idx + 1 < len(parts):
            album = parts[idx + 1]
            return os.path.join(r"C:\Users\lg\Documents", marker, album, "CapCut Drafts")
    return os.path.join(input_folder, "CapCut Drafts")


def theme_name_from_song(song_path):
    base = os.path.splitext(os.path.basename(song_path))[0]
    base = re.sub(r"\s*\(\d+\)\s*$", "", base).strip()  # "제목 (1)" -> "제목"
    return base or "주제"


def process_theme(theme_name, songs, images, image_sec, draft_dir, position=None, total=None):
    if position is not None:
        print(f"[{position}/{total}] {theme_name} 처리 시작...")
    else:
        print(f"[처리 시작] {theme_name} ...")
    os.makedirs(draft_dir, exist_ok=True)
    draft_folder = cc.DraftFolder(draft_dir)
    script = draft_folder.create_draft(theme_name, 1920, 1080, fps=30, allow_replace=True)

    script.add_track(cc.TrackType.audio)
    durations = []
    total_us = 0
    for song in songs:
        mat = cc.AudioMaterial(song)
        script.add_segment(cc.AudioSegment(mat, trange(total_us, mat.duration)))
        durations.append(mat.duration)
        total_us += mat.duration

    script.add_track(cc.TrackType.video, "이미지")
    slot_us = int(image_sec * 1_000_000)
    transition = TRANSITION

    cursor = 0
    idx = 0
    n_images = len(images)
    segment_count = 0
    while cursor < total_us:
        img = images[idx % n_images]
        dur = min(slot_us, total_us - cursor)
        seg = cc.VideoSegment(img, trange(cursor, dur))
        if transition is not None and dur == slot_us and (cursor + slot_us) < total_us:
            seg.add_transition(transition, duration=TRANSITION_DUR_US)
        script.add_segment(seg, "이미지")
        cursor += dur
        idx += 1
        segment_count += 1

    script.save()
    patch_transition_paths(os.path.join(draft_dir, theme_name, "draft_content.json"))
    print(
        f"[완료] {theme_name}: 노래 {len(durations)}곡("
        f"{' + '.join(f'{d/1_000_000:.1f}s' for d in durations)}), "
        f"이미지 {n_images}장을 {segment_count}번 배치"
    )


def build_combined_draft(song_groups, image_chunks, image_sec, draft_dir, combined_name):
    """모든 주제를 순서대로 이어붙인 캡컷 프로젝트 1개를 만든다."""
    print(f"\n[전곡] '{combined_name}' 만드는 중...")
    os.makedirs(draft_dir, exist_ok=True)
    draft_folder = cc.DraftFolder(draft_dir)
    script = draft_folder.create_draft(combined_name, 1920, 1080, fps=30, allow_replace=True)

    script.add_track(cc.TrackType.audio)
    script.add_track(cc.TrackType.video, "이미지")
    slot_us = int(image_sec * 1_000_000)
    transition = TRANSITION

    cursor = 0
    n = min(len(song_groups), len(image_chunks))
    for i in range(n):
        theme_name, songs = song_groups[i][:2]
        images = image_chunks[i]

        theme_start = cursor
        theme_end = cursor
        for song in songs:
            mat = cc.AudioMaterial(song)
            script.add_segment(cc.AudioSegment(mat, trange(theme_end, mat.duration)))
            theme_end += mat.duration

        idx = 0
        n_images = len(images)
        while cursor < theme_end:
            img = images[idx % n_images]
            dur = min(slot_us, theme_end - cursor)
            seg = cc.VideoSegment(img, trange(cursor, dur))
            if transition is not None and dur == slot_us and (cursor + slot_us) < theme_end:
                seg.add_transition(transition, duration=TRANSITION_DUR_US)
            script.add_segment(seg, "이미지")
            cursor += dur
            idx += 1
        print(f"  [{i+1}/{n}] {theme_name} 이어붙임 ({(theme_end - theme_start)/1_000_000:.1f}s)")

    script.save()
    patch_transition_paths(os.path.join(draft_dir, combined_name, "draft_content.json"))
    print(f"[완료] 전곡 '{combined_name}': 총 길이 {cursor/1_000_000:.1f}초 ({n}개 주제 이어붙임)")


def main():
    if len(sys.argv) < 2:
        print(
            "사용법: python capcut_assemble_classical.py <입력폴더> "
            "[출력 CapCut Drafts 폴더] [초당 이미지길이=5] [그룹경계 간격(초)=120]"
        )
        sys.exit(1)

    input_folder = sys.argv[1].strip().strip('"')
    output_drafts_folder = normalize_output_folder(sys.argv[2], input_folder) if len(sys.argv) > 2 else None
    image_sec = float(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_IMAGE_SEC
    gap_threshold = float(sys.argv[4]) if len(sys.argv) > 4 else DEFAULT_GAP_THRESHOLD_SEC

    song_dir = os.path.join(input_folder, "노래")
    image_dir = os.path.join(input_folder, "이미지")

    if not os.path.isdir(song_dir) or not os.path.isdir(image_dir):
        print(f"!! '{input_folder}' 안에 '노래', '이미지' 폴더가 모두 있어야 합니다.")
        sys.exit(1)

    songs = list_wav_sorted_by_ctime(song_dir)
    images_with_ctime = list_images_with_ctime_sorted(image_dir)
    track_folders = numbered_image_folders(image_dir)
    if track_folders:
        print(f"wav 파일 {len(songs)}개 발견")
    else:
        print(f"wav 파일 {len(songs)}개, 이미지 {len(images_with_ctime)}개 발견")

    song_groups = group_songs_by_title(songs)  # [(제목, [곡1, 곡2]), ...]
    if track_folders:
        # 주제 번호 폴더 방식: N번 폴더 = N번째 주제 (시간 간격·날짜와 무관)
        print(f"노래 제목(주제) {len(song_groups)}개, 이미지 주제 번호 폴더 {len(track_folders)}개 사용")
        song_groups, image_chunks = pair_with_numbered_folders(song_groups, track_folders)
    else:
        image_chunks = cluster_images_by_time_gap(images_with_ctime, gap_threshold)
        print(f"노래 제목(주제) {len(song_groups)}개, 이미지 그룹별 장수:", [len(c) for c in image_chunks])

    n_themes = min(len(song_groups), len(image_chunks))
    if n_themes == 0:
        print("!! 노래 제목 또는 이미지 그룹을 만들 수 없습니다 (수량 확인 필요).")
        sys.exit(1)
    if len(song_groups) != len(image_chunks):
        print(
            f"!! 주의: 노래 주제 {len(song_groups)}개와 이미지 그룹 {len(image_chunks)}개의 "
            f"개수가 다릅니다. 앞에서부터 {n_themes}개만 짝지어 처리합니다."
        )
    print(f"주제 {n_themes}개로 구성합니다\n")

    draft_root = output_drafts_folder or default_output_folder(input_folder)
    print(f"결과 저장 위치: {draft_root}\n")

    success = 0
    for i in range(n_themes):
        theme_name, songs = song_groups[i][:2]
        theme_images = image_chunks[i]
        try:
            process_theme(theme_name, songs, theme_images, image_sec, draft_root, i + 1, n_themes)
            success += 1
        except Exception as e:
            print(f"[실패] {theme_name}: {e}")

    print(f"\n=== 전체 완료 === 성공 {success} / 전체 {n_themes}")

    combined_name = os.path.basename(input_folder.rstrip("\\/")) + " 전곡"
    try:
        build_combined_draft(song_groups, image_chunks, image_sec, draft_root, combined_name)
    except Exception as e:
        print(f"[실패] 전곡 만들기: {e}")


if __name__ == "__main__":
    main()
