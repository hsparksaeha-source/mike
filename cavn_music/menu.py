"""음악 · 이미지 자동화 메뉴: 1 = 음악(CAVN), 2 = 이미지·영상(Flow), 3 = 둘 다, 4 = 썸네일"""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from md_parser import ask_md_path, ask_only  # noqa: E402


def main():
    md = ask_md_path(sys.argv[1] if len(sys.argv) > 1 else None)
    print("\n  1 = 음악 만들기 (CAVN AI)")
    print("  2 = 이미지 15장 + 영상 만들기 (Google Flow)")
    print("  3 = 둘 다 (음악 먼저, 이어서 이미지)")
    print("  4 = 유튜브 썸네일 만들기 (Flow 배경 + 캡컷 초안)")
    choice = ""
    while choice not in ("1", "2", "3", "4"):
        choice = input("번호를 고르세요 (1/2/3/4): ").strip()
    if choice == "4":
        subprocess.run([sys.executable, "-u", str(HERE / "thumb_maker.py"), md])
        return
    only = ask_only()
    extra = ["--only", ",".join(map(str, sorted(only)))] if only else []
    scripts = {"1": ["cavn_maker.py"], "2": ["flow_maker.py"], "3": ["cavn_maker.py", "flow_maker.py"]}[choice]
    for script in scripts:
        subprocess.run([sys.executable, "-u", str(HERE / script), md, *extra])


if __name__ == "__main__":
    main()
