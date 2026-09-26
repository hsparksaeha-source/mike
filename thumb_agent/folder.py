"""썸네일 폴더를 읽어서 파일 -> 언어코드 로 연결한다."""

from dataclasses import dataclass, field
from pathlib import Path

from .languages import LanguageTable

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp"}
MAX_BYTES = 2 * 1024 * 1024  # YouTube 썸네일 권장 최대 용량 2MB


@dataclass
class FolderScan:
    matched: dict = field(default_factory=dict)      # code -> Path
    unmatched: list = field(default_factory=list)    # 언어를 알 수 없는 파일
    duplicates: list = field(default_factory=list)   # (code, 버려진 Path, 사용하는 Path)
    too_big: list = field(default_factory=list)      # 2MB 초과 파일


def scan_folder(folder, table: LanguageTable) -> FolderScan:
    folder = Path(folder).expanduser()
    if not folder.is_dir():
        raise FileNotFoundError(f"폴더를 찾을 수 없습니다: {folder}")

    result = FolderScan()
    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTS:
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
    if scan.too_big:
        print(f"\n[주의] 2MB가 넘는 파일은 YouTube에서 거부될 수 있습니다:")
        for path in scan.too_big:
            print(f"  - {path.name} ({path.stat().st_size / 1024 / 1024:.1f}MB)")
