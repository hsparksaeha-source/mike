"""
캡컷 초안 - 사진 클립에 천천히 커지는 줌(켄 번즈) 효과 자동 넣기

이미 만들어진 캡컷 초안(클래식·가요 조립 프로그램이 만든 것, 캡컷에서 손본 것 모두)을 열어서
사진 클립마다 크기 키프레임 2개를 넣습니다.
  - 클립 처음: 항상 100%
  - 클립 끝:   110~120% 등 원하는 비율 (넣은 숫자 그대로)
  캡컷에서 손으로 넣었던 크기 키프레임이 있어도 지우고 100% → 넣은 숫자로 새로 넣습니다.
  (캡컷은 키프레임이 있는 클립의 기본 크기 칸에 마지막 키프레임 값을 적어 두기 때문에,
   그 값을 시작점으로 쓰면 110% → 126% 처럼 엉뚱하게 커짐)
그래서 사진이 천천히 다가오는 것처럼 움직여 보입니다.

- 동영상 클립은 이미 움직이므로 건드리지 않습니다 (사진만).
- 다시 실행하면 예전 줌을 지우고 새 비율로 다시 넣습니다 (줌이 두 번 겹치지 않음).
- 처음 실행할 때 원래 파일을 draft_content.before_zoom.json 으로 한 번 백업해 둡니다.
- 캡컷이 켜져 있으면 캡컷이 파일을 덮어쓸 수 있으니, 캡컷을 완전히 끈 뒤 실행하세요.

넣을 수 있는 폴더 (어느 것이든):
  - "CapCut Drafts" 폴더  -> 그 안의 모든 초안
  - 앨범 폴더 (안에 "CapCut Drafts"가 있는 폴더) -> 그 안의 모든 초안
  - 초안 폴더 하나 (안에 draft_content.json 이 있는 폴더) -> 그 초안만

사용법:
  python capcut_zoom_keyframes.py <폴더> [끝 크기 %=115]
"""

import json
import os
import shutil
import sys
import uuid

DEFAULT_END_PERCENT = 115
DRAFT_FILE = "draft_content.json"
BACKUP_FILE = "draft_content.before_zoom.json"
SCALE_PROPS = ("KFTypeScaleX", "KFTypeScaleY", "UNIFORM_SCALE")


def find_drafts(path):
    """폴더 안에서 처리할 초안 폴더 목록."""
    path = path.strip().strip('"').strip()
    if os.path.isfile(os.path.join(path, DRAFT_FILE)):
        return [path]
    drafts_dir = path
    if os.path.isdir(os.path.join(path, "CapCut Drafts")):
        drafts_dir = os.path.join(path, "CapCut Drafts")
    if not os.path.isdir(drafts_dir):
        return []
    found = []
    for name in sorted(os.listdir(drafts_dir)):
        sub = os.path.join(drafts_dir, name)
        if os.path.isfile(os.path.join(sub, DRAFT_FILE)):
            found.append(sub)
    return found


def _keyframe(time_offset, value):
    return {
        "curveType": "Line",
        "graphID": "",
        "left_control": {"x": 0.0, "y": 0.0},
        "right_control": {"x": 0.0, "y": 0.0},
        "id": uuid.uuid4().hex,
        "time_offset": int(time_offset),
        "values": [float(value)],
    }


def add_zoom_to_content(data, end_ratio):
    """draft_content 데이터의 사진 클립마다 줌 키프레임을 넣는다. 넣은 클립 수를 돌려준다."""
    photo_ids = {
        m.get("id") for m in data.get("materials", {}).get("videos", [])
        if m.get("type") == "photo"
    }
    count = 0
    for track in data.get("tracks", []):
        if track.get("type") != "video":
            continue
        for seg in track.get("segments", []):
            if seg.get("material_id") not in photo_ids:
                continue
            duration = (seg.get("target_timerange") or {}).get("duration", 0)
            if duration <= 0:
                continue
            clip = seg.setdefault("clip", {})
            clip["scale"] = {"x": 1.0, "y": 1.0}  # 시작은 항상 100%
            # 예전에 넣은 크기 키프레임은 지우고 새로 넣는다
            others = [k for k in seg.get("common_keyframes") or []
                      if k.get("property_type") not in SCALE_PROPS]
            others.append({
                "id": uuid.uuid4().hex,
                "keyframe_list": [_keyframe(0, 1.0), _keyframe(duration, end_ratio)],
                "material_id": "",
                "property_type": "KFTypeScaleX",
            })
            seg["common_keyframes"] = others
            seg["uniform_scale"] = {"on": True, "value": 1.0}
            count += 1
    return count


def process_draft(draft_dir, end_ratio):
    content_path = os.path.join(draft_dir, DRAFT_FILE)
    backup_path = os.path.join(draft_dir, BACKUP_FILE)
    with open(content_path, encoding="utf-8") as f:
        data = json.load(f)
    if not os.path.exists(backup_path):
        shutil.copy2(content_path, backup_path)
    count = add_zoom_to_content(data, end_ratio)
    with open(content_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return count


def main():
    if len(sys.argv) < 2:
        print("사용법: python capcut_zoom_keyframes.py <CapCut Drafts 폴더 / 앨범 폴더 / 초안 폴더> [끝 크기 %=115]")
        sys.exit(1)

    folder = sys.argv[1]
    percent_text = sys.argv[2].strip() if len(sys.argv) > 2 and sys.argv[2].strip() else str(DEFAULT_END_PERCENT)
    try:
        percent = float(percent_text.rstrip("%"))
    except ValueError:
        print(f"!! 끝 크기 '{percent_text}'을(를) 숫자로 읽지 못했습니다. 예: 115")
        sys.exit(1)
    if not 100 < percent <= 200:
        print(f"!! 끝 크기는 101 ~ 200 사이로 넣어 주세요. (넣은 값: {percent_text})")
        sys.exit(1)

    drafts = find_drafts(folder)
    if not drafts:
        print(f"!! '{folder}' 에서 캡컷 초안을 찾지 못했습니다.")
        print("   'CapCut Drafts' 폴더나, 그 폴더가 들어 있는 앨범 폴더를 넣어 주세요.")
        sys.exit(1)

    print(f"사진 줌: 클립 처음 100% → 끝 {percent:g}%")
    print(f"초안 {len(drafts)}개를 처리합니다.\n")
    total = 0
    for i, draft in enumerate(drafts, 1):
        name = os.path.basename(draft)
        try:
            count = process_draft(draft, percent / 100)
            total += count
            print(f"[{i}/{len(drafts)}] {name}: 사진 클립 {count}개에 줌을 넣었습니다.")
        except Exception as e:
            print(f"[실패] {name}: {e}")
    print(f"\n=== 완료 === 사진 클립 모두 {total}개")
    print("캡컷을 열어 확인해 보세요.")


if __name__ == "__main__":
    main()
