"""
캡컷 초안 자동 조립 - 클래식 "두 바퀴" 버전

기존 클래식 버전(capcut_assemble_classical.py)과 폴더 구성·곡 짝짓기·이미지 배정은 똑같고,
전곡 프로젝트의 순서만 다릅니다.

  기존 전곡:   1번.wav → 1번 (1).wav → 2번.wav → 2번 (1).wav → ...
  두 바퀴 전곡: [1바퀴] 1번.wav → 2번.wav → ... → N번.wav
               [2바퀴] 1번 (1).wav → 2번 (1).wav → ... → N번 (1).wav

- 이미지는 트랙 번호를 따라갑니다 (1번.wav와 1번 (1).wav 모두 1번 트랙의 이미지).
  2바퀴째에는 1바퀴에서 보여 준 다음 이미지부터 이어서 보여 줍니다.
- wav가 하나뿐인 트랙은 1바퀴에만 나옵니다.
- 곡별 프로젝트는 기존 클래식 버전과 같습니다 (트랙마다 제목.wav + 제목 (1).wav 1개).

사용법:
  python capcut_assemble_classical_2pass.py <입력폴더> [출력폴더] [초당 이미지길이=5] [그룹경계 간격(초)=120]
"""

import os
import sys

import pycapcut as cc
from pycapcut import trange

from capcut_assemble_classical import (
    DEFAULT_GAP_THRESHOLD_SEC,
    DEFAULT_IMAGE_SEC,
    TRANSITION,
    TRANSITION_DUR_US,
    cluster_images_by_time_gap,
    default_output_folder,
    group_songs_by_title,
    list_images_with_ctime_sorted,
    list_wav_sorted_by_ctime,
    numbered_image_folders,
    pair_with_numbered_folders,
    patch_transition_paths,
    process_theme,
)


def add_song_with_images(script, song, images, start_idx, cursor, slot_us):
    """곡 하나를 cursor 위치에 놓고, 그 길이만큼 이미지를 start_idx번째부터 돌아가며 채운다.
    (다음 커서 위치, 다음 이미지 번호)를 돌려준다."""
    mat = cc.AudioMaterial(song)
    script.add_segment(cc.AudioSegment(mat, trange(cursor, mat.duration)))
    song_end = cursor + mat.duration
    idx = start_idx
    while cursor < song_end:
        dur = min(slot_us, song_end - cursor)
        seg = cc.VideoSegment(images[idx % len(images)], trange(cursor, dur))
        if TRANSITION is not None and dur == slot_us and (cursor + slot_us) < song_end:
            seg.add_transition(TRANSITION, duration=TRANSITION_DUR_US)
        script.add_segment(seg, "이미지")
        cursor += dur
        idx += 1
    return cursor, idx


def build_two_pass_combined(song_groups, image_chunks, image_sec, draft_dir, combined_name):
    print(f"\n[전곡 - 두 바퀴] '{combined_name}' 만드는 중...")
    os.makedirs(draft_dir, exist_ok=True)
    draft_folder = cc.DraftFolder(draft_dir)
    script = draft_folder.create_draft(combined_name, 1920, 1080, fps=30, allow_replace=True)
    script.add_track(cc.TrackType.audio)
    script.add_track(cc.TrackType.video, "이미지")
    slot_us = int(image_sec * 1_000_000)

    n = min(len(song_groups), len(image_chunks))
    next_image = [0] * n  # 트랙별로 다음에 보여 줄 이미지 번호 (2바퀴째에 이어서 보여 주기 위해)
    cursor = 0
    count = 0
    for round_no in (1, 2):
        print(f"  --- {round_no}바퀴 ---")
        for i in range(n):
            title, songs = song_groups[i][:2]
            if len(songs) < round_no:
                continue  # wav가 하나뿐인 트랙은 2바퀴째에 없음
            song = songs[round_no - 1]
            start = cursor
            cursor, next_image[i] = add_song_with_images(
                script, song, image_chunks[i], next_image[i], cursor, slot_us)
            count += 1
            print(f"  [{count}] {os.path.basename(song)} ({(cursor - start) / 1_000_000:.1f}s)")

    script.save()
    patch_transition_paths(os.path.join(draft_dir, combined_name, "draft_content.json"))
    print(f"[완료] 전곡 '{combined_name}': 총 길이 {cursor / 1_000_000:.1f}초 ({count}곡, 두 바퀴 순서)")


def main():
    if len(sys.argv) < 2:
        print(
            "사용법: python capcut_assemble_classical_2pass.py <입력폴더> "
            "[출력 CapCut Drafts 폴더] [초당 이미지길이=5] [그룹경계 간격(초)=120]"
        )
        sys.exit(1)

    input_folder = sys.argv[1].strip().strip('"')
    output_drafts_folder = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2].strip() else None
    image_sec = float(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_IMAGE_SEC
    gap_threshold = float(sys.argv[4]) if len(sys.argv) > 4 else DEFAULT_GAP_THRESHOLD_SEC

    song_dir = os.path.join(input_folder, "노래")
    image_dir = os.path.join(input_folder, "이미지")
    if not os.path.isdir(song_dir) or not os.path.isdir(image_dir):
        print(f"!! '{input_folder}' 안에 '노래', '이미지' 폴더가 모두 있어야 합니다.")
        sys.exit(1)

    songs = list_wav_sorted_by_ctime(song_dir)
    print(f"wav 파일 {len(songs)}개 발견")
    song_groups = group_songs_by_title(songs)  # [(제목, [곡...], 번호), ...]

    track_folders = numbered_image_folders(image_dir)
    if track_folders:
        print(f"노래 트랙 {len(song_groups)}개, 이미지 번호 폴더 {len(track_folders)}개 사용")
        song_groups, image_chunks = pair_with_numbered_folders(song_groups, track_folders)
    else:
        image_chunks = cluster_images_by_time_gap(list_images_with_ctime_sorted(image_dir), gap_threshold)
        print(f"노래 트랙 {len(song_groups)}개, 이미지 그룹별 장수:", [len(c) for c in image_chunks])

    n = min(len(song_groups), len(image_chunks))
    if n == 0:
        print("!! 노래 트랙 또는 이미지를 찾지 못했습니다 (수량 확인 필요).")
        sys.exit(1)
    if len(song_groups) != len(image_chunks):
        print(f"!! 주의: 노래 트랙 {len(song_groups)}개와 이미지 그룹 {len(image_chunks)}개의 "
              f"개수가 다릅니다. 앞에서부터 {n}개만 짝지어 처리합니다.")

    draft_root = output_drafts_folder or default_output_folder(input_folder)
    print(f"결과 저장 위치: {draft_root}\n")

    success = 0
    for i in range(n):
        title, track_songs = song_groups[i][:2]
        try:
            process_theme(title, track_songs, image_chunks[i], image_sec, draft_root, i + 1, n)
            success += 1
        except Exception as e:
            print(f"[실패] {title}: {e}")
    print(f"\n=== 곡별 프로젝트 완료 === 성공 {success} / 전체 {n}")

    combined_name = os.path.basename(input_folder.rstrip("\\/")) + " 전곡"
    try:
        build_two_pass_combined(song_groups, image_chunks, image_sec, draft_root, combined_name)
    except Exception as e:
        print(f"[실패] 전곡 만들기: {e}")


if __name__ == "__main__":
    main()
