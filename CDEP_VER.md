# CDEP_VER — 사내 클라우드 버전(cdep-ver) 리눅스 호환 점검

브랜치 `cdep-ver`(사내 로컬 버전 `in-house-local` 6b61585에서 시작). 대상은 리눅스 클라우드 VS Code(code-server 계열, `HOME`이 `/config`일 수 있음, 릴리스 폴더 예 `/config/work/beol/<release_label>/`), 폐쇄망, Claude Code 없이 VS Code + Roo Code. 화면은 역방향 프록시 경로·도메인으로 연다. 사내 로컬 버전과 같게 두고 **경로·리눅스 차이만** 고쳤다. Windows 동작은 바꾸지 않았다(Windows 테스트 그대로 통과).

- 점검 범위: 저장소 전체(`docs/`·`.omc/` 제외)의 `.py`·`.sh`·문서 인라인 명령.
- 상시 검사: `tests/test_linux_compat.py`(git 없이 폴더를 훑는다 — 허용 목록은 경로·구문·이유).
- 실행 형태: `bash tools/cloud_setup.sh --dry-run` → `bash tools/cloud_setup.sh`(패키지는 설치하지 않고 명령만 출력).

## 점검 표

| 위치 | 문제 | 조치 |
|---|---|---|
| `labelbot/cdp.py` `browser_candidates` | 리눅스 후보가 `/usr/bin/{microsoft-edge,google-chrome,chromium}`뿐 — `chromium-browser`·`google-chrome-stable`·PATH·Chrome for Testing(CfT) 반입본을 못 찾음 | **고침**: env `BEOL_CHROME`(실행 파일 또는 CfT 폴더 → `chrome-linux64/chrome`)을 맨 앞에, 리눅스에서만 PATH(`chromium` `chromium-browser` `google-chrome` `google-chrome-stable` `microsoft-edge`)·`/snap/bin/chromium`·`~/.local/opt/chrome-linux64/chrome`를 뒤에 붙임. `render.browser_path`가 여전히 최우선. Windows 후보 순서 그대로 |
| `labelbot/cdp.py` `Browser` 실행 인자 | root로 돌거나 사용자 네임스페이스가 막힌 컨테이너에서 headless chromium이 sandbox 오류로 종료, `/dev/shm` 64MB 컨테이너에서 탭 충돌 | **고침**: `linux_flags()` — 리눅스에서만 `--no-sandbox`(euid 0 또는 `BEOL_CHROME_NO_SANDBOX=1`), `--disable-dev-shm-usage`(`/dev/shm` < 512MB 또는 `BEOL_CHROME_DISABLE_DEV_SHM=1`). Windows·macOS는 빈 목록 |
| `tools/beol_doctor.py` `_find_chrome`(E09) | doctor와 렌더러가 찾는 브라우저가 다를 수 있음 | **고침**: `BEOL_CHROME`·`google-chrome-stable`·CfT 경로를 같은 기준으로 추가(3.8 문법 유지) |
| `.claude/launch.json` | `screens-parshing-test-files` 항목이 Windows 절대경로(스크립트·작업 폴더) | **고침**: 그 항목 삭제. `docs-static`·`rag-ui`는 상대경로 그대로. 첫 라벨링 때 `init_workspace.py`가 그 머신 경로로 다시 넣는다(Roo는 launch.json을 쓰지 않음) |
| `injested-file-list/*.json` 16개 | `workspace`·`input`이 Windows 절대경로 | **고침**: `python tools/cloud_migrate_paths.py --old-root "<옛 Windows 저장소 루트>" --include-ingested-list --apply` → 32필드 CONVERTED(`workspaces/<이름>`, `../../parshing test files`), 재실행 `files_converted=0`. 도구는 작업 폴더가 없어도 목록을 변환한다(코드 변경 없음) |
| `CLOUD_SETUP.md`·`CLOSED_NETWORK_RUNBOOK.md`·`.roo/skills/beol-release-accept`·`beol-import-verify` 인라인 manifest 읽기(`json.load(open …)`) | 인코딩 미지정 → cp949 등 비 UTF-8 로캘에서 `UnicodeDecodeError`, `$(…)`가 비어 **전체 스위트**가 돌고 더미 의존 13개 모듈이 오류 | **고침**: `python3 tools/beol_status.py test-modules [--unittest]`(UTF-8로 읽음, 목록이 비면 `사유=TEST_LIST_EMPTY`·종료 1·출력 없음) + `T=$(…) && python -m pytest … $T` 형식. 남은 인라인 `open(…json…)`에는 `encoding='utf-8'`. 테스트가 문서·skill·`.sh`의 인라인 `open(`을 검사 |
| `CLOUD_SETUP.md` 2절 `env.json 기록` | `/etc/os-release` 읽기·`env.json` 쓰기에 인코딩 미지정 | **고침**: `encoding='utf-8'` |
| `domain_engrbot/tests/test_taxonomy_board.py::test_open_board_uses_browser` | `BEOL_NO_BROWSER=1` 또는 DISPLAY 없는 리눅스에서 실패(환경 의존) | **고침**: `serve.no_browser`를 False로 고정해 "연다" 분기를 보고, "주소만 출력" 분기 테스트(`test_open_board_no_browser_prints_url`)를 따로 둠 |
| `tests/test_import_tools.py::test_real_repo_dummy_graph`, `tests/test_prepush_scan.py::test_current_tree_passes` | git 체크아웃 필요 — 반입 ZIP에는 `.git`이 없어 폐쇄망 목록에서 실패 | **고침**: `tests/test_import_tools_git.py`·`tests/test_prepush_scan_git.py`로 옮기고 모듈 맨 위 `CLOSED_NETWORK_EXCLUDE = "<이유>"`. `tools/make_import_manifest.py`가 이 표시를 읽어 `test_modules`에서 빼고 `test_modules_excluded[{path, excluded_reason}]`에 이유를 싣는다(더미는 `DUMMY_IMPORT`). 로컬 전체 스위트에서는 그대로 돈다 |
| 사이트 설정(`workspaces/_site/`) | 문서의 `cp`·`touch` 수작업뿐, 예시가 doctor 대상 하나 | **고침**: `config/site.example/`(`beol.env.example`, `profile.example.json`, `doctor_targets.example.json` 사본, `scan_denylist.example.json`, `crontab.example`, placeholder만) + `tools/site_init.py`(3.8, M00): 없는 파일만 복사, 덮어쓰지 않음, 값 파일 chmod 600 |
| crontab(CLOUD_SETUP 9절) | `. $B/…; cd $B` — 따옴표 없음, `TZ` 없음, daily report 줄 없음 | **고침**: `crontab.example` — `SHELL=/bin/bash`, `TZ`·`CRON_TZ=Asia/Seoul`, `cd "$B" && set -a && . workspaces/_site/beol.env && set +a`, 로그 `workspaces/_nightly/cron.log`(상대경로만) |
| `.roo/rules/00-beol-governing.md` | 리눅스 경로 규칙 없음 | **고침**: `tools/gen_roo_skills.py` 고정 절에 "리눅스 클라우드 경로 규칙"(릴리스 폴더에서 실행, 상대경로, `python`=3.14, `python3`=3.8 도구) → 재생성, `--check` ok. `.claude/skills` 원본은 바꾸지 않음 |
| C1 실행 형태 | 문서 붙여 넣기만 | **고침**: `tools/cloud_setup.sh`(bash, `set -euo pipefail`, 실행 비트 `100755`) — 문서와 같은 step 도우미, `--dry-run`·`--from`·`--only`, 패키지는 설치하지 않고 apt/dnf 명령과 이유만 출력, C3는 `config/known_test_failures.txt` 밖 실패만 실패 |
| `.claude/skills/BEOL-labeling-feedback/scripts/collect_inbox.py` `winreg` | Windows 전용 모듈 | **유지**: `try` 안 import → 리눅스는 `ImportError`로 `~/Downloads`(`HOME=/config`면 `/config/Downloads`). 단 클라우드에서는 브라우저 다운로드가 사용자 PC로 가므로 검수 JSON은 화면 서버(`labelbot serve`)가 `inbox/`에 바로 쓰는 경로를 쓴다 |
| `labelbot/cdp.py`·`tools/beol_doctor.py` `msedge.exe`·`chrome.exe` | Windows 경로 후보 | **유지**: `ProgramFiles*` env가 없는 리눅스에서는 후보가 생기지 않음 |
| `os.startfile`·`msvcrt`·`windll`·`cmd /c`·`powershell`·`shell=True`·`mbcs` | Windows 전용 실행 | **유지(0건)**: 코드에 없음. `change-dashboard/collect.py`의 `"PowerShell"`은 세션 기록의 도구 이름 문자열(실행 아님), `code_engrbot` C2 규칙의 `shell=True`는 검사 패턴 문자열 |
| `subprocess`에 `"python"` 문자열 | 리눅스에서 `python`이 3.14가 아닐 수 있음 | **유지(0건)**: 하위 프로세스는 모두 `sys.executable`(`nightly_run.py`, `build_workflow.py`, 테스트) |
| `labelbot/ingest.py` `cp949` | 하드코딩 인코딩 | **유지**: CLAUDE.md 규칙(사내 CSV는 `utf-8-sig` → 실패 시 `cp949`), 플랫폼 무관 |
| `tools/*.py` 콘솔 `reconfigure(errors="replace")` | Windows 콘솔 대비 | **유지**: 리눅스에서 무해. 셸은 `PYTHONIOENCODING=utf-8`(beol.env, cloud_setup.sh 기본값) |
| `.replace("\\", "/")` 정규화 약 20곳 | `\` 구분자 가정 | **유지**: 리눅스에서는 바꿀 것이 없음(파일 이름에 `\`를 쓰지 않음) |
| `relpath(…).replace(os.sep, "/")`·`split(os.sep)` | 구분자 의존 | **유지**: 모두 같은 OS의 `relpath` 결과에만 적용 |
| `webbrowser.open`(`daily_report.py`, `taxonomy_board.py`, `taxonomy_editor.py`) | 화면 없는 서버에서 브라우저 열기 | **유지**: 모두 `BEOL_NO_BROWSER=1` 또는 DISPLAY·WAYLAND_DISPLAY 없음이면 주소만 출력 |
| 텍스트 쓰기 줄바꿈 | `newline` 미지정 시 Windows CRLF·리눅스 LF | **유지**: 해시가 걸린 작성기(manifest, 경로 변환, init_workspace, gen_roo_skills, taxonomy 저장)는 `newline="\n"`. 나머지는 리눅스에서 LF = git blob 형태라 오히려 기준과 같음 |
| `os.replace` | 덮어쓰기 이름 바꾸기 | **유지**: 두 OS에서 같은 의미 |
| `labelbot/axisupdate.py:180` `os.rename(moved, path)` | 리눅스는 대상이 있으면 덮어씀(Windows는 실패) | **유지**: 바로 앞에서 `exists(path)`가 거짓일 때만 부름. 경쟁 창이 μs 단위이고 축 재라벨링은 한 번에 하나만 돈다 |
| `tempfile`·`/tmp`·`%TEMP%` | 임시 폴더 하드코딩 | **유지(0건)**: `tempfile`만 씀(리눅스는 `TMPDIR` → `/tmp`) |
| `datetime.now()` 등 로컬 시각 | 서버 시간대가 UTC일 수 있음 | **유지(메모)**: `TZ=Asia/Seoul`을 beol.env·crontab(`CRON_TZ`)에 둠, doctor E11이 확인 |
| `tools/beol_doctor.py:868` `open("/etc/timezone")` | 인코딩 미지정 | **유지**: ASCII 한 줄 |
| `labelbot/screens/slides.html` 글꼴 `'Noto Sans KR'` | `fonts-noto-cjk` 패밀리 이름은 `Noto Sans CJK KR` | **유지**: fontconfig가 `sans-serif`·한글 글리프로 Noto CJK에 대체. 템플릿을 바꾸면 `renderer_base` 해시가 바뀌어 Windows 슬라이드 이미지가 전부 다시 그려짐. 실제 리눅스에서 미리보기 확인(아래) |
| 대소문자 다른 경로 참조 | 리눅스는 대소문자 구분 | **유지(0건)**: 추적 경로 토큰·`os.path.join` 문자열 전수 대조에서 불일치 없음 |
| `.sh` shebang·실행 비트·CRLF | 리눅스 실행 | **유지/고침**: `.sh`는 `tools/cloud_setup.sh` 하나(LF, `#!/usr/bin/env bash`, 인덱스 `+x`). `tools/*.py`는 `python3 …`로 부르므로 실행 비트 불필요 |
| `CLOSED_NETWORK_RUNBOOK.md` R0의 `powershell`·`7z.exe` | Windows 명령 | **유지**: 사내 업무 PC(Windows)에서 ZIP을 푸는 단계 |
| `labelbot/rulesdiff.py` `git` 호출 | 폐쇄망 릴리스 폴더에 `.git` 없음 | **유지**: 기존 C6 수락 항목(git 없이 출처 표시) |
| `init_workspace.py` `upsert_launch` | launch.json에 그 머신 절대경로를 씀 | **유지**: 머신별 로컬 미리보기 등록(의도). 서버에서 생기는 변경은 반출 대상 아님 |
| `transfer/import_manifest.json` | 이 브랜치에서 바뀐 파일의 해시와 다름 | **유지(메모)**: 커밋 뒤 `tools/make_import_manifest.py`로 다시 만든다. `injested-file-list/*.json`은 state라 `--base-manifest`를 주면 `--override injested-file-list/<이름>.json=경로 상대화`가 필요 |

건수: 고침 13 · 유지 22(그중 해당 구문 0건 확인 6).

## 남은 Windows 사용자 폴더 꼴 문자열

`CLOSED_NETWORK_RUNBOOK.md`의 `--old-root '…/<업무 PC 사용자>/<저장소 폴더>'` 두 줄(자리표시 — 업무 PC 작업 폴더를 옮길 때 쓰는 예시)과 `tests/test_prepush_scan.py`의 탐지 시험 입력 한 줄뿐이다(`docs/` 제외).

## 실제 리눅스에서만 확인할 것 (폐쇄망 C1·C6 체크리스트)

1. `bash tools/cloud_setup.sh` 전 단계(특히 E08: 비로그인 셸과 `env -i` 빈 환경에서 `python -V` = 3.14.x, cron 환경 PATH).
2. headless chromium 실제 기동: root·비root 각각, `/dev/shm` 크기별로 `--no-sandbox`·`--disable-dev-shm-usage` 자동 판단이 맞는지 → `python -m labelbot slide-images --workspace <ws>` 1건.
3. Chrome for Testing 반입본: `BEOL_CHROME=$HOME/.local/opt`로 찾는지, `ldd`에 빠진 라이브러리 없는지(doctor E09).
4. 한글 글꼴 대체: 슬라이드 미리보기 JPG에서 한글이 두부(□)가 아닌지(`fc-list :lang=ko`가 Noto Sans CJK를 내는지).
5. `HOME=/config`에서 `~/.local/bin`·`~/.local/opt`·`~/Downloads` 해석, `workspaces/`가 실제 폴더(심볼릭 아님)인지.
6. `crontab.example` 두 줄이 cron에서 `TZ`·beol.env를 읽고 `workspaces/_nightly/cron.log`에 남기는지(`CRON_TZ` 지원 여부는 cron 구현마다 다름).
7. 역방향 프록시 뒤 화면: `BEOL_ALLOWED_HOSTS`·`BEOL_PATH_PREFIX` 값으로 검수 화면 POST가 통과하는지(C5).
8. 비 UTF-8 로캘(`LANG=C` 등)에서 `python3 tools/beol_status.py test-modules`가 목록을 내는지, manifest가 없을 때 `TEST_LIST_EMPTY`로 멈추는지.
9. `python -m labelbot rules-diff`가 git 없는 릴리스 폴더에서 오류 없이 출처를 표시하는지(기존 C6).
10. 파일 이름 정규화: 사내 PC에서 푼 한글 pptx 이름이 리눅스에서 NFC로 읽히는지(ingest는 NFC로 비교).
