"""일괄 작업: md 파일 1개 이상을 넣으면 노래 → 이미지·영상 → 썸네일을 차례로 끝까지 한다.

- 질문은 처음에 한 번에 다 묻고, 그다음에는 사람 손 없이 끝까지 간다 (나중에 예약 실행하기 쉽게).
- 노래(CAVN)      : 모든 md
- 이미지·영상(Flow): 연주곡 md (경음악·클래식)만. 가요·칸쏘네·미사곡처럼 가사가 있는 md 는 건너뜀
- 썸네일          : md 에 썸네일 문구가 있으면
- 한 단계가 실패해도 다음 단계·다음 md 로 넘어가고, 마지막에 실패한 것만 모아서 알려 준다.
  다시 실행하면 끝난 곡·트랙·썸네일은 건너뛰고 남은 것만 한다.
- 실행 기록: F:\\음악생성\\<md 이름>\\일괄작업기록.txt

기존 프로그램(cavn_maker.py, flow_maker.py, thumb_maker.py, menu.py)은 그대로 두고 그것들을 차례로 부른다.

실행:  python batch_maker.py "앨범1.md" "앨범2.md"
       python batch_maker.py "앨범.md" --master 0     (마스터링 질문 없이 '안 함')
"""

import argparse
import re
import sys
import time
import traceback
from pathlib import Path

import cavn_maker
import flow_maker
import thumb_maker
from md_parser import parse_md_file

DEFAULT_OUT = r"F:\음악생성"
YES = ("y", "yes", "ㅛ", "예", "네")
NO = ("n", "no", "ㅜ", "아니요", "아니오")


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


class Tee:
    """까만 창에 나오는 글을 기록 파일에도 같이 적는다."""

    def __init__(self, stream, path):
        self.stream = stream
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = open(path, "a", encoding="utf-8")

    def write(self, text):
        self.stream.write(text)
        self.file.write(text)
        self.file.flush()

    def flush(self):
        self.stream.flush()

    def close(self):
        self.file.close()


def split_paths(line):
    """까만 창에 파일 여러 개를 끌어다 놓으면 "a b.md" c.md 처럼 한 줄로 들어온다."""
    return [a or b for a, b in re.findall(r'"([^"]+)"|(\S+\.md)', line, re.I)]


def ask_md_files(given):
    files = [Path(p.strip('"')) for p in given]
    if not files:
        print("md 파일을 이 창에 끌어다 놓고 Enter 를 누르세요. (여러 개를 한꺼번에 놓아도 됩니다)")
        print("다 넣었으면 그냥 Enter 를 누르세요.")
        while True:
            line = input(f"md 파일 {len(files) + 1}: ").strip()
            if not line:
                if files:
                    break
                continue
            files += [Path(p) for p in split_paths(line) or [line.strip('"')]]
    ok = []
    for f in files:
        if f.is_file():
            ok.append(f)
        else:
            print(f"!! 파일을 찾지 못해 뺍니다: {f}")
    return ok


class Plan:
    def __init__(self, md):
        self.md = md
        self.tracks = parse_md_file(md)
        self.instrumental = bool(self.tracks) and all(t.classical for t in self.tracks)
        self.images = self.instrumental and any(t.image_prompt for t in self.tracks)
        self.thumbs = thumb_maker.parse_thumbnails(md.read_text(encoding="utf-8-sig"))
        self.master = 0

    @property
    def kind(self):
        return "연주곡(경음악·클래식)" if self.instrumental else "가사 있는 곡(가요·칸쏘네·미사곡)"


def ask_master(plan):
    """종류에 맞는 기본값을 보여 주고, Enter 만 누르면 그 기본값."""
    default = 0 if plan.instrumental else 1
    hint = "Y/n" if default else "y/N"
    while True:
        ans = input(f"  AI 마스터링 할까요? [{hint}] (Enter = {'함' if default else '안 함'}): ").strip().lower()
        if not ans:
            return default
        if ans in YES:
            return 1
        if ans in NO:
            return 0


def run_step(name, func, failed, md):
    print(f"\n[{now()}] ===== {md.stem} : {name} 시작 =====", flush=True)
    try:
        func()
        print(f"[{now()}] ===== {md.stem} : {name} 끝 =====", flush=True)
    except (Exception, SystemExit) as e:   # 한 단계가 실패해도 다음 단계는 계속
        print(f"[{now()}] !! {md.stem} : {name} 실패: {e}", flush=True)
        traceback.print_exc(file=sys.stdout)
        failed.append(f"{md.stem} : {name} ({str(e).splitlines()[0] if str(e) else type(e).__name__})")


def prepare_flow():
    """Flow 프로젝트가 열린 탭이 있는지 지금(사람이 있을 때) 확인해 둔다. 없으면 열어 달라고 한다."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        flow_maker.connect(pw)


def main():
    ap = argparse.ArgumentParser(description="노래 → 이미지·영상 → 썸네일 일괄 작업")
    ap.add_argument("md", nargs="*", help="음악 md 파일 (여러 개 가능, 없으면 실행할 때 물어봄)")
    ap.add_argument("--out", default=DEFAULT_OUT, help=f"저장 폴더 (기본 {DEFAULT_OUT})")
    ap.add_argument("--master", type=int, choices=[0, 1], help="모든 md 의 마스터링 0=안 함, 1=함 (안 주면 md 마다 물어봄)")
    ap.add_argument("--yes", action="store_true", help="'시작할까요?' 를 묻지 않고 바로 시작")
    args = ap.parse_args()

    files = ask_md_files(args.md)
    if not files:
        print("할 md 파일이 없습니다.")
        return

    print("\n================================================")
    print(f"  일괄 작업: md {len(files)}개")
    print("================================================")
    plans = []
    for i, md in enumerate(files, 1):
        plan = Plan(md)
        if not plan.tracks:
            print(f"\n{i}. {md.name}\n  !! 곡을 찾지 못해 뺍니다")
            continue
        steps = ["노래"] + (["이미지·영상"] if plan.images else []) + (["썸네일"] if plan.thumbs else [])
        print(f"\n{i}. {md.name}")
        print(f"  종류: {plan.kind}, {len(plan.tracks)}곡")
        print(f"  할 일: {' → '.join(steps)}")
        if not plan.instrumental:
            print("  (가사 있는 곡이라 이미지·영상은 하지 않습니다)")
        plan.master = args.master if args.master is not None else ask_master(plan)
        plans.append(plan)
    if not plans:
        return
    print("\n마스터링: " + ", ".join(f"{p.md.stem}={'함' if p.master else '안 함'}" for p in plans))
    print("하나 끝나는 데 최대 3~4시간 걸릴 수 있습니다. 실행 중에는 크롬 창을 건드리지 마세요.")
    if not args.yes and input("시작할까요? (y/n): ").strip().lower() not in YES:
        return

    # 밤새 돌다가 Flow 에서 멈추지 않게, 사람이 있을 때 Flow 프로젝트를 열어 둔다
    if any(p.images or p.thumbs for p in plans):
        print("\nFlow 프로젝트가 열려 있는지 확인합니다.")
        try:
            prepare_flow()
        except (Exception, SystemExit) as e:
            print(f"!! Flow 확인 실패: {e}  (이미지·썸네일 단계에서 다시 시도합니다)")

    failed = []
    started = now()
    stdout = sys.stdout
    for k, plan in enumerate(plans, 1):
        md = plan.md
        album_dir = Path(args.out) / thumb_maker.safe_filename(md.stem)
        tee = Tee(stdout, album_dir / "일괄작업기록.txt")
        sys.stdout = tee
        try:
            print(f"\n################ [{k}/{len(plans)}] {md.name}  ({now()}) ################")
            run_step("노래", lambda: cavn_maker.run(md, args.out, confirm=False, master=plan.master, ask_album=False), failed, md)
            if plan.images:
                run_step("이미지·영상", lambda: flow_maker.run(md, args.out, confirm=False), failed, md)
            if plan.thumbs:
                run_step("썸네일", lambda: thumb_maker.run(md, args.out, confirm=False), failed, md)
        finally:
            sys.stdout = stdout
            tee.close()

    print("\n================================================")
    print(f"  일괄 작업 끝  ({started} ~ {now()})")
    print("================================================")
    if failed:
        print("실패한 것 (다시 실행하면 남은 것만 이어서 합니다):")
        for f in failed:
            print(f"  - {f}")
    else:
        print("모두 성공했습니다.")
    for p in plans:
        print(f"  기록: {Path(args.out) / thumb_maker.safe_filename(p.md.stem) / '일괄작업기록.txt'}")


if __name__ == "__main__":
    main()
