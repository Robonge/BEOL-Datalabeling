---
name: beol-upgrade-carry
description: '새 릴리스(R2부터)로 업그레이드할 때 이전 릴리스 폴더의 상태(taxonomy, 라벨링 규칙, 처리 완료 목록, 발표·RAG 화면, workspaces)를 새 폴더로 이어받는다(CU). tools/carry_state.py dry-run → 사용자가 CONFLICT를 고름(--resolve) → --apply → tools/cloud_migrate_paths.py 경로 변환 → smoke 확인 순서다. 사용자가 "업그레이드", "새 릴리스로 옮겨줘", "상태 이어받기", "carry state", "이전 릴리스에서 가져와"라고 하면 이 스킬을 쓴다. 반입 확인은 beol-import-verify가 먼저 한다.'
---

# beol-upgrade-carry: 업그레이드 — 새 폴더 + 상태 이어받기 (CU)

> 수작성 skill(폐쇄망 운영). 근거 문서: `CLOSED_NETWORK_RUNBOOK.md` "CU — 업그레이드".

새 릴리스 폴더가 `beol-import-verify` 스킬(C0)을 통과한 뒤 한다. 바꾸는 명령(`--apply`)은 사용자가 dry-run 결과를 확인한 뒤에만 실행한다.

```bash
OLD=/config/work/beol/<이전 release_label>
NEW=/config/work/beol/<새 release_label>
```

## 절차

1. **운영 중지(사용자가 한다).** `crontab -e`로 줄을 주석 처리하고, 떠 있는 화면 서버는 그 터미널에서 Ctrl+C로 끈다. 끝났다고 알려 오면 다음으로 간다.
2. **이어받기 dry-run**(배포판 python3도 된다).
   ```bash
   cd "$NEW" && python3 tools/carry_state.py --old "$OLD" --new "$NEW"
   ```
   - 기준은 `$OLD/transfer/import_manifest.json`의 state 해시다. 없으면 `NO_BASE_MANIFEST`로 멈춘다 → 수동 비교가 필요하다고 알리고 반출 보고로 넘긴다.
   - 판정을 건수로 보고한다: `KEEP_CLOSED`(폐쇄망 사본 유지) · `TAKE_RELEASE`(릴리스만 바뀜) · `CONFLICT`(둘 다 바뀜) · `ADDED_CLOSED` · `FLAG_RELEASE_DELETED` · `FLAG` · `COPIED_UNTRACKED`.
   - 새 manifest에 `state_overrides`가 있으면 그 이유를 사용자에게 보여 준다(예: `rag/beol_rag.html`은 B6 릴리스가 바꾼다).
3. **CONFLICT 해결.** 출력의 차이(taxonomy는 `taxonomy[축|값|상위값]` 행, 그 밖 JSON은 키 경로, HTML은 줄 범위)를 보여 주고 파일마다 `closed`(폐쇄망 것)·`release`(새 릴리스 것) 중 하나를 사용자에게 묻는다. 고른 대로:
   ```bash
   python3 tools/carry_state.py --old "$OLD" --new "$NEW" --resolve taxonomy/taxonomy.json=closed --resolve rag/beol_rag.html=release
   ```
   `FLAG`·`FLAG_RELEASE_DELETED`는 사람이 파일을 보고 직접 정한다(Roo가 정하지 않는다).
4. **적용**(사용자 확인 후): 3의 명령에 `--apply`를 붙인다 → `$NEW/carry_report.json`.
5. **`.env`**: 이어받기 대상이 아니다. `cp .env.example .env && chmod 600 .env`(키 값은 `workspaces/_site/beol.env`에 있어 함께 넘어왔다).
6. **경로 변환**(옛 폴더 경로가 박힌 작업 폴더):
   ```bash
   python tools/cloud_migrate_paths.py --old-root "$OLD"            # dry-run, 건수 확인
   python tools/cloud_migrate_paths.py --old-root "$OLD" --apply
   python tools/cloud_migrate_paths.py --old-root "$OLD"            # files_converted=0 이어야 한다
   ```
   업무 PC에서 옮겨 온 작업 폴더(CM)면 `--old-root '<업무 PC 저장소 경로>'`(슬래시로 쓴 Windows 경로)로 같은 순서를 한다. 입력 폴더가 저장소 밖이면 `OUTSIDE_REPO`로 그대로 둔다(정상).
7. **smoke**: 저장소 안 입력은 `True True`(업무 PC 입력 `OUTSIDE_REPO`는 `False`가 정상).
   ```bash
   python -c "from labelbot.workspace import Workspace as W;import glob,os;[print(os.path.basename(p),os.path.isfile(W(p,create=False).taxonomy_path),os.path.isdir(W(p,create=False).input_root)) for p in sorted(glob.glob('workspaces/261004_BEOL_*'))]"
   ```
   Code-Engr-bot 축·규칙 점검이 같은 입력 폴더를 한 묶음으로 보는지 확인한다. 같은 입력이 두 번 재라벨링되면 반출 보고.
8. **운영 재개(사용자가 한다).** `~/.bashrc`의 `beol.env` 경로와 crontab의 `B=`를 `$NEW`로 바꾸고 cron을 다시 켠다. `$OLD`는 다음 릴리스까지 보존한다(롤백 = 경로를 되돌림).

## 수락

- `carry_report.json`이 있고 CONFLICT가 모두 해결됨, `cloud_migrate_paths.py` 재실행 `files_converted=0`, smoke 출력이 위 기준과 같음.
- 이어서 `beol-release-accept` 스킬로 릴리스 수락을 한다.

## 마일스톤

| 명령 | 마일스톤 |
|---|---|
| `tools/carry_state.py` | M19 IMPORT |
| `tools/cloud_migrate_paths.py` | M19 IMPORT |

담당 마일스톤: M19

## 실패하면

터미널의 `[Mxx …] 실패` 블록을 먼저 읽는다 → `python -m labelbot status --workspace <작업 폴더>`(Python 3.14가 없으면 `python3 tools/beol_status.py status --workspace <작업 폴더>`) 출력을 복사해 알려 달라. 환경 문제면 `python3 tools/beol_doctor.py`. `BEOL_TRACE=1`은 Roo 명령으로 실행하지 말고 일반 터미널에서만.
