"""
캡컷 초안 자동 조립 - 대중가요 플레이리스트(일괄) 버전

두 가지 폴더 구조를 자동으로 인식합니다.

[구조 A] 곡마다 폴더가 따로 있는 경우 - 상위 폴더 안에 "곡" 폴더가 여러 개:
  <곡 폴더>/노래/    (노래 파일 - 파일명에 "mastered"가 들어간 것을 사용)
  <곡 폴더>/이미지/  (그 곡의 이미지)
  <곡 폴더>/*.srt 또는 *.lrc   (그 곡의 가사 파일, 곡 폴더 바로 안에)

[구조 B] 앨범 폴더 하나에 여러 곡이 섞여 있는 경우:
  <입력폴더>/노래/    (여러 곡의 "제목_mastered.wav"들과, 각 제목에 대응하는
                       "제목....lrc"(또는 .srt) 가사 파일들이 전부 한 폴더에 섞여 있음)
  <입력폴더>/이미지/  두 가지 방식 중 하나:
     (1) 트랙 번호 폴더(추천): 이미지/1/, 이미지/2/, ... 이미지/10/ 처럼 번호 폴더마다 그 트랙의
         이미지를 넣는다. N번 폴더 = N번째 곡(노래 만든 날짜 순). 파일 이름·날짜는 상관없다.
     (2) 번호 폴더가 없으면 예전처럼 모든 이미지를 한 폴더에 섞어 두고, 만든 날짜 오름차순으로
         정렬해서 정해진 장수(기본 15장)씩 순서대로 끊어 곡별로 배정

어느 쪽이든 곡 폴더 하나(또는 앨범 폴더 하나) = 캡컷 초안 하나.
곡이 2개 이상이면 전부 이어붙인 "전곡" 통합 프로젝트도 추가로 만듭니다.

사용법:
  python capcut_assemble_playlist.py <폴더> [출력 CapCut Drafts 폴더] [곡당 이미지 장수=15]
"""

import os
import re
import sys

import pycapcut as cc
from pycapcut.exceptions import SegmentOverlap

from capcut_assemble import add_song_to_script, build_pop_draft, load_images
from capcut_assemble_classical import list_images_with_ctime_sorted

AUDIO_EXTS = (".wav", ".mp3", ".m4a", ".flac", ".aac")
DEFAULT_IMAGES_PER_SONG = 15


def list_sorted_by_ctime(folder, exts):
    items = [
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if f.lower().endswith(exts)
    ]
    items.sort(key=lambda p: os.path.getctime(p))
    return items


# ---------- 구조 A: 곡마다 폴더가 따로 있는 경우 ----------

def resolve_song_folder(song_folder):
    """곡 폴더에서 (곡이름, 노래파일, 가사파일, 이미지목록)을 찾는다.
    조건이 안 맞으면 None을 반환하고 이유를 출력한다."""
    song_name = os.path.basename(song_folder.rstrip("\\/"))
    song_dir = os.path.join(song_folder, "노래")
    image_dir = os.path.join(song_folder, "이미지")

    if not os.path.isdir(song_dir) or not os.path.isdir(image_dir):
        print(f"[건너뜀] {song_name}: '노래' 또는 '이미지' 폴더가 없습니다.")
        return None

    songs = list_sorted_by_ctime(song_dir, AUDIO_EXTS)
    mastered = [s for s in songs if "mastered" in os.path.basename(s).lower()]
    if not mastered:
        print(f"[건너뜀] {song_name}: 파일명에 'mastered'가 들어간 노래 파일이 없습니다.")
        return None

    lyric_files = [
        f for f in os.listdir(song_folder)
        if f.lower().endswith(".srt") or f.lower().endswith(".lrc")
    ]
    if not lyric_files:
        print(f"[건너뜀] {song_name}: .srt 또는 .lrc 가사 파일이 없습니다.")
        return None

    song_path = mastered[0]
    lyrics_path = os.path.join(song_folder, lyric_files[0])
    images = load_images(image_dir)
    if not images:
        # 이미지를 "이미지\\1" 같은 번호 폴더에 넣어 둔 경우
        track_folders = numbered_image_folders(image_dir)
        if track_folders:
            images = load_images(track_folders[min(track_folders)])
    if not images:
        print(f"[건너뜀] {song_name}: 이미지가 없습니다.")
        return None
    return song_name, song_path, lyrics_path, images


# ---------- 구조 B: 앨범 폴더 하나에 여러 곡이 섞여 있는 경우 ----------

def strip_mastered_suffix(filename):
    name = os.path.splitext(os.path.basename(filename))[0]
    return re.sub(r"_mastered$", "", name, flags=re.IGNORECASE).strip()


def find_lyrics_for_title(song_dir, title):
    """"title.lrc"/"title.srt"를 정확히 우선 찾고, 없을 때만 뒤에 "(1)" 등이 덧붙은
    파일로 대신 찾는다(정확히 일치하는 파일을 항상 우선해서, "제목 (1).lrc" 같은 중복
    파일 때문에 엉뚱한 파일이 골라지지 않도록 한다)."""
    for ext in (".lrc", ".srt"):
        exact = os.path.join(song_dir, title + ext)
        if os.path.isfile(exact):
            return exact

    candidates = [
        f for f in os.listdir(song_dir)
        if f.lower().endswith(".srt") or f.lower().endswith(".lrc")
    ]
    for f in candidates:
        base = os.path.splitext(f)[0]
        if base.startswith(title) and base[len(title):].strip("() ").isdigit():
            return os.path.join(song_dir, f)
    return None


def numbered_image_folders(image_dir):
    """이미지 폴더 안의 트랙 번호 폴더들 {번호: 폴더경로}. ("1", "01", "1번" 처럼 숫자로 시작하는 폴더)"""
    folders = {}
    if not os.path.isdir(image_dir):
        return folders
    for d in os.listdir(image_dir):
        path = os.path.join(image_dir, d)
        m = re.match(r"\s*(\d+)", d)
        if os.path.isdir(path) and m:
            folders.setdefault(int(m.group(1)), path)
    return folders


def resolve_flat_album(input_folder, images_per_song):
    """노래(mastered)는 만든 날짜 오름차순으로 정렬하고, 이미지도 만든 날짜 오름차순으로
    정렬해서 images_per_song장씩 묶어 같은 순번끼리 짝짓는다. 가사(.srt/.lrc)는 같은 제목의
    파일("제목.lrc")을 정확히 찾아서 짝짓는다 - 같은 제목으로 "제목 (1).lrc"처럼 중복
    저장된 파일이 섞여 있어도 순서가 밀리지 않도록 하기 위해서다."""
    song_dir = os.path.join(input_folder, "노래")
    image_dir = os.path.join(input_folder, "이미지")

    songs = list_sorted_by_ctime(song_dir, AUDIO_EXTS)
    mastered = [s for s in songs if "mastered" in os.path.basename(s).lower()]

    track_folders = numbered_image_folders(image_dir)
    if track_folders:
        # 트랙 번호 폴더 방식: N번 폴더의 이미지를 N번째 곡에 그대로 배정 (날짜·이름 순서와 무관)
        print(f"노래 {len(mastered)}개, 이미지 트랙 번호 폴더 {len(track_folders)}개 사용")
        resolved_list = []
        for i, wav_path in enumerate(mastered, 1):
            title = strip_mastered_suffix(wav_path)
            folder = track_folders.get(i)
            if folder is None:
                print(f"[건너뜀] {i}번 '{title}': 이미지\\{i} 폴더가 없습니다.")
                continue
            images = [p for p, _ in list_images_with_ctime_sorted(folder)]
            if not images:
                print(f"[건너뜀] {i}번 '{title}': 이미지\\{os.path.basename(folder)} 폴더에 이미지가 없습니다.")
                continue
            lyrics_path = find_lyrics_for_title(song_dir, title)
            if not lyrics_path:
                print(f"[건너뜀] '{title}': 가사 파일('{title}.lrc' 또는 '.srt')을 찾을 수 없습니다.")
                continue
            print(f"  {i}번 폴더({len(images)}장) → {title}")
            resolved_list.append((title, wav_path, lyrics_path, images))
        extra = sorted(n for n in track_folders if n > len(mastered))
        if extra:
            print(f"!! 주의: 노래보다 이미지 번호 폴더가 많습니다 (사용 안 함: {', '.join(map(str, extra))}번)")
        return resolved_list

    images = [p for p, _ in list_images_with_ctime_sorted(image_dir)]
    image_chunks = [images[i:i + images_per_song] for i in range(0, len(images), images_per_song)]

    n = min(len(mastered), len(image_chunks))
    print(
        f"노래 {len(mastered)}개, "
        f"이미지 {len(images)}장을 {images_per_song}개씩 {len(image_chunks)}그룹으로 분리"
    )
    if len(mastered) != len(image_chunks):
        print(
            f"!! 주의: 개수가 서로 달라서(노래{len(mastered)}/이미지그룹{len(image_chunks)}) "
            f"앞에서부터 {n}개만 순서대로 짝지어 처리합니다."
        )

    resolved_list = []
    for i in range(n):
        wav_path = mastered[i]
        title = strip_mastered_suffix(wav_path)
        lyrics_path = find_lyrics_for_title(song_dir, title)
        if not lyrics_path:
            print(f"[건너뜀] '{title}': 가사 파일('{title}.lrc' 또는 '.srt')을 찾을 수 없습니다.")
            continue
        resolved_list.append((title, wav_path, lyrics_path, image_chunks[i]))
    return resolved_list


# ---------- 공통 처리 ----------

def process_song(resolved, draft_dir):
    song_name, song_path, lyrics_path, images = resolved
    os.makedirs(draft_dir, exist_ok=True)
    print(f"\n--- {song_name} 처리 중 ---")
    return build_pop_draft(song_path, lyrics_path, None, song_name, draft_dir, images=images)


def allow_subtitle_overflow(script):
    """가사 줄이 길어서 자막이 같은 트랙의 다른 자막과 겹치면(예: 마지막 줄이 곡 끝까지 이어짐)
    멈추지 않고, 비어 있는 다른 자막 트랙에 넣는다. 없으면 자막 트랙을 하나 더 만든다.
    (자막 말고 노래·이미지가 겹치면 예전처럼 오류로 알린다)"""
    original_add = script.add_segment

    def add_segment(segment, track_name=None):
        try:
            return original_add(segment, track_name)
        except SegmentOverlap:
            if not isinstance(segment, cc.TextSegment):
                raise
        text_tracks = [t for t in script.tracks.values() if t.track_type == cc.TrackType.text]
        for track in text_tracks:
            if not any(seg.overlaps(segment) for seg in track.segments):
                return original_add(segment, track.name)
        name = f"자막_추가{len(text_tracks) + 1}"
        script.add_track(cc.TrackType.text, name, relative_index=len(text_tracks) + 1)
        return original_add(segment, name)

    script.add_segment = add_segment


def build_combined_draft(resolved_list, draft_dir, combined_name):
    print(f"\n[전곡] '{combined_name}' 만드는 중...")
    os.makedirs(draft_dir, exist_ok=True)
    draft_folder = cc.DraftFolder(draft_dir)
    script = draft_folder.create_draft(combined_name, 1920, 1080, fps=30, allow_replace=True)

    script.add_track(cc.TrackType.audio)
    script.add_track(cc.TrackType.video, "이미지")
    # 자막 트랙은 add_song_to_script 안에서 필요한 만큼 동적으로 생성됨

    allow_subtitle_overflow(script)

    cursor = 0
    text_tracks_created = set()
    for i, (song_name, song_path, lyrics_path, images) in enumerate(resolved_list, 1):
        print(f"  [{i}/{len(resolved_list)}] {song_name} 이어붙이는 중...")
        cursor = add_song_to_script(
            script, song_path, lyrics_path, None, cursor, images=images,
            text_tracks_created=text_tracks_created,
        )

    script.save()
    print(f"[완료] 전곡 '{combined_name}': 총 길이 {cursor/1_000_000:.1f}초 ({len(resolved_list)}곡 이어붙임)")


def default_output_folder(input_folder):
    """출력 폴더를 안 넘기면, F드라이브(외장하드) 원본 폴더 대신 캡컷이 실제로 읽는
    Documents 쪽 폴더를 자동으로 찾아서 사용한다.
    (F:\\Playlist 유튜브\\<앨범> -> C:\\Users\\lg\\Documents\\노래방유튜브 3차\\<앨범>\\CapCut Drafts)
    이 규칙에 안 맞으면 예전처럼 <입력폴더>\\CapCut Drafts를 사용한다."""
    marker = "Playlist 유튜브"
    parts = os.path.normpath(input_folder).split(os.sep)
    if marker in parts:
        idx = parts.index(marker)
        if idx + 1 < len(parts):
            album = parts[idx + 1]
            return os.path.join(r"C:\Users\lg\Documents\노래방유튜브 3차", album, "CapCut Drafts")
    return os.path.join(input_folder, "CapCut Drafts")


def normalize_output_folder(path, input_folder):
    """출력 폴더를 캡컷이 읽는 "<앨범 폴더>\\CapCut Drafts" 형태로 맞춘다.

    - "CapCut Drafts" 폴더를 넣으면 그대로 사용
    - 앨범 폴더(입력 폴더와 이름이 같은 폴더)를 넣으면 그 안의 "CapCut Drafts"
    - 그 밖의 폴더(채널 폴더)를 넣으면 그 아래에 입력 폴더와 같은 이름의 앨범 폴더를 만들고
      그 안의 "CapCut Drafts"  (예: C:\\...\\채널B -> C:\\...\\채널B\\앨범명\\CapCut Drafts)
    캡컷 초안 위치는 "CapCut Drafts" 바로 위 폴더(앨범 폴더)로 지정하면 된다."""
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


def main():
    if len(sys.argv) < 2:
        print("사용법: python capcut_assemble_playlist.py <폴더> [출력 CapCut Drafts 폴더] [그룹경계 간격(초)=120]")
        sys.exit(1)

    input_folder = sys.argv[1]
    output_drafts_folder = normalize_output_folder(sys.argv[2], input_folder) if len(sys.argv) > 2 else None
    images_per_song = int(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_IMAGES_PER_SONG
    if not os.path.isdir(input_folder):
        print(f"!! 폴더를 찾을 수 없습니다: {input_folder}")
        sys.exit(1)
    print(f"결과 저장 위치: {output_drafts_folder or default_output_folder(input_folder)}")

    song_dir = os.path.join(input_folder, "노래")
    image_dir = os.path.join(input_folder, "이미지")
    is_direct = os.path.isdir(song_dir) and os.path.isdir(image_dir)

    resolved_list = []
    skipped = 0

    if is_direct:
        mastered_count = len([
            f for f in os.listdir(song_dir)
            if f.lower().endswith(AUDIO_EXTS) and "mastered" in f.lower()
        ])
        if mastered_count > 1:
            print(f"앨범 폴더로 인식했습니다 (노래 폴더 안에 mastered 파일 {mastered_count}개).")
            resolved_list = resolve_flat_album(input_folder, images_per_song)
        else:
            print("단일 곡 폴더로 인식했습니다.")
            resolved = resolve_song_folder(input_folder)
            if resolved:
                resolved_list = [resolved]
            else:
                skipped = 1
    else:
        song_folders = [
            os.path.join(input_folder, d)
            for d in sorted(os.listdir(input_folder))
            if os.path.isdir(os.path.join(input_folder, d))
        ]
        print(f"상위 폴더로 인식, 곡 폴더 {len(song_folders)}개 발견")
        for song_folder in song_folders:
            resolved = resolve_song_folder(song_folder)
            if resolved:
                resolved_list.append(resolved)
            else:
                skipped += 1

    success = 0
    total = len(resolved_list)
    for i, resolved in enumerate(resolved_list, 1):
        song_name = resolved[0]
        print(f"\n[{i}/{total}] {song_name} 처리 시작...")
        draft_dir = output_drafts_folder or default_output_folder(input_folder)
        ok = process_song(resolved, draft_dir)
        if ok:
            success += 1
        else:
            skipped += 1

    print(f"\n=== 전체 완료 === 성공 {success} / 건너뜀 {skipped}")

    if len(resolved_list) >= 2:
        combined_name = os.path.basename(input_folder.rstrip("\\/")) + " 전곡"
        combined_drafts_dir = output_drafts_folder or default_output_folder(input_folder)
        try:
            build_combined_draft(resolved_list, combined_drafts_dir, combined_name)
        except Exception as e:
            print(f"[실패] 전곡 만들기: {e}")


if __name__ == "__main__":
    main()
