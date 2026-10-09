---
name: BEOL-labeling-Domain-Engr-bot
description: 사람 검수 결과(BEOL-labeling-feedback이 반영한 교정·재검토 요청·검수 등록 동의어)와 누적 교정 장부를 읽고, LLM으로 엔지니어에게 물을 도메인 질문 10개 안팎을 만들어 질문 화면(서버)에 띄운다. 사람이 답하고 초안(규칙 문장·taxonomy 행)을 고쳐 확정한 것만 taxonomy/labeling_rules.json(다음 /BEOL-labeling 프롬프트)과 taxonomy 수정 보드(출처 S7 "엔지니어 답변")로 보낸다. 승인된 규칙·사례 관리(끄기·켜기·문장 수정·승인 취소, 갱신 대기 사례 승인)와 taxonomy 수정 보드(흩어진 taxonomy 수정 제안을 한 화면에 모으고, 사람이 고쳐 "최종 완료"하면 봇이 taxonomy.json에 쓴다)도 맡는다. 봇은 결정을 만들지 않고, taxonomy.json은 사람이 보드에서 확정한 것만 쓴다. 사용자가 "Domain-Engr-bot 돌려줘", "Engr-bot 돌려줘"(옛 이름), "도메인 질문", "엔지니어 질문", "질문 답변", "질문 답변 끝났어", "도메인 지식 반영", "승인 규칙 관리", "규칙 끄기", "taxonomy 수정", "taxonomy 보드", "taxonomy 반영 화면"이라고 하거나 /BEOL-labeling-Domain-Engr-bot을 부르면 이 스킬을 쓴다. 예전 표현("도메인 검수", "QA 검수 끝났어", "라벨링 규칙 검수", "교정 규칙 승인")으로 불러도 이 스킬이 맡되 새 절차(도메인 질문 또는 승인 규칙 관리)로 안내한다. 보드 화면만 띄울 때는 BEOL-taxonomy-dashboard를 쓴다.
---

# BEOL-labeling-Domain-Engr-bot: 도메인 질문

> 그룹: ② 품질 점검 · 재라벨링 · 상위: 없음 · 하위: /BEOL-taxonomy-dashboard · 전체 지도: README.md "스킬 지도"

사람이 이미 검수한 chunk를 Domain-Engr-bot이 다시 도메인 검수하지 않는다(사용자 결정, 2026-10-06). Domain-Engr-bot은 **검수 결과를 읽고 엔지니어에게 질문해 도메인 지식을 얻는 봇**이다. 사람이 질문 화면에서 답하고 초안을 고쳐 확정한 것만 다음 라벨링 프롬프트와 taxonomy 수정 보드로 간다. 설계는 `domain_engrbot/docs/plan-question-loop.md`다.

이 스킬은 세 가지 일을 한다. 사용자가 무엇을 원하는지 보고 하나를 고른다.

- **① 도메인 질문**(기본. "Domain-Engr-bot 돌려줘", "도메인 질문", "엔지니어 질문", "질문 답변", "도메인 지식 반영"): 아래 "도메인 질문 절차"를 따른다. 질문 화면 서버가 반영을 마치고 끝나거나 사용자가 "질문 답변 끝났어"라고 하면 그 절차 5부터 한다.
- **② 승인된 규칙 관리**("승인 규칙 관리", "규칙 끄기", "규칙 문장 수정"): 아래 "승인된 규칙 관리"를 따른다.
- **③ taxonomy 수정 보드**("taxonomy 수정", "taxonomy 보드", "taxonomy 반영 화면", "taxonomy 피드백"): 아래 "taxonomy 수정 보드"를 따른다.

**품질 점검 · 재라벨링 루프에서의 자리**(사용자 결정, 2026-10-07): 이 스킬은 라벨링 파이프라인(`/BEOL-labeling-run-labeling` → BEOL-labeling → feedback)이 자동으로 부르지 않는다. 적재가 끝난 뒤 사람이 따로 시작하는 품질 루프의 앞쪽이다. 하위 스킬은 `/BEOL-taxonomy-dashboard`(③과 같은 보드)다. ①에서 규칙이 확정되면 마무리 보고 끝에 "규칙이 바뀌었으니 `/BEOL-labeling-Code-Engr-bot` 규칙 점검으로 옛 실행을 다시 라벨링할 수 있다"를, 사람이 taxonomy를 저장했다고 하면 "축 점검으로 바뀐 축만 다시 라벨링할 수 있다"를 한 줄 안내한다. Code-Engr-bot을 직접 부르지는 않는다.

```
[품질 점검 · 재라벨링]
Domain-Engr-bot ─ 질문 → 답 확정 → labeling_rules.json ─┐
  └ taxonomy-dashboard ─ 보드 확정 → taxonomy.json ───────┤
Code-Engr-bot ← 규칙 · 축 변경 감지 ─────────────────────┘
  ├ rules-update(규칙 범위만)   └ axis-update(바뀐 축만)
```

예전 표현으로 부르면 이렇게 안내한다. "도메인 검수"는 ①로 진행하며 "도메인 검수는 이제 질문으로 바뀌었다"를 한 줄 알린다. "라벨링 규칙 검수"·"교정 규칙 승인"·"규칙 후보 검수"는 새 후보 승인이 질문 화면으로 합쳐졌으므로 ①로 진행하고, 이미 승인한 규칙을 고치려는 뜻이면 ②로 간다. "QA 검수 끝났어"·"검토 화면 검수 끝났어"·"qa_decisions 반영"은 예전 QA 검토 화면의 반영인데 이 스킬은 그 절차를 더 하지 않는다. 그 사실을 알리고, 질문 화면에서 답을 마친 것이면 ①의 절차 5로 간다.

```
/BEOL-labeling-feedback(검수 반영) → domain_engrbot intake → 교정 장부
  → [이 스킬] 작업 폴더 고르기 → questions generate: 검수 결과 + 누적 장부 → LLM → 질문 10개 안팎
  → questions serve: 질문 화면(근거·선택지·자유 답·초안) → [사람: 답하고 초안을 고쳐 확정 → 답변 완료 · 저장]
  → 서버가 qa/inbox에 저장하고 바로 반영(확정분만)한 뒤 닫힌다 → Claude 마무리 보고
       (서버 없이 저장했으면 "질문 답변 끝났어" → 답 파일 확인 → questions apply)
       (a) taxonomy/labeling_rules.json → 다음 /BEOL-labeling 1차 분류·3차 라벨링 프롬프트
       (b) taxonomy_proposals.jsonl → taxonomy 수정 보드 출처 S7 → 사람이 보드에서 확정해 taxonomy.json에 저장
```

## 고정 값

- 코드 폴더: 저장소 루트(`git rev-parse --show-toplevel`, 이 SKILL.md 기준 ../../..). 모든 명령은 여기서 `PYTHONIOENCODING=utf-8`을 붙여 실행한다.
- 작업 폴더 `<WS>`: 사람이 고른다(절차 1). 인자로 받았으면 그 폴더를 고른 것으로 본다. 후보는 `python -m domain_engrbot workspaces`가 내는 코드 폴더 `workspaces\` 아래 `work.sqlite`가 있는 폴더다(`_`·`.`으로 시작하는 `_domain_engrbot`·`_feedback`·`.omc`는 작업 폴더가 아니다). 임의로 고르지 않는다.
- 질문 폴더: `workspaces\_domain_engrbot\questions\`(장부처럼 작업 폴더 공용, 커밋 제외). 질문 묶음·질문 화면·답 이력·taxonomy 제안이 여기에 있다.
- 교정 장부: `workspaces\_domain_engrbot\ledger\`(커밋 제외). 사람 검수 교정이 Domain-Engr-bot 입력으로 들어오는 곳이다. 설계는 `domain_engrbot/docs/plan-ledger.md`.
- 답 파일: 질문 화면이 `<WS>\qa\inbox\engr_answers_<set_id>.json`으로 저장한다.
- 승인 파일: `taxonomy/labeling_rules.json`. labelbot이 읽는 유일한 계약 파일이다. 다음 `/BEOL-labeling`이 켜진 규칙·사례를 프롬프트에 넣는다.

## 진행 현황 표시

`/BEOL-labeling`과 같은 블록 형식으로 보여 준다. 단계는 작업마다 3개로 압축한다. 시작할 때(0%)와 milestone이 끝날 때마다 블록을 갱신한다.

| 작업 | # | milestone | 포함하는 절차 | 끝나는 신호 | 누적 |
|---|---|---|---|---|---|
| 도메인 질문 | 1 | 질문 생성 | 절차 1~3(폴더 고르기·`questions generate`·질문 화면 서버) | `[questions] set_id=…`(또는 `[questions] 재사용: …`) 줄과 서버 주소 | 40% |
| | 2 | 사람 답변 | 절차 4(질문 화면에서 답하기) | 질문 화면 서버의 `[serve] 답 저장: …` 줄(또는 사용자의 "질문 답변 끝났어") | 70% |
| | 3 | 답 반영 | 절차 5(서버 출력 확인 또는 답 파일 확인·`questions apply`, 보드 안내) | `[questions] 반영: …` 줄 | 100% |
| 승인 규칙 관리 | 1 | 화면 | 절차 1~2(`status`·`review`) | `[labeling-rules] …` 화면 줄 | 30% |
| | 2 | 사람 결정 | 화면에서 끄기·켜기·문장 수정·승인 취소 | 사용자의 "규칙 관리 끝났어" | 60% |
| | 3 | 반영 | 절차 3~5(결정 파일 확인·`apply`) | `[labeling-rules] 반영: …` 줄 | 100% |

블록 형식(제목 줄 + 막대 줄 + 지금 줄 + 세로 목록. 막대는 10칸이며 `🟩` 칸 수 = 누적% ÷ 10을 내림한 값, 나머지는 `⬜`):
```
**진행 현황 · BEOL-labeling-Domain-Engr-bot (도메인 질문)** · set_id: <QS 또는 ->

🟩🟩🟩🟩⬜⬜⬜⬜⬜⬜ **40%** · 1/3 완료

> ▶️ **지금 2단계 · 사람 답변** — 질문 화면 답변 완료 · 저장 대기

- ✅ 1. 질문 생성 — 질문 10(라벨링 6 · taxonomy 4, 이월 2)
- ▶️ **2. 사람 답변** — 질문 화면 답변 완료 · 저장 대기
- ⬜ 3. 답 반영
```
- 제목의 괄호는 `(도메인 질문)` 또는 `(승인 규칙 관리)`다. 승인 규칙 관리에는 묶음 ID가 없으므로 `· set_id:` 부분을 뺀다.
- 목록에는 milestone 3개를 번호 순서대로 한 줄에 하나씩 항상 모두 쓴다. 제목 줄·막대 줄·지금 줄·목록 사이는 빈 줄로 띄운다.
- `✅` 완료, `▶️` 진행 중, `⬜` 대기, `❌` 실패, `⏭️` 건너뜀. `▶️` 줄은 단계 번호·이름을 굵게 쓰고 `— 진행 중`을 붙인다(사람 단계는 `— 질문 화면 답변 완료 · 저장 대기`·`— 결정 JSON 저장 대기`). 막대 줄의 `N/3 완료`는 `✅`와 `⏭️` 줄을 합한 수다. 건너뛴 단계도 누적%에 넣는다.
- 지금 줄에는 `▶️` 단계의 번호와 이름을 굵게 쓴다. 멈췄으면 `> ❌ **N단계 · <이름>에서 멈춤** — <사유 코드>`, 다 끝났으면 `> ✅ **3단계 모두 완료**`로 쓴다.
- 사람 단계에서 턴을 끝낼 때는 그 단계를 `▶️`로 둔 블록을 보여 주고 끝낸다. 사용자가 다음 턴에 "끝났어"라고 하면 그 단계를 `✅`로 바꿔 이어 간다. 사용자가 처음부터 "질문 답변 끝났어"처럼 반영만 부르면 앞 단계는 `⏭️`로 둔다.
- 도메인 질문에서 질문 재료가 없거나(`NO_REVIEW_INPUT`) 질문이 0건이면 1을 `✅`, 2·3을 `⏭️`로 둔 블록 한 번으로 끝낸다. 승인 규칙 관리에서 승인분·갱신 대기가 모두 0이면 같은 방식으로 끝낸다. 명령이 `[오류]`를 내면 그 단계를 `❌`로 두고 도달한 %를 그대로 둔다.
- 단계 줄 끝에는 `—` 뒤에 건수나 사유 코드만 붙인다. 파일명·본문·근거 인용·질문 문장은 넣지 않는다. 상태가 바뀔 때만 다시 보여 준다.

## 본문이 있는 파일

| 파일 | 내용 | 본문 |
|---|---|---|
| `workspaces/_domain_engrbot/questions/questions.json` | 지금 열려 있는 질문 묶음 | **있음**(질문 문장·용어) |
| `workspaces/_domain_engrbot/questions/engr_questions.html` | 질문 화면 | **있음**(근거 인용·슬라이드 미리보기) |
| `workspaces/_domain_engrbot/questions/answers.jsonl` | 답 이력(질문 문장·고른 답·확정 초안) | **있음** |
| `workspaces/_domain_engrbot/questions/taxonomy_proposals.jsonl` | 보드 출처 S7 입력(확정한 taxonomy 제안) | **있음**(용어·정의 문장) |
| `workspaces/_domain_engrbot/questions/asked.json` | 답함·묻지 않음 지문 | 없음 |
| `workspaces/_domain_engrbot/questions/generate_log.jsonl` | 생성 이력(set_id·건수·코드·LLM 호출 수) | 없음 |
| `workspaces/_domain_engrbot/questions/rules_history.jsonl` | 승인 파일을 바꾸기 전 이전 본 | 없음(승인 파일과 같은 부류) |
| `<WS>/qa/inbox/engr_answers_<set_id>.json` | 질문 화면이 저장한 답(사람 입력) | **있음** |
| `<WS>/inputs/` | `questions apply`가 읽은 답 파일의 사본(사람 입력 보관) | **있음** |
| `workspaces/_domain_engrbot/ledger/golden.jsonl`·`judge_examples.jsonl`·`evidence.jsonl` | 장부의 사례·근거 | **있음** |
| `workspaces/_domain_engrbot/ledger/labeling_review.html` | 승인 규칙 관리 화면 | **있음**(근거 인용) |
| `workspaces/_domain_engrbot/ledger/labeling_candidates.md` | 장부의 규칙·사례 후보 건수 | 없음 |
| `taxonomy/labeling_rules.json` | 승인 파일 | 없음 |

본문이 "있음"인 파일은 위치만 알리고, Read·Grep·`cat`·`get_page_text`·`read_page`·스크린샷으로 내용을 읽어 보고하지 않는다(사람만 본다). 보고에는 명령 출력의 건수·ID·사유 코드만 쓴다. 본문이 "없음"인 파일은 위치를 링크해도 된다.

## 지켜야 할 것

- 봇은 결정을 만들지 않는다. 규칙·taxonomy 제안·사례는 사람이 질문 화면에서 확정한 초안만 반영한다. 질문 화면의 버튼(답 확정·묻지 않기·답변 완료 · 저장)을 Claude가 대신 누르지 않는다.
- `questions generate`와 질문 화면의 **초안 만들기**는 LLM을 부른다. `<WS>`의 `pipeline.json` `llm` 주소로 가는 것은 다음과 같다. 초안 만들기를 끄려면 `questions serve`에 `--no-draft`를 붙인다.
  - 누적 장부의 교정·확인 사례(봇 값·사람 값), 검수자가 남긴 근거 인용(본문·문서 제목·파일명에서 드래그한 부분)과 이유, 재검토 요청의 메모
  - 교정이 있는 chunk의 제목과 본문 앞부분(기본 600자, 최대 40건). 다른 작업 폴더의 chunk도 표본에 들어가는데, 그 작업 폴더의 `llm` 주소가 `<WS>`와 같을 때만 본문·근거 인용·이유·재검토 메모를 보낸다(다르거나 그 폴더가 없으면 교정 값만)
  - taxonomy의 축·값 정의와 동의어, 승인 질문 문장, 이미 승인된 규칙 문장, 이전에 답한 질문과 답
  - 초안 만들기는 그 질문 문장과 사람이 쓴 자유 답만 보낸다
- 콘솔과 대화에 본문·파일명·질문 문장·답 내용을 옮기지 않는다. 보고에는 건수, set_id, 사유 코드만 쓴다.
- 사내 파일을 Read 도구로 열지 않는다. 사내 파일은 DRM이 걸려 있고, 열기는 labelbot의 ingest 한 곳뿐이다(루트 `CLAUDE.md`).
- 이 봇은 labelbot의 산출, 라벨, 프롬프트 파일을 고치지 않는다. taxonomy.json은 사람이 보드에서 "최종 완료"한 것만 쓴다. 승인 파일은 `questions apply`·`labeling-rules apply`로만 바뀐다.
- 답 파일·결정 파일은 사람이 고른 것만 반영한다. 질문 화면 서버의 **답변 완료 · 저장**은 사람이 화면의 확인 창("저장하고 바로 반영합니다")을 거쳐 누르는 것이므로 그 자체가 반영 승인이다(사용자 결정, 2026-10-06). 그 밖의 경로(내려받기·텍스트 붙여넣기·`--no-apply`로 띄운 서버)로 온 답 파일과 결정 파일은 반영하기 전에 항상 `AskUserQuestion`으로 확인받는다.

## 사람 검수 결과를 입력으로 받는다

`/BEOL-labeling-feedback`이 검수 교정을 반영하면(`labelbot apply`) 바로 `python -m domain_engrbot intake --workspace "<WS>"`를 불러 그 작업 폴더의 교정을 교정 장부에 넣는다. `questions generate`도 시작할 때 그 작업 폴더를 다시 intake한다(멱등, LLM 0회). 장부는 질문 재료(교정·확인 사례, 재검토 요청, 검수 등록 동의어, 규칙 후보), few-shot 사례 후보, 규칙 후보(FR-)에 쓰인다. 장부 상태가 필요하면 `python -m domain_engrbot ledger --workspace "<WS>" status` 출력의 건수 줄만 전한다.

## 도메인 질문 절차

milestone 1 "질문 생성"은 절차 1~3, milestone 2 "사람 답변"은 절차 4, milestone 3 "답 반영"은 절차 5다. milestone 1은 절차 3(서버 주소 안내)까지 마친 뒤 `✅`로 바꾼다.

### 1. 작업 폴더 고르기 (LLM 0회)

```bash
python -m domain_engrbot workspaces
```

출력은 `{"workspaces": [...], "questions": {"set_id", "open", "answered_total"}}`다. `workspaces[]`는 `work.sqlite`가 최근에 바뀐 순이다. 폴더마다 기존 `state`와 함께 `question_state`·`review_runs`(교정이 있는 라벨러 실행 수)가 있다. 선택지 설명은 `question_state`를 쓴다.

| question_state | 뜻 | 선택지 설명에 쓸 말 |
|---|---|---|
| `no_review` | 검수 교정이 없다 | 검수 결과 없음(질문 재료 없음) |
| `new` | 검수 결과가 아직 질문에 쓰이지 않았다 | 새 검수 결과 |
| `asked` | 검수 결과가 이미 질문에 반영됐다 | 이미 질문에 반영됨 |

1. **어느 작업 폴더를 할지 고른다.** 인자로 받지 않았으면 폴더가 하나뿐이어도 `AskUserQuestion`(`multiSelect: true`)으로 묻는다. 선택지는 폴더 이름이고, 설명에 위 말과 `review_runs`를 쓴다. `new`가 있으면 가장 최근 `new` 폴더를 첫 선택지로 두고 "(Recommended)"를 붙인다. 폴더가 4개보다 많으면 최근 4개를 선택지로 두고 나머지 이름은 질문 문장에 적는다(사용자는 "Other"로 고른다). `reason`이 있는 폴더(작업 DB를 못 읽음)는 사유 코드만 알리고 선택지에서 뺀다.
2. **`no_review` 폴더를 골랐으면** 그 폴더는 빼고 "검수 결과가 없어 질문 재료가 없다. `/BEOL-labeling-feedback`으로 검수를 먼저 한다"를 한 줄 알린다.
3. **`asked` 폴더를 골랐으면** 폴더마다 `AskUserQuestion`으로 묻는다(한 번에 4개 질문까지, 넘으면 나눠 묻는다). 선택지:
   - **건너뛰기**: 이 폴더는 이번에 하지 않는다.
   - **다시 질문 만들기(중복 진행)**: 절차 2에 `--force`를 붙인다. 이미 답한 질문은 다시 묻지 않는다.
   - 최상위 `questions.open`이 1 이상이면 **남은 질문 이어서 답하기**도 둔다: generate 없이 절차 3부터 한다. 이 선택지가 있으면 여기에 권장 표시를 붙이고, 없으면 건너뛰기에 붙인다.
4. 남은 폴더가 없으면(모두 건너뜀·제외) 그 폴더 이름과 상태만 한 줄씩 알리고 끝낸다.
5. **여러 폴더를 골랐으면** 장부와 질문 폴더가 작업 폴더 공용이므로 질문 묶음은 하나다. 고른 폴더 중 가장 최근 폴더(목록에서 가장 앞)를 `<WS>`로 쓰고, 나머지 폴더는 먼저 장부에만 넣는다.

   ```bash
   python -m domain_engrbot intake --workspace "<다른 폴더>"
   ```

   `[intake] …` 줄의 건수만 전한다. 그다음 `<WS>` 하나로 절차 2~5를 한다.

### 2. 질문 만들기 (LLM 호출)

질문을 만들기 전에 아직 반영하지 않은 답 파일이 있는지 본다. `python -m domain_engrbot questions status --workspace "<WS>"`의 `inbox`에 `open_matches`가 1 이상인 파일이 있으면, 그 답을 먼저 반영할지(절차 5) 사용자에게 `AskUserQuestion`으로 묻는다. 반영하지 않고 새로 만들어도 그 답 파일은 나중에 반영할 수 있다(답은 질문 단위로 받는다).

```bash
python -m domain_engrbot questions generate --workspace "<WS>" [--force] [--max N]
```

- 콘솔의 `[questions] set_id=<ID> 질문 n건(라벨링 a · taxonomy b, 이월 c), LLM 호출 k회 → <화면 상대 경로>` 줄을 그대로 전한다. 이월은 지난 묶음에서 답하지 않은 질문이 앞에 다시 올라온 것이다.
- `[questions] 재사용: 입력이 그대로다(LLM 0회). 질문 n건 대기 → <화면>`이면 지난 묶음을 그대로 쓴다. 새로 만들려면 `--force`로 다시 돌린다(사용자가 원할 때만).
- `[questions] 질문 재료 없음(NO_REVIEW_INPUT)`이면 누적 장부에 교정 사례·재검토 요청·검수 등록 동의어가 모두 없다는 뜻이다. 그 사실과 "`/BEOL-labeling-feedback`으로 검수를 먼저 한다"를 알리고 끝낸다. 줄 끝에 `남은 질문 n건 대기`가 붙어 있으면 지난 묶음의 질문이 남아 있는 것이므로 절차 3으로 이어 간다.
- 이미 답한 질문은 다시 묻지 않는다. 다만 그 뒤에 새 교정이나 새 규칙 후보가 그 주제에 붙으면 "새 근거로 다시 올라온 질문"으로 한 번 더 나온다.
- 질문이 0건이면 절차 3·4·5를 건너뛴다.
- 한 번에 만드는 수는 기본 10개다(`--max N` 또는 정책의 `questions.max`).
- 질문 재료로 쓰는 chunk(교정이 있는 레코드)는 **`<WS>`(가장 최근 작업 폴더)에서 60%, 전체 기간(모든 작업 폴더)에서 무작위로 40%**를 고른다(사용자 결정, 2026-10-06. 정책의 `questions.context.recent_percent`, 기본 60). 그래서 `<WS>`는 가장 최근 작업 폴더로 준다. 무작위 몫은 장부가 같으면 같은 표본이고, 새 검수 결과가 들어오면 바뀐다.

### 3. 질문 화면 서버 (사람 답변 대기)

아래 명령을 Bash `run_in_background`로 띄우고(timeout은 최대 7200000), 출력에 나오는 `127.0.0.1` 주소를 브라우저 창에서 연다. 포트는 set_id로 정해진다(8900~9099, 쓰고 있으면 빈 포트).

```bash
python -m domain_engrbot questions serve --workspace "<WS>" [--port N] [--no-draft] [--no-apply]
```

서버는 **답변 완료 · 저장**을 받으면 답 파일을 `qa/inbox`에 쓰고 바로 반영한다(`questions apply`와 같은 일. taxonomy 제안이 생기면 수정 보드도 다시 만든다). 반영을 마치면 서버가 스스로 닫히고, 백그라운드 작업이 끝났다는 알림으로 Claude가 깨어나 절차 5-A로 마무리한다(사용자 결정, 2026-10-06). 반영이 실패하면(`[serve] 반영 실패: <코드>`) 답 파일은 저장된 채 서버가 열려 있고, 사람이 다시 저장하면 다시 반영한다. `--no-apply`는 예전처럼 저장만 하는 서버다(반영은 절차 5-B).

화면 파일만 다시 만들어야 하면 서버를 띄우기 전에 `python -m domain_engrbot questions screen --workspace "<WS>"`를 쓴다. LLM 설정이 없으면 서버는 초안 만들기 없이 뜬다.

화면은 이렇게 쓴다고 안내한다(문구는 짧게).
- 왼쪽 질문 목록(순위·목표 배지·상태), 오른쪽 상세. 상세에 질문 문장, 왜 묻는지, 영향 건수, 근거 카드(슬라이드 미리보기 확대, 봇 값 → 사람 값, 검수자가 남긴 인용·이유), 재검토 메모가 나온다.
- 선택지를 하나 고르거나 **직접 답하기**에 쓴다. 직접 쓴 답은 **초안 만들기**로 초안을 받을 수 있다.
- 초안 패널에서 규칙 문장(1차 분류·3차 라벨링, 대상 축, 300자 이내)과 taxonomy 행(값 추가·정의·동의어·질문 등)을 고친다. 넣지 않을 초안은 체크를 끈다. 버튼 바로 위에 확정될 초안 전문이 보이고 **초안 n개 확정**(few-shot 사례가 함께 승인되면 **초안 n개 · 사례 m개 확정**)을 누르면 그 질문의 답이 확정된다. 규칙이나 taxonomy 초안이 1개 이상 있어야 확정된다.
- 지금 답하기 어려우면 **나중에**(다음 묶음에 다시 올라온다), 물을 필요가 없으면 **묻지 않기**를 누른다.
- 다 하면 오른쪽 위 **답변 완료 · 저장**을 누른다. 확인 창을 거쳐 답이 작업 폴더 `qa/inbox`에 저장되고 바로 반영된다. 결과 창에 반영 건수(규칙·사례·taxonomy 제안, 반영하지 못한 답)가 나오고 서버가 닫힌다. 화면을 파일로 열었거나 서버 저장이 막히면 내려받기(또는 텍스트 창)로 저장되며, 이때는 Claude에게 "질문 답변 끝났어"라고 알린다.

안내 끝에 "답을 마치면 오른쪽 위 **답변 완료 · 저장**을 누르면 반영까지 끝나고, Claude가 마무리 보고를 한다"를 쓴다. 그다음 milestone 2를 `▶️ — 질문 화면 답변 완료 · 저장 대기`로 둔 블록을 보여 주고 턴을 끝낸다. 사용자가 지금 답하지 않겠다고 하면 그대로 둔다(다시 불러 "남은 질문 이어서 답하기"로 이어 간다).

### 4. 사람 답변

사람이 질문 화면에서 답한다. Claude는 화면을 대신 누르거나 내용을 읽지 않는다.

### 5. 답 반영 (LLM 0회)

#### 5-A. 서버가 반영을 마치고 끝났을 때 (기본)

절차 3의 백그라운드 작업이 끝났다는 알림이 오면(또는 사용자가 "질문 답변 끝났어"라고 했는데 서버 출력에 반영 줄이 이미 있으면) 그 작업의 출력 파일을 읽는다. 출력에는 건수·ID·사유 코드만 있다.

- `[questions] 반영: …` 줄과 `[serve] 반영을 마쳐 질문 화면 서버를 닫았다`가 있으면 반영이 끝난 것이다. `AskUserQuestion`·`questions apply`·TaskStop은 하지 않는다(같은 파일을 다시 반영하면 모두 `not_open`이다). 반영 줄을 그대로 전하고, 뒤따르는 JSON 줄(`invalid`·`not_open`·`notes`)은 아래 5-B의 3과 같이 설명한다. `[taxonomy-board] …` 줄이 있으면 보드가 이미 갱신된 것이므로 그 줄을 전하고 보드에서 S7 항목을 확정하라고 안내한다(보드 명령은 다시 돌리지 않는다). 그다음 5-B의 6처럼 마무리 보고를 한다.
- 반영 줄 없이 끝났으면(사람이 저장하지 않았거나 2시간 timeout) 저장된 답 파일이 있는지 `questions status`로 보고, 있으면 5-B로 간다. 없으면 남은 질문 수만 알리고 끝낸다.
- 사용자가 "질문 답변 끝났어"라고 했는데 서버가 아직 떠 있으면 출력 파일에서 `[serve] 반영 실패: <코드>` 줄을 본다. 있으면 그 코드를 알리고(오류 코드 안내 표), 화면에서 **다시 저장**을 누르라고 안내한다. 저장 줄도 없으면 아직 저장하지 않은 것이므로 화면의 **답변 완료 · 저장**을 누르라고 안내한다.

#### 5-B. 서버 없이 저장한 답 파일 ("질문 답변 끝났어")

내려받기·텍스트 창으로 저장했거나, `--no-apply`로 띄운 서버였거나, 5-A에서 저장만 되고 반영이 안 된 파일이 남은 경우다.

1. 답 파일 후보를 본다.

   ```bash
   python -m domain_engrbot questions status --workspace "<WS>"
   ```

   출력 JSON의 열린 질문 수와 `inbox` 목록(답 파일 이름·저장 시각·답/묻지 않음/나중에 건수·`open_matches`)을 본다.

2. **항상** `AskUserQuestion`으로 이번 답 파일을 확인받는다(이름·저장 시각·건수, 여럿이면 선택지로). 사람이 고르지 않은 파일은 반영하지 않는다.
   - 사용자가 대화에 파일 경로를 직접 주었으면 그 파일을 고른 것으로 본다.
   - 내려받기 폴더(`%USERPROFILE%\Downloads`)에 저장된 경우는 그 경로를 `--answers`로 준다.
   - 텍스트 창의 내용을 붙여 넣었으면 그 JSON을 고치지 않고 `<WS>\qa\inbox\engr_answers_<set_id>.json`으로 써서 쓴다.

3. 반영한다.

   ```bash
   python -m domain_engrbot questions apply --workspace "<WS>" --answers "<답 파일 경로>"
   ```

   `--answers`를 빼면 `<WS>\qa\inbox\`의 `engr_answers_*.json` 중 가장 늦게 저장된 파일을 쓴다. 답은 질문 단위로 반영하므로 묶음이 바뀐 뒤 저장한 파일도 받는다.
   - `[questions] 반영: 답 n(규칙 a · taxonomy 제안 b · 사례 c), 후보 승인 x · 종결 y, 묻지 않음 d, 건너뜀 e, 남은 질문 r` 줄을 그대로 전한다.
   - 뒤따르는 JSON 줄에서 아래를 설명한다(건수와 코드만).
     - `invalid`: 반영하지 않은 질문과 코드. `NO_CONFIRMED_DRAFT`는 확정한 규칙·taxonomy 초안이 없는 답이다(few-shot 사례만 고른 답도 여기에 든다). 그 질문은 열린 채 남으므로 화면에서 초안을 확정하거나 **묻지 않기**를 고른다. `DRAFT_*`는 그 초안이 형식에 맞지 않아 빠진 것이다(문장이 비었거나 너무 김, 금지 글자, 필수 칸 빠짐 등).
     - `not_open`: 지금 열려 있지 않은 질문의 답(이미 반영했거나 닫힌 질문)이라 건너뛴 것이다. 같은 파일을 다시 반영하면 모두 여기로 간다.
     - `notes`의 `RULES_OVER_CAP`: 켜진 규칙 수(`enabled_rules`)가 labelbot 상한(`cap`, pipeline.json `feedback.max_rules`)을 넘어 일부가 다음 라벨링 프롬프트에서 잘린다. "승인 규칙 관리"에서 덜 중요한 규칙을 끄라고 안내한다.
     - `notes`의 `PATTERN_GONE`: 초안이 가리키던 규칙 후보가 그사이 사라졌거나 기각돼 있어 수동 규칙으로 넣었다.
     - `notes`의 `EXAMPLE_GONE`: 고른 few-shot 사례가 장부에서 사라져 승인하지 못했다. `EXAMPLE_REJECTED`: 사람이 기각해 둔 사례라 승인하지 않았다. `SCREEN_REBUILD_FAILED`: 반영은 끝났지만 질문 화면을 다시 만들지 못했다(`questions screen`으로 다시 만든다).
   - 반영하면 질문 화면도 다시 써진다.

4. 절차 3에서 띄운 질문 화면 서버가 아직 떠 있으면 멈춘다(TaskStop).

5. taxonomy 제안이 1건 이상이면 보드를 갱신한다(LLM 0회). 사용자가 원하면 `--open`을 붙인다.

   ```bash
   python -m domain_engrbot taxonomy-board
   ```

   `[taxonomy-board] …` 줄을 그대로 전하고, "출처 '엔지니어 답변(S7)' 항목을 보드 카드에서 고치고 반영함·최종 완료로 taxonomy.json에 저장한다"를 안내한다(아래 "taxonomy 수정 보드" 절차 2).

6. 마무리 보고: 반영 줄 한 줄, 승인 파일 [`taxonomy/labeling_rules.json`](taxonomy/labeling_rules.json) 링크, "다음 `/BEOL-labeling` 실행부터 1차 분류·3차 라벨링 프롬프트에 들어간다"는 한 줄, 남은 질문 수(1 이상이면 "다음에 `/BEOL-labeling-Domain-Engr-bot`으로 이어서 답할 수 있다").

## 승인된 규칙 관리

새 규칙·사례 후보의 승인은 질문 화면으로 합쳐졌다(사용자 결정, 2026-10-06). 승인 화면(`labeling_review.html`)에는 **이미 승인된 규칙·사례의 관리**(끄기·켜기·문장 수정·승인 취소)와 **갱신 대기 사례**(승인 뒤 확정 라벨이 바뀐 사례)의 승인(갱신)·기각만 남는다. 새 후보는 이 화면에 없다.

| 파일 | 내용 | 본문 |
|---|---|---|
| `workspaces/_domain_engrbot/ledger/labeling_review.html` | 승인 규칙 관리 화면. 서버 없이 파일로 연다 | **있음(근거 인용)** |
| `labeling_decisions_<시각>.json` | 화면이 저장한 사람의 결정(ID·동작·고친 문장) | 없음 |
| `taxonomy/labeling_rules.json` | 승인 파일 | 없음 |
| `workspaces/_domain_engrbot/ledger/labeling_decisions.jsonl` | 결정 이력(ID·동작·결과만) | 없음 |

### 절차

1. 건수를 본다(LLM 0회).

   ```bash
   python -m domain_engrbot labeling-rules status --workspace "<WS>"
   ```

   `rules.approved`·`rules.enabled`, `examples.approved`·`examples.enabled`를 한 줄로 전한다. `<WS>`는 아무 작업 폴더나 된다(장부는 공용이다). 승인분이 모두 0이면 그 사실을 알리고 끝낸다.

2. 화면을 만든다.

   ```bash
   python -m domain_engrbot labeling-rules review --workspace "<WS>"
   ```

   `[labeling-rules] …` 줄의 건수와 화면 위치 `workspaces/_domain_engrbot/ledger/labeling_review.html`을 링크로 알리고, 브라우저 창에서 그 파일을 연다(`file:///` 경로). 사람이 승인된 규칙·사례를 끄기·켜기, 문장 수정(300자 이내), 승인 취소로 고르고, 갱신 대기 사례는 승인(갱신)·기각을 고른다. 다 고르면 **결정 JSON 저장**을 누르고 Claude에게 "규칙 관리 끝났어"라고 알려 달라고 안내한다. 그다음 milestone 2를 `▶️ — 결정 JSON 저장 대기`로 둔 블록을 보여 주고 턴을 끝낸다.

3. 사용자가 끝났다고 하면 결정 파일을 찾는다. 화면을 만든 뒤에 저장된 가장 새 `labeling_decisions_*.json`을 사용자의 내려받기 폴더(`%USERPROFILE%\Downloads`)에서 찾는다. 반영하기 전에 **항상** `AskUserQuestion`으로 그 파일(이름·저장 시각·결정 건수)을 이번 결정 파일로 쓸지 확인한다. 후보가 여럿이면 선택지로 보여 준다. 내려받기가 막혀 사용자가 **텍스트로 복사**한 내용을 붙여 넣었으면, 그 JSON을 그대로 `<WS>\qa\inbox\labeling_decisions_<시각>.json`으로 써서 쓴다(내용을 고치지 않는다).

4. 결정을 반영한다(LLM 0회).

   ```bash
   python -m domain_engrbot labeling-rules apply --workspace "<WS>" --decisions "<결정 JSON 경로>"
   ```

   `[labeling-rules] 반영: …` 줄을 그대로 전한다. 모르는 ID·문장 오류(비었거나 300자 초과이거나 `{{`·제어 문자, 그 결정은 하지 않음)가 붙으면 함께 알린다. `DECISIONS_STALE`(화면을 만든 뒤 승인 상태가 바뀜)·`DECISIONS_ID_NOT_ON_SCREEN`(화면에 없던 ID)이면 아무것도 반영되지 않았으니 2단계부터 다시 한다. 반영하면 승인 화면도 다시 써진다.

5. 마무리 보고: 반영 건수 한 줄, 승인 파일 `taxonomy/labeling_rules.json` 링크, "다음 `/BEOL-labeling` 실행부터 켜진 규칙·사례만 프롬프트에 들어간다"는 한 줄.

오류는 `[오류] <코드>`로 나온다. `DECISIONS_JSON_INVALID`·`DECISIONS_FORMAT_INVALID`·`DECISIONS_DUPLICATE_ID`·`DECISIONS_TOO_LARGE`는 결정 파일이 깨진 것이므로 화면에서 다시 저장해 달라고 한다. `RULES_JSON_INVALID`는 승인 파일을 사람이 고치다 깨진 것이므로 위치만 알리고 고치지 않는다.

## taxonomy 수정 보드 (사용자 결정, 2026-10-05, 2026-10-07 개정)

taxonomy 수정 제안은 여러 곳에 흩어져 있다: **S7 엔지니어 답변**(질문 화면에서 확정한 제안, `workspaces/_domain_engrbot/questions/taxonomy_proposals.jsonl`), Domain-Engr-bot 예전 도메인 검수의 승인 피드백(`feedback.json`)·제안(`proposals.jsonl`)·L6 지표(`taxonomy_candidates.jsonl`), labelbot 후보(`reports/candidates.jsonl`), 재검토 요청(`reports/taxonomy_revisit.jsonl`, `taxonomy/taxonomy_revisit_requests/*.json`), 교정 장부(`synonyms.jsonl`). 보드는 이것을 위치(축·값, 동의어, 질문 ID) 하나로 묶어 카드로 보여 준다. 사람이 카드의 편집 칸을 고치고 반영함·기각을 표시한 뒤 "최종 완료"를 누르면 변경 미리보기를 거쳐 봇이 `taxonomy/taxonomy.json`에 쓴다(원자적 저장, 이력 `taxonomy/taxonomy_history.jsonl`). 봇은 정의 문장을 지어내지 않는다(LLM 0회). 문장은 사람이 질문 화면이나 보드에서 확정한 것이다. 2026-10-07부터 Excel에 붙여넣지 않는다.

절차, 규칙, 오류 코드는 `/BEOL-taxonomy-dashboard` 스킬이 맡는다. 이 스킬에서 ③을 고르면 그 스킬의 절차를 그대로 따른다.

```bash
python -m domain_engrbot taxonomy-board --serve --open
```

taxonomy를 직접 보고 고치려면(축·값 트리, 칸 수정, 행 추가·삭제) 편집기를 쓴다: `python -m domain_engrbot taxonomy-editor --open`.

| 파일 | 내용 | 본문 |
|---|---|---|
| `workspaces/_domain_engrbot/taxonomy_board/taxonomy_board.html` | 보드 화면. 서버(`--serve`)로 열어야 반영된다 | **있음(용어·메모)** |
| `workspaces/_domain_engrbot/taxonomy_board/taxonomy_board.json` | 화면 데이터(항목, 행 초안, 상태, 출처) | **있음** |
| `workspaces/_domain_engrbot/taxonomy_board/seen.json` | 문장 편집 항목의 처음 본 대상 행 해시 | 없음 |

화면·json은 위치만 알리고 내용을 읽어 보고하지 않는다. 콘솔 줄(건수·코드·화면 상대 경로)만 전한다. 저장 뒤 재라벨링은 하지 않는다. 사람이 저장했다고 하면 축 점검(`/BEOL-labeling-Code-Engr-bot`)을 한 줄 안내한다.

## 오류 코드 안내

명령은 `[오류] <코드>`로 멈춘다. 코드만 전하고 아래처럼 안내한다.

| 코드 | 뜻 | 안내 |
|---|---|---|
| `QUESTIONS_INVALID`·`ASKED_INVALID` | 질문 폴더의 `questions.json`·`asked.json`이 깨졌다 | 위치만 알리고 고치지 않는다(조용히 비우면 이월 질문이나 답한 기록이 사라진다) |
| `LLM_CONFIG_MISSING`·`KEY_MISSING` | 작업 폴더 `pipeline.json`에 llm 주소·모델이 없거나 키가 없다 | 기존 질문 묶음과 화면은 그대로다. 설정을 채운 뒤 다시 돌린다 |
| `LLM_RESPONSE_INVALID`·전송 실패 코드 | LLM 응답이 형식에 맞지 않거나 전송이 실패했다 | 기존 질문 묶음과 화면은 그대로다. 다시 돌리거나 남은 질문으로 이어 간다 |
| `LEDGER_DISABLED` | 정책에서 장부가 꺼져 있다 | 질문을 만들 수 없다는 것만 알린다 |
| `ANSWERS_NOT_FOUND`·`ANSWERS_READ_FAILED` | 답 파일이 없거나 읽지 못했다 | 화면의 **답변 완료 · 저장**을 다시 누르거나 경로를 확인한다 |
| `QUESTIONS_NOT_FOUND` | 질문 묶음이 아직 없다 | 절차 2(`questions generate`)부터 한다 |
| `PROPOSALS_INVALID`·`ANSWERS_LOG_INVALID` | 질문 폴더의 `taxonomy_proposals.jsonl`·`answers.jsonl`이 깨졌다 | 위치만 알리고 고치지 않는다 |
| `QUESTIONS_CONFIG_INVALID` | 정책의 `questions` 설정이나 `--max` 값이 범위를 벗어났다 | 값을 고쳐 다시 돌린다 |
| `ANSWERS_JSON_INVALID`·`ANSWERS_FORMAT_INVALID`·`ANSWERS_TOO_LARGE`·`ANSWERS_DUPLICATE_ID` | 답 파일이 깨졌다 | 화면에서 다시 저장해 달라고 한다 |
| `LEDGER_LOCKED` | 다른 명령이 장부·질문 폴더를 쓰는 중이다 | 그 명령이 끝난 뒤 다시 돌린다 |
| `LEGACY_DATA_DIR` | 이름 변경 전 데이터 폴더 `workspaces/_engrbot`가 남아 있다 | 안의 파일을 `workspaces/_domain_engrbot`로 옮기고 빈 옛 폴더를 지운 뒤 다시 돌린다. 두 폴더에 같은 파일이 있으면 사용자에게 먼저 묻는다 |
| `NO_CONFIRMED_DRAFT`·`DRAFT_*` | 답 단위·초안 단위의 거절(`apply` 결과의 `invalid`) | 그 질문만 열린 채 남는다. 화면에서 초안을 고쳐 확정하거나 **묻지 않기**를 고른다 |

## 이 스킬이 하지 않는 일

- 도메인 검수(`domain_engrbot run`·`review`·`serve`·`golden`·`feedback`·`eval`, L0~L6 검사·judge·L4/L5, QA 검토 화면 `qa_review`): 명령과 코드는 남아 있지만 이 스킬은 부르지 않는다(2026-10-06 사용자 결정).
- 봇이 답·초안을 대신 확정하는 일, 규칙·사례의 승인·기각을 봇이 정하는 일(사람이 화면에서 확정한 것만 반영한다)
- taxonomy.json을 사람 확정 없이 고치는 일, L4 도메인 규칙 승인(`draft` → `approved`), labelbot 코드·프롬프트 수정
- 라벨링 실행: BEOL-labeling
- 사람 검수 반영과 Supabase 적재: BEOL-labeling-feedback
- 저장소 코드와 workflow 검수: BEOL-labeling-Code-Engr-bot
- `scripts/collect_qa_decisions.py` 실행: 예전 QA 흐름에서 남은 스크립트로, skill 스크립트 계약 스냅샷(`tests/contracts/snapshots/skill_scripts_help.json`)이 그 `--help`를 동결해 지우지 않고 두지만 이 스킬은 더 이상 부르지 않는다.

## 관계

- 라벨링 실행은 BEOL-labeling, 사람 검수 반영과 적재는 BEOL-labeling-feedback, 저장소 코드 검수는 BEOL-labeling-Code-Engr-bot이 맡는다.
