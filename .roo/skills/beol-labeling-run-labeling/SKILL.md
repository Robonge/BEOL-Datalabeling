---
name: beol-labeling-run-labeling
description: 'BEOL 라벨링 파이프라인(입력 폴더 → BEOL-labeling 파싱·분류·라벨링·검수 대기 → 사람 검수 완료 → BEOL-labeling-feedback 반영·장부·임베딩·벡터 저장소 적재)을 한 번에 이어서 돌리는 트리거 스킬. 사람 손이 필요한 곳(검수 완료)에서만 멈추고, 적재가 끝나면 품질 점검 단계(도메인 질문 beol-labeling-domain-engr-bot 스킬, taxonomy 보드, 축·규칙 점검 beol-labeling-code-engr-bot 스킬)를 한 줄로 안내하고 끝낸다. 품질 점검 스킬은 자동으로 부르지 않는다. 사용자가 "라벨링 끝까지 돌려줘", "라벨링부터 적재까지", "flow대로 라벨링 실행", "run-labeling", "run-all"(옛 이름), "전체 라벨링 실행"이라고 하면 이 스킬을 쓴다. 한 단계만이면 BEOL-labeling 또는 BEOL-labeling-feedback을 쓴다.'
---

# BEOL-labeling-run-labeling: 입력 → 라벨링 → 검수 → 반영 · 적재

> 이 문서는 `.claude/skills/BEOL-labeling-run-labeling/SKILL.md`에서 생성됐다. 직접 고치지 말고 원본을 고친 뒤 `python tools/gen_roo_skills.py`를 다시 실행한다.

> 그룹: ① 라벨링 파이프라인 · 상위: 없음 · 하위: beol-labeling 스킬, beol-labeling-feedback 스킬 · 전체 지도: README.md "스킬 지도"

라벨링 파이프라인의 단계 스킬을 **순서대로 부르는 지휘자**다(2026-10-07 `BEOL-labeling-run-all`에서 이름과 범위를 바꿈). 새 로직은 없고, 각 단계의 절차·규칙·"지켜야 할 것"은 해당 스킬 `SKILL.md`를 그대로 따른다(충돌하면 루트 `CLAUDE.md` → 단계 스킬 → 이 파일 순).

범위는 **벡터 저장소 적재까지**다. 도메인 질문(Domain-Engr-bot) · taxonomy 수정 보드 · 축/규칙 변경 재라벨링(Code-Engr-bot → axis-update · rules-update)은 **품질 점검 · 재라벨링** 루프로 옮겼고, 이 스킬은 부르지 않는다. 그 루프는 사람이 필요할 때 따로 시작한다.

```
[1] BEOL-labeling           입력 폴더 → 파싱 → 1~3차 라벨링 → 대시보드          ⏸ 사람: 검수 완료
[2] BEOL-labeling-feedback  교정 반영 → Domain-Engr-bot 장부 → 임베딩 → 벡터 저장소 적재   (자동)
→ 끝. 품질 점검 단계 안내 한 줄
```

## 인자

- 입력 폴더: 사용자가 준 경로. 없으면 `parshing test files`(코드 폴더 기준). 사용자가 다른 이름을 말했는데 그 폴더가 없으면, 어느 폴더로 대체했는지 첫 줄에 알린다.
- 코드 폴더: 저장소 루트(`git rev-parse --show-toplevel`, 이 SKILL.md 기준 ../../..).

## 절차

각 단계는 해당 스킬의 절차를 순서대로 끝까지 따른다. 단계 사이에서 "계속할까요"를 묻지 않는다. 묻는 것은 단계 스킬이 원래 묻는 것(중복 파일, 작업 폴더 고르기 등)뿐이다.

1. **BEOL-labeling** — `beol-labeling` 스킬 절차를 따른다(인자: <입력 폴더>). 7단계 안내까지 하고 멈춘다(검수 완료는 사용자가 알려 준다).
2. **검수 완료 신호** — 사용자가 "검수 끝났어"라고 하거나 완료 대기 출력(`done: true`)을 붙여 넣으면 `beol-labeling` 스킬 7-3대로 `beol-labeling-feedback` 스킬 절차를 이어서 따른다.
3. **feedback이 끝나면** 진행 현황을 100%로 보여 주고 아래 안내 한 줄로 끝낸다. 품질 점검 스킬을 부르지 않는다.
   - `다음(선택): 도메인 질문 beol-labeling-domain-engr-bot 스킬 · taxonomy 보드 beol-taxonomy-dashboard 스킬 · 축/규칙 점검 beol-labeling-code-engr-bot 스킬`
   - feedback 보고의 "라벨링 피드백: 규칙 후보 k개" 줄이 0이 아니면 Domain-Engr-bot을 맨 앞에 둔다.

## 진행 현황

시작할 때와 사람 지점에서 멈출 때, 끝날 때 아래 블록을 보여 준다(건수·ID·사유 코드만. 파일명·본문 금지). 단계 스킬 안의 세부 진행 블록은 그 스킬 형식대로 따로 나온다.

```
**진행 현황 · BEOL-labeling-run-labeling** · run_id: <RUN 또는 ->

🟩🟩🟩🟩🟩⬜⬜⬜⬜⬜ **50%** · 1/2 완료

> ⏸ **지금 1단계 끝 · 사람 검수 완료 대기**

- ⏸ **1. 라벨링** — 대시보드에서 검수 시작 → 검수 완료 대기
- ⬜ 2. 검수 반영·적재
```

막대는 10칸, `🟩` 수 = 누적% ÷ 10 내림(단계당 50%). `✅` 완료, `⏸` 사람 대기, `⬜` 대기, `❌` 실패, `⏭️` 건너뜀.

## 멈춤·실패 처리

- 단계 스킬이 `[오류]`나 사전 점검 FAIL로 멈추면 그 단계를 `❌`로 두고 사유 코드만 보고한 뒤 멈춘다. 다음 단계로 넘어가지 않는다.
- 사람 지점에서는 무엇을 눌러야 하는지 한 줄로 안내하고 여기서 멈추고 사용자가 알려 줄 때까지 기다린다. 대기 중에 임의로 폴링하지 않는다.

## 하지 않는 일

- 사람 화면의 버튼(검수 시작, 검수 완료)을 대신 누르지 않는다.
- Domain-Engr-bot · taxonomy 보드 · Code-Engr-bot을 자동으로 부르지 않는다(품질 점검 루프, 사용자 결정 2026-10-07).
- `taxonomy/taxonomy.json`을 직접 고치지 않는다. taxonomy는 사람이 taxonomy 보드·편집기에서 고친다.
- 사내 파일을 경로로 열지 않는다. 열기는 `labelbot.ingest.read_input` 한 곳이다(루트 `CLAUDE.md` DRM 규칙).

## 관계

- 한 단계만 원하면 BEOL-labeling 또는 BEOL-labeling-feedback, 도메인 질문은 BEOL-labeling-Domain-Engr-bot, taxonomy 보드는 BEOL-taxonomy-dashboard, 축·규칙 변경 재라벨링은 BEOL-labeling-Code-Engr-bot이 맡는다.

## 마일스톤

이 스킬의 명령은 터미널에 `[Mxx 이름] 시작·완료·실패` 줄을 낸다. 실패하면 아래 ID로 어느 단계인지 보고, `python -m labelbot codes --milestone <Mxx>`로 사유 코드와 조치를 본다.

| 명령 | 마일스톤 |
|---|---|
| `labelbot run` | M01 INGEST · M02 CLASSIFY · M03 LABEL · M04 REPORT |
| `.claude/skills/BEOL-labeling/scripts/init_workspace.py` | M24 WORKSPACE_INIT |
| `domain_engrbot labeling-rules` | M11 DOMAIN_QA |
| `labelbot taxonomy-diff` | M23 DIFF_CHECK |
| `labelbot selfcheck` | M00 ENV/CLI |
| `.claude/skills/BEOL-labeling/scripts/record_ingested.py` | M01 INGEST |
| `labelbot compare` | M04 REPORT |
| `labelbot slide-images` | M09 SLIDE_IMAGES |
| `labelbot review` | M04 REPORT |
| `labelbot dashboard` | M04 REPORT |
| `.claude/skills/BEOL-labeling/scripts/summary.py` | M00 ENV/CLI |
| `labelbot serve` | M05 REVIEW_SERVE |
| `.claude/skills/BEOL-labeling-feedback/scripts/wait_review_done.py` | M05 REVIEW_SERVE |
| `.claude/skills/BEOL-labeling-feedback/scripts/collect_inbox.py` | M06 FEEDBACK_APPLY |
| `labelbot apply` | M06 FEEDBACK_APPLY |
| `domain_engrbot intake` | M11 DOMAIN_QA |
| `domain_engrbot taxonomy-board` | M12 TAXONOMY_BOARD |
| `labelbot report` | M04 REPORT |
| `labelbot embed` | M07 EMBED |
| `labelbot push-vectors` | M08 PUSH_VECTORS |
| `labelbot push-slides` | M10 PUSH_SLIDES |

담당 마일스톤: M00·M01·M02·M03·M04·M05·M06·M07·M08·M09·M10·M11·M12·M23·M24

명령은 단계 스킬(`beol-labeling`, `beol-labeling-feedback`)이 낸다.

## 실패하면

터미널의 `[Mxx …] 실패` 블록을 먼저 읽는다 → `python -m labelbot status --workspace <작업 폴더>`(Python 3.14가 없으면 `python3 tools/beol_status.py status --workspace <작업 폴더>`) 출력을 복사해 알려 달라. 환경 문제면 `python3 tools/beol_doctor.py`. `BEOL_TRACE=1`은 Roo 명령으로 실행하지 말고 일반 터미널에서만.
