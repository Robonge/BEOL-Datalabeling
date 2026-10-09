---
name: BEOL-labeling-axis-update
description: taxonomy.json의 축이 추가·삭제·변경(값 추가·삭제 포함)됐을 때, 이미 라벨링·검수를 마친 작업 폴더에서 이전 라벨은 그대로 두고 바뀐 축만 1차 분류로 다시 라벨링한다. 삭제된 축은 라벨에서 뺀다. 사람 검수는 바뀐 축에 불량이 있는 chunk만 받고, 결과는 축별 카드와 슬라이드별 이미지·새 축 라벨만 보여 주는 현황판(axis_update.html)으로 띄운 뒤 검수 대기에서 멈춘다. 검수 완료 뒤에는 반영·임베딩·Supabase 적재까지 이어 간다. BEOL-labeling-Code-Engr-bot이 축 점검에서 걸린 작업 폴더마다 묻지 않고 자동으로 부른다. 사용자가 "축 변경분만 라벨링", "새 축만 라벨링", "axis update", "축 추가 재라벨링", "taxonomy 바뀐 축만 다시"라고 하거나 /BEOL-labeling-axis-update를 부르면 이 스킬을 쓴다. 전체 재라벨링은 BEOL-labeling, 규칙 변경분은 rules-update가 맡는다.
---

# BEOL-labeling-axis-update: 바뀐 축만 다시 라벨링

> 그룹: ② 품질 점검 · 재라벨링 · 상위: /BEOL-labeling-Code-Engr-bot · 하위: 없음 · 전체 지도: README.md "스킬 지도"

같은 작업 폴더 안에 `axis-update` 실행을 하나 더 만든다. 이전 실행의 chunk·라벨·사람 교정을 이어받고, 바뀐 축만 1차 분류를 다시 돌린다(사용자 결정, 2026-10-06. 계획 `.omc/plans/axis-update-plan.md`).

```
대상 확인(dry-run) → 사전 점검 → 바뀐 축 1차 분류 → 화면(슬라이드 이미지·검수·현황판) → 현황판 띄우기 → 검수 완료 대기
→ [검수 완료] 반영 → Domain-Engr-bot 장부·규칙 후보 → 현황판 갱신 → 임베딩 → Supabase 적재
```

## 무엇을 다시 하고 무엇을 이어받나

| 구분 | 처리 |
|---|---|
| 대상 축 | taxonomy-diff의 추가 축, 변경 축(종류·다중값·계층·값 구성), 값이 삭제된 축, 값이 추가된 축. 사용 여부 N→Y는 추가로 본다 |
| 삭제 축 | LLM 없이 새 실행 라벨에서 뺀다. 사용 여부 Y→N도 같다. Supabase 적재 때 라벨 JSON에서도 빠진다 |
| 1차 분류 | 대상 축만 chunk당 1회 다시 호출한다. 다른 축 값은 참고로만 주고 다시 출력하지 않는다. chunk_type은 이어받는다 |
| 2·3차 질문 | 다시 돌리지 않는다. 대상 축에 걸린 질문(`대상축=값` 적용 대상, 대상 축 검증·대조 질문)의 답은 버리고, 나머지 답(공통 질문 포함)은 이어받는다 |
| 이전 사람 교정 | 삭제 축·변경 축 교정은 새 실행에 적용하지 않는다(기록은 남는다). 값만 추가된 축의 교정은 유지한다 |
| 확인 상태 | 이미 사람 검수를 거쳐 확인된 chunk는 확인 상태를 유지한다 |
| 실행 범위 | 이전 실행에 들어 있던 chunk만. 입력 폴더를 다시 읽지 않는다. 새 파일·바뀐 파일은 `/BEOL-labeling` 전체 실행으로 처리하라고 안내한다 |
| 사람 검수 | 대상 축에 불량(낮은 확신도, unknown 비율, 근거 인용 없음, 분류 실패)이 있는 chunk만. 검수 화면에서는 대상 축만 고칠 수 있다 |

taxonomy-diff는 축 정의 문장(H열) 변경을 감지하지 않는다. 정의만 바꿨다면 이 스킬은 `NO_AXIS_CHANGE`로 끝난다.

## 고정 값

- 코드 폴더: 저장소 루트(`git rev-parse --show-toplevel`, 이 SKILL.md 기준 ../../..). 모든 명령은 여기서 `PYTHONIOENCODING=utf-8`을 붙여 실행한다.
- 작업 폴더 `<WS>`: 인자로 받는다(BEOL-labeling-Code-Engr-bot이 넘긴다). 없으면 사용자가 말한 입력 폴더의 최신 작업 폴더(최신 라벨 실행 시각 기준)를 쓰고, 어느 폴더인지 보고에 적는다.
- 화면 서버: `.claude/launch.json`에서 `--workspace`가 `<WS>`인 항목(`screens-<slug>`, 그 항목의 `port`).
- 현황판: `<WS>\screens\axis_update.html`. 검수 화면은 `review.html`(대상 축만 편집).

## 지켜야 할 것

- 원본 파일, 작업 폴더 데이터(`*.b64`, inbox JSON, `work.sqlite` 본문), `taxonomy.json`을 Read·`cat`으로 열지 않는다(루트 `CLAUDE.md`). 보고에는 건수·실행 ID·축 이름·사유 코드만 쓴다.
- `taxonomy.json`과 `pipeline.json`의 모델·안전 설정을 고치지 않는다.
- 검수하는 동안 검수·현황판 탭을 읽거나 클릭하지 않는다(`get_page_text`·`read_page`·스크린샷 금지). 완료 신호만 기다린다.
- 같은 작업 폴더에서 `/BEOL-labeling`·`/BEOL-labeling-feedback`과 동시에 돌리지 않는다. 열린 검수가 있으면 `REVIEW_IN_PROGRESS`로 건너뛴다.

## 건너뜀 사유 코드

| 코드 | 뜻 | 안내 |
|---|---|---|
| `NO_PREVIOUS_RUN` | 기준이 될 라벨링 실행이 없다 | `/BEOL-labeling`으로 처음부터 |
| `NO_AXIS_CHANGE` | 지금 taxonomy와 축이 같다 | 할 일 없음 |
| `PREV_NOT_REVIEWED` | 기준 실행의 사람 검수가 끝나지 않았다 | 먼저 `/BEOL-labeling-feedback`으로 검수를 마친다 |
| `REVIEW_IN_PROGRESS` | 기준 실행의 검수가 열려 있다(시작 신호만 있고 완료 신호가 없다) | 검수 완료 뒤 다시 |
| `PREV_PUSH_PENDING` | supabase를 쓰는데 기준 실행의 확정 라벨이 아직 다 적재되지 않았다(axis-update 뒤에는 기준 실행을 적재할 수 없다) | 기준 작업 폴더에서 `/BEOL-labeling-feedback` 4단계(`embed` → `push-vectors`)를 다시 실행한다. Supabase를 쓰지 않으면 `pipeline.json`의 `supabase.enabled=false`. 그 뒤 다시 |
| `AXIS_UPDATE_LOCKED` | 같은 작업 폴더에서 다른 axis-update가 돌고 있다(`logs/axis_update.lock.json`, 6시간 넘은 잠금은 무시) | 그 실행이 끝난 뒤 다시. 실행 중인 axis-update가 없으면 `logs/axis_update.lock.json`을 지우거나, 오래된 잠금 기준 시간(6시간)이 지나기를 기다린다 |
| `AXIS_UPDATE_LOCK_LOST` | 실행 중에 잠금을 잃었다(다른 실행이 남은 잠금으로 보고 넘겨받음). 이번 실행은 끝나지 않은 채 멈춘다 | 다른 axis-update가 끝난 뒤 다시. 다시 돌리면 같은 기준에서 멱등 복사로 덮어쓴다 |

## 진행 현황 표시

시작할 때(0%)와 milestone이 끝날 때마다 BEOL-labeling과 같은 블록 형식(제목 줄 + 막대 줄 + 지금 줄 + 세로 목록, 막대 10칸)으로 보여 준다. 제목 줄은 `**진행 현황 · BEOL-labeling-axis-update** · run_id: <RUN 또는 ->`이다.

| # | milestone | 끝나는 신호 | 누적 |
|---|---|---|---|
| 1 | 대상 확인 | `axis-update --dry-run` JSON | 10% |
| 2 | 사전 점검 | `결과: 전 항목 PASS` | 20% |
| 3 | 바뀐 축 라벨링 | `[axis-update] 완료 run_id=…` | 60% |
| 4 | 현황판 띄우기 | 탭 열기 끝(또는 URL 안내) | 70% |
| 5 | 검수 완료 대기 | 완료 신호 `done: true` | 80% |
| 6 | 반영·현황판 갱신 | `[apply] …`와 `axis-board` 끝 | 90% |
| 7 | 임베딩·적재 | `[push-vectors] …`·`[push-slides] …` | 100% |

- `✅` 완료, `▶️` 진행 중, `⬜` 대기, `❌` 실패, `⏭️` 건너뜀. 1단계에서 건너뜀 사유 코드가 나오면 1단계를 `⏭️ — <코드>`로 두고 나머지는 그대로 둔 채 끝낸다(실패가 아니다).
- 3단계 줄 끝에 `대상 축 n · 삭제 축 n · chunk n · LLM n회`, 7단계 줄 끝에 Supabase 전송 행 수를 붙인다.
- 검수 완료 대기 중에는 5번을 `▶️ … — 검수 완료 버튼 대기`로 둔다.

## 절차

`<WS>` = 작업 폴더, `<RUN>` = 새 axis-update 실행 ID.

### 1. 대상 확인

```bash
python -m labelbot axis-update --workspace "<WS>" --dry-run
```
출력 JSON의 기준 실행 ID, 대상 축·삭제 축 이름과 건수, 버릴 답·교정 건수를 한 줄로 전한다. 사유 코드(`NO_PREVIOUS_RUN`·`NO_AXIS_CHANGE`·`PREV_NOT_REVIEWED`·`REVIEW_IN_PROGRESS`·`PREV_PUSH_PENDING`·`AXIS_UPDATE_LOCKED`·`AXIS_UPDATE_LOCK_LOST`)가 나오면 위 표의 안내를 전하고 끝낸다.

### 2. 사전 점검

```bash
python -m labelbot selfcheck --workspace "<WS>" --probe-llm
```
`결과: 전 항목 PASS`가 아니면 FAIL 항목과 사유 코드를 보고하고 멈춘다. `taxonomy_axes` WARN은 축 이름·건수만 보고하고 계속한다.

### 3. 바뀐 축 라벨링

```bash
python -m labelbot axis-update --workspace "<WS>"
```
백그라운드로 돌리고 `Monitor`로 `^\[axis-update\]|^\[오류\]|Traceback` 줄을 본다. `[axis-update] 완료 run_id=...`의 실행 ID를 `<RUN>`으로 쓴다. 종료 코드 3과 `[axis-update] 건너뜀 <코드>`는 1단계와 같은 건너뜀이고, 4는 잠금을 잃은 것(`AXIS_UPDATE_LOCK_LOST`)이다. `--dry-run`도 사유 코드가 있으면 3이다. 0·3·4가 아닌 종료 코드나 `[오류]`는 그 줄을 보고하고 멈춘다.

### 4. 화면 만들고 현황판 띄우기 (LLM 호출 0회)

```bash
python -m labelbot slide-images --workspace "<WS>" --run <RUN>
python -m labelbot review --workspace "<WS>" --run <RUN>
python -m labelbot axis-board --workspace "<WS>" --run <RUN>
```
- `slide-images` 실패는 멈추지 않는다. 사유 코드만 보고한다. 이미지가 없는 슬라이드는 현황판에서 근사 미리보기로 보인다.
- 화면 서버를 띄우고(`preview_start` name=`<launch_name>`) 사용자의 Chrome에서 `http://localhost:<port>/axis_update.html`을 연다. 여는 방법과 탭 재사용 규칙은 BEOL-labeling 6단계와 같다. 열린 탭 내용은 읽지 않는다.

### 5. 검수 완료 대기

현황판의 **검수 시작** 버튼은 검수 화면만 연다(화면 서버는 시작 신호도 쓰지만 이 스킬은 기다리지 않는다). 안내하기 전에 완료 대기를 백그라운드로 건다.
```bash
python ".claude/skills/BEOL-labeling-feedback/scripts/wait_review_done.py" --workspace "<WS>" --run <RUN>
```
Bash `run_in_background: true`, `timeout: 7200000`. 그다음 아래를 안내하고 턴을 끝낸다.
1. 현황판에서 축별 불량·슬라이드별 새 라벨을 훑어본다. 이미지를 누르면 크게 보인다.
2. **검수 시작**을 누르고, 검수 화면에서 불량 chunk n개의 대상 축만 확인·교정한다. 강조된 라벨부터 확인하고, 확신도 높은 라벨은 접혀 있다. 다른 축은 잠겨 있다.
3. 다 끝나면 검수 화면 상단의 **검수 완료**를 누른다. 교정할 것이 없어도 누른다. 누르면 화면이 잠기고 반영·적재가 이어진다.
4. 검수가 끝나기 전에는 Supabase에 올리지 않는다.

`code: WAIT_TIMEOUT`이면 같은 대기를 다시 건다.

### 6. 반영과 현황판 갱신

완료 신호(`done: true`)가 오면 `counts` 건수만 한 줄로 알리고, BEOL-labeling-feedback의 1·2·2-1·2-2단계를 그대로 한다(`collect_inbox.py` → `labelbot apply --kind review` → `domain_engrbot intake` → `domain_engrbot labeling-rules candidates`). `apply` 출력의 `AXIS_NOT_TARGET`(대상이 아닌 축·질문 교정이라 건너뜀) 건수를 보고에 적는다.

```bash
python -m labelbot review --workspace "<WS>" --run <RUN>
python -m labelbot axis-board --workspace "<WS>" --run <RUN>
python -m labelbot report --workspace "<WS>" --run <RUN>
```
`results.html`(dashboard)은 이 실행에서 만들지 않는다. 결과 화면은 현황판이다.

### 7. 임베딩과 적재

BEOL-labeling-feedback 4단계와 같다(`embed` → `slide-images` → `push-vectors` → `push-slides`, 모두 `--run <RUN>`). 라벨 JSON이 바뀐 chunk(새 축 추가, 삭제 축 제거)만 다시 전송된다. 끝나면 `axis-board`를 한 번 더 만들어 적재 건수를 채우고, 현황판 탭을 새로고침한다.

### 8. 보고

마지막 블록 아래에 짧게 쓴다(6줄 이내).
```
## 축 변경 재라벨링 (run_id: <RUN>, 기준 <이전 RUN>)
- 대상 축 <이름 목록>(n) · 삭제 축 <이름 목록>(n) · 버린 답 n · 적용 안 한 이전 교정 n
- 불량 n(사유별) → 교정 n · 확인 n · 남은 불량 n
- 적재: Supabase n행 · 임베딩 n · 슬라이드 JPG 실패 n
- [현황판](http://localhost:<port>/axis_update.html) · [작업 폴더](<WS 상대>)
```
0건인 항목은 쓰지 않는다. 라벨링 규칙 후보가 나왔으면 BEOL-labeling-feedback 보고 형식의 피드백 줄을 한 줄 붙인다.

## 이 스킬이 하지 않는 일

- 새 파일·바뀐 파일 처리, 2·3차 질문 재실행: BEOL-labeling(전체 실행)
- 축 불일치 찾기: BEOL-labeling-Code-Engr-bot(이 스킬을 부른다)
- 도메인 질문과 규칙 확정: BEOL-labeling-Domain-Engr-bot
- taxonomy.json 수정: 사람(BEOL-taxonomy-dashboard의 보드, 또는 `taxonomy-editor`)

## 관계

- 전체 재라벨링(새 파일, 2·3차 질문까지)은 BEOL-labeling, 일반 검수 반영은 BEOL-labeling-feedback이 맡는다.
