"""
캡컷에서 이미 수정(자막 오타 수정 등)을 마친 개별 곡 프로젝트들을 그대로 이어붙여서
전곡(총괄) 프로젝트를 다시 만드는 프로그램.

원본 노래/가사/이미지 파일을 다시 읽지 않는다. 이미 만들어진 각 곡의 draft_content.json을
그대로 읽어서, 그 안에 있는 수정된 자막을 시간만 밀어서 이어붙인다.
합치는 대상은 오디오, 이미지, 그리고 텍스트(자막) 트랙들이다.
오디오/이미지는 이름("audio"/"이미지")으로 찾는다. 텍스트 트랙은 캡컷에서 프로젝트를
열어 수정하면 트랙 이름("자막-한글"/"자막-영어")이 지워지는 경우가 있어서, 이름 대신
"각 곡에서 몇 번째로 나오는 텍스트 트랙인지"(순서)로 짝짓는다 - 예: 모든 곡의 첫 번째
텍스트 트랙끼리 합쳐 하나의 트랙이 되고, 두 번째 텍스트 트랙끼리 합쳐 또 다른 트랙이 된다.
(스티커처럼 텍스트가 아닌 장식은 합치지 않는다. 총괄 프로젝트를 새로 만든 뒤에 그 위에
 다시 작업하면 된다.)

곡 순서는 원본 "...전곡" 프로젝트가 있으면 그 안의 오디오 순서(진짜 앨범 순서)를 그대로
따르고, 없으면 곡 폴더의 만든 날짜 오름차순으로 정한다(수정 날짜는 캡컷에서 나중에
수정한 시점이라 순서가 안 맞을 수 있어서 쓰지 않는다).

사용법:
  python capcut_merge_edited_projects.py <CapCut Drafts 폴더> [전곡 프로젝트 이름]
"""

import json
import os
import sys

import pycapcut as cc

import re

HANGUL_RE = re.compile(r"[가-힣]")


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def find_existing_combined(drafts_folder):
    candidates = [
        d for d in os.listdir(drafts_folder)
        if d.endswith(" 전곡") and os.path.isdir(os.path.join(drafts_folder, d))
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda d: os.path.getmtime(os.path.join(drafts_folder, d)), reverse=True)
    return os.path.join(drafts_folder, candidates[0])


def strip_mastered_suffix(filename):
    import re
    name = os.path.splitext(os.path.basename(filename))[0]
    return re.sub(r"_mastered$", "", name, flags=re.IGNORECASE).strip()


def get_song_order_from_combined(combined_dir):
    """기존(원본) 전곡 프로젝트의 오디오 트랙 순서를 읽어서, 실제 앨범 순서대로 된
    곡 제목(폴더 이름) 목록을 알아낸다. 개별 곡 폴더의 수정 날짜는 사용자가 캡컷에서
    수정한 순서일 뿐 앨범 순서가 아닐 수 있어서, 원본 전곡이 있으면 그 순서를 우선한다.
    같은 CapCut Drafts 폴더에 이 앨범과 상관없는 다른 프로젝트가 섞여 있을 때 걸러내는
    용도로도 쓴다."""
    draft_path = os.path.join(combined_dir, "draft_content.json")
    if not os.path.isfile(draft_path):
        return None
    draft = load_json(draft_path)
    audio_track = next((t for t in draft["tracks"] if t.get("type") == "audio"), None)
    if not audio_track:
        return None
    materials_by_id = {m["id"]: m for m in draft["materials"].get("audios", [])}
    order = []
    for seg in audio_track["segments"]:
        mat = materials_by_id.get(seg.get("material_id"))
        if mat and mat.get("name"):
            order.append(strip_mastered_suffix(mat["name"]))
    return order or None


def collect_referenced_material_ids(segment):
    ids = []
    if segment.get("material_id"):
        ids.append(segment["material_id"])
    for ref in segment.get("extra_material_refs") or []:
        ids.append(ref)
    return ids


def find_material(materials, material_id):
    for category, items in materials.items():
        for item in items:
            if isinstance(item, dict) and item.get("id") == material_id:
                return category, item
    return None, None


def first_caption_text(src_materials, track):
    """텍스트 트랙 이름을 짓기 위해, 그 트랙 첫 세그먼트의 실제 자막 내용을 읽어온다."""
    segments = track.get("segments") or []
    if not segments:
        return ""
    material_id = segments[0].get("material_id")
    _, item = find_material(src_materials, material_id)
    if not item:
        return ""
    try:
        return json.loads(item.get("content", "{}")).get("text", "")
    except (json.JSONDecodeError, TypeError):
        return ""


def merge_projects(project_dirs, drafts_folder, combined_name):
    merged_segments = {"audio": [], "이미지": []}
    text_track_segments = []  # index = 그 곡에서 몇 번째 텍스트 트랙인지
    text_track_samples = []  # 트랙 이름을 짓기 위한 예시 텍스트(트랙 인덱스별로 하나씩)
    combined_materials = {}
    seen_material_ids = set()
    cursor = 0
    merged_count = 0

    for project_dir in project_dirs:
        song_name = os.path.basename(project_dir.rstrip("\\/"))
        draft_path = os.path.join(project_dir, "draft_content.json")
        if not os.path.isfile(draft_path):
            print(f"[건너뜀] {song_name}: draft_content.json이 없습니다.")
            continue

        draft = load_json(draft_path)
        src_materials = draft["materials"]

        audio_track = next((t for t in draft["tracks"] if t.get("type") == "audio"), None)
        if not audio_track or not audio_track.get("segments"):
            print(f"[건너뜀] {song_name}: 오디오 트랙이 없습니다.")
            continue
        song_duration = max(
            seg["target_timerange"]["start"] + seg["target_timerange"]["duration"]
            for seg in audio_track["segments"]
        )

        print(f"  이어붙이는 중: {song_name} ({song_duration / 1_000_000:.1f}초)")

        def copy_segments(track, dest_list):
            for seg in track.get("segments", []):
                seg_copy = json.loads(json.dumps(seg))
                seg_copy["target_timerange"]["start"] += cursor
                for mid in collect_referenced_material_ids(seg):
                    if not mid or mid in seen_material_ids:
                        continue
                    category, item = find_material(src_materials, mid)
                    if item is None:
                        continue
                    combined_materials.setdefault(category, []).append(item)
                    seen_material_ids.add(mid)
                dest_list.append(seg_copy)

        text_index = 0
        for track in draft["tracks"]:
            ttype = track.get("type")
            name = track.get("name")
            if ttype == "audio" and name == "audio":
                copy_segments(track, merged_segments["audio"])
            elif ttype == "video" and name == "이미지":
                copy_segments(track, merged_segments["이미지"])
            elif ttype == "text":
                while len(text_track_segments) <= text_index:
                    text_track_segments.append([])
                    text_track_samples.append("")
                if not text_track_samples[text_index]:
                    text_track_samples[text_index] = first_caption_text(src_materials, track)
                copy_segments(track, text_track_segments[text_index])
                text_index += 1
            # (스티커 등 텍스트가 아닌 장식 트랙은 합치지 않는다)

        cursor += song_duration
        merged_count += 1

    text_track_names = []
    for i, sample in enumerate(text_track_samples, 1):
        if sample and HANGUL_RE.search(sample):
            text_track_names.append(f"자막{i}-한글")
        elif sample:
            text_track_names.append(f"자막{i}-영어")
        else:
            text_track_names.append(f"자막{i}")

    return merged_segments, text_track_segments, text_track_names, combined_materials, cursor, merged_count


def build_combined_project(
    merged_segments, text_track_segments, text_track_names, combined_materials,
    total_duration, drafts_folder, combined_name,
):
    draft_folder = cc.DraftFolder(drafts_folder)
    try:
        script = draft_folder.create_draft(combined_name, 1920, 1080, fps=30, allow_replace=True)
    except PermissionError:
        print(
            f"\n!! '{combined_name}' 프로젝트가 지금 캡컷에서 열려 있어서 새로 만들 수 없습니다.\n"
            f"   캡컷에서 그 프로젝트를 닫은 뒤 다시 실행해 주세요."
        )
        sys.exit(1)

    if merged_segments["audio"]:
        script.add_track(cc.TrackType.audio)
    if merged_segments["이미지"]:
        script.add_track(cc.TrackType.video, "이미지")
    for track_name, segments in zip(text_track_names, text_track_segments):
        if segments:
            script.add_track(cc.TrackType.text, track_name)

    script.save()

    draft_path = os.path.join(drafts_folder, combined_name, "draft_content.json")
    data = load_json(draft_path)

    all_named_segments = dict(merged_segments)
    all_named_segments.update(zip(text_track_names, text_track_segments))

    for track in data["tracks"]:
        name = track.get("name") or ("audio" if track.get("type") == "audio" else None)
        track["segments"] = all_named_segments.get(name, [])

    for category in data["materials"]:
        data["materials"][category] = combined_materials.get(category, [])

    data["duration"] = total_duration

    save_json(draft_path, data)


def main():
    if len(sys.argv) < 2:
        print("사용법: python capcut_merge_edited_projects.py <CapCut Drafts 폴더> [전곡 프로젝트 이름]")
        sys.exit(1)

    drafts_folder = sys.argv[1]
    if not os.path.isdir(drafts_folder):
        print(f"!! 폴더를 찾을 수 없습니다: {drafts_folder}")
        sys.exit(1)

    existing_combined = find_existing_combined(drafts_folder)
    combined_name = None

    if len(sys.argv) > 2 and sys.argv[2].strip():
        combined_name = sys.argv[2].strip()
    elif existing_combined:
        old_name = os.path.basename(existing_combined)
        if old_name.endswith(" 전곡"):
            combined_name = old_name[: -len(" 전곡")] + " 수정전곡"
        else:
            combined_name = old_name + " 수정전곡"
        print(f"기존 전곡 프로젝트는 그대로 두고, 새 이름으로 만듭니다: {combined_name}")
    else:
        combined_name = os.path.basename(drafts_folder.rstrip("\\/")) + " 수정전곡"

    all_dirs = [
        d for d in os.listdir(drafts_folder)
        if os.path.isdir(os.path.join(drafts_folder, d))
        and not d.endswith("전곡")
        and not d.startswith(".")
    ]

    song_order = get_song_order_from_combined(existing_combined) if existing_combined else None
    if song_order:
        found = set(all_dirs)
        skipped_others = [d for d in all_dirs if d not in song_order]
        all_dirs = [title for title in song_order if title in found]
        if skipped_others:
            print(f"[안내] 이 앨범과 상관없는 다른 프로젝트라서 제외: {', '.join(skipped_others)}")
        missing = [title for title in song_order if title not in found]
        if missing:
            print(f"[주의] 원래 있던 곡 폴더를 찾을 수 없습니다: {', '.join(missing)}")
        print("원본 전곡 프로젝트의 순서를 그대로 사용합니다.")
    else:
        # 폴더의 "만든 날짜"를 쓴다 - 원래 만들 때(process_song이 순서대로 실행되며
        # 폴더를 생성한 시점) 순서를 그대로 보존하고, 나중에 캡컷에서 수정한 시점
        # (수정 날짜)에는 영향을 받지 않는다.
        all_dirs.sort(key=lambda d: os.path.getctime(os.path.join(drafts_folder, d)))

    project_dirs = [os.path.join(drafts_folder, d) for d in all_dirs]

    if not project_dirs:
        print("!! 합칠 곡 프로젝트를 찾지 못했습니다.")
        sys.exit(1)

    print(f"총 {len(project_dirs)}곡을 '{combined_name}'(으)로 새로 합칩니다.\n")

    merged_segments, text_track_segments, text_track_names, combined_materials, total_duration, merged_count = (
        merge_projects(project_dirs, drafts_folder, combined_name)
    )

    if merged_count == 0:
        print("!! 합칠 수 있는 곡이 없습니다.")
        sys.exit(1)

    build_combined_project(
        merged_segments, text_track_segments, text_track_names, combined_materials,
        total_duration, drafts_folder, combined_name,
    )

    print(
        f"\n[완료] 전곡 '{combined_name}': 총 길이 {total_duration / 1_000_000:.1f}초 "
        f"({merged_count}곡 이어붙임, 수정된 자막 그대로 반영됨)"
    )


if __name__ == "__main__":
    main()
