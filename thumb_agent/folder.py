"""썸네일 폴더를 읽어서 파일 -> 언어코드 로 연결한다."""

from dataclasses import dataclass, field
from pathlib import Path

from .languages import LanguageTable

# YouTube 가 바로 받는 형식
UPLOAD_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp"}
# 크롬에서 저장하면 흔히 생기는 형식 (올릴 때 자동으로 jpg 로 바꿔서 올림)
CONVERT_EXTS = {".jfif", ".jpe", ".webp", ".avif", ".heic"}
IMAGE_EXTS = UPLOAD_EXTS | CONVERT_EXTS
MAX_BYTES = 2 * 1024 * 1024  # YouTube 썸네일 권장 최대 용량 2MB


@dataclass
class FolderScan:
    matched: dict = field(default_factory=dict)      # code -> Path
    unmatched: list = field(default_factory=list)    # 언어를 알 수 없는 파일
    duplicates: list = field(default_factory=list)   # (code, 버려진 Path, 사용하는 Path)
    too_big: list = field(default_factory=list)      # 2MB 초과 파일
    other_files: list = field(default_factory=list)  # 이미지가 아니라서 무시한 파일


def scan_folder(folder, table: LanguageTable) -> FolderScan:
    folder = Path(folder).expanduser()
    if not folder.is_dir():
        raise FileNotFoundError(f"폴더를 찾을 수 없습니다: {folder}")

    result = FolderScan()
    for path in sorted(folder.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in IMAGE_EXTS:
            if not path.name.startswith(".") and path.name.lower() != "desktop.ini":
                result.other_files.append(path)
            continue
        code = table.match_filename(path.stem)
        if code is None:
            result.unmatched.append(path)
            continue
        if code in result.matched:
            result.duplicates.append((code, path, result.matched[code]))
            continue
        result.matched[code] = path
        if path.stat().st_size > MAX_BYTES:
            result.too_big.append(path)
    return result


def print_scan(scan: FolderScan, table: LanguageTable) -> None:
    print(f"\n[폴더 확인] 언어가 확인된 썸네일: {len(scan.matched)}개")
    for code, path in sorted(scan.matched.items(), key=lambda kv: table.display_name(kv[0])):
        print(f"  - {table.display_name(code):<16} ({code:<7}) <- {path.name}")
    if scan.unmatched:
        print(f"\n[주의] 어느 나라 것인지 알 수 없는 파일 {len(scan.unmatched)}개 (건너뜀):")
        for path in scan.unmatched:
            print(f"  - {path.name}")
        print("  -> 파일 이름을 'gu.jpg' 또는 '구자라트어.jpg' 처럼 바꿔 주세요.")
    if scan.duplicates:
        print(f"\n[주의] 같은 언어의 파일이 여러 개 있습니다 (첫 번째 파일만 사용):")
        for code, dropped, kept in scan.duplicates:
            print(f"  - {table.display_name(code)}: {kept.name} 사용, {dropped.name} 무시")
    if scan.other_files:
        print(f"\n[주의] 이미지로 인식되지 않은 파일 {len(scan.other_files)}개:")
        for path in scan.other_files:
            print(f"  - {path.name}")
    if scan.too_big:
        print(f"\n[주의] 2MB가 넘는 파일은 YouTube에서 거부될 수 있습니다:")
        for path in scan.too_big:
            print(f"  - {path.name} ({path.stat().st_size / 1024 / 1024:.1f}MB)")


def ensure_uploadable(path, convert_dir) -> Path:
    """YouTube 가 받지 않는 형식(jfif, webp 등)이면 jpg 로 바꾼 사본의 경로를 돌려준다."""
    path = Path(path)
    if path.suffix.lower() in UPLOAD_EXTS:
        return path
    from PIL import Image

    convert_dir = Path(convert_dir)
    convert_dir.mkdir(parents=True, exist_ok=True)
    target = convert_dir / f"{path.stem}.jpg"
    with Image.open(path) as img:
        img.convert("RGB").save(target, "JPEG", quality=92)
    return target


def describe_scan(scan: FolderScan, limit=8) -> str:
    """폴더에서 무엇을 찾았는지 사람이 읽을 수 있게 정리 (썸네일이 연결되지 않을 때 안내용)."""
    def names(paths):
        shown = ", ".join(p.name for p in paths[:limit])
        return shown + (f" 외 {len(paths) - limit}개" if len(paths) > limit else "")

    lines = [f"폴더에서 언어가 확인된 이미지: {len(scan.matched)}개"]
    if scan.unmatched:
        lines.append(f"언어를 알 수 없는 이미지 {len(scan.unmatched)}개: {names(scan.unmatched)}")
        lines.append("  → 파일 이름을 gu.jpg, 구자라트어.jpg 처럼 언어로 바꿔 주세요.")
    if scan.other_files:
        lines.append(f"이미지로 인식되지 않은 파일 {len(scan.other_files)}개: {names(scan.other_files)}")
        lines.append("  → jpg / png 형식인지 확인해 주세요.")
    if not scan.matched and not scan.unmatched and not scan.other_files:
        lines.append("폴더가 비어 있습니다. 이미지가 하위 폴더 안에 있다면 그 폴더를 선택해 주세요.")
    return "\n".join(lines)
