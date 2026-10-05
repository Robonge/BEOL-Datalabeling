---
name: labeling-Engr-bot
description: labelbot 라벨링 결과를 BEOL 도메인 지식으로 검수한다. 구조 게이트(L0~L3B, L6) 위에 도메인 규칙 층 L4와 중복 문서 일관성 층 L5를 켜서 engrbot을 돌리고, qa_run_id·판정 건수·리포트와 검토 화면 위치를 알린 뒤 도메인 이슈(L4·L5 코드)를 건수 중심으로 요약한다. 사용자가 "도메인 검수", "Engr-bot 돌려줘", "엔지니어 관점 검수", "라벨 도메인 검수 돌려줘"라고 하거나 /labeling-Engr-bot을 부르면 이 스킬을 쓴다. 라벨링 실행은 BEOL-labeling, 사람 검수 반영과 적재는 BEOL-labeling-feedback, 저장소 코드 검수는 labeling-codebot이 맡는다.
---

# labeling-Engr-bot: 도메인 검수

labelbot이 만든 라벨을 BEOL 도메인 관점으로 검수한다. 기본 구조 게이트(L0~L3B, L6)에 **L4 도메인 규칙**과 **L5 중복 문서 일관성**을 더해 `engrbot`을 돌린다. engrbot은 라벨링 결과를 읽기만 하며, 판정과 리포트를 `qa/` 아래에 쓴다.

```
작업 폴더 확인 → engrbot run(L0~L6) → qa_run_id·건수 전달 → 리포트·검토 화면 안내 → 도메인 이슈 요약
```

## 고정 값

- 코드 폴더: `C:\Users\dltkd\Desktop\261004 BEOL AX day2`. 모든 명령은 여기서 `PYTHONIOENCODING=utf-8`을 붙여 실행한다.
- 작업 폴더 `<WS>`: 인자로 받는다. 없으면 코드 폴더의 `workspaces\` 아래에서 고른다. 폴더가 없거나 여러 개이면 사용자에게 어느 폴더인지 묻는다. 임의로 고르지 않는다.
- 결과 위치: `<WS>\qa\runs\<qa_run_id>\` 아래에 `report.md`, `report.json`, `review.html` 등이 생긴다.
- 도메인 규칙 파일: `engrbot/defaults/domain_rules.json`(`policy`의 `l4.rules_path`로 바꿀 수 있다).
- 교정 장부: `workspaces\_engrbot\ledger\`(커밋 제외). 사람 검수 교정이 Engr-bot 입력으로 들어오는 곳이다. 설계는 `engrbot/docs/plan-ledger.md`.

## 사람 검수 결과를 입력으로 받는다 (사용자 결정, 2026-10-05)

`/BEOL-labeling-feedback`이 검수 교정을 반영하면(`labelbot apply`) 바로 `python -m engrbot intake --workspace "<WS>"`를 불러 그 작업 폴더의 교정을 교정 장부에 넣는다. `engrbot run`도 시작할 때 그 작업 폴더를 다시 intake한다(멱등, LLM 0회). 장부는 세 곳에 쓰인다.

| 장부 산출 | 쓰는 곳 |
|---|---|
| `golden.jsonl` 누적 골든셋 | `python -m engrbot eval --workspace "<WS>" --golden ledger`(층별 탐지율·오탐률) |
| `judge_examples.jsonl` 사람 판정 예시 | L3b judge 호출에 비슷한 라벨의 사람 판정 사례를 예시로 붙인다. 같은 파일·같은 본문의 사례는 쓰지 않고, 사외 호스트에서 허용되지 않는 출처의 사례는 빠진다 |
| `rule_candidates.json` L4 규칙 후보 | 반복된 교정 패턴에서 만든 draft 규칙이다. `run`이 draft로 함께 적용해 `L4_RULE_DRAFT_HIT`(판정 영향 없음)로 얼마나 걸리는지 보여 준다. 승인은 사람이 `engrbot/defaults/domain_rules.json`에 옮겨 `approved`로 바꾸는 것이다 |

장부의 `golden.jsonl`·`judge_examples.jsonl`에는 본문 인용이 들어 있다. Read·Grep·`cat`으로 열어 보고하지 않고 `python -m engrbot ledger --workspace "<WS>" status` 출력의 건수만 쓴다. 후보 규칙 목록은 `rule_candidates.md`(본문 없음)를 사람이 연다.

## 도메인 규칙의 상태

규칙마다 `status`가 있다.

| status | 동작 |
|---|---|
| `draft` | 기록만 한다(`L4_RULE_DRAFT_HIT`, info). 판정은 바꾸지 않는다 |
| `approved` | 규칙의 `severity`(major 또는 minor)로 이슈를 내고 판정에 반영한다 |

규칙 유형은 세 가지다.

| 유형 | 잡는 것 |
|---|---|
| `axis_combo` | 한 축의 값이 조건에 맞을 때 다른 축의 값이 기대와 다르거나 금지된 값이다 |
| `title_label` | chunk 제목에서 뽑은 축 값이 라벨에 없다 |
| `synonym_suggest` | 축 값이 taxonomy 밖이고 동의어 표의 alias와 같아 표준값을 제안한다(자동 수정하지 않는다) |

`draft`를 `approved`로 올리는 것은 도메인 담당자 몫이다. 이 스킬은 규칙을 임의로 `approved`로 올리지 않고, 규칙 파일도 고치지 않는다.

## 지켜야 할 것

- 이 봇은 labelbot의 산출, taxonomy, 프롬프트를 고치지 않는다. 읽고 판정만 한다.
- 콘솔과 대화에 본문과 파일명을 옮기지 않는다. 보고에는 건수, 실행 ID, 사유 코드만 쓴다.
- 사내 파일을 Read 도구로 열지 않는다. 사내 파일은 DRM이 걸려 있고, 열기는 labelbot의 ingest 한 곳뿐이다(루트 `CLAUDE.md`).
- judge 설정이 없으면 `--no-judge`를 쓸 수 있다. 이때 judge를 거치지 않은 레코드는 PASS가 되지 않으므로 이 실행의 PASS는 0건이다. 보고에 그 사실을 적는다.
- 도메인 판정은 규칙 파일이 정한 범위에서만 한다. LLM 도메인 judge는 아직 없다.

## 절차

### 1. 작업 폴더 확인

위 "고정 값"대로 `<WS>`를 정한다. 없거나 여러 개이면 `AskUserQuestion`으로 한 번 묻는다.

### 2. 검수 실행

```bash
python -m engrbot run --workspace "<WS>" --layers L0,L1,L2,L3A,L3B,L4,L5,L6
```

judge 설정이 없거나 judge를 부르지 않으려면 `--no-judge`를 붙인다. 가장 최근 라벨링 실행이 아닌 다른 실행을 검수하려면 `--run <라벨러 실행 ID>`를 붙인다.

### 3. 콘솔 결과 전달

콘솔의 `[run] qa_run_id=<ID> 레코드 n (PASS n, AUTO_FIX n, REVIEW n, REJECT n)` 줄에서 qa_run_id와 판정 건수를 그대로 전한다. judge 줄(`호출 n회` 또는 `미실행`)도 한 줄로 전한다. 교정 장부 상태가 필요하면 아래 명령의 건수 줄만 전한다.

```bash
python -m engrbot ledger --workspace "<WS>" status
```

### 4. 리포트와 검토 화면 안내

- 리포트: `<WS>\qa\runs\<ID>\report.md`
- 검토 화면은 `<WS>\qa\runs\<ID>\review.html`이다. 다시 만들어야 하면 아래 명령을 쓴다.

```bash
python -m engrbot review --workspace "<WS>" --qa-run <ID>
```

리포트만 다시 만들 때는 `python -m engrbot report --workspace "<WS>" --qa-run <ID>`(LLM 0회)를 쓴다.

### 5. 도메인 이슈 요약

`report.md`에서 도메인 층의 이슈 코드를 건수 중심으로 요약한다.

| 코드 | 뜻 |
|---|---|
| `L4_AXIS_COMBO_VIOLATION` | 축 조합 규칙 위반 |
| `L4_TITLE_LABEL_MISMATCH` | 제목과 라벨 불일치 |
| `L4_SYNONYM_SUGGEST` | 동의어 표준값 제안(info) |
| `L4_RULE_DRAFT_HIT` | draft 규칙에 걸림(info, 판정 영향 없음) |
| `L5_DUP_GROUP_DISAGREE` | 중복 묶음 안에서 분류 축 값이 서로 다름 |

보고는 코드별 건수와 판정(PASS·AUTO_FIX·REVIEW·REJECT) 건수, 리포트와 검토 화면 위치만 짧게 쓴다. 본문과 파일명은 옮기지 않는다. `draft` 규칙에 걸린 건이 있으면 "규칙이 draft라 판정에는 반영되지 않았다"고 한 줄 덧붙인다. 리포트 요약의 "교정 장부" 줄이 있으면(이번 intake 사례·누적 골든·judge 예시 사용·L4 후보 건수) 그대로 한 줄로 전하고, draft 적중 중 `cand-`로 시작하는 규칙은 장부 후보라고 구분한다.

## 이 스킬이 하지 않는 일

- 라벨링 실행: BEOL-labeling
- 사람 검수 반영과 Supabase 적재: BEOL-labeling-feedback
- 저장소 코드와 workflow 검수: labeling-codebot
- 규칙 승인(`draft` → `approved`), taxonomy 수정, labelbot 코드 수정
