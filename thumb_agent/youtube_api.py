"""YouTube Data API 로 동영상의 언어별 제목·설명(현지화)을 등록한다.

스튜디오 화면을 클릭하는 대신 API 한 번 호출로 모든 언어를 넣으므로 빠르고 안정적이다.
안전장치:
  - 기본값은 '아직 없는 언어만 추가' (이미 등록된 제목·설명은 건드리지 않음)
  - '번역 실패', 빈 제목 등은 올리지 않음
  - 제목 100자 / 설명 5000자 제한, 유튜브가 금지하는 < > 문자 자동 처리

처음 한 번 필요한 것: 프로그램 폴더에 client_secret.json (README 의 'YouTube API 설정' 참고)
"""

from pathlib import Path

from .languages import LanguageTable

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
TITLE_MAX = 100
DESC_MAX = 5000

# 번역기 언어코드와 유튜브 언어코드가 다른 경우의 후보들
CODE_ALIASES = {
    "zh-cn": ["zh-Hans", "zh-CN"], "zh-tw": ["zh-Hant", "zh-TW"],
    "zh-hans": ["zh-Hans", "zh-CN"], "zh-hant": ["zh-Hant", "zh-TW"],
    "he": ["iw", "he"], "iw": ["iw", "he"],
    "tl": ["fil", "tl"], "fil": ["fil", "tl"],
    "jw": ["jv", "jw"], "jv": ["jv", "jw"],
    "no": ["no", "nb"], "nb": ["no", "nb"],
}


class YouTubeSetupError(RuntimeError):
    pass


def get_service(base_dir, client_secret="client_secret.json", token_file="youtube_token.json"):
    """OAuth 로그인 후 YouTube API 객체를 돌려준다. 처음 한 번은 브라우저에서 권한 허용이 필요."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    base_dir = Path(base_dir)
    secret_path = base_dir / client_secret
    token_path = base_dir / token_file
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        refreshed = False
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                refreshed = True
            except Exception:
                # 테스트 모드 앱은 7일마다 로그인이 만료된다 -> 다시 권한 허용
                creds = None
        if not refreshed:
            if not secret_path.exists():
                raise YouTubeSetupError(
                    f"YouTube API 설정 파일이 없습니다: {secret_path}\n"
                    "README 의 'YouTube API 설정' 순서대로 client_secret.json 을 받아 이 폴더에 넣어 주세요.")
            flow = InstalledAppFlow.from_client_secrets_file(str(secret_path), SCOPES)
            creds = flow.run_local_server(port=0, prompt="consent")
        token_path.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def valid_language_codes(service) -> dict:
    """유튜브가 받는 언어코드 목록 {코드: 한국어 이름}."""
    resp = service.i18nLanguages().list(part="snippet", hl="ko").execute()
    return {item["snippet"]["hl"]: item["snippet"]["name"] for item in resp.get("items", [])}


def resolve_code(code, valid: dict, table: LanguageTable):
    """번역기 언어코드 -> 유튜브가 받는 언어코드 (모르면 None)."""
    lower_valid = {k.lower(): k for k in valid}
    candidates = [code, *CODE_ALIASES.get(code.lower(), [])]
    studio_code = table.code_for(code)
    if studio_code:
        candidates += [studio_code, *CODE_ALIASES.get(studio_code.lower(), [])]
    for cand in candidates:
        if cand.lower() in lower_valid:
            return lower_valid[cand.lower()]
    return None


def clean_text(text: str, limit: int) -> str:
    text = (text or "").strip().replace("<", "‹").replace(">", "›")
    return text[:limit].rstrip()


def is_bad_translation(title: str, desc: str) -> bool:
    title = (title or "").strip()
    return (not title or title.startswith("번역 실패") or title == "번역 중..."
            or (desc or "").strip().startswith("오류:"))


def _same_language(a: str, b: str) -> bool:
    a, b = a.lower(), b.lower()
    if a == b:
        return True
    return b in [x.lower() for x in CODE_ALIASES.get(a, [])]


def apply_localizations(service, video_id, items: dict, *, table: LanguageTable,
                        default_language="ko", overwrite=False, dry_run=False, log=print) -> dict:
    """items: {번역기 언어코드: (제목, 설명)} 를 동영상의 언어별 제목·설명으로 등록한다."""
    resp = service.videos().list(part="snippet,localizations", id=video_id).execute()
    if not resp.get("items"):
        raise RuntimeError(f"동영상 {video_id} 를 찾지 못했습니다. 주소와, API 로그인한 채널이 맞는지 확인해 주세요.")
    video = resp["items"][0]
    snippet = video.get("snippet", {})
    existing = dict(video.get("localizations") or {})
    main_language = snippet.get("defaultLanguage") or default_language
    valid = valid_language_codes(service)

    summary = {"added": [], "updated": [], "existing": [], "bad": [], "unknown": [], "main": []}
    new_locs = dict(existing)
    for code, (title, desc) in items.items():
        yt_code = resolve_code(code, valid, table)
        if yt_code is None:
            summary["unknown"].append(code)
            continue
        if _same_language(yt_code, main_language):
            summary["main"].append(code)  # 원래 언어는 기본 제목·설명을 사용
            continue
        if is_bad_translation(title, desc):
            summary["bad"].append(code)
            continue
        key = next((k for k in existing if _same_language(k, yt_code)), None)
        if key is not None and not overwrite:
            summary["existing"].append(code)
            continue
        new_locs[key or yt_code] = {"title": clean_text(title, TITLE_MAX),
                                    "description": clean_text(desc, DESC_MAX)}
        summary["updated" if key else "added"].append(code)

    changed = summary["added"] or summary["updated"]
    log(f"제목·설명: 새로 추가 {len(summary['added'])}개, 교체 {len(summary['updated'])}개, "
        f"이미 있어서 건너뜀 {len(summary['existing'])}개")
    if summary["bad"]:
        log(f"  번역이 비었거나 실패해서 건너뜀: {', '.join(summary['bad'])}")
    if summary["unknown"]:
        log(f"  유튜브가 지원하지 않는 언어코드: {', '.join(summary['unknown'])}")
    if not changed or dry_run:
        if dry_run and changed:
            log("  (시험 실행이라 실제로 등록하지 않았습니다)")
        return summary

    body = {"id": video_id, "localizations": new_locs}
    parts = ["localizations"]
    if not snippet.get("defaultLanguage"):
        # 언어별 제목을 쓰려면 동영상의 기본 언어가 지정되어 있어야 한다 (기존 값은 그대로 유지)
        keep = {k: snippet[k] for k in ("title", "description", "categoryId", "tags", "defaultAudioLanguage")
                if k in snippet}
        keep["defaultLanguage"] = default_language
        body["snippet"] = keep
        parts.append("snippet")
    service.videos().update(part=",".join(parts), body=body).execute()
    log("  ✅ 유튜브에 등록 완료")
    return summary
