# CLOSED_NETWORK_RUNBOOK — 반입·업그레이드·장애·반출

폐쇄망(VS Code + Roo Code, 인터넷·GitHub·Claude Code 없음)에서 릴리스를 받아 쓰는 절차다. 환경 구성(C1)은 `CLOUD_SETUP.md`.

- 저장소는 공개다. 이 문서·Roo skill에는 사내 호스트·IP·경로·키가 없다. 실제 값은 비추적 `workspaces/_site/`(`beol.env`, `doctor_targets.json`, `scan_denylist.json`, `profile.json`)에만 둔다.
- **폐쇄망에서 코드를 고치지 않는다.** 코드 문제는 반출(아래 "반출")로 로컬에 넘기고 다음 릴리스로 고친다. 설정으로 고칠 수 있는 것은 "설정만으로 고칠 수 있는 것" 표.
- 폴더: 릴리스마다 `/config/work/beol/<release_label>/`(새 폴더). `current` 같은 심볼릭은 쓰지 않는다. 반입 보고는 `/config/work/beol/_import/`.
- 명령은 Roo 명령 도구로 사용자 승인 후 실행하거나, Roo가 약하면 이 문서 명령을 터미널에서 직접 실행한다.

## R0 — 사내 업무 PC (릴리스마다)

1. **R1 전 한 번 시험**: 실제 사내 PC 도구로 시험 ZIP을 풀어 C0까지 돌려 본다(경로 길이·이름 인코딩·DRM 변형 확인). 사내 PC에 python이 없으면 폐쇄망으로 옮겨서 C0를 돌린다.
2. 브랜치 `LLM-added` ZIP을 받는다(`<저장소 주소>/archive/refs/heads/LLM-added.zip`).
3. **반드시 압축을 푼다**: 7-Zip 또는 Windows 11 기본 압축 풀기로 **짧은 루트**(예 `C:\x\`)에 푼다. 한글 이름 pptx가 많고 최장 경로가 260자에 가깝다. UTF-8 이름 플래그를 무시하는 도구는 이름이 깨진다(C0가 `RENAMED_OK`로 잡지만 피한다). 풀린 폴더 이름(`BEOL-Datalabeling-LLM-added`)은 그대로 둔다.
   ```powershell
   & "C:\Program Files\7-Zip\7z.exe" x .\BEOL-Datalabeling-LLM-added.zip -oC:\x\
   ```
4. `C:\x\BEOL-Datalabeling-LLM-added\transfer\download_list.json`의 설치 파일을 받는다(R1, 이후 바뀐 항목만). 배포판을 모르면 `variant` 후보를 모두 받는다. 받은 파일은 압축 해제 폴더 **밖**의 반입 폴더(예 `C:\x\inbox\`)에 둔다.
5. 받은 파일의 sha256을 `transfer-received.json`으로 남긴다(PowerShell). `url`·`published_checksum_match`는 손으로 채운다(공식 페이지의 체크섬과 같으면 `true`).
   ```powershell
   Get-ChildItem C:\x\inbox -File | Where-Object Name -ne 'transfer-received.json' | ForEach-Object {
     [pscustomobject]@{ name = $_.Name; url = ''; size = $_.Length
       sha256 = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower(); published_checksum_match = $null }
   } | ConvertTo-Json | Out-File -Encoding utf8 C:\x\inbox\transfer-received.json
   ```
6. 승인 경로로 폐쇄망에 옮긴다. 사내 PC에서 파일을 열거나 편집하지 않는다.

## C0 — 반입 확인 (Roo skill `beol-import-verify`, M19)

배포판 python3(3.8+)로 된다. `verify_import.py`는 Python 3.14 없이도 `[M19 IMPORT] …` 줄을 낸다.

```bash
cd /config/work/beol
L=$(python3 -c "import json;print(json.load(open('BEOL-Datalabeling-LLM-added/transfer/import_manifest.json',encoding='utf-8'))['release_label'])")
mv BEOL-Datalabeling-LLM-added "/config/work/beol/$L" && cd "/config/work/beol/$L"
mkdir -p /config/work/beol/_import
python3 tools/verify_import.py --manifest transfer/import_manifest.json --root . --out "/config/work/beol/_import/$L.json"
echo "rc=$?"
```

| 결과 | 뜻 | 할 일 |
|---|---|---|
| `code` CHANGED·MISSING (종료 2, `CODE_CHANGED`) | 압축 해제·DRM 변형 또는 직접 수정 | **이 릴리스를 쓰지 않는다.** 반입 보고를 반출하고, 사내 PC에서 7-Zip으로 다시 풀어 본다 |
| `state` CHANGED | 이어받는 상태(taxonomy 등) | 차단 안 함. CU에서 처리 |
| `office` CHANGED + `DRM_ENCRYPTED`/`NOT_OOXML` | 사내 PC DRM이 더미 문서를 바꿈 | 허용, 기록(G-UNZIP) |
| `office` `RENAMED_OK` | 이름 인코딩만 깨짐(내용 같음) | 허용 |
| `EOL_CRLF` | 줄 끝만 바뀜 | code면 차단(다시 풀기), 그 밖은 기록 |
| `media`·`text-other` CHANGED | 기록 | `requirements*.txt`는 허용 |
| `EXTRA` | manifest에 없는 파일 | 사용자 확인 |

- 반입 보고 `/config/work/beol/_import/<release_label>.json`: code 파일은 경로, office는 manifest 순번 + 사유 코드만(반출 가능).
- 수락: 종료 코드 0, 출력의 `release_label`과 폴더 이름이 같음.
- R1이면 이어서 `CLOUD_SETUP.md`, R2부터는 CU.

## CU — 업그레이드: 새 폴더 + 상태 이어받기 (R2부터, `beol-upgrade-carry`, M19)

```bash
OLD=/config/work/beol/<이전 release_label>
NEW=/config/work/beol/<새 release_label>          # C0 통과
```

1. 운영 중지: `crontab -e`로 줄을 주석 처리, 화면 서버(Ctrl+C) 종료.
2. 이어받기 dry-run(배포판 python3도 됨):
   ```bash
   cd "$NEW" && python3 tools/carry_state.py --old "$OLD" --new "$NEW"
   ```
   - 기준은 `$OLD/transfer/import_manifest.json`의 state 해시다. 없으면 `NO_BASE_MANIFEST`로 멈춘다 → 수동 비교, 반출 보고.
   - 판정: `KEEP_CLOSED`(폐쇄망 사본 유지·폐쇄망 삭제도 유지) / `TAKE_RELEASE`(릴리스만 바뀜) / `CONFLICT`(둘 다 바뀜 — 행 단위 차이 출력) / `ADDED_CLOSED`(폐쇄망에만 있음, 복사) / `FLAG_RELEASE_DELETED`(릴리스에서 지움, 손대지 않음) / `FLAG`(폐쇄망에서 지웠는데 릴리스도 바꿈, 손대지 않음) / `COPIED_UNTRACKED`(`workspaces/`, `workspaces/_site/`, `taxonomy/taxonomy_history.jsonl`, `docs/snapshots/*`를 비교 없이 복사).
   - 새 manifest에 `state_overrides`가 있으면 그 이유를 사용자에게 보여 준다(예: `rag/beol_rag.html`은 B6 릴리스가 바꾼다).
3. CONFLICT 해결: 출력의 차이(taxonomy는 `taxonomy[축|값|상위값]` 행, 그 밖 JSON은 키 경로, HTML은 줄 범위)를 보고 고른다.
   ```bash
   python3 tools/carry_state.py --old "$OLD" --new "$NEW" --resolve taxonomy/taxonomy.json=closed --resolve rag/beol_rag.html=release
   ```
   `FLAG`·`FLAG_RELEASE_DELETED`는 사람이 파일을 보고 직접 정한다.
4. 사용자 확인 후 적용: 같은 명령에 `--apply` → `$NEW/carry_report.json`.
5. `.env`는 이어받기 대상이 아니다 → `cp .env.example .env && chmod 600 .env`(키 값은 `workspaces/_site/beol.env`에 있으므로 함께 넘어왔다).
6. 경로 변환(옛 폴더 경로가 박힌 작업 폴더):
   ```bash
   python tools/cloud_migrate_paths.py --old-root "$OLD"            # dry-run, 건수 확인
   python tools/cloud_migrate_paths.py --old-root "$OLD" --apply
   python tools/cloud_migrate_paths.py --old-root "$OLD"            # files_converted=0 이어야 한다
   ```
7. smoke — 저장소 안 입력은 `True True`(업무 PC 입력 `OUTSIDE_REPO`는 `False`가 정상):
   ```bash
   python -c "from labelbot.workspace import Workspace as W;import glob,os;[print(os.path.basename(p),os.path.isfile(W(p,create=False).taxonomy_path),os.path.isdir(W(p,create=False).input_root)) for p in sorted(glob.glob('workspaces/261004_BEOL_*'))]"
   ```
   Code-Engr-bot 축·규칙 점검이 같은 입력 폴더를 한 묶음으로 보는지 확인한다. 같은 입력이 두 번 재라벨링되면 반출 보고.
8. `~/.bashrc`의 `beol.env` 경로와 crontab의 `B=`를 `$NEW`로 바꾸고 cron 재개. `$OLD`는 다음 릴리스까지 보존한다(롤백 = 경로를 되돌림).

## CM — 업무 PC → 폐쇄망 작업 폴더 이동 (G-DRM = 미복호화일 때)

- 업무 PC(Windows 사본)에서 ingest·라벨링한 작업 폴더(`.b64`·`work.sqlite`·`pipeline.json`)만 승인 경로로 옮긴다. 원본 문서·폴더 경로는 옮기지 않는다.
- 폐쇄망에서 `workspaces/` 아래에 두고 경로를 바꾼다:
  ```bash
  python tools/cloud_migrate_paths.py --old-root 'C:/Users/<업무 PC 사용자>/<저장소 폴더>'
  python tools/cloud_migrate_paths.py --old-root 'C:/Users/<업무 PC 사용자>/<저장소 폴더>' --apply
  ```
- 입력 폴더가 저장소 밖이면 `OUTSIDE_REPO`로 그대로 둔다(폐쇄망은 임베딩 이후만 하므로 입력 폴더를 읽지 않는다).

## C3 — 비더미 테스트 (릴리스마다)

```bash
T=$(python3 tools/beol_status.py test-modules) && BEOL_NO_BROWSER=1 python -m pytest -p no:cacheprovider -q $T
```

- 더미 문서 폴더가 없으므로 `tests._dummy`를 import하는 모듈과, git 체크아웃이 필요한 모듈(`CLOSED_NETWORK_EXCLUDE` 표시, 반입 ZIP에는 `.git`이 없다)은 manifest `test_modules`에서 빠져 있다(이유는 `test_modules_excluded`).
- 목록이 비었거나 manifest를 못 읽으면 `test-modules`가 `사유=TEST_LIST_EMPTY`로 멈추고 pytest는 돌지 않는다. **`$(…)`가 비어 전체 스위트가 도는 일이 없게 위 형식(`T=… &&`)만 쓴다.**
- 같은 검사를 기준선 비교까지 하려면 `bash tools/cloud_setup.sh --only C3`(`config/known_test_failures.txt` 밖의 실패만 실패).
- 수락: 실패는 로컬 기준선 10건 중 남은 것만(`domain_engrbot` test_harness 2·test_integration 3·test_judge 4, `tests/test_defaults_taxonomy` 1), 새 실패 0. 차이는 실패 테스트 ID·오류 유형으로 반출.

## 설정만으로 고칠 수 있는 것 (릴리스 불필요)

| 증상 | 고칠 곳 |
|---|---|
| 프록시 뒤 화면 POST 403 | `workspaces/_site/beol.env`의 `BEOL_ALLOWED_HOSTS`·`BEOL_PATH_PREFIX` |
| `EXTERNAL_BLOCKED` | `beol.env`의 `BEOL_ALLOWED_HOST_SUFFIXES` |
| 모델·URL·키 변경 | `workspaces/_site/profile.json`, `beol.env` |
| 슬라이드 렌더 실패 | 작업 폴더 `pipeline.json`의 `render.browser_path` |
| 프록시·CA·시계·시간대 | `beol.env`, 시스템 CA 저장소, NTP(`CLOUD_SETUP.md` 3–4) |
| cron 시각·경로 | crontab |
| `TAXONOMY_XLSX_NEWER` 경고(압축 해제 시각) | `touch taxonomy/taxonomy.json` |
| 그 밖(코드 동작) | 반출 → 로컬 릴리스 |

설정을 바꾼 뒤에는 새 터미널을 열거나 `set -a; . workspaces/_site/beol.env; set +a`로 다시 읽고 같은 명령을 재실행한다.

## 장애 시 절차 (모든 단계 공통)

0. **환경 문제로 보이면 먼저**(설치·접속·인증서·프록시·포트·시계): `python3 tools/beol_doctor.py`(또는 `--step E0x`). 처음 ✖의 원인·조치와 "담당자에게:" 문장을 그대로 전달한다. 설치 중 실패는 `step` 도우미가 이미 단계 ID를 알려 준다.
1. 터미널의 실패 블록을 본다:
   ```
   [M07 EMBED] 실패  사유=HTTP_401
     원인: …
     조치: …
   ```
   같은 `HTTP_401`이라도 M07이면 임베딩 API, M02·M03이면 LLM API, M08이면 벡터 저장이다. stdout 줄과 stderr 블록은 순서가 섞일 수 있다 — 사유 코드는 블록 안의 것을 본다.
2. 상태 표: `python -m labelbot status --workspace <ws>`(또는 `--all-workspaces`). Python 3.14가 안 되면 `python3 tools/beol_status.py status --workspace <ws>`. 처음 ✖, 마지막 사유 코드·시각, "다음에 할 일"이 나온다. nightly 실패는 daily report 할 일에 `<사유 코드>@<Mxx>`로 나온다. 화면 서버를 Ctrl+C로 끄면 `[Mxx] 중단(사용자)`·종료 0 — 실패가 아니다.
3. 사유 코드 목록: `python -m labelbot codes --milestone <Mxx>`(배포판 python3: `python3 tools/beol_status.py codes --milestone <Mxx>`). 어느 명령이 어느 마일스톤인지는 `codes --entrypoints`(반입 도구는 M19, 환경은 M00).
4. 조치가 설정이면 위 표대로 고치고 같은 명령을 재실행한다. 코드 문제면 `status` 출력 + `milestones.jsonl` + `trace_<run>.log`를 반출 묶음에 넣는다 → 로컬이 가짜 데이터로 재현·수정 → 다음 릴리스.
5. Roo에게는 `status` 출력을 붙여 넣고 원인 설명을 요청한다.

**`BEOL_TRACE=1`(전체 traceback)은 일반 VS Code 터미널에서만** 켠다. Roo 명령 도구에서 켜면 traceback이 Roo 대화 기록·사내 LLM 맥락에 들어간다. 이 출력은 반출하지 않는다.

```bash
BEOL_TRACE=1 python -m labelbot <명령> --workspace <ws>     # 일반 터미널에서만
```

## 반출 (G-OUT, 승인 절차)

| 허용 | 금지 |
|---|---|
| `status`·`codes` 출력, `milestones.jsonl`, `trace_<run>.log`(파일·줄·예외 이름·사유 코드만) | `.b64`, `work.sqlite` |
| `doctor_report.json`(별칭·사유 코드), `setup_<YYYYMMDD>.log`(키 값 가림 — 사내 호스트 이름이 남았는지 확인) | chunk 본문, 원본 문서, 파일명 |
| 사유 코드 로그(`*.log`, `*_events.jsonl`), 테스트 결과(실패 ID·오류 유형), 평가 지표 `.json` | 내부 질문 원문 |
| 반입 보고 `/config/work/beol/_import/<release_label>.json`, `carry_report.json`(CONFLICT 행 키에 taxonomy 값이 들어가므로 `rows[].diff`를 확인) | 키·토큰·비밀번호, `BEOL_TRACE=1` 출력 |
| 설정 차이(키 이름, 비밀이 아닌 값) | 사내 호스트·IP(문서·코멘트 포함) |

```bash
O=out-<release_label>-$(date +%Y%m%d)
mkdir -p "$O" && cp <반출할 파일들> "$O"/
find "$O" \( -name '*.b64' -o -name '*.sqlite' -o -name '*.pptx' -o -name '*.docx' -o -name '*.xlsx' \) -print   # 0줄이어야 한다
python tools/prepush_scan.py --paths "$O"/* --denylist workspaces/_site/scan_denylist.json                        # hits=0이어야 한다
```

- `scan_denylist.json`(비추적, `{"hosts": [...], "domains": [...], "paths": [...]}`)에 사내 호스트·도메인·내부 경로를 적어 두면 반출물에 남은 사내 이름을 잡는다.
- 로컬은 반출물로 가짜 데이터 재현 테스트를 먼저 만들고 고친 뒤 다음 릴리스를 낸다.
