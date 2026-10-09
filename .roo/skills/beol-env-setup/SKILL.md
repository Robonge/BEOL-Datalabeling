---
name: beol-env-setup
description: '폐쇄망 서버에 처음(R1) 실행 환경을 만든다(C1). 설치 전에 tools/beol_doctor.py로 진단하고, CLOUD_SETUP.md의 단계(OS 확인, 사이트 설정 beol.env, 인증서·시계, 빌드 패키지, Python 3.14.2, 브라우저·폰트, 작업 폴더, crontab, 확인)를 step 도우미로 하나씩 실행한다. 실패하면 실패 블록과 doctor의 "담당자에게:" 문장을 그대로 인용하고 다음 단계로 넘어가지 않는다. 사용자가 "환경 구성", "서버 세팅", "설치 시작", "CLOUD_SETUP 진행", "doctor 돌려줘", "파이썬 설치", "프록시 안 돼"라고 하면 이 스킬을 쓴다.'
---

# beol-env-setup: 환경 구성 (C1)

> 수작성 skill(폐쇄망 운영). 근거 문서: `CLOUD_SETUP.md`(절 번호는 그 문서 기준), `CLOSED_NETWORK_RUNBOOK.md`.

## 지킬 것

- **doctor 먼저.** 설치 명령보다 `python3 tools/beol_doctor.py`를 먼저 돌린다.
- **한 번에 한 단계.** `CLOUD_SETUP.md`의 `step <ID> "<설명>" -- <명령>`을 하나씩 실행하고, `[M00 ENV/<ID>] 완료`를 확인한 뒤에만 다음으로 간다. `[M00 ENV/<ID>] 실패 rc=<n>`이면 **다음 단계로 넘어가지 않는다**(도우미도 `건너뜀`으로 막는다).
- **실패는 그대로 인용한다.** 실패 블록(마지막 20줄)과 `python3 tools/beol_doctor.py --step <ID>` 표의 처음 ✖ 줄, 그 줄의 "담당자에게:" 문장을 고치지 않고 그대로 사용자에게 보여 준다. 사용자가 그 문장을 보안·인프라 담당에게 전달한다.
- **실값은 저장소에 쓰지 않는다.** 프록시·CA·사내 도메인 같은 실제 값은 터미널과 비추적 `workspaces/_site/`(`beol.env`, `doctor_targets.json`)에만 둔다. 이 대화에도 키 값을 옮기지 않는다.
- `sudo`가 필요한 명령과 비밀번호 입력은 사용자가 직접 한다.

## 절차

0. **step 도우미 준비.** `step`은 셸 함수라 터미널마다 다시 정의해야 한다. 사용자에게 VS Code 터미널을 하나 열고 `CLOUD_SETUP.md` 0절의 `# >>> step 도우미` ~ `# <<< step 도우미` 블록을 붙여 넣어 달라고 한다. 이후 `step` 명령은 **그 터미널**에서 실행한다(Roo 명령 도구가 다른 셸을 쓰면 `step: command not found`가 난다 — 그때는 사용자에게 그 터미널에서 실행해 달라고 안내하고 출력 끝 줄을 받는다).
1. **설치 전 진단(1절).**
   ```bash
   mkdir -p workspaces/_site
   cp config/doctor_targets.example.json workspaces/_site/doctor_targets.json
   chmod 600 workspaces/_site/doctor_targets.json
   ```
   사용자가 `workspaces/_site/doctor_targets.json`의 host를 실제 사내 호스트로 고치고(쓰지 않는 대상은 지움) 알려 오면:
   ```bash
   python3 tools/beol_doctor.py
   ```
   표에서 처음 ✖를 본다. 프록시 판정(E05)이 먼저 요약된다. `CONN_TIMEOUT`·`PROXY_AUTH_407`·`PROXY_BLOCKED_URL`·`DNS_UNRESOLVED`·`TLS_CA_UNKNOWN`·`PKG_NOT_IN_MIRROR`·`PIP_INDEX_UNREACHABLE`은 "담당자에게:" 문장을 그대로 인용한다.
2. **이후 절을 순서대로** `CLOUD_SETUP.md`에서 한 절씩 읽어 `step` 명령을 하나씩 안내·실행한다. 절마다 끝나면 `[M00 ENV/<ID>] 완료` 줄 수를 보고한다.

| 절 | 단계 ID | 내용 | 메모 |
|---|---|---|---|
| 2 | E01 | OS·아키텍처, `/config/work/beol/_import/env.json` | deb·rpm 계열을 정한다 |
| 3 | E14·E05·E11 | `.env`·`workspaces/_site/beol.env`, 프록시, 시간대 | `beol.env` 내용은 사용자가 편집기로 쓴다 |
| 4 | E04·E10 | 사내 루트 CA, 시계 동기 | `sudo` |
| 5 | E06 | 빌드 의존 패키지 | `sudo`, 미러 |
| 6 | E08 | Python 3.14.2 빌드 | `make`는 오래 걸린다 → 사용자 터미널에서 실행하고 끝나면 알려 달라 |
| 7 | E09 | chromium·Noto Sans CJK 폰트 | 브라우저 경로는 `pipeline.json` `render.browser_path` |
| 8 | E13 | `~/Downloads`, `workspaces` 실제 폴더 | 심볼릭 링크 금지 |
| 9 | — | crontab(nightly) | 사용자가 `crontab -e` |
| 10 | E15 | doctor 재실행, `selfcheck`, 테스트 | 아래 수락 |

3. **확인(10절).**
   ```bash
   python3 tools/beol_doctor.py
   python -V
   mkdir -p workspaces/_setup_check && python -m labelbot selfcheck --workspace workspaces/_setup_check
   ```
   테스트 묶음은 오래 걸리므로 `beol-release-accept` 스킬에서 사용자 터미널로 돌린다.

## 수락

- 위 `step`이 모두 `완료`, `/config/work/beol/_import/env.json` 기록, doctor 재실행에서 E01–E14 ✔(E15는 게이트 후 릴리스), `workspaces/_site/doctor_report.json` 보관.
- `python -V` = `Python 3.14.2`(비로그인 셸·cron과 같은 빈 환경 둘 다).

## 마일스톤

| 명령 | 마일스톤 |
|---|---|
| `tools/beol_doctor.py` | M00 ENV/CLI |
| `step <ID> …`(`[M00 ENV/<ID>]` 줄) | M00 ENV/CLI |
| `labelbot selfcheck` | M00 ENV/CLI |

담당 마일스톤: M00

## 실패하면

터미널의 `[Mxx …] 실패` 블록을 먼저 읽는다 → `python -m labelbot status --workspace <작업 폴더>`(Python 3.14가 없으면 `python3 tools/beol_status.py status --workspace <작업 폴더>`) 출력을 복사해 알려 달라. 환경 문제면 `python3 tools/beol_doctor.py`. `BEOL_TRACE=1`은 Roo 명령으로 실행하지 말고 일반 터미널에서만.
