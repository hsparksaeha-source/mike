# 유튜브 언어별 썸네일 자동 등록

YouTube 스튜디오 **언어** 화면에서 나라별로 **썸네일 → 추가**를 눌러 이미지를 넣는 작업을
자동으로 해 주는 프로그램입니다.
제목·설명 자동 번역 프로그램으로 언어(구자라트어, 그리스어 …)를 먼저 등록해 두었다면,
**썸네일 폴더와 동영상 주소만 입력하면** 각 언어에 맞는 썸네일이 차례대로 들어갑니다.

> 참고: YouTube API 로는 언어별 썸네일을 올릴 수 없어서, 이 프로그램은 사람 대신
> 크롬 브라우저에서 스튜디오 화면을 직접 클릭합니다.
> (언어 이름 클릭 → 썸네일 '추가' → 파일 선택 → '업데이트')

## 두 가지 사용 방법

| 프로그램 | 설명 |
|---|---|
| **`youtube_translator_thumbnail.pyw`** (추천) | 기존 번역기 화면에 **썸네일 칸이 추가된 새 버전**. 제목·설명 번역과 썸네일 등록을 한 화면에서 |
| `run.bat` | 썸네일만 올리는 간단한 버전 (질문에 답하는 방식) |
| `youtube_translator_maker.pyw` | 기존 번역기 **원본 그대로** (수정하지 않음) |

### 번역기 + 썸네일 (`youtube_translator_thumbnail.pyw`)

1. `google_translate_api_key.txt` 를 이 폴더에 넣습니다 (기존 번역기와 같은 파일).
2. 파일을 더블클릭해서 실행합니다.
3. 처음 한 번 **[① 유튜브 로그인]** → 열린 크롬에서 로그인·채널 선택 → 안내창 [확인]
4. 평소처럼 제목·설명을 번역합니다.
5. **[ 썸네일 자동 등록 ]** 칸에 **동영상 주소**를 넣고, **🖼️ 이미지 선택**으로 **영문 썸네일 한 장**을 고릅니다.
   → 이 한 장이 스튜디오에 등록된 **모든 언어(77개국 등)에 똑같이** 들어갑니다.
6. **[② 시험 실행]** 으로 한 번 확인한 뒤 **[🖼️ 썸네일 자동 등록]** 을 누릅니다.
   진행 상황은 '진행 기록' 창에 표시됩니다.

> 나라마다 **다른** 썸네일을 넣고 싶을 때만 '(선택) 언어별 폴더' 칸을 사용합니다.
> 이때는 '썸네일 이미지' 칸을 비워 두고, 폴더 안 파일 이름을 언어로 지어 주세요.

파일 이름은 번역기의 언어코드(`zh-CN.jpg`, `he.jpg`, `tl.jpg` …)나
한국어 이름(`구자라트어.jpg`, `미얀마어(버마어).jpg` …) 그대로 쓰면 됩니다.
번역기의 '새로운 언어 추가' 목록에 있는 106개 언어를 모두 인식하므로 77~78개국도 문제없습니다.

---

## 1. 설치 (처음 한 번)

1. 파이썬 설치: <https://www.python.org/downloads/>
   (설치 화면에서 **"Add python.exe to PATH"** 체크)
2. 크롬 브라우저 설치 (이미 있으면 그대로 사용)
3. 이 폴더의 **`install.bat`** 더블클릭
   (번역기용 `requests`, `pyperclip` 도 함께 설치됩니다)

## 2. 썸네일 폴더 준비

한 동영상의 썸네일을 한 폴더에 넣고, **파일 이름에 언어**를 적어 주세요.
아래 방식이 모두 인식됩니다.

| 방식 | 예시 |
|---|---|
| 언어 코드 | `gu.jpg`, `el.png`, `zh-Hans.jpg`, `pt-BR.jpg` |
| 한국어 이름 (스튜디오 표기) | `구자라트어.jpg`, `그리스어.png`, `중국어(간체).jpg` |
| 영어 이름 | `Gujarati.jpg`, `Greek.png`, `Chinese (Simplified).jpg` |
| 앞뒤에 다른 글자 | `01_gu.jpg`, `thumb_Greek.jpg`, `구자라트어_썸네일.jpg` |

- 이미지 형식: JPG, PNG, GIF, BMP / 크기 1280×720 권장 / **2MB 이하**
- 인식하는 전체 언어 목록: `run.bat languages`
- 파일 이름이 제대로 인식되는지 미리 확인: `run.bat check --folder "폴더경로"`

## 3. 실행

**`run.bat`** 더블클릭 → 질문에 답하면 됩니다.

1. 처음 실행이면 크롬 창이 열립니다. 구글 로그인 후 **채널을 선택**하고, 까만 창으로 돌아와 Enter.
   (로그인 정보는 `browser_profile` 폴더에 저장되어 다음부터는 바로 시작합니다.)
2. 동영상 주소(또는 ID) 붙여넣기
3. 썸네일 폴더 경로 붙여넣기 (탐색기 주소창을 복사하거나, 폴더를 까만 창에 끌어다 놓기)
4. 인식된 목록을 확인하고 `y` 입력 → 자동으로 올라갑니다.

실행 중에는 크롬 창을 건드리지 말고 지켜보기만 해 주세요.

### 명령어로 실행하기 (선택)

```bat
run.bat upload --video https://youtu.be/XXXXXXXXXXX --image "C:\썸네일\영문썸네일.jpg"
run.bat upload --video https://youtu.be/XXXXXXXXXXX --folder "C:\썸네일\가을과수원"
run.bat upload --video XXXXXXXXXXX --folder "C:\썸네일\가을과수원" --only gu,el,nl
run.bat upload --video XXXXXXXXXXX --folder "C:\썸네일\가을과수원" --dry-run
run.bat upload --video XXXXXXXXXXX --folder "C:\썸네일\가을과수원" --overwrite
run.bat batch --jobs jobs.csv
```

| 옵션 | 설명 |
|---|---|
| `--only gu,el` | 지정한 언어만 올리기 |
| `--dry-run` | 실제로 올리지 않고, 창 열기·버튼 찾기까지만 시험 |
| `--overwrite` | 이미 썸네일이 있는 언어도 새 이미지로 교체 |
| `batch --jobs` | 여러 동영상을 한 번에 (`jobs.example.csv` 참고) |

## 4. 결과와 다시 실행

- 끝나면 **완료 / 건너뜀 / 실패** 목록이 나옵니다.
- 완료된 언어는 `progress` 폴더에 기록되어, **같은 명령을 다시 실행하면 실패한 언어만** 다시 시도합니다.
- 실패한 언어는 `logs` 폴더에 당시 화면이 캡처되어 있습니다.
- "스튜디오에 해당 언어 없음"은 그 언어의 제목·설명 번역이 아직 등록되지 않았다는 뜻입니다.
  제목·설명 번역 프로그램을 먼저 실행해 주세요.

## 5. 문제가 생기면

| 증상 | 해결 |
|---|---|
| 구글이 "안전하지 않은 브라우저" 라며 로그인을 막음 | 아래 **이미 쓰는 크롬에 연결하기** 사용 |
| 언어 이름을 못 찾음 (스튜디오 표기가 다름) | `config.example.json` 을 `config.json` 으로 복사하고 `language_aliases` 에 `"스튜디오표기": "언어코드"` 추가 |
| 버튼 이름이 바뀌어 못 찾음 | `config.json` 의 `ui_text` 에 새 버튼 글자 추가 |
| 너무 빨라서 실패함 | `config.json` 의 `step_delay_sec` 을 2~3 으로, `slow_mo_ms` 를 300 으로 |
| 스튜디오가 영어로 표시됨 | 그대로 사용해도 됩니다 (영어 화면도 지원) |

### 이미 쓰는 크롬에 연결하기

크롬을 모두 닫고, 명령 프롬프트에서 디버깅 모드로 크롬을 켭니다.

```bat
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\yt-thumb-chrome"
```

열린 크롬에서 유튜브 스튜디오에 로그인한 뒤, 다음처럼 실행합니다.

```bat
run.bat --cdp http://localhost:9222
```

## 폴더 구성

```
youtube_translator_thumbnail.pyw  번역기 + 썸네일 칸 (새 버전)
youtube_translator_maker.pyw      기존 번역기 원본 (수정 안 함)
main.py                 썸네일만 올리는 실행 프로그램 (질문형 / 명령어)
thumb_agent/
  languages.py          스튜디오 언어 이름 ↔ 언어 코드 표
  folder.py             썸네일 폴더 읽기 · 파일 이름으로 언어 찾기
  studio.py             스튜디오 화면 자동 조작 (클릭 · 파일 선택 · 업데이트)
  browser.py            크롬 열기 / 로그인 유지
  tk_thumbs.py          창 프로그램용 로그인 · 업로드 · 진행 기록 창
tests/                  가짜 스튜디오 화면으로 동작 시험 (python -m pytest tests)
install.bat / run.bat   윈도우용 설치 · 실행
```

> ⚠️ `browser_profile` 폴더에는 로그인 정보가 들어 있습니다. 다른 사람에게 주거나 인터넷에 올리지 마세요.
