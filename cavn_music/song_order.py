"""노래 폴더의 파일 날짜를 md 트랙 순서대로 맞춘다.

캡컷 조립 프로그램(대중가요 조립, 전곡 재조립, 클래식 일괄·두바퀴 조립)은 노래 파일을
'만든 날짜(생성 시간)' 순서로 줄 세운다. 3·4번 곡을 나중에 받으면 맨 뒤로 가서
곡과 이미지 짝이 어긋난다. 그래서 파일 내용은 그대로 두고 날짜만 1번 곡 → 2번 곡 … 순서로 바꾼다.

- CAVN 노래 프로그램(cavn_maker.py)이 끝날 때마다 자동으로 한다 (일괄 작업 포함).
- 이미 받아 둔 앨범이나, 노래 폴더를 다른 드라이브로 복사해서 날짜가 바뀐 경우:
  '노래순서맞추기.bat' 에 md 파일을 끌어다 놓으면 된다.

실행:  python song_order.py "앨범.md"              (F:\\음악생성\\<md 이름>\\노래)
       python song_order.py "앨범.md" --dir "D:\\다른곳\\노래"
"""

import argparse
import os
import time
from pathlib import Path

from md_parser import ask_md_path, parse_md_file

DEFAULT_OUT = r"F:\음악생성"
TRACK_STEP_SEC = 60      # 곡과 곡 사이 날짜 간격
# 한 곡 안에서의 순서: 긴 곡(제목.*) → 짧은 곡(제목 (1).*) → 마스터링 → 나머지
SUFFIX_ORDER = ["", " (1)", "_mastered"]


def _set_times(path, when):
    """파일의 수정 시간과 (윈도우면) 만든 시간을 when 으로."""
    os.utime(path, (when, when))
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes
    ft = int((when + 11644473600) * 10_000_000)          # 1601년부터 100나노초 단위
    filetime = wintypes.FILETIME(ft & 0xFFFFFFFF, ft >> 32)
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateFileW.restype = wintypes.HANDLE
    handle = kernel32.CreateFileW(str(path), 0x100, 0x7, None, 3, 0x02000000, None)   # FILE_WRITE_ATTRIBUTES
    if handle in (None, wintypes.HANDLE(-1).value):
        raise OSError(f"날짜를 바꿀 수 없습니다: {path}")
    try:
        if not kernel32.SetFileTime(handle, ctypes.byref(filetime), ctypes.byref(filetime), ctypes.byref(filetime)):
            raise OSError(f"날짜를 바꿀 수 없습니다: {path}")
    finally:
        kernel32.CloseHandle(handle)


def _rank(stem, title):
    """이 파일이 이 제목의 것이면 한 곡 안에서의 순서, 아니면 None."""
    if stem == title:
        return 0
    for k, suffix in enumerate(SUFFIX_ORDER[1:], 1):
        if stem == title + suffix:
            return k
    if stem.startswith(title + "_") or stem.startswith(title + " ("):
        return len(SUFFIX_ORDER)
    return None


def fix_song_order(song_dir, tracks, base=None, quiet=False):
    """song_dir 의 파일 날짜를 트랙 번호 순서로 맞춘다. 바꾼 파일 수를 돌려준다."""
    song_dir = Path(song_dir)
    if not song_dir.is_dir():
        return 0
    files = [p for p in song_dir.iterdir() if p.is_file() and not p.name.startswith(".")]
    # 긴 제목부터 짝지어야 'Love' 와 'Love Song' 이 섞이지 않는다
    import re
    names = [(t, re.sub(r'[\\/:*?"<>|]', "_", t.title).strip().rstrip(".")) for t in tracks]   # 파일 이름에 쓴 제목
    names.sort(key=lambda x: len(x[1]), reverse=True)
    order = []
    for p in files:
        for t, title in names:
            rank = _rank(p.stem, title)
            if rank is not None:
                order.append((t.number, rank, p.name, p))
                break
    order.sort()
    if not order:
        return 0
    base = base or (time.time() - len(tracks) * TRACK_STEP_SEC - 3600)   # 지금보다 조금 전부터
    count = 0
    for number, rank, _, p in order:
        try:
            _set_times(p, base + number * TRACK_STEP_SEC + rank)
            count += 1
        except OSError as e:
            print(f"  !! {e}")
    if not quiet:
        print(f"노래 파일 {count}개의 날짜를 트랙 순서(1번 → {max(t.number for t in tracks)}번)로 맞췄습니다: {song_dir}")
    return count


def main():
    ap = argparse.ArgumentParser(description="노래 파일 날짜를 md 트랙 순서대로 맞추기 (캡컷 조립 순서용)")
    ap.add_argument("md", nargs="?", help="음악 md 파일 (없으면 실행할 때 물어봄)")
    ap.add_argument("--out", default=DEFAULT_OUT, help=f"저장 폴더 (기본 {DEFAULT_OUT})")
    ap.add_argument("--dir", help="노래 폴더를 직접 지정 (기본: <저장 폴더>\\<md 이름>\\노래)")
    args = ap.parse_args()
    md = Path(ask_md_path(args.md))
    import cavn_maker
    song_dir = Path(args.dir) if args.dir else Path(args.out) / cavn_maker.safe_filename(md.stem) / "노래"
    tracks = parse_md_file(md)
    if not song_dir.is_dir():
        print(f"!! 노래 폴더가 없습니다: {song_dir}")
        return
    if not fix_song_order(song_dir, tracks):
        print("md 의 곡 제목과 맞는 노래 파일을 찾지 못했습니다.")


if __name__ == "__main__":
    main()
