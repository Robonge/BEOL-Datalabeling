---
name: beol-labeling-code-engr-bot
description: '저장소 코드와 workflow가 프로젝트 규칙(루트 CLAUDE.md), 기술 stack, 단계 사이 계약을 지키는지 code review 형태로 검수한다. 읽기 전용이며 코드를 고치지 않는다. code_engrbot review를 돌려 review ID·판정·건수를 전하고, review.md의 critical·major 이슈를 path:line, 규칙 ID, 수정 제안으로 요약한다. 이어서 작업 폴더의 최신 실행이 지금 taxonomy.json의 축과 다른지(축 추가·삭제·종류 변경) 점검하고, 걸린 작업 폴더는 묻지 않고 BEOL-labeling-axis-update로 바뀐 축만 자동 재라벨링한다. 같은 방식으로 라벨링 규칙(taxonomy/labeling_rules.json)이 바뀌어 옛 실행과 달라진 작업 폴더도 찾아 BEOL-labeling-rules-update로 바뀐 규칙 범위만 자동 재라벨링한다. 사용자가 "코드 검수", "Code-Engr-bot 돌려줘", "codebot 돌려줘"·"code-bot 돌려줘"(옛 이름), "workflow 검수", "코드 리뷰 봇", "축 점검", "taxonomy 축 바뀐 실행 찾아줘", "새 축으로 재라벨링", "규칙 점검", "규칙 바뀐 실행 찾아줘"라고 하면 이 스킬을 쓴다. 재라벨링 실행은 axis-update·rules-update가 맡는다.'
---

# BEOL-labeling-Code-Engr-bot: 코드 검수

> 이 문서는 `.claude/skills/BEOL-labeling-Code-Engr-bot/SKILL.md`에서 생성됐다. 직접 고치지 말고 원본을 고친 뒤 `python tools/gen_roo_skills.py`를 다시 실행한다.

> 폐쇄망: LLM 호출(M02·M03)·임베딩(M07)·벡터 저장소 적재(M08)·슬라이드 JPG 저장(M10)은 사내 API·벡터 저장소·S3 단계라 게이트 G-API·G-VDB·G-S3 이후 릴리스에서 활성화된다. 그 전에는 이 단계가 설정 누락 사유 코드로 멈추거나 "호출하지 않습니다"로 끝나므로 사유 코드만 보고하고 나머지 단계를 계속한다.

> 그룹: ② 품질 점검 · 재라벨링 · 상위: 없음 · 하위: beol-labeling-rules-update 스킬, beol-labeling-axis-update 스킬 · 전체 지도: README.md "스킬 지도"

> **간소화 지침(2026-10-08~, 루트 `CLAUDE.md`의 "임시 지침: 코드 검수 간소화"가 우선)**: 작업 끝에 한 번, `--paths`로 바뀐 파일만 검수하고, critical만 고치며, 보고는 판정 · 건수 · critical 한 줄씩만 쓴다. 축 · 규칙 점검 자동 호출은 그대로 한다.

저장소 코드와 workflow를 정적 분석으로 검수한다. 소스를 import하거나 실행하지 않고 텍스트와 AST로만 읽는다. 결과는 `code_engrbot/out/<review ID>/`에 쓴다. 라벨 내용의 도메인 판단은 하지 않는다(검수 결과로 엔지니어에게 질문해 도메인 지식을 규칙·taxonomy 제안으로 돌려주는 일은 BEOL-labeling-Domain-Engr-bot).

```
검수 실행(review ID·판정·건수) → 결과 요약(critical·major) → taxonomy 축·라벨링 규칙 점검(걸린 작업 폴더) → 자동 재라벨링·수정 대기(축 불일치는 바로 BEOL-labeling-axis-update, 규칙 불일치는 바로 BEOL-labeling-rules-update, 요청하면 코드 수정·재검수)
```

## 고정 값

- 코드 폴더: 저장소 루트(`git rev-parse --show-toplevel`, 이 SKILL.md 기준 ../../..). 모든 명령은 여기서 `PYTHONIOENCODING=utf-8`을 붙여 실행한다.
- 출력: `code_engrbot/out/<review ID>/findings.jsonl`, `review.md`, `manifest.json`.
- 기본 검사 대상: `labelbot`, `domain_engrbot`, `code_engrbot`, `tests`, `.claude/skills`.

## 규칙 층

| 층 | 보는 것 |
|---|---|
| C1 프로젝트 규칙 | 루트 `CLAUDE.md`의 DRM 규칙과 쓰기 규칙(경로 기반 파서, 표준 라이브러리 밖 import, 금지 확장자 쓰기, ingest 밖의 원본 열기) |
| C2 stack | Python 3.14 문법, 사외 전송 안전장치(transport 모듈 밖 직접 호출), 비밀값 리터럴, `requirements.txt` |
| C3 workflow 계약 | skill·README에 적힌 명령이 CLI에 있는지, domain_engrbot의 labelbot import 경계, 단계 사이 표·열 계약 |
| C4 완료 위생 | 테스트 skip, TODO·FIXME와 빈 함수 |

규칙 ID와 severity 전체는 카탈로그 명령으로 본다. 카탈로그를 `code_engrbot/docs/rules.md`에 다시 쓰고 `rules=<n> out=<경로>`만 출력한다.

```bash
python -m code_engrbot rules
```

## 판정과 종료 코드

| 조건 | 판정 | 종료 코드 |
|---|---|---|
| critical이 1건 이상 | `REQUEST_CHANGES` | 1 |
| major가 1건 이상 | `COMMENT` | 0 |
| 검사 실행 오류가 1건 이상(critical 없음) | `APPROVE`였으면 `COMMENT`로 올림 | 2 |
| 그 밖 | `APPROVE` | 0 |

억제된(`suppressed`) finding은 판정에서 제외하고 리포트에 건수만 낸다. 종료 코드 1은 오류가 아니라 critical이 있다는 신호다. 종료 코드 2는 검사 하나가 예외를 냈다는 뜻이며, 콘솔 줄 끝에 `errors=<n>`이 붙고 `review.md`의 "검사 실행 오류" 절에 검사 이름·경로·예외 종류가 남는다. 나머지 검사 결과는 그대로 유효하다.

## 지켜야 할 것

- 읽기 전용이다. 사용자가 고치라고 하기 전에는 소스를 고치지 않는다.
- 이 봇(`code_engrbot` 코드)은 소스를 import·실행하지 않는다. 그 방식은 바꾸지 않는다. taxonomy 축 점검은 code_engrbot이 아니라 이 skill 절차가 `labelbot taxonomy-diff`를 불러 한다. 점검 결과는 code_engrbot 판정·종료 코드에 넣지 않는다.
- 재라벨링은 자동이다(사용자 결정, 2026-10-06). 3단계에서 재라벨링 대상이 된 작업 폴더는 묻지 않고 `beol-labeling-axis-update` 스킬로 바뀐 축만 다시 라벨링한다. 이전 라벨·검수 결과는 유지되고, 같은 작업 폴더에 `axis-update` 실행이 하나 더 생긴다. 대상이 아닌 폴더는 돌리지 않는다. 전체 재라벨링(`beol-labeling` 스킬)은 부르지 않는다.
- 규칙 재라벨링도 자동이다(사용자 결정, 2026-10-07). 3단계에서 규칙 불일치로 걸린 작업 폴더는 묻지 않고 `beol-labeling-rules-update` 스킬로 바뀐 규칙이 닿는 범위만 다시 라벨링한다. 이 흐름에는 사람 검수가 없고 벡터 저장소 적재까지 이어진다. 같은 폴더에 축 불일치도 있으면 axis-update만 먼저 부른다. 규칙 점검도 `labelbot rules-diff`가 하고, 점검 결과는 code_engrbot 판정·종료 코드에 넣지 않는다.
- 축 점검 보고에는 작업 폴더 이름·실행 ID·축 이름·건수만 쓴다. 축 정의 문장, 값 목록, 본문은 쓰지 않는다. taxonomy.json을 Read 도구로 열거나 직접 파싱하지 않는다(축 비교는 `taxonomy-diff`가 `open(path,"rb")` → `parse_bytes`로 한다).
- 사내 파일을 Read 도구로 열지 않는다(루트 `CLAUDE.md`). 코드 검수에는 필요 없다.
- 오탐은 코드를 억지로 바꾸지 않고 해당 줄에 주석으로 누른다. 사유를 반드시 적는다.
  ```python
  data = open(path, "rb").read()  # code_engrbot: allow C1_OPEN_OUTSIDE_INGEST <사유>
  ```
  저장소 단위 허용은 `code_engrbot/defaults/policy.json`의 `allow`(`rule`, `path`, `reason`)에 둔다. 억제는 사람이 정한다. 사용자 요청 없이 주석을 달지 않는다.
- LLM 코드 리뷰, 실행 흔적 연결(C5, C6)은 아직 없다. 있는 것처럼 쓰지 않는다.

## 진행 현황 표시

BEOL-labeling과 같은 블록 형식으로 보여 준다. 시작할 때(0%)와 milestone이 끝날 때 응답 텍스트로 낸다. 검수 실행은 몇 초면 끝나므로 출력 감시는 쓰지 않는다.

| # | milestone | 끝나는 신호 | 누적 |
|---|---|---|---|
| 1 | 검수 실행 | 콘솔에 `<review ID> <판정> critical=…` 줄 | 30% |
| 2 | 결과 요약 | `review.md` 요약을 씀 | 60% |
| 3 | taxonomy 축·라벨링 규칙 점검 | 작업 폴더별 `taxonomy-diff`·`rules-diff` 결과 표를 씀 | 80% |
| 4 | 자동 재라벨링·수정 대기 | 재라벨링 대상을 `beol-labeling-axis-update` 스킬·`beol-labeling-rules-update` 스킬에 넘김(대상이 없으면 바로) + 안내 출력. 수정을 요청받았으면 재실행에서 해당 finding이 사라짐 | 100% |

블록 형식(제목 줄 + 막대 줄 + 지금 줄 + 세로 목록. 막대는 10칸이며 `🟩` 칸 수 = 누적% ÷ 10을 내림한 값, 나머지는 `⬜`):
```
**진행 현황 · BEOL-labeling-Code-Engr-bot** · review ID: <review ID 또는 ->

🟩🟩🟩⬜⬜⬜⬜⬜⬜⬜ **30%** · 1/4 완료

> ▶️ **지금 2단계 · 결과 요약**

- ✅ 1. 검수 실행 — COMMENT, critical 0·major 1
- ▶️ **2. 결과 요약** — 진행 중
- ⬜ 3. taxonomy 축·라벨링 규칙 점검
- ⬜ 4. 자동 재라벨링·수정 대기
```
- 목록에는 milestone 4개를 번호 순서대로 한 줄에 하나씩 항상 모두 쓴다. 제목 줄·막대 줄·지금 줄·목록 사이는 빈 줄로 띄운다.
- `✅` 완료, `▶️` 진행 중, `⬜` 대기, `❌` 실패. `▶️` 줄은 단계 번호·이름을 굵게 쓰고 `— 진행 중`을 붙인다. 막대 줄의 `N/4 완료`는 `✅` 줄의 수다.
- 지금 줄에는 `▶️` 단계의 번호와 이름을 굵게 쓴다. 멈췄으면 `> ❌ **N단계 · <이름>에서 멈춤** — <사유>`로, 모두 끝났으면 `> ✅ **4단계 모두 완료**`로 쓴다.
- 1단계 줄 끝에는 판정과 critical·major 건수를, 종료 코드 2면 `errors=<n>`을 붙인다. 종료 코드 1·2는 멈춤이 아니다. 콘솔 줄 없이 끝났거나(예외 추적, 인자 오류) `review.md`가 없으면 그 단계를 `❌`로 두고 멈춘다.
- 3단계 줄 끝에는 `점검 <n>개 · 축 불일치 <m>개 · 규칙 불일치 <k>개`를 붙인다. `taxonomy-diff` 또는 `rules-diff` 명령이 아직 없으면 `✅`로 두고 `— 건너뜀(<명령> 없음)`을 붙인다. 이것은 멈춤이 아니다.
- 재라벨링으로 `beol-labeling-axis-update` 스킬이나 `beol-labeling-rules-update` 스킬을 부르면 그 뒤 진행 표시는 그 skill 블록이 맡는다. 이 블록은 4단계 `✅ — 재라벨링 <k>개 폴더 넘김`으로 끝낸다.
- 같은 응답 안에서 여러 milestone이 함께 끝나면 마지막 상태의 블록 한 번만 보여 준다. 같은 블록을 연속으로 반복하지 않는다.

## 절차

milestone이 끝날 때마다 위 "진행 현황 표시"의 블록을 갱신해 보여 준다.

### 1. 검수 실행

```bash
python -m code_engrbot review --root .
```

- 일부만 볼 때: `--paths <경로> [<경로> …]`
- 층을 고를 때: `--layers C1,C2,C3,C4`
- 출력 위치나 정책을 바꿀 때: `--out <폴더>`, `--policy <파일>`

콘솔에 나오는 review ID, 판정, severity별 건수(critical, major, minor, info, suppressed)와 종료 코드를 그대로 전한다.

### 2. 결과 요약

`code_engrbot/out/<review ID>/review.md`를 읽고 critical, major 순으로 요약한다. 항목마다 아래를 적는다.

- `path:line`
- 규칙 ID
- 수정 제안

minor와 info는 건수만 전한다. 억제된 건수는 있으면 한 줄로 전한다. 위반처럼 보이지만 오탐으로 의심되는 항목은 "오탐 의심"이라고 표시하고 사유를 한 줄로 적는다.

검사 실행 오류가 있으면 "검사 실행 오류" 절의 검사 이름과 예외 종류를 한 줄씩 덧붙인다.

### 3. taxonomy 축·라벨링 규칙 점검

taxonomy.json에 축이 더해지거나 빠지거나 종류·값이 바뀌면, 그 전에 라벨링한 실행에는 새 축 값이 없거나 지금 taxonomy에 없는 값이 남는다. Domain-Engr-bot이 라벨링 규칙(`taxonomy/labeling_rules.json`)을 추가·수정·끄기·기각해도, 옛 실행의 라벨은 옛 규칙으로 만든 그대로다. 이 단계는 그런 작업 폴더를 찾고, 4단계가 바뀐 축(축 불일치) 또는 바뀐 규칙 범위(규칙 불일치)만 다시 라벨링한다. 작업 폴더마다 `taxonomy-diff`와 `rules-diff`를 둘 다 돌린다.

1. 명령이 있는지 본다. `python -m labelbot --help` 출력에 `taxonomy-diff`가 없으면 축 점검을, `rules-diff`가 없으면 규칙 점검을 건너뛰고 "<명령>이 아직 없어 <축|규칙> 점검을 건너뜀"을 한 줄로 알린다. 이 skill에서 taxonomy.json이나 meta를 따로 읽어 비교하지 않는다(로직은 `labelbot` 한 곳에 둔다).
2. 대상은 `workspaces/` 아래에서 이름이 `_`로 시작하지 않고 `pipeline.json`이 있는 폴더다. 폴더마다 실행한다.
   ```bash
   python -m labelbot taxonomy-diff --workspace "<WS>"
   ```
   - 첫 줄은 JSON이고 둘째 줄은 사람용 요약이다. JSON에서 `added`·`removed`·`changed`·`values_added`·`values_removed`·`run_id`를 읽는다. `values_removed`는 값이 줄었을 때만 있다. `code`가 `NO_PREVIOUS_RUN`이면 "실행 없음"으로 세고 넘어간다.
   - `partial: true`는 옛 실행이라 축 이름·종류만 비교했다는 뜻이다. 표의 판정 칸에 `(이름·종류만)`을 붙인다.
   - `added`·`removed`·`changed`·`values_removed`·`values_added` 중 하나라도 비어 있지 않으면 **불일치**다(`labelbot.taxdiff.needs_rerun`과 같은 기준, 사용자 결정 2026-10-06). 값이 추가된 축도 새 값이 라벨에 반영되도록 다시 라벨링한다.
   - 명령이 실패하면 그 폴더만 "점검 실패(종료 코드)"로 적고 다음 폴더로 간다.
   - 같은 폴더에서 규칙 점검도 한다.
     ```bash
     python -m labelbot rules-diff --workspace "<WS>"
     ```
     종료 코드는 변경이 있으면 0, 변경이 없거나(`NO_RULE_CHANGE`) 기준을 모르면 3이다(3은 점검 실패가 아니다). 첫 줄은 JSON이다. `added`·`edited`·`disabled`·`removed`(기각 포함) 건수, 사례 변경 건수(`examples_changed`), 단계 전체(축 없는) 규칙 건수(`stage_wide`)를 읽는다. `code`가 `NO_PREVIOUS_RUN`이면 "실행 없음", `NO_RULE_CHANGE`면 일치, `RULES_BASELINE_UNKNOWN`이면 "기준 모름(전체 실행 안내)", `STAGE_WIDE_ONLY`면 "축 없는 규칙만 바뀜(다음 전체 실행 때 반영)"으로 적는다. 이 코드들(`NO_PREVIOUS_RUN`·`NO_RULE_CHANGE`·`RULES_BASELINE_UNKNOWN`·`STAGE_WIDE_ONLY`)은 규칙 불일치가 아니다. 코드 없이 축 규칙·답 규칙 변경이 1건 이상 나오면 **규칙 불일치**다. 사례 변경만 있으면 건수만 보고하고 불일치로 세지 않는다.
3. 결과를 표 하나로 보고한다. 축 이름과 건수만 쓰고, 규칙은 id와 건수만 쓴다(규칙 문장은 쓰지 않는다).

   | 작업 폴더 | 실행 ID | 추가 축 | 삭제 축 | 종류·설정·값 구성 변경 | 값 추가 | 값 삭제 | 규칙 추가/수정/끄기/기각 | 축 없는 규칙 | 사례 변경 | 판정 |
   |---|---|---|---|---|---|---|---|---|---|---|
   | `261004_BEOL_<slug>_<시각>` | `<RUN>` | `축A` (1) | - (0) | `축B`(values) (1) | 3 | 0 | 1/0/1/0 | 0 | 2 | 불일치(축) |

   판정 칸은 `일치`, `불일치(축)`, `불일치(규칙)`, `불일치(축·규칙)`(둘 다) 중 하나다.

4. 불일치 폴더를 입력 폴더로 묶는다(축 불일치와 규칙 불일치 모두 같은 규칙). 입력 폴더는 그 작업 폴더 `pipeline.json`의 `input_root` 문자열이 아니라 풀어 낸 실제 경로 `os.path.normcase(os.path.realpath(Workspace(p, create=False).input_root))`(`from labelbot.workspace import Workspace`, `p` = 작업 폴더)로 묶는다(상대·절대 표기가 섞여도 같은 입력 폴더는 한 묶음이 된다). 같은 입력 폴더의 작업 폴더가 여러 개면 최신 라벨 실행(JSON의 `run_id`) 시각이 가장 늦은 폴더만 남긴다. 그 입력 폴더에 이미 지금 taxonomy와 같은 더 새 작업 폴더가 있으면 재라벨링 대상에서 뺀다. 남은 작업 폴더가 4단계의 재라벨링 대상이다.

### 4. 자동 재라벨링·수정 대기

- **코드 수정**: 폐쇄망에서는 코드를 고치지 않는다. 고칠 항목(review ID·`path:line`·규칙 ID)은 `CLOSED_NETWORK_RUNBOOK.md`의 반출 절차로 로컬에 넘기고 다음 릴리스에서 고친다. 오탐 억제 주석·`policy.json` 수정도 같다.
- **재라벨링(자동)**: 3단계의 재라벨링 대상이 1개 이상이면 묻지 않고 바로 실행한다. 작업 폴더마다 하나만 부른다.
  - 축 불일치만: `BEOL-labeling-axis-update`. 규칙 불일치만: `BEOL-labeling-rules-update`. 둘 다: **axis-update만** 부르고 "축 검수 완료 후 다음 Code-Engr-bot 실행에서 규칙 변경분 처리(REVIEW_IN_PROGRESS로 건너뜀)"를 표에 적는다(축 검수가 끝나기 전에는 rules-update가 건너뛴다).
  - 시작 전에 한 줄로 알린다: `재라벨링 <k>개 작업 폴더 자동 실행: <작업 폴더 이름 목록> (축 불일치는 바뀐 축만 1차 분류 후 바뀐 축만 사람 검수, 규칙 불일치는 바뀐 규칙 범위만 다시 라벨링해 사람 검수 없이 바로 반영·적재)`.
  - 작업 폴더마다 해당 skill의 절차를 따르고 인자로 그 작업 폴더 경로를 넘긴다. 여러 개면 하나씩 차례로 부른다. axis-update 실행은 그 skill 절차대로 사람 검수 대기에서 멈추고, rules-update 실행은 적재까지 끝낸 뒤, 그다음 작업 폴더로 넘어간다.
  - 그 skill이 건너뜀 사유 코드를 내면 표에 `⏭️ <코드>`로 적고 다음 폴더로 간다. 멈추면(selfcheck FAIL 등) `❌ <사유>`로 적는다. rules-update가 적재 보류(`RULES_CHANGE_RATIO_HIGH`)로 끝나면 `✅ 적재 보류`로 적고 현황판에서 확인하라고 안내한다(실패가 아니다).
    - axis-update 코드: `PREV_NOT_REVIEWED`·`REVIEW_IN_PROGRESS`·`PREV_PUSH_PENDING`·`AXIS_UPDATE_LOCKED`·`NO_AXIS_CHANGE`·`NO_PREVIOUS_RUN`.
    - rules-update 코드: 위 코드에 `RULES_BASELINE_UNKNOWN`(기준 규칙을 복원하지 못함 → 전체 `beol-labeling` 스킬 안내만), `NO_RULE_CHANGE`(할 일 없음), `STAGE_WIDE_ONLY`(축 없는 규칙만 바뀜 → 다음 전체 `beol-labeling` 스킬 때 반영), `AXIS_CHANGE_PENDING`(축도 바뀜 → 먼저 axis-update), `NO_RELABEL_TARGET`(대상이 모두 사람 값·확인 chunk라 다시 라벨할 것이 없음. 다음 점검에서도 다시 나올 수 있다)가 더해진다.
    - `PREV_PUSH_PENDING`에서 빠져나오기: 기준 작업 폴더에서 `beol-labeling-feedback` 스킬 6단계(`embed` → `push-vectors`)를 다시 실행한다(`RULES_CHANGE_RATIO_HIGH`로 보류된 실행이면 현황판을 확인한 뒤 `push-vectors --force`). 벡터 저장소를 쓰지 않으면 `pipeline.json`의 `supabase.enabled=false`.
    - `AXIS_UPDATE_LOCKED`에서 빠져나오기: 실행 중인 axis-update·rules-update가 없으면 `logs/axis_update.lock.json`을 지우거나, 오래된 잠금 기준 시간(6시간)이 지나기를 기다린다.
  - 끝나면 작업 폴더별 결과(axis-update 또는 rules-update 실행 ID·대상 축·바뀐 규칙 id, 또는 건너뜀·실패 사유)를 한 표로 보고한다.
  - 입력 폴더에 새 파일이 생겨 전체 재라벨링이 필요해 보이면 `beol-labeling` 스킬(<입력 폴더>)을 안내만 한다.
  - 대상이 없으면 이 줄은 쓰지 않는다.

## 이 스킬이 하지 않는 일

- 도메인 질문(검수 결과 → 엔지니어 답 → 규칙·taxonomy 제안): BEOL-labeling-Domain-Engr-bot
- 라벨링 실행: BEOL-labeling(전체), BEOL-labeling-axis-update(축 변경분), BEOL-labeling-rules-update(규칙 변경분). 이 skill은 3단계에서 걸린 작업 폴더를 자동으로 넘기기만 한다
- taxonomy 축·라벨링 규칙 비교 로직: `labelbot taxonomy-diff`·`labelbot rules-diff`(이 skill은 부르고 결과를 표로 옮긴다)
- 사람 검수 반영과 벡터 저장소 적재: BEOL-labeling-feedback
- LLM 코드 리뷰, 실행 흔적 연결, `eval`

## 관계

- 검수 결과로 엔지니어에게 도메인 질문을 하는 일은 BEOL-labeling-Domain-Engr-bot, 라벨링 실행은 BEOL-labeling, 축 변경분 재라벨링은 BEOL-labeling-axis-update, 규칙 변경분 재라벨링은 BEOL-labeling-rules-update, 사람 검수 반영과 적재는 BEOL-labeling-feedback이 맡는다.

## 마일스톤

이 스킬의 명령은 터미널에 `[Mxx 이름] 시작·완료·실패` 줄을 낸다. 실패하면 아래 ID로 어느 단계인지 보고, `python -m labelbot codes --milestone <Mxx>`로 사유 코드와 조치를 본다.

| 명령 | 마일스톤 |
|---|---|
| `code_engrbot rules` | M20 CODE_REVIEW |
| `labelbot taxonomy-diff` | M23 DIFF_CHECK |
| `labelbot rules-diff` | M23 DIFF_CHECK |
| `code_engrbot review` | M20 CODE_REVIEW |

담당 마일스톤: M20·M23

## 실패하면

터미널의 `[Mxx …] 실패` 블록을 먼저 읽는다 → `python -m labelbot status --workspace <작업 폴더>`(Python 3.14가 없으면 `python3 tools/beol_status.py status --workspace <작업 폴더>`) 출력을 복사해 알려 달라. 환경 문제면 `python3 tools/beol_doctor.py`. `BEOL_TRACE=1`은 Roo 명령으로 실행하지 말고 일반 터미널에서만.
