---
name: BEOL-labeling-rules-update
description: Domain-Engr-bot이 taxonomy/labeling_rules.json의 라벨링 규칙을 추가·수정·끄기·기각해서, 이미 라벨링·검수를 마친 작업 폴더의 옛 라벨이 지금 규칙과 달라졌을 때, 바뀐 규칙이 닿는 범위만 LLM으로 다시 라벨링한다(축 규칙은 그 축 전체 chunk의 1차 분류만, 답 규칙은 그 질문의 O/X만 3차로). 사람이 교정하거나 확인한 값은 건드리지 않는다. 사람 검수 없이 바로 반영하고, 규칙별 카드와 값이 바뀐 슬라이드(이전 → 지금)를 보여 주는 현황판(rules_update.html)을 띄운 뒤 임베딩·Supabase 적재까지 이어 간다. BEOL-labeling-Code-Engr-bot이 규칙 점검에서 걸린 작업 폴더마다 묻지 않고 자동으로 부른다. 사용자가 "규칙 바뀐 것만 다시", "라벨링 규칙 반영", "rules update", "규칙 변경 재라벨링"이라고 하거나 /BEOL-labeling-rules-update를 부르면 이 스킬을 쓴다. 축 변경분은 axis-update, 규칙 확정은 Domain-Engr-bot이 맡는다.
---

# BEOL-labeling-rules-update: 바뀐 규칙이 닿는 범위만 다시 라벨링

> 그룹: ② 품질 점검 · 재라벨링 · 상위: /BEOL-labeling-Code-Engr-bot · 하위: 없음 · 전체 지도: README.md "스킬 지도"

같은 작업 폴더 안에 `rules-update` 실행을 하나 더 만든다. 이전 실행의 chunk·라벨·사람 교정을 이어받고, 바뀐 규칙이 닿는 범위만 LLM으로 다시 라벨링해 **사람 검수 없이 바로 반영**한다(사용자 결정, 2026-10-07. 계획 `.omc/plans/rules-update-plan.md`).

```
대상 확인(dry-run) → 사전 점검 → 바뀐 규칙 범위 재라벨링 → 현황판(rules-board) 띄우기
→ 임베딩 → Supabase 적재 → 현황판 갱신 → 보고
```

검수 대기 단계는 없다.

## 무엇을 다시 하고 무엇을 이어받나

| 구분 | 처리 |
|---|---|
| 변경 종류 | 규칙 추가·문장 수정·끄기·기각(삭제) 네 가지 모두 변경으로 센다. 끄거나 기각한 규칙도 그 규칙으로 만든 라벨을 다시 본다 |
| 축 규칙(1차 분류) | 규칙의 대상 축을 라벨한 chunk **전부**에서 그 축만 1차 분류를 다시 호출한다(값 필터 없음, chunk당 1회). 다른 축 값·chunk_type은 이어받는다. 그 축의 지금 규칙은 바뀐 것만이 아니라 전부 프롬프트에 들어간다 |
| 답 규칙(3차 라벨링) | 바뀐 답 규칙이 가리키는 질문에 답했던 chunk만 골라 **그 질문의 O/X만** 다시 매긴다(chunk당 1회). 축 값과 다른 질문 답은 이어받는다 |
| 축 값이 바뀐 chunk | 옛 값에 묶인 답(적용 대상이 `축=옛 값`인 질문, 그 축의 검증·대조 질문)은 낡았으므로 버린다(`낡은 답 버림`) |
| 사람 값 | 사람이 교정하거나 확인한 chunk의 그 축·답은 건너뛴다. 확인된 chunk는 답 하나만 바뀌어도 확인이 깨지므로 chunk 전체를 뺀다 |
| 단계 전체 규칙 | 대상 축이 없는 규칙(`classify`/`label` 전체)은 재라벨링하지 않고 건수만 보고한다 |
| few-shot 사례 | 사례 변경은 범위를 정할 수 없어 건수만 보고한다 |
| 실행 범위 | 이전 실행에 들어 있던 chunk만. 입력 폴더를 다시 읽지 않는다. 새 파일·바뀐 파일은 `/BEOL-labeling` 전체 실행으로 처리하라고 안내한다 |
| 호출 실패 | 호출이 성공한 (chunk, 축/질문)만 덮어쓴다. 실패하면 이어받은 값이 남고 실패 사유가 기록된다 |

## 고정 값

- 코드 폴더: 저장소 루트(`git rev-parse --show-toplevel`, 이 SKILL.md 기준 ../../..). 모든 명령은 여기서 `PYTHONIOENCODING=utf-8`을 붙여 실행한다.
- 작업 폴더 `<WS>`: 인자로 받는다(BEOL-labeling-Code-Engr-bot이 넘긴다). 없으면 사용자가 말한 입력 폴더의 최신 작업 폴더(최신 라벨 실행 시각 기준)를 쓰고, 어느 폴더인지 보고에 적는다.
- 화면 서버: `.claude/launch.json`에서 `--workspace`가 `<WS>`인 항목(`screens-<slug>`, 그 항목의 `port`).
- 현황판: `<WS>\screens\rules_update.html`. 검수 화면은 만들지 않는다.

## 명령

```bash
python -m labelbot rules-diff --workspace "<WS>"
python -m labelbot rules-update --workspace "<WS>" [--dry-run]
python -m labelbot rules-board --workspace "<WS>" --run <RUN>
python -m labelbot embed --workspace "<WS>" --run <RUN>
python -m labelbot push-vectors --workspace "<WS>" --run <RUN> [--force]
python -m labelbot push-slides --workspace "<WS>" --run <RUN>
```

- `rules-diff`: 기준 실행 대비 변경(추가·수정·끄기·기각 건수, 사례 변경 건수)과 단계별 범위(대상 축, 질문, 단계 전체)를 JSON 한 줄로 낸다. 규칙 id·축 이름·건수만 나온다.
- `rules-update`: 재라벨링, `export`·`report`까지 이 명령 안에서 한다. `--dry-run`은 실행을 만들지 않고 대상만 낸다.
- `push-vectors --force`: 변경 비율 상한으로 막힌 적재를 사용자가 확인한 뒤 보낼 때만 쓴다.

## 지켜야 할 것

- 원본 파일, 작업 폴더 데이터(`*.b64`, inbox JSON, `work.sqlite` 본문), `taxonomy.json`을 Read·`cat`으로 열지 않는다(루트 `CLAUDE.md`). 보고에는 건수·실행 ID·규칙 id·축 이름·사유 코드만 쓴다. 규칙 문장은 보고·로그에 쓰지 않는다.
- `taxonomy/labeling_rules.json`, `taxonomy.json`, `pipeline.json`의 모델·안전 설정을 고치지 않는다. 규칙을 만들거나 확정하는 일은 Domain-Engr-bot이다.
- 현황판 탭을 읽거나 클릭하지 않는다(`get_page_text`·`read_page`·스크린샷 금지). 띄우기만 한다.
- 같은 작업 폴더에서 `/BEOL-labeling`·`/BEOL-labeling-feedback`·`/BEOL-labeling-axis-update`와 동시에 돌리지 않는다.

## 건너뜀 사유 코드

| 코드 | 뜻 | 안내 |
|---|---|---|
| `NO_PREVIOUS_RUN` | 기준이 될 라벨링 실행이 없다 | `/BEOL-labeling`으로 처음부터 |
| `NO_RULE_CHANGE` | 기준 실행 이후 바뀐 규칙이 없다 | 할 일 없음 |
| `STAGE_WIDE_ONLY` | 바뀐 규칙이 모두 대상 축이 없는 단계 전체 규칙이다 | 다음 전체 `/BEOL-labeling` 때 반영한다. 축 없는 규칙은 Domain-Engr-bot이 더 이상 만들지 않으므로 옛 규칙만 해당한다 |
| `RULES_BASELINE_UNKNOWN` | 기준 실행이 쓴 규칙 파일을 복원하지 못했다(규칙 이력·git에 같은 것이 없다) | 전체 `/BEOL-labeling`을 안내한다 |
| `PREV_NOT_REVIEWED` | 기준 실행의 사람 검수가 끝나지 않았다 | 먼저 `/BEOL-labeling-feedback`으로 검수를 마친다 |
| `REVIEW_IN_PROGRESS` | 기준 실행의 검수가 열려 있다(시작 신호만 있고 완료 신호가 없다) | 검수 완료 뒤 다시 |
| `PREV_PUSH_PENDING` | supabase를 쓰는데 기준 실행의 확정 라벨이 아직 다 적재되지 않았다 | 기준 작업 폴더에서 `/BEOL-labeling-feedback` 적재 단계(`embed` → `push-vectors`)를 다시 실행한다. Supabase를 쓰지 않으면 `pipeline.json`의 `supabase.enabled=false`. 그 뒤 다시 |
| `AXIS_UPDATE_LOCKED` | 같은 작업 폴더에서 axis-update 또는 rules-update가 돌고 있다(`logs/axis_update.lock.json`, 6시간 넘은 잠금은 무시) | 그 실행이 끝난 뒤 다시. 실행 중인 것이 없으면 잠금 파일을 지우거나 6시간이 지나기를 기다린다 |
| `AXIS_CHANGE_PENDING` | 기준 실행 대비 활성 taxonomy 축이 바뀌어 있다(비활성 축만의 변경은 막지 않는다) | 먼저 `/BEOL-labeling-axis-update`. 그 검수가 끝난 뒤 다시 |
| `NO_RELABEL_TARGET` | 바뀐 규칙이 닿는 값이 모두 사람이 교정·확인한 값이거나 질문이 없다(건너뜀 줄 뒤에 건수) | 할 일 없음. 기록이 바뀌지 않으므로 다음 점검에서도 같은 사유로 건너뛴다 |
| `AXIS_UPDATE_LOCK_LOST` | 실행 중에 잠금을 잃었다 | 다른 실행이 끝난 뒤 다시(멱등 복사로 덮어쓴다) |

건너뜀은 실패가 아니다. 종료 코드: 0 실행함, 3 건너뜀(위 사유 코드, `--dry-run`에서 사유 코드가 있을 때 포함), 4 `AXIS_UPDATE_LOCK_LOST`.
`rules-diff`는 변경이 있으면(`STAGE_WIDE_ONLY` 포함) 0, 변경이 없거나(`NO_RULE_CHANGE`) 기준을 모르면(`RULES_BASELINE_UNKNOWN`·`NO_PREVIOUS_RUN`) 3이다. `push-vectors`가 변경 비율 상한으로 막히면 3이다.

### 적재 보류: `RULES_CHANGE_RATIO_HIGH` (건너뜀도 실패도 아님)

다시 라벨링한 (chunk, 축/질문) 중 값이 바뀐 비율이 상한(`rules_update.max_change_ratio`, 기본 0.3)을 넘으면 실행은 끝내되 Supabase 적재만 멈춘다. 사람 검수가 없는 흐름이라 규칙 하나가 라벨을 대량으로 뒤집는 사고를 막는 장치다. 호출 성공 수가 `rules_update.min_relabels`(기본 10) 미만이면 이 검사를 하지 않는다.

- 현황판에서 이전 → 지금을 보고 맞으면 `push-vectors --force`로 보낸다(이어서 `push-slides`). 이때 `[push-vectors] FORCED RULES_CHANGE_RATIO_HIGH ratio=… limit=…` 줄이 나오고 실행 기록에 `forced_at`이 남는다.
- 되돌리려면 이 실행의 라벨을 쓰지 않는 전체 `/BEOL-labeling`을 돌린다.
- 보류된 실행은 적재가 끝나지 않았으므로 이후 axis-update·rules-update도 `PREV_PUSH_PENDING`으로 건너뛴다. 위 방법 중 하나로 먼저 정리한다.

## 진행 현황 표시

시작할 때(0%)와 milestone이 끝날 때마다 BEOL-labeling과 같은 블록 형식(제목 줄 + 막대 줄 + 지금 줄 + 세로 목록, 막대 10칸)으로 보여 준다. 제목 줄은 `**진행 현황 · BEOL-labeling-rules-update** · run_id: <RUN 또는 ->`이다.

| # | milestone | 끝나는 신호 | 누적 |
|---|---|---|---|
| 1 | 대상 확인 | `rules-update --dry-run` JSON | 10% |
| 2 | 사전 점검 | `결과: 전 항목 PASS` | 20% |
| 3 | 재라벨링 | `[rules-update] 완료 run_id=…` | 60% |
| 4 | 현황판 띄우기 | 탭 열기 끝(또는 URL 안내) | 70% |
| 5 | 적재 | `[push-vectors] …`·`[push-slides] …`, 또는 적재 보류 | 100% |

- `✅` 완료, `▶️` 진행 중, `⬜` 대기, `❌` 실패, `⏭️` 건너뜀. 1단계에서 건너뜀 사유 코드가 나오면 1단계를 `⏭️ — <코드>`로 두고 나머지는 그대로 둔 채 끝낸다(실패가 아니다).
- 목록에는 milestone 5개를 번호 순서대로 한 줄에 하나씩 항상 모두 쓴다. 제목 줄·막대 줄·지금 줄·목록 사이는 빈 줄로 띄운다. `▶️` 줄은 단계 번호·이름을 굵게 쓰고 `— 진행 중`을 붙인다. 막대 줄의 `N/5 완료`는 `✅` 줄의 수다.
- 3단계 줄 끝에 `규칙 n건 · 축 대상 chunk n · 답 대상 n · LLM n회`, 5단계 줄 끝에 Supabase 전송 행 수 또는 `보류 RULES_CHANGE_RATIO_HIGH`를 붙인다. 적재 보류는 5단계를 `✅ — 보류 RULES_CHANGE_RATIO_HIGH`로 두고 100%로 끝낸다.

## 절차

`<WS>` = 작업 폴더, `<RUN>` = 새 rules-update 실행 ID.

### 1. 대상 확인

```bash
python -m labelbot rules-update --workspace "<WS>" --dry-run
```
출력 JSON의 기준 실행 ID, 바뀐 규칙 id와 종류별 건수, 축 대상(축, chunk 수), 답 대상(질문 수, chunk 수), 사람 값이라 건너뛸 수, 단계 전체 규칙·사례 변경 건수를 한 줄로 전한다. 사유 코드가 나오면 위 표의 안내를 전하고 끝낸다. 필요하면 `rules-diff`로 변경 범위만 따로 볼 수 있다.

### 2. 사전 점검

```bash
python -m labelbot selfcheck --workspace "<WS>" --probe-llm
```
`결과: 전 항목 PASS`가 아니면 FAIL 항목과 사유 코드를 보고하고 멈춘다. `taxonomy_axes` WARN은 축 이름·건수만 보고하고 계속한다.

### 3. 바뀐 규칙 범위 재라벨링

```bash
python -m labelbot rules-update --workspace "<WS>"
```
백그라운드로 돌리고 `Monitor`로 `^\[rules-update\]|^\[오류\]|Traceback` 줄을 본다. `[rules-update] 완료 run_id=...`의 실행 ID를 `<RUN>`으로 쓴다. 종료 코드 3과 `[rules-update] 건너뜀 <코드>`는 1단계와 같은 건너뜀이고, 4는 잠금을 잃은 것(`AXIS_UPDATE_LOCK_LOST`)이다. 0·3·4가 아닌 종료 코드나 `[오류]`는 그 줄을 보고하고 멈춘다.

### 4. 현황판 띄우기 (LLM 호출 0회)

```bash
python -m labelbot slide-images --workspace "<WS>" --run <RUN>
python -m labelbot rules-board --workspace "<WS>" --run <RUN>
```
- `slide-images` 실패는 멈추지 않는다. 사유 코드만 보고한다. 이미지가 없는 슬라이드는 현황판에서 근사 미리보기로 보인다.
- 화면 서버를 띄우고(`preview_start` name=`<launch_name>`) 사용자의 Chrome에서 `http://localhost:<port>/rules_update.html`을 연다. 여는 방법과 탭 재사용 규칙은 BEOL-labeling 6단계와 같다. 열린 탭 내용은 읽지 않는다.
- 현황판에는 규칙별 카드(다시 라벨한 수·값이 바뀐 수·사람 값이라 건너뛴 수)와 값이 바뀐 슬라이드(이전 → 지금), 변경 비율과 적재 상태가 나온다. 검수 시작 버튼은 없다.

### 5. 적재

```bash
python -m labelbot embed --workspace "<WS>" --run <RUN>
python -m labelbot push-vectors --workspace "<WS>" --run <RUN>
python -m labelbot push-slides --workspace "<WS>" --run <RUN>
```
라벨이 바뀐 chunk만 다시 전송된다. `[push-vectors] 차단 RULES_CHANGE_RATIO_HIGH`가 나오면 `push-slides`를 하지 않고 적재 보류로 보고한다(위 "적재 보류"). 끝나면 `rules-board`를 한 번 더 만들어 적재 상태를 채우고 현황판 탭을 새로고침한다.

### 6. 보고

마지막 블록 아래에 짧게 쓴다(6줄 이내).
```
## 규칙 변경 재라벨링 (run_id: <RUN>, 기준 <이전 RUN>)
- 바뀐 규칙 id <목록>(추가 n · 수정 n · 끄기 n · 기각 n)
- 다시 라벨 n · 값 바뀜 n(비율 %) · 사람 값이라 건너뜀 n · 낡은 답 버림 n
- 적재: Supabase n행 · 임베딩 n · 슬라이드 JPG 실패 n (또는 보류 RULES_CHANGE_RATIO_HIGH)
- [현황판](http://localhost:<port>/rules_update.html) · [작업 폴더](<WS 상대>)
```
0건인 항목은 쓰지 않는다. 단계 전체 규칙·사례 변경을 보고만 했으면 건수를 한 줄 덧붙인다. 규칙 문장은 쓰지 않는다.

## 이 스킬이 하지 않는 일

- 사람 검수: 없다(검수 화면·완료 대기를 만들지 않는다). 사람 값은 건너뛰기만 한다
- 축 변경(taxonomy.json 축 추가·삭제·변경): BEOL-labeling-axis-update
- 새 파일·바뀐 파일 처리, 전체 재실행, 단계 전체 규칙 반영: BEOL-labeling
- 규칙 만들기·확정, 규칙 끄기·수정: BEOL-labeling-Domain-Engr-bot
- 규칙 불일치 찾기: BEOL-labeling-Code-Engr-bot(이 스킬을 부른다)
- taxonomy.json 수정: 사람(BEOL-taxonomy-dashboard의 보드, 또는 `taxonomy-editor`)

## 관계

- 축 변경(taxonomy.json)은 BEOL-labeling-axis-update, 전체 재라벨링은 BEOL-labeling, 규칙 만들기·확정은 BEOL-labeling-Domain-Engr-bot이 맡는다.
