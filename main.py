"""유튜브 언어별 썸네일 자동 등록 프로그램.

사용법 (자세한 설명은 README.md):
  python main.py                                   # 질문에 답하면서 진행 (가장 쉬움)
  python main.py login                             # 처음 한 번: 유튜브 로그인
  python main.py check  --folder "썸네일폴더"        # 파일 이름 -> 언어 연결 확인
  python main.py upload --video 영상주소 --folder "썸네일폴더"
  python main.py batch  --jobs jobs.csv            # 여러 영상 한꺼번에 (영상주소,폴더)
"""

import argparse
import csv
import json
import sys
from pathlib import Path

from thumb_agent.folder import print_scan, scan_folder
from thumb_agent.languages import LANGUAGES, LanguageTable

BASE_DIR = Path(__file__).resolve().parent


def load_config(path):
    path = Path(path)
    if not path.is_absolute():
        path = BASE_DIR / path
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def browser_options(cfg, args):
    return dict(
        profile_dir=str(BASE_DIR / cfg.get("profile_dir", "browser_profile")),
        channel=cfg.get("browser_channel", "chrome"),
        cdp_url=args.cdp or cfg.get("cdp_url"),
        slow_mo=int(cfg.get("slow_mo_ms", 100)),
    )


def cmd_login(cfg, args):
    from thumb_agent.browser import open_studio_page

    with open_studio_page(**browser_options(cfg, args)) as page:
        page.goto("https://studio.youtube.com/")
        print("\n브라우저에서 구글 계정으로 로그인하고, 썸네일을 넣을 채널을 선택해 주세요.")
        input("로그인이 끝나고 YouTube 스튜디오 화면이 보이면 여기서 Enter 를 누르세요... ")
    print("로그인 정보가 저장되었습니다. 다음부터는 바로 업로드할 수 있습니다.")


def cmd_check(cfg, args, table):
    scan = scan_folder(args.folder, table)
    print_scan(scan, table)
    return scan


def select_codes(scan, only):
    thumbs = dict(scan.matched)
    if only:
        wanted = {c.strip() for c in only.split(",") if c.strip()}
        thumbs = {c: p for c, p in thumbs.items() if c in wanted}
    return thumbs


def run_jobs(cfg, args, table, jobs):
    """jobs: [(video, folder)] 를 차례대로 처리."""
    from thumb_agent.studio import parse_video_id

    prepared = []
    for video, folder in jobs:
        video_id = parse_video_id(video)
        scan = scan_folder(folder, table)
        print(f"\n===== 동영상 {video_id} / 폴더 {folder}")
        print_scan(scan, table)
        thumbs = select_codes(scan, args.only)
        if not thumbs:
            print("올릴 썸네일이 없어 건너뜁니다.")
            continue
        prepared.append((video_id, thumbs))
    if not prepared:
        return 1
    return run_uploads(cfg, args, table, prepared)


def run_uploads(cfg, args, table, prepared):
    """prepared: [(video_id, {언어코드: 이미지경로})] 를 스튜디오에 올린다. 실패가 있으면 1."""
    from thumb_agent.browser import open_studio_page
    from thumb_agent.studio import StudioThumbnailUploader

    failed_any = False
    with open_studio_page(**browser_options(cfg, args)) as page:
        uploader = StudioThumbnailUploader(
            page, table,
            ui_text=cfg.get("ui_text"),
            log_dir=BASE_DIR / "logs",
            progress_dir=BASE_DIR / "progress",
            step_delay=float(cfg.get("step_delay_sec", 1.0)),
            overwrite=args.overwrite,
            dry_run=args.dry_run,
        )
        for video_id, thumbs in prepared:
            try:
                summary = uploader.upload_all(video_id, thumbs)
            except RuntimeError as exc:
                print(f"\n[오류] {video_id}: {exc}")
                failed_any = True
                continue
            print_summary(video_id, summary, table)
            failed_any |= bool(summary["failed"])
    return 1 if failed_any else 0


def print_summary(video_id, summary, table):
    names = lambda codes: ", ".join(table.display_name(c) for c in codes) or "-"
    print(f"\n===== 결과 ({video_id})")
    print(f"  완료        {len(summary['ok']):>3}개")
    print(f"  건너뜀      {len(summary['skipped']):>3}개  {names(summary['skipped'])}")
    print(f"  실패        {len(summary['failed']):>3}개  {names(summary['failed'])}")
    if summary["not_in_studio"]:
        print(f"  스튜디오에 해당 언어 없음: {names(summary['not_in_studio'])}")
        print("    -> 제목/설명 번역이 먼저 등록된 언어에만 썸네일을 넣을 수 있습니다.")
    if summary["no_file"]:
        print(f"  썸네일 파일 없는 언어: {names(summary['no_file'])}")
    if summary["failed"]:
        print("  실패한 언어는 logs 폴더의 화면 캡처를 확인한 뒤, 같은 명령을 다시 실행하면")
        print("  완료된 언어는 건너뛰고 실패한 언어만 다시 시도합니다.")


def cmd_interactive(cfg, args, table):
    print("=" * 60)
    print(" 유튜브 언어별 썸네일 자동 등록")
    print("=" * 60)
    profile = BASE_DIR / cfg.get("profile_dir", "browser_profile")
    if not profile.exists() and not (args.cdp or cfg.get("cdp_url")):
        print("\n처음 실행이라 먼저 유튜브 로그인을 진행합니다.")
        cmd_login(cfg, args)

    video = input("\n1) 동영상 주소 또는 ID 를 붙여넣으세요: ").strip()
    folder = input("2) 썸네일 이미지 폴더 경로를 붙여넣으세요: ").strip().strip('"').strip("'")
    scan = scan_folder(folder, table)
    print_scan(scan, table)
    if not scan.matched:
        print("\n올릴 썸네일이 없습니다. 파일 이름을 확인해 주세요.")
        return 1
    answer = input(f"\n위 {len(scan.matched)}개 썸네일을 올릴까요? (y/n): ").strip().lower()
    if answer not in ("y", "yes", "ㅛ", "네", "예"):
        print("취소했습니다.")
        return 0
    return run_jobs(cfg, args, table, [(video, folder)])


def read_jobs(path):
    jobs = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            if not row or row[0].strip().startswith("#") or row[0].strip().lower() in ("video", "동영상"):
                continue
            if len(row) < 2:
                raise ValueError(f"jobs 파일 형식 오류 (영상주소,폴더 필요): {row}")
            jobs.append((row[0].strip(), row[1].strip()))
    return jobs


def main(argv=None):
    # 윈도우 콘솔에서 여러 나라 글자가 들어간 파일 이름을 출력해도 멈추지 않도록
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="유튜브 언어별 썸네일 자동 등록")
    parser.add_argument("--config", default="config.json", help="설정 파일 (없어도 됨)")
    parser.add_argument("--cdp", help="이미 켜 둔 크롬에 연결 (예: http://localhost:9222)")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("login", help="처음 한 번: 유튜브 로그인")
    sub.add_parser("languages", help="인식하는 언어 이름 목록 보기")

    p = sub.add_parser("check", help="폴더의 파일 이름이 어느 언어로 인식되는지 확인")
    p.add_argument("--folder", required=True)

    for name in ("upload", "batch"):
        p = sub.add_parser(name, help="썸네일 올리기" if name == "upload" else "여러 영상 한꺼번에")
        if name == "upload":
            p.add_argument("--video", required=True, help="동영상 주소 또는 ID")
            p.add_argument("--folder", required=True, help="썸네일 이미지 폴더")
        else:
            p.add_argument("--jobs", required=True, help="CSV: 영상주소,폴더 (한 줄에 하나)")
        p.add_argument("--only", help="이 언어코드만 (예: gu,el,nl)")
        p.add_argument("--overwrite", action="store_true", help="이미 썸네일이 있거나 완료된 언어도 다시 올림")
        p.add_argument("--dry-run", action="store_true", help="실제로 올리지 않고 화면 동작만 확인")

    args = parser.parse_args(argv)
    for attr in ("only", "overwrite", "dry_run"):
        if not hasattr(args, attr):
            setattr(args, attr, None if attr == "only" else False)

    cfg = load_config(args.config)
    table = LanguageTable(cfg.get("language_aliases"))

    try:
        if args.command == "login":
            cmd_login(cfg, args)
        elif args.command == "languages":
            for code, ko, en in LANGUAGES:
                print(f"{code:<8} {' / '.join(ko):<28} {' / '.join(en)}")
        elif args.command == "check":
            cmd_check(cfg, args, table)
        elif args.command == "upload":
            return run_jobs(cfg, args, table, [(args.video, args.folder)])
        elif args.command == "batch":
            return run_jobs(cfg, args, table, read_jobs(args.jobs))
        else:
            return cmd_interactive(cfg, args, table)
    except (FileNotFoundError, ValueError) as exc:
        print(f"\n[오류] {exc}")
        return 1
    except KeyboardInterrupt:
        print("\n중단했습니다. 다시 실행하면 완료된 언어는 건너뜁니다.")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
