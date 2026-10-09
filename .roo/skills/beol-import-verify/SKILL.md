---
name: beol-import-verify
description: '폐쇄망에 반입한 릴리스 압축 해제 폴더를 확인한다(C0). 폴더 이름을 release_label로 바꾸고 tools/verify_import.py로 transfer/import_manifest.json과 대조해 OK·MISSING·EXTRA·CHANGED·RENAMED_OK를 판정표대로 읽고, code 변경이면 이 릴리스를 쓰지 않는다. 사용자가 "반입 확인", "릴리스 검증", "verify import", "manifest 대조", "새 릴리스 받았어", "압축 풀었어"라고 하면 이 스킬을 쓴다. 이전 릴리스에서 상태를 이어받는 일은 beol-upgrade-carry가 맡는다.'
---

# beol-import-verify: 반입 확인 (C0)

> 수작성 skill(폐쇄망 운영). 근거 문서: `CLOSED_NETWORK_RUNBOOK.md` "C0 — 반입 확인".

배포판 python3(3.8+)로 된다. Python 3.14가 아직 없어도 `verify_import.py`는 `[M19 IMPORT] …` 줄을 낸다. 명령은 사용자 승인 후 Roo 명령 도구로 실행한다(모두 짧다).

## 절차

1. 위치와 폴더 이름을 확인한다. 압축 해제 폴더(`BEOL-Datalabeling-LLM-added`)가 `/config/work/beol/` 아래에 있어야 한다. 다르면 사용자에게 실제 위치를 묻는다.
2. release_label로 폴더 이름을 바꾸고 그 폴더로 간다.
   ```bash
   cd /config/work/beol
   L=$(python3 -c "import json;print(json.load(open('BEOL-Datalabeling-LLM-added/transfer/import_manifest.json',encoding='utf-8'))['release_label'])")
   mv BEOL-Datalabeling-LLM-added "/config/work/beol/$L" && cd "/config/work/beol/$L"
   ```
3. 대조한다. 반입 보고는 항상 `/config/work/beol/_import/<release_label>.json`이다.
   ```bash
   mkdir -p /config/work/beol/_import
   python3 tools/verify_import.py --manifest transfer/import_manifest.json --root . --out "/config/work/beol/_import/$L.json"
   echo "rc=$?"
   ```
4. 결과를 아래 표로 판정하고 한 줄씩 보고한다(건수·class·사유 코드만. office 파일 이름은 쓰지 않는다).

| 결과 | 뜻 | 할 일 |
|---|---|---|
| `code` CHANGED·MISSING(종료 2, `CODE_CHANGED`) | 압축 해제·DRM 변형 또는 직접 수정 | **이 릴리스를 쓰지 않는다.** 반입 보고를 반출하고, 사내 PC에서 7-Zip으로 다시 풀어 보라고 안내한다 |
| `state` CHANGED | 이어받는 상태(taxonomy 등) | 차단 안 함. 업그레이드면 `beol-upgrade-carry` 스킬에서 처리 |
| `office` CHANGED + `DRM_ENCRYPTED`·`NOT_OOXML` | 사내 PC DRM이 더미 문서를 바꿈 | 허용, 기록 |
| `office` `RENAMED_OK` | 이름 인코딩만 깨짐(내용 같음) | 허용 |
| `EOL_CRLF` | 줄 끝만 바뀜 | code면 차단(다시 풀기), 그 밖은 기록 |
| `media`·`text-other` CHANGED | 기록 | `requirements*.txt`는 허용 |
| `EXTRA` | manifest에 없는 파일 | 사용자에게 묻는다 |

## 수락

- 종료 코드 0, 출력의 `release_label`과 폴더 이름이 같다.
- 다음: R1(처음 반입)이면 `beol-env-setup` 스킬, R2부터는 `beol-upgrade-carry` 스킬.

## 마일스톤

| 명령 | 마일스톤 |
|---|---|
| `tools/verify_import.py` | M19 IMPORT |

담당 마일스톤: M19

## 실패하면

터미널의 `[Mxx …] 실패` 블록을 먼저 읽는다 → `python -m labelbot status --workspace <작업 폴더>`(Python 3.14가 없으면 `python3 tools/beol_status.py status --workspace <작업 폴더>`) 출력을 복사해 알려 달라. 환경 문제면 `python3 tools/beol_doctor.py`. `BEOL_TRACE=1`은 Roo 명령으로 실행하지 말고 일반 터미널에서만.
