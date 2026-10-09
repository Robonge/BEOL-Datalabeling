---
name: beol-release-accept
description: '폐쇄망에서 릴리스마다 수락 검사를 한다(C3·C6): 반입 확인·업그레이드 통과 확인, 더미 의존 모듈을 뺀 테스트 묶음(manifest test_modules), Roo skill 생성물 일치(gen_roo_skills --check), status·codes 출력이 배포판 python3와 Python 3.14에서 같은지, 그리고 릴리스 종류별(R1·B2b·B3·B4·B6·B7) 수락 항목. 수락 단계마다 끝에 status를 돌린다. 사용자가 "릴리스 수락", "수락 테스트", "릴리스 검사", "테스트 돌려줘", "C3", "C6", "새 릴리스 써도 돼?"라고 하면 이 스킬을 쓴다.'
---

# beol-release-accept: 릴리스별 수락 (C3·C6)

> 수작성 skill(폐쇄망 운영). 근거: `CLOSED_NETWORK_RUNBOOK.md` "C3 — 비더미 테스트", 폐쇄망 계획 C6.

수락 단계마다 끝에 `status`를 돌려 처음 ✖가 없는지 본다. 실패는 원인을 분류해 반출 보고로 넘긴다(폐쇄망에서 코드를 고치지 않는다).

## 공통 (모든 릴리스)

1. **반입·업그레이드 확인.** `/config/work/beol/_import/<release_label>.json`이 있고 종료 코드 0이었는지(`beol-import-verify` 스킬), 업그레이드면 `carry_report.json`이 있는지(`beol-upgrade-carry` 스킬) 확인한다.
2. **비더미 테스트(C3).** 몇 분 걸리므로 사용자에게 별도 VS Code 터미널에서 실행하고 마지막 요약 줄을 붙여 달라고 한다.
   ```bash
   python -m pytest -p no:cacheprovider -q $(python -c "import json;print(' '.join(json.load(open('transfer/import_manifest.json'))['test_modules']))")
   ```
   pytest가 미러에 없으면:
   ```bash
   python -m unittest $(python -c "import json;print(' '.join(m[:-3].replace('/','.') for m in json.load(open('transfer/import_manifest.json'))['test_modules']))")
   ```
   수락: 실패는 로컬 기준선 10건 중 남은 것만(`domain_engrbot` test_harness 2·test_integration 3·test_judge 4, `tests/test_defaults_taxonomy` 1), 새 실패 0. 차이는 실패 테스트 ID·오류 유형으로 반출.
3. **Roo skill 생성물 일치.**
   ```bash
   python tools/gen_roo_skills.py --check
   ```
   `"check": "ok"`여야 한다(`.roo/`를 폐쇄망에서 고치지 않았다는 확인).
4. **상태·사유 코드 표가 두 Python에서 같은지.**
   ```bash
   python3 tools/beol_status.py status --all-workspaces
   python3 tools/beol_status.py codes --entrypoints
   python -m labelbot status --all-workspaces
   python -m labelbot codes --entrypoints
   ```
   배포판 python3와 Python 3.14 출력이 같아야 한다.

## 릴리스별

| 릴리스 | 수락 |
|---|---|
| R1 마일스톤 | `python -m labelbot selfcheck --workspace <작업 폴더>`(M00)가 빠진 env·설정을 조치와 함께 표시. 화면 서버가 `[M05 REVIEW_SERVE] 대기 중 URL=…` 출력, 같은 포트로 다시 띄우면 `PORT_IN_USE` |
| R1 | `beol-env-setup`·`beol-drm-probe`·`beol-proxy-measure` 스킬 수락 완료, Roo skill 선택 19/19와 규칙 답변(C2), `python -m labelbot rules-diff --workspace <작업 폴더>`가 git 없이 오류 없이 출처 표시 |
| B2b 프로필 | `beol.env`에 `BEOL_ALLOWED_HOST_SUFFIXES`·키 env 추가 후 `python -c "import os;os.environ['BEOL_ALLOWED_HOST_SUFFIXES']"` 오류 없음(빠지면 외부 전송 가드가 꺼진다), `selfcheck --probe-llm` LLM PASS, 임베딩 차원 = G-API, 허용 목록 밖 URL은 `EXTERNAL_BLOCKED` |
| B3 벡터 | `selfcheck` 벡터 저장 PASS, 스키마 적용(DBA 승인), 소량 `push-vectors` OK |
| B4 S3 | 접미사 목록에 S3 도메인 포함, 작은 객체 PUT/GET/DELETE·SSE, `CLOCK_SKEW` 없음 |
| B6 ragsrv | 프록시 URL로 질문 1건, `/img/` 이미지, 위조 Origin 403 |
| B7 백업 | `beol-backup-ops` 스킬의 리허설 수락 |

각 줄을 마치면 `python -m labelbot status --all-workspaces`(배포판 python3면 `python3 tools/beol_status.py status --all-workspaces`)를 돌려 처음 ✖·사유 코드를 보고한다.

## 마일스톤

| 명령 | 마일스톤 |
|---|---|
| `labelbot selfcheck` · `labelbot status` · `labelbot codes` · `tools/beol_status.py` | M00 ENV/CLI |
| `tools/verify_import.py` · `tools/carry_state.py`(확인) | M19 IMPORT |
| `labelbot serve`(R1 확인) | M05 REVIEW_SERVE |
| `labelbot rules-diff` | M23 DIFF_CHECK |
| `tools/gen_roo_skills.py --check` | M25 RELEASE_TOOLS |

담당 마일스톤: M00·M05·M19·M23·M25

## 실패하면

터미널의 `[Mxx …] 실패` 블록을 먼저 읽는다 → `python -m labelbot status --workspace <작업 폴더>`(Python 3.14가 없으면 `python3 tools/beol_status.py status --workspace <작업 폴더>`) 출력을 복사해 알려 달라. 환경 문제면 `python3 tools/beol_doctor.py`. `BEOL_TRACE=1`은 Roo 명령으로 실행하지 말고 일반 터미널에서만.
