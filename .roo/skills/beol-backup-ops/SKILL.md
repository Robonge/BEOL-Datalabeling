---
name: beol-backup-ops
description: '벡터·작업 DB 백업 운영과 복원 리허설(C8)을 안내한다. B7 릴리스 이후 활성화된다(백업 도구가 그 릴리스에서 들어온다). 활성화 뒤에는 crontab 백업 줄(daily·weekly·월간 리허설), 첫 수동 실행, daily report의 백업 상태 카드 확인, 리허설 수락(행 수·체크섬·top-k 일치)을 다룬다. 사용자가 "백업", "백업 설정", "복원 리허설", "restore drill", "백업 상태", "SSE_UNAVAILABLE"이라고 하면 이 스킬을 쓴다.'
---

# beol-backup-ops: 백업 운영·리허설 (C8)

> 수작성 skill(폐쇄망 운영). 근거: 폐쇄망 계획 C8.

> **B7 릴리스 이후 활성화.** 백업 도구(`tools/vector_backup.py`·`tools/vector_restore.py`)는 B7 릴리스에서 들어온다. 지금 릴리스에 없으면 "B7 릴리스 이후 활성화"라고 한 줄로 알리고 끝낸다(확인: `ls tools/vector_backup.py`).

## 시작 조건

- 게이트 G-S3에서 SSE/KMS가 확인돼 있어야 한다. 없으면 백업이 `SSE_UNAVAILABLE`로 멈춘다 → 백업에 본문을 넣을지(G-BODY)를 다시 정해야 한다고 알린다.
- 백업에는 `work.sqlite` 전체(본문·파일명)·원본 `.b64`·덤프 `.b64`가 들어간다. 보존은 전부 보관(스크립트가 지우지 않는다).

## 절차 (B7 이후)

1. **crontab(사용자가 `crontab -e`).** 맨 위 `B=`는 지금 릴리스 폴더(업그레이드 때 `beol-upgrade-carry` 스킬 8단계에서 바꾼다).
   ```cron
   B=/config/work/beol/<release_label>
   0 2 * * *  . $B/workspaces/_site/beol.env; cd $B && python tools/vector_backup.py --kind daily  >> workspaces/_backup/backup.log 2>&1
   30 3 * * 0 . $B/workspaces/_site/beol.env; cd $B && python tools/vector_backup.py --kind weekly >> workspaces/_backup/backup.log 2>&1
   0 4 1 * *  . $B/workspaces/_site/beol.env; cd $B && python tools/vector_restore.py --drill     >> workspaces/_backup/backup.log 2>&1
   0 6 * * *  . $B/workspaces/_site/beol.env; cd $B && python nightly_run.py                     >> workspaces/_nightly/cron.log  2>&1
   ```
2. **첫 수동 실행.** 오래 걸릴 수 있으므로 사용자 터미널에서 `python tools/vector_backup.py --kind daily`를 실행하고 마지막 줄을 붙여 달라고 한다. S3의 백업 manifest가 마지막에 올라간다. `SKIPPED_BUSY`(라벨링 실행 중)면 끝난 뒤 다시.
3. **알림 = daily report.** `beol-labeling-daily-report` 스킬로 백업 상태 카드(성공/실패·사유 코드·마지막 성공 시각·워터마크·총용량)를 본다. 마지막 성공이 26시간을 넘으면 경고다. 메일·webhook은 없다.
4. **복원 리허설.** 사용자 터미널에서 `python tools/vector_restore.py --drill`. 결과 `restore_drill_<date>.json`의 모델별 OK 행 수·행별 체크섬·정확 top-k가 일치하고 임시 표가 지워졌는지 본다.

## 장애 복구 순서(요약)

벡터 DB 장애 → S3 sqlite 스냅샷 + `push-vectors --resend` → 운영 `work.sqlite`에서 `--resend` → 원본 `.b64`만 남으면 업무 PC 재수집. 서버 재설치는 `beol-env-setup` 스킬 + `beol-upgrade-carry` 스킬.

## 수락

- 리허설 json의 행 수·체크섬·top-k 일치, 임시 표 삭제, daily report 백업 카드가 성공.

## 마일스톤

| 명령 | 마일스톤 |
|---|---|
| `tools/vector_backup.py` · `tools/vector_restore.py`(B7 릴리스) | M17 BACKUP |
| `nightly_run.py` · `daily_report.py` | M18 NIGHTLY_REPORT |

담당 마일스톤: M17·M18

## 실패하면

터미널의 `[Mxx …] 실패` 블록을 먼저 읽는다 → `python -m labelbot status --workspace <작업 폴더>`(Python 3.14가 없으면 `python3 tools/beol_status.py status --workspace <작업 폴더>`) 출력을 복사해 알려 달라. 환경 문제면 `python3 tools/beol_doctor.py`. `BEOL_TRACE=1`은 Roo 명령으로 실행하지 말고 일반 터미널에서만.
