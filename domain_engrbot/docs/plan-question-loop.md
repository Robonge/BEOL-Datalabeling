> 2026-10-06 이름 변경: Engr-bot → Domain-Engr-bot(`domain_engrbot`), code-bot → Code-Engr-bot(`code_engrbot`). 아래 본문은 이력이라 옛 이름을 그대로 둔다.

# Engr-bot 개념 전환: 질문 루프 (2026-10-06)

## 0. 왜 바꾸나

사람이 이미 검수한 chunk를 Engr-bot이 다시 도메인 검수하는 것은 의미가 없다. Engr-bot을 **검수 결과를 읽고
엔지니어에게 질문해 도메인 지식을 얻는 봇**으로 바꾼다. 답은 사람이 확정한 초안만 labelbot 프롬프트와 taxonomy
수정 보드로 간다.

```
/BEOL-labeling-feedback(검수 반영) → 교정 장부(ledger, intake)
  → [/BEOL-labeling-Engr-bot] questions generate: 검수 결과 + 누적 장부 → LLM → 질문 10개 안팎
  → questions serve: 질문 화면(근거·선택지·자유 답) → 사람이 답하고 초안을 고쳐 확정 → qa/inbox/engr_answers_<set>.json
  → (저장 즉시, 10절) questions apply: 확정분만 (a) taxonomy/labeling_rules.json (b) taxonomy 보드 출처 S7
  → 다음 /BEOL-labeling: 승인 규칙·사례가 프롬프트에 들어감 / 사람이 보드에서 taxonomy.xlsx에 붙여넣음
```

## 1. 사용자 결정 (확정, 다시 묻지 않는다)

| # | 결정 |
|---|---|
| D1 | 입력은 검수 결과(작업 폴더 corrections·재검토 요청·검수 등록 동의어) + 누적 교정 장부. 장부의 규칙·사례 후보도 질문 재료다 |
| D2 | 질문은 LLM이 전부 만든다(무엇을 물을지·문장·선택지·초안). 목표는 라벨링 정확도·확신도와 taxonomy 확신도 |
| D3 | 질문 채널은 서버로 여는 질문 화면 HTML(127.0.0.1, 같은 출처만, 답은 작업 폴더 qa/inbox에 바로 저장) |
| D4 | 답을 고르면 같은 화면에 초안(규칙 문장·taxonomy 행)이 보이고 사람이 고쳐 확정한다. 확정분만 반영한다 |
| D5 | 기존 '라벨링 규칙 최종 검수'의 후보 승인은 질문 화면으로 합친다. 기존 화면에는 승인된 규칙·사례 관리(끄기·켜기·문장 수정·승인 취소)만 남긴다 |
| D6 | taxonomy 수정 보드는 그대로 두고 새 출처 S7(엔지니어 답변)을 더한다. 봇은 taxonomy.xlsx를 쓰지 않는다 |
| D7 | QA 검토 화면·골든셋·피드백 묶음·L0~L6 검사·judge·L4/L5는 스킬 절차에서만 뺀다. 코드·명령·테스트는 남긴다 |
| D8 | /BEOL-labeling-Engr-bot을 부를 때만 질문을 만든다(feedback 뒤 자동 실행 없음) |
| D9 | 한 번에 10개 안팎(설정). 답한 질문은 다시 묻지 않고, 건너뛴 질문은 다음에 다시 올린다 |
| D10 | 다른 세션의 변경과 겹쳐도 필요한 파일은 고친다(2026-10-06 사용자 지시) |
| D11 | 질문 재료 chunk(레코드)는 가장 최근 작업 폴더(명령에 준 `--workspace`)에서 60%, 전체 기간에서 무작위 40%로 뽑는다(`questions.context.recent_percent`, 2026-10-06 사용자 결정) |

## 2. 지킬 것

- 루트 CLAUDE.md: 표준 라이브러리만, Python 3.14.2. 쓰기 형식은 .json .jsonl .html .md .log(.b64 .sqlite)뿐.
- engrbot에서 labelbot을 import할 수 있는 곳은 `adapters/labelbot_ws.py`, `io.py`, `llm_http.py`뿐(test_core BoundaryTest).
- LLM 호출은 `engrbot/llm_http.py`(→ `labelbot.llm.post_json`, check_send)만 거친다. LLM에는 파싱한 텍스트만 넣는다.
- 콘솔·로그에는 실행 ID·건수·사유 코드만. 본문·인용·파일명·질문 문장은 내지 않는다.
- 화면 템플릿에는 외부 주소를 넣지 않는다(템플릿과 만든 화면에 "http" 글자가 없어야 한다. 데이터는 `screen.embed`로 넣는다).
- 봇은 결정을 만들지 않는다. 규칙·taxonomy 제안·사례는 사람이 화면에서 확정(체크)한 초안만 반영한다.
- codebot 규칙(C1 open(...,'rb') 금지, C2 전송 우회 금지, C4 빈 함수·TODO 금지)을 지킨다.

## 3. 저장 위치

질문 폴더 `QDIR = <코드 폴더>/workspaces/_engrbot/questions/` (장부처럼 작업 폴더 공용, 커밋 제외).

| 파일 | 내용 | 본문 |
|---|---|---|
| `questions.json` | 지금 열려 있는 질문 묶음 | **있음**(질문 문장·용어) |
| `engr_questions.html` | 질문 화면 | **있음**(근거 인용·슬라이드 미리보기) |
| `answers.jsonl` | 답 이력(질문 문장·고른 답·확정 초안) | **있음** |
| `taxonomy_proposals.jsonl` | 보드 출처 S7 입력(확정한 taxonomy 제안) | **있음**(용어·정의 문장) |
| `asked.json` | 답함·묻지 않음 지문(fingerprint) | 없음 |
| `generate_log.jsonl` | 생성 이력(set_id·건수·코드·LLM 호출 수) | 없음 |
| `<WS>/qa/inbox/engr_answers_<set_id>.json` | 화면이 저장한 답(사람 입력) | **있음** |

## 4. 계약 (모듈 사이 자료 형식) — `engrbot/qmodel.py`가 코드로 고정한다

### 4.1 질문 묶음 `questions.json`

```json
{"kind": "engr_questions", "version": 1, "set_id": "QS-20261006T010203-ab12", "generated_at": "<ISO>",
 "workspace": "<작업 폴더 이름>", "model": "<LLM 이름>", "context_digest": "<sha256>",
 "inputs": {"<source_ws>": "<corrections_sha>"},
 "questions": [{
   "question_id": "EQ-<10hex>", "fingerprint": "<문자열>", "goal": "labeling|taxonomy",
   "topic": {"type": "axis_value|axis|question|term|general", "axis": "", "values": [], "qid": "", "term": ""},
   "text": "질문 문장", "why": "왜 묻는지", "carried": false,
   "evidence": ["<case_id>"], "patterns": ["FR-…"], "examples": ["EX-…"],
   "revisits": [{"reason": "", "target": "", "key": "", "memo": "", "count": 1}],
   "impact": {"records": 3},
   "options": [{"option_id": "A", "label": "선택지", "drafts": [<draft>]}]
 }]}
```

- `fingerprint`는 코드가 만든다: topic.type이 general이 아니면 `goal|type|norm(axis)|norm(values 정렬)|qid|norm(term)`,
  general이면 `goal|general|sha256(norm(text))[:16]`. `question_id = "EQ-" + sha256(fingerprint)[:10]`.
- 순서가 우선순위다(LLM이 효과 큰 순으로 낸다. 이월 질문이 앞).

### 4.2 초안 `draft`

```json
{"type": "rule", "stage": "classify|label", "target": "<축 이름 또는 빈칸>", "text": "<규칙 문장 300자 이내>", "pattern_id": "FR-… 또는 없음"}
{"type": "taxonomy", "kind": "value_add|value_def|axis_def|overlap|value_off|new_axis|synonym|q_edit|q_new",
 "axis": "", "value": "", "values": [], "parent": "", "name": "", "alias": "", "canonical": "", "qid": "", "text": "",
 "definition": "", "include": "", "exclude": "", "memo": ""}
{"type": "example", "example_id": "EX-…"}
```

kind별 필수 칸: value_add(axis,value) · value_def(axis,value) · axis_def(axis) · overlap(axis,values 2개) · value_off(axis,value) ·
new_axis(name) · synonym(alias,canonical) · q_edit(qid) · q_new(text). 문장 상한: rule.text 300, definition·include·exclude·text 500, memo 300.
금지 글자와 `{{`는 `labeling_review._clean_text` 규칙과 같다. `qmodel.normalize_draft(draft, axes)`가 정리·검증한다(틀리면 None).

### 4.3 답 파일 `engr_answers_<set_id>.json` (화면이 만든다)

```json
{"kind": "engr_answers", "set_id": "QS-…", "reviewer": "",
 "answers": [
  {"question_id": "EQ-…", "action": "answer", "option_id": "A 또는 null", "option_label": "", "free_text": "",
   "confirmed": [<draft>, …]},
  {"question_id": "EQ-…", "action": "dismiss"},
  {"question_id": "EQ-…", "action": "skip"}]}
```

### 4.4 taxonomy 제안 `taxonomy_proposals.jsonl` (apply가 쓰고 보드가 읽는다)

`{"proposal_id": "QP-<12hex>", "set_id", "question_id", "at": "<ISO>", "kind": <4.2 taxonomy kind>, …4.2 taxonomy 칸}`.
`proposal_id = "QP-" + hash(kind + 대상 키 + 문장)[:12]`(같은 제안을 두 번 쓰지 않는다).

## 5. 모듈과 담당

| 모듈 | 내용 | 담당 |
|---|---|---|
| `qmodel.py` (새) | 상수·파일 이름·`qdir`·`fingerprint`·`question_id`·`clean_text`·`normalize_draft`·`load_set`/`save_set`·`load_asked`/`save_asked`·`digest` | 리드(먼저 작성) |
| `adapters/labelbot_ws.py` | `chunk_context(ws_root, chunk_ids)` 추가 | 리드(먼저 작성) |
| `questions.py` (새) | 입력 context 조립, LLM 호출·응답 검증, 이월·재사용, `draft_for_answer`, `status`, `main_cli` | A |
| `prompts/engr_questions.md`, `prompts/engr_draft.md` (새) | 프롬프트 | A |
| `policy.py` | `EXTENSION_BLOCKS`에 `"questions"` 추가(defaults/policy.json은 바꾸지 않는다) | A |
| `cli.py` | `questions` 하위 명령(generate·status·screen·serve·apply) | A |
| `workspaces.py` | 상태를 질문 루프 기준으로 바꿈 | A |
| `answers.py` (새) | 답 파일 읽기·검증·반영 | B |
| `taxonomy_board.py`, `screens/taxonomy_board.html` | 출처 S7 | B |
| `labeling_review.py`, `screens/labeling_review.html` | 후보 탭 제거(승인분 관리만) | B |
| `question_screen.py` (새), `screens/engr_questions.html` (새) | 질문 화면 | C |
| `serve.py` | 질문 화면 서버(답 저장, 자유 답 초안) | C |
| SKILL.md·README·관련 스킬 문서 | 새 개념 반영 | D |

### 5.1 A — 질문 생성 (`questions.py`)

- 설정: `config(policy)` = 기본값 위에 `policy.get("questions")` 병합.
  기본값 `{"max": 10, "model": null, "temperature": null, "timeout": 180, "max_retries": 1,
  "context": {"max_records": 40, "recent_percent": 60, "text_chars": 600, "max_cases": 120, "max_patterns": 60,
  "max_history": 40}}`.
- `generate(paths, policy, llm=None, qd=None, rules_path=None, now=None, force=False, max_n=None)`:
  1. `ledger.intake(paths.root, policy)`(멱등). 장부가 꺼져 있으면 `LEDGER_DISABLED`.
  2. context 조립(아래). 재료가 없으면(교정 사례·재검토 요청·검수 동의어 모두 0) LLM을 부르지 않고 질문 0건 묶음을 쓴다(`NO_REVIEW_INPUT`).
  3. `context_digest`가 지난 묶음과 같고 `force`가 아니면 재사용(LLM 0회, 화면만 다시 만든다).
  4. 이월: 지난 묶음의 열린 질문(답함·묻지 않음이 아닌 것)을 `carried=true`로 앞에 둔다. 새로 필요한 수 = max − 이월 수(0 이하면 LLM 0회).
  5. LLM 호출(JSON 모드). 응답이 JSON이 아니거나 형식이 틀리면 `max_retries`번 다시 부르고, 그래도 틀리면 `LLM_RESPONSE_INVALID`.
  6. 질문 정리: 초안은 `qmodel.normalize_draft`로 거르고, 모르는 ref는 버리고, 선택지는 A·B·C…로 번호를 붙인다.
     지문이 `asked.json`(답함·묻지 않음)이나 이월 질문과 같으면 버린다. 선택지가 하나도 없는 질문도 자유 답만으로 둔다.
     `patterns`는 refs 중 지금 승인 대기인 FR- ID, `examples`는 evidence 사례의 레코드가 사례 후보(EX-)이면 그 ID,
     `impact.records`는 evidence 사례의 서로 다른 레코드 수와 patterns 건수 중 큰 값.
  7. `questions.json` 저장(원자 교체) → `question_screen.build` → `generate_log.jsonl`에 한 줄.
  반환은 건수만: `{"set_id", "questions", "labeling", "taxonomy", "carried", "llm_calls", "reused", "reason"}`.
- context(LLM 입력, user 메시지의 JSON):
  `taxonomy`(활성 축·값·정의, 승인 질문, 동의어) · `patterns`(`labeling_rules.all_rules(cases, 1)` 중 미결정, ref=rule_id) ·
  `cases`(교정·확인 사례, ref=C1…, 봇 값·사람 값·근거 인용·이유) · `records`(교정이 있는 레코드의 제목·본문 앞 text_chars자·확정 라벨,
  `labelbot_ws.chunk_context`) · `axis_stats`(축별 확인·교정 수) · `revisits`(장부 revisits + 각 작업 폴더
  `reports/taxonomy_revisit.jsonl`의 메모·제안, ref=V1…) · `synonyms_registered` · `approved_rules`(문장만) ·
  `answered`(answers.jsonl 최근 max_history건의 질문·답) · `open`(이월 질문 문장) · `limits.max_new`.
  원래 작업 폴더가 없으면 그 레코드의 본문은 뺀다(사유 코드만 센다).
- 레코드 표본(D11): 후보는 교정이 1건 이상 있는 장부 레코드다. `context.recent_percent`(기본 60, 0~100 정수, 밖이면
  `QUESTIONS_CONFIG_INVALID`)에 따라 `round(max_records × recent_percent / 100)`건은 가장 최근 작업 폴더(`--workspace`와 같은
  source_ws)의 레코드에서 교정 많은 순으로, 나머지는 전체 기간(최근 폴더의 남은 레코드 포함)에서 무작위로 뽑는다.
  한쪽이 모자라면 다른 쪽으로 채워 합이 `min(max_records, 후보 수)`가 되게 한다. 무작위는 `random.Random(seed)`이고 seed는
  장부 sources의 (작업 폴더, corrections_sha) 목록 해시다(같은 장부면 같은 표본이라 재사용 판정이 그대로, 새 검수가 들어오면
  표본이 바뀐다). R 번호는 최근 몫 먼저, 그다음 무작위 몫. `cases`는 뽑힌 레코드의 사례를 먼저 두어 `max_cases`에서 잘려도
  남게 하고, `patterns`·`axis_stats`는 전체 사례 기준이다. 건수 `records_recent`·`records_random`을 generate_log의 context에 남긴다.
- LLM 출력: `{"questions": [{"goal", "topic", "text", "why", "refs": [...], "options": [{"label", "drafts": [...]}]}]}`.
  rule 초안의 `pattern_ref`가 patterns의 ref이면 `pattern_id`로 옮긴다.
- LLM 객체: `llm.complete(messages, file_ids, hint)`(engrbot.llm.JudgeLLM 인터페이스). 기본은 pipeline.json의 llm 블록에
  questions 설정(model·temperature·timeout)을 덮어 `llm_http.OpenAICompatJudgeLLM`(mode json). base_url·model이 없으면
  `LLM_CONFIG_MISSING`, 키가 없으면 `KEY_MISSING`. 테스트는 `MockJudgeLLM(responder=…)`를 넣는다.
- `draft_for_answer(question, answer_text, llm, axes)`: 자유 답 → 초안 목록(`prompts/engr_draft.md`). 실패하면 `QuestionError`.
- CLI(`main_cli(args, paths, say)`):
  - `generate [--force] [--max N]` → `[questions] set_id=<ID> 질문 n건(라벨링 a · taxonomy b, 이월 c), LLM 호출 k회 → <화면 상대 경로>`
    재사용이면 `[questions] 재사용: 입력이 그대로다(LLM 0회). 질문 n건 대기 → <화면>`. 재료가 없으면 `[questions] 질문 재료 없음(NO_REVIEW_INPUT)`.
  - `status` → 건수 JSON 한 줄. `screen` → 화면만 다시 만든다.
  - `serve [--port N] [--no-draft]` → `serve.serve_questions(paths, qd, port, drafter)`. LLM 설정이 없으면 drafter 없이 띄운다.
  - `apply [--answers PATH]` → `answers.apply(...)` 결과 줄:
    `[questions] 반영: 답 n(규칙 a · taxonomy 제안 b · 사례 c), 후보 승인 x · 종결 y, 묻지 않음 d, 건너뜀 e, 남은 질문 r`
- `workspaces.scan()`: 상태를 `no_review`(검수 교정 없음) · `new`(검수 결과가 아직 질문에 안 쓰임: 장부 sources의
  corrections_sha가 questions.json `inputs`와 다르거나 없음) · `asked`(쓰임)로 바꾸고, 최상위에 `questions`
  (`set_id`, `open`, `answered_total`)를 더한다. `engrbot workspaces` 출력은 `{"workspaces": [...], "questions": {...}}`.

### 5.2 B — 답 반영 (`answers.py`), 보드 S7, 승인 화면 축소

- `apply(paths, policy, answers_path=None, qd=None, rules_path=None, by="screen", now=None)`:
  - 답 파일: 기본은 `<WS>/qa/inbox/engr_answers_<지금 set_id>.json`. `io.read_json_input`으로 읽는다(크기 상한 1MB).
    오류 코드: `ANSWERS_NOT_FOUND` · `ANSWERS_JSON_INVALID` · `ANSWERS_FORMAT_INVALID` · `ANSWERS_TOO_LARGE` ·
    `ANSWERS_OTHER_SET`(set_id가 지금 묶음과 다름) · `ANSWERS_DUPLICATE_ID`.
  - 질문 단위로 반영한다. 지금 묶음에 열려 있지 않은 question_id는 `not_open`에 넣고 건너뛴다(파일 전체를 거부하지 않는다).
  - `answer`: confirmed 초안을 `qmodel.normalize_draft`로 다시 검증한다(틀린 초안은 `invalid`에 코드와 함께, 나머지는 반영).
    - rule + pattern_id(그 질문의 patterns 안, 지금 후보): `lr.apply_decision(d, doc, "approve", cfg, ids=[FR])` 뒤 text를 확정 문장으로 바꾼다
      (edited_at·edited_by). 그 밖의 rule: MANUAL 규칙 추가 —
      `{"rule_id": "QR-" + hash(fingerprint + text)[:10], "kind": "MANUAL", "target": stage가 label이면 "label", 아니면 축 이름 또는 "classify",
      "from": "", "to": "", "count": impact.records, "text", "enabled": true, "approved_at", "approved_by": by,
      "question_id", "set_id"}`. 같은 rule_id가 있으면 문장만 갱신한다.
    - taxonomy: `taxonomy_proposals.jsonl`에 4.4 행을 더한다(proposal_id가 이미 있으면 쓰지 않는다).
    - example: 그 질문의 examples 안이면 `lr.apply_decision(..., "approve", ids=[EX])`.
    - 그 질문의 patterns 중 승인되지 않은 것은 `lr.apply_decision(..., "reject", ...)`로 종결한다(다시 후보로 올리지 않는다).
  - `dismiss`: 그 질문의 patterns를 종결하고 `asked.json` dismissed에 지문을 넣는다. `skip`: 아무것도 하지 않는다(다음에 다시 올라온다).
  - 쓰기는 `ledger.locked(d)` 안에서 승인 파일(원자 교체) → taxonomy_proposals → answers.jsonl → asked.json → questions.json
    (답함·묻지 않음 질문 제거) → 후보 리포트 다시 쓰기 → `question_screen.build`. 승인 파일 저장 전 예외면 아무것도 바꾸지 않는다.
  - 반환(건수·ID·코드만): `{"answered", "dismissed", "skipped", "rules", "patterns_approved", "patterns_closed", "taxonomy",
    "examples", "invalid": [{"question_id", "code"}], "not_open": [ids], "remaining"}`.
- 보드 S7: `collect(..., questions_dir=None)`이 `taxonomy_proposals.jsonl`을 읽어 `_entry("S7", "", set_id, kind, …)`를 더한다.
  `SOURCE_CODES`·`SOURCE_LABELS["S7"]="엔지니어 답변"`·`HUMAN_SOURCES`에 S7을 넣는다. S7 제안에 사람이 확정한 문장
  (definition·include·exclude·text·memo)이 있으면 붙여넣기 행의 해당 칸(H·I·J, 질문 문장, 동의어 메모)에 채운다. 같은 항목에
  S7이 여럿이면 `at`이 가장 늦은 것을 쓴다. 다른 출처만 있는 항목의 동작은 그대로다. `main_cli`는 기본 질문 폴더를 넘긴다.
- 승인 화면: `labeling_review.data()`의 pending_rules·pending_examples는 항상 빈 목록, 화면에서 '규칙 후보'·'사례 후보' 탭과
  관련 도움말을 뺀다(제목 "승인된 규칙 관리"). `labeling-rules review/apply/status/candidates/approve/reject` 명령은 남긴다.

### 5.3 C — 질문 화면과 서버

- `question_screen.data(doc, d, roots)`: 질문 묶음 + 근거 풀이. evidence 사례마다
  `{"case_id", "record_id", "source_ws", "field", "kind", "bot", "human", "items": [{"kind", "slide_no", "quote"}], "reason",
  "slide_key"}`, `slides[slide_key] = {"slide_no", "title", "preview": data URL 또는 null}`(레코드마다 한 번, 전체 40장 상한,
  `labelbot_ws.chunk_context`의 preview_rel을 `WsLoader.image_bytes`로 읽는다). examples의 EX- ID는 그 레코드의 근거 카드에 표시한다.
  `axes`(초안 편집용 축·값 이름), `set_id`, `digest`도 넣는다. 시각을 넣지 않아 같은 입력이면 같은 HTML이다.
- `question_screen.build(qd, d, policy=None)`: `engr_questions.html`을 쓴다. 반환: 질문 수.
- 화면(단일 파일, 외부 참조 없음, 판정 로직 없음):
  - 왼쪽 질문 목록(순위·목표 배지·상태: 미답·답함·나중에·묻지 않음), 오른쪽 상세.
  - 상세: 질문 문장, 왜 묻는지, 영향 건수, 근거 카드(슬라이드 미리보기 확대, 봇 값 → 사람 값, 검수자가 남긴 인용·이유), 재검토 메모.
  - 답: 선택지(하나 고름) + 자유 답. 서버로 열렸고 초안 기능이 있으면 **초안 만들기**(POST `draft`)로 자유 답의 초안을 받는다.
    초안 기능이 없으면 자유 답을 규칙 문장 초안 하나로 둔다(stage classify, target은 topic의 축).
  - 초안 패널: 고른 선택지의 초안마다 포함 체크(기본 켜짐)와 편집 칸. rule은 단계(1차 분류·3차 라벨링)·대상 축·문장(300자 카운터),
    taxonomy는 kind 표시와 칸 편집, example은 "few-shot 사례로 쓰기" 체크. 사람이 초안을 직접 더할 수도 있다(규칙 문장 추가).
  - 질문마다 **답 확정** · **나중에** · **묻지 않기**. 위쪽에 진행 수와 **답변 완료 · 저장**.
    서버로 열렸으면 POST `inbox/engr_answers` → qa/inbox 저장, 아니면 내려받기(막히면 텍스트 창). 진행 상황은 localStorage(try/catch, 키에 set_id).
- `serve.py`: QA 검토 서버와 공통 부분(Host·Origin 확인, 응답 도우미)을 기반 클래스로 묶고 질문 서버를 더한다.
  - `serve_questions(paths, qd, port=None, drafter=None)`, `make_question_server(paths, qd, set_id, port, drafter=None)`.
  - GET `/`·`/engr_questions.html` → 화면 하나만. GET `/inbox/status` → `{"ok", "set_id", "draft": bool}`.
  - POST `/inbox/engr_answers`: 같은 출처·JSON·크기 상한(1MB)·kind·set_id 확인 → `qa/inbox/engr_answers_<set_id>.json`
    (임시 파일은 inbox 밖에 쓰고 os.replace). 저장하면 `[serve] 답 저장: qa/inbox/<이름> (답 n, 묻지 않음 n, 나중에 n)` 한 줄.
  - POST `/draft`: `{"question_id", "answer_text"(2000자 이내)}` → `drafter(question_id, answer_text)` →
    `{"ok": true, "drafts": [...]}` 또는 `{"ok": false, "code": …}`. drafter가 없으면 404 `DRAFT_UNAVAILABLE`.
  - 기본 포트는 set_id로 정한 8900~9099(QA 검토 서버 8700~8899와 겹치지 않게), 쓰고 있으면 빈 포트.

### 5.4 D — 문서

- `.claude/skills/BEOL-labeling-Engr-bot/SKILL.md`: 세 가지 일로 다시 쓴다 — ① 도메인 질문(기본: 작업 폴더 고르기 → generate →
  serve → [사람 답] → "질문 답변 끝났어" → 답 파일 확인(AskUserQuestion) → apply → 보드 갱신 안내) ② 승인된 규칙 관리
  ③ taxonomy 수정 보드. 진행 현황 블록(질문 생성 40% · 사람 답변 70% · 답 반영 100%), 본문 있는 파일 표, 하지 않는 일
  (도메인 검수 run·review·golden·feedback은 명령만 남고 스킬은 부르지 않는다)을 넣는다. frontmatter description도 바꾼다.
- README engrbot 절, BEOL-labeling·BEOL-labeling-feedback·BEOL-labeling-workflow 스킬 문서와 workflow 템플릿의 Engr-bot 설명.

## 6. 테스트와 확인

- 새 테스트: `test_questions.py`(context·LLM mock·검증·이월·재사용·지문 중복 제거·오류 코드·콘솔에 본문 없음),
  `test_question_answers.py`(MANUAL 규칙·후보 승인/종결·taxonomy 제안·사례·dismiss·skip·not_open·오류 코드·멱등),
  `test_question_screen.py`(화면 데이터·"http" 없음·서버 GET/POST/draft·거절), 보드 S7, 승인 화면 축소, workspaces 상태.
- `python -m unittest discover -s engrbot/tests -t .`, `python -m codebot review --root .`(critical·major 0).
- 실제 작업 폴더로 `questions generate` 1회와 브라우저에서 화면·저장 확인. 승인 파일 반영(apply)은 사본 경로로만 시험한다.

## 7. 하지 않는 것

- 저신뢰 라벨(사람이 안 본 chunk)에서 질문 만들기, feedback 뒤 자동 실행, 답 원문을 labelbot이 직접 읽는 별도 지식 저장소.
- 기존 QA 코드(runner·judge·L0~L6·golden·feedback·qa_review.html) 삭제.

## 8. 검토 반영 (2026-10-06, 앞 절과 다르면 이 절을 따른다)

비판 검토(조건부 승인)에서 나온 수정이다. `qmodel.py`에 이미 반영한 것은 (qmodel)로 표시한다.

### 8.1 답이 사라지지 않게 (R1)

- 답 파일은 **질문 단위**로 받는다. `set_id`가 지금 묶음과 달라도 거부하지 않는다(`ANSWERS_OTHER_SET` 없음).
  question_id는 지문에서 나오므로 묶음이 바뀌어도 같다. 지금 열려 있는 question_id의 답만 반영하고 나머지는 `not_open`.
- `apply`의 기본 답 파일: `<--workspace>/qa/inbox/`의 `engr_answers_*.json` 중 수정 시각이 가장 늦은 것. `--answers`로 고를 수 있다.
  inbox 기준은 항상 명령에 준 `--workspace`다(questions.json의 workspace 칸은 표시용).
- 답 파일의 `digest`는 쓰지 않는다. `option_id`·`option_label`·`free_text`는 이력에만 남기고, 반영은 `confirmed`만 본다.
- `questions.json`·`asked.json`이 있는데 깨졌으면 `QUESTIONS_INVALID`·`ASKED_INVALID`로 멈춘다(qmodel: `QModelError`).
  generate·apply·serve·status는 이 예외를 `[오류] <코드>`로 낸다.

### 8.2 패턴 승인·종결 순서 (R2)

- `apply`는 파일 전체에서 **승인을 먼저 모두** 하고(규칙·사례), 그다음 종결을 한다. 한 FR이 여러 질문에 걸려도 결과가 같다.
- 종결(reject) 대상은 답함·묻지 않음 질문의 patterns 중 **반영 시점의 승인 파일 rules에 없는 것**뿐이다. 이미 승인된 FR은 건드리지 않는다.
- `answer`는 유효한 확정 초안이 1개 이상 있어야 한다. 0개면 그 질문은 `invalid`에 `NO_CONFIRMED_DRAFT`로 넣고 열린 채 둔다
  (규칙이 필요 없으면 사람이 '묻지 않기'를 고른다).
- rule 초안의 `pattern_id`가 반영 시점에 후보도 승인분도 아니면(장부가 바뀜) MANUAL 규칙으로 넣고 결과 `notes`에 `PATTERN_GONE`을 남긴다.
- `pattern_id`가 있는 초안은 stage·target을 쓰지 않는다(단계는 패턴 kind가 정한다). 화면은 그 두 칸을 잠근다.

### 8.3 지문 중복과 다시 열기 (R3) (qmodel)

- generate는 한 묶음 안에서 지문이 같은 질문은 앞의 것만 남긴다(`dup_in_set` 건수).
- `asked.json` 값은 `qmodel.asked_entry(q, set_id, at)`(question_id·set_id·at·refs). 닫힘 판정은 `qmodel.is_closed(asked, q)`:
  지문이 닫혀 있어도 general이 아닌 질문에 그때 없던 근거(새 FR·새 교정 사례)가 붙으면 다시 연다.

### 8.4 승인 화면의 갱신 사례 (R4)

- `labeling_review.data()`: `pending_rules`는 항상 빈 목록, `pending_examples`는 **update=True(승인 뒤 확정 라벨이 바뀐 사례)만** 둔다.
  화면은 '승인된 사례' 탭 안에 '갱신 대기' 묶음으로 보여 주고 그 ID에는 승인(갱신)·기각만 허용한다. 새 후보(update=False)는 질문 화면에서만 다룬다.

### 8.5 서버 보안 (R5)

- POST `/draft`도 `/inbox/engr_answers`와 같은 검사(Host·같은 출처 Origin·Content-Type application/json·크기 상한 8KB)를 거친다.
  한 번에 한 건만 처리한다(진행 중이면 409 `DRAFT_BUSY`). drafter 예외는 `{"ok": false, "code": <사유 코드>}`로만 돌려준다.
- 2절의 "check_send"는 "`labelbot.llm.post_json` 공용 경로(judge와 같은 길)"로 읽는다. labelbot보다 엄격한 URL 검사는 더하지 않는다.

### 8.6 초안 확정과 규칙 수 (R6)

- 초안 포함 체크는 고른 선택지의 초안에 기본 켜짐으로 둔다(사용자 결정 D4: 초안을 보고 '답 확정'을 누르는 것이 확정이다).
  대신 **답 확정 버튼 바로 위에 확정될 초안 전문을 보여 주고**, 버튼 문구에 확정 건수를 넣는다("초안 n개 확정").
- 화면은 확정 초안마다 `origin`을 넣는다: `llm`(LLM 초안 그대로) · `edited`(사람이 고침) · `human`(사람이 직접 씀).
  `qmodel.check_draft`는 origin을 버리므로 `answers.apply`가 따로 읽어(세 값 밖이면 `llm`) MANUAL 규칙과 이력에 남긴다.
- `apply` 결과에 단계별 켜진 유효 규칙 수 `enabled_rules: {"classify": n, "label": n}`와 상한 `cap`(pipeline.json
  `feedback.max_rules`, 기본 30, `labelbot_ws.read_config`)을 넣고, 넘으면 `notes`에 `RULES_OVER_CAP`을 넣는다
  (labelbot은 MANUAL을 앞에 두고 상한에서 자른다. 단계 판정은 labelbot.feedback._rules_for_run과 같다:
  REPLACE·REMOVE·ADD → classify, ANSWER·GEN_ANSWER → label, MANUAL은 target이 "label"이면 label 아니면 classify).

### 8.7 잠금·멱등·이력 (R7)

- generate: intake와 LLM 호출은 잠금 밖에서 한다. 저장할 때 `ledger.locked(d)` 안에서 `asked.json`·`questions.json`을 **다시 읽어**
  그사이 닫힌 질문을 빼고 쓴다. 잠금은 재진입이 안 되므로 잠금 안에서는 `lr.decide`·`ledger.intake`·`lr.write_candidates`를
  부르지 않고 `lr.apply_decision`·`lr.write_candidates_unlocked`만 쓴다.
- apply를 다시 돌리면 답한 질문이 이미 닫혀 `not_open`이 되므로 아무것도 다시 쓰지 않는다(answers.jsonl 중복 없음).
- 승인 파일을 바꾸기 직전에 이전 문서를 `QDIR/rules_history.jsonl`에 한 줄(`{"at", "set_id", "doc"}`)로 남긴다
  (승인 파일 `taxonomy/labeling_rules.json`은 git이 추적한다(2026-10-06 사용자 결정). 이력 파일은 커밋 사이의 변경을 되돌리는 데 쓴다).
- LLM 실패(`LLM_RESPONSE_INVALID`·`KEY_MISSING`·전송 실패 코드)면 기존 `questions.json`과 화면을 그대로 둔다.
  응답 전체가 JSON이 아니거나 `questions` 배열이 없을 때만 다시 부른다. 질문 하나가 틀리면 그 질문만 버린다(`dropped` 건수).

### 8.8 위치와 workspaces (R8) (qmodel)

- 질문 폴더는 `qmodel.qdir(ledger_dir)` = 장부 폴더의 형제 `questions`. 모든 명령이 `ledger.ledger_dir(paths.root, policy)`에서 구한다
  (테스트 임시 작업 폴더는 `<WS>/qa/questions`). 보드의 S7도 장부 폴더 형제에서 읽는다.
- `workspaces.scan()`의 기존 `state`(new·qa_done·applied)와 칸은 그대로 두고 `question_state`(no_review·new·asked)와
  `review_runs`(교정이 있는 라벨러 실행 수)를 더한다. `no_review`·`new` 판정은 장부가 아니라 작업 DB의 교정 유무
  (`labelbot_ws.correction_runs`)와 장부 sources의 sha를 함께 본다: 교정이 없으면 no_review, 교정이 있는데 장부에 그 작업
  폴더가 없거나 장부 sha가 questions.json `inputs`와 다르면 new, 같으면 asked.

### 8.9 그 밖

- `NO_REVIEW_INPUT`은 누적 장부 기준이다(교정 사례·재검토 요청·검수 동의어가 모두 0). 이월 질문이 있으면 그대로 둔다(0건 묶음으로 덮지 않는다).
- 보드 S7: `merge`가 묶음에 가장 늦은 S7 제안을 `g["s7"]`로 따로 들고, `draft`가 그 문장으로 칸을 채운다. value_add의 parent는 S7 값이 있으면 S7을 쓴다.
  `build(..., questions_dir=None)`·`collect(..., questions_dir=None)`.
- 계약 테스트: 루트 `tests/`에 `answers.apply`가 쓴 승인 파일을 `labelbot.feedback`의 읽기 함수로 읽어 MANUAL·FR 규칙이
  단계에 맞게 들어가는지 확인하는 테스트를 둔다(B 담당).
- 기존 테스트 수정 범위: `test_labeling_review.py`(후보 탭·pending 가정), `test_serve_workspaces.py`(새 칸 추가분만). 그 밖의 기존 테스트는 고치지 않는다.

## 9. 검증 반영 (2026-10-06, 설계·보안·코드 리뷰. 앞 절과 다르면 이 절을 따른다)

| # | 지적 | 반영 |
|---|---|---|
| V1 | taxonomy 초안에서 화면에 보이지 않는 칸(include·exclude 등)이 확정돼 보드까지 감 | `qmodel.TAX_FIELDS`가 종류별 허용 칸을 정한다. `check_draft`가 그 밖의 칸을 비우고, 화면은 이 표로 편집·미리보기·내보내기를 한다. overlap의 구분 기준은 memo에 쓴다 |
| V2 | 답한 질문이 "그때 인용하지 않은 근거"만으로 다시 열림(D9) | 다시 여는 조건은 "그때 없던 근거"다: 새 승인 대기 FR이 붙었거나, 닫은 시각보다 늦게 반영된 교정 사례가 붙었을 때. generate만 정하고 질문에 `reopened: true`를 적는다(`qmodel.is_closed`) |
| V3 | 다시 열린 질문에 예전 답 파일이 또 반영될 수 있음 | asked 값에 그 질문을 닫은 답 파일 해시(`answers_sha`)를 남기고, 같은 파일의 답은 `not_open`으로 건너뛴다 |
| V4 | 기각됐거나 후보 기준 아래인 FR을 pattern_id 초안이 되살림(8.2) | 지금 후보이거나 이미 승인된 FR만 승인한다. 그 밖은 MANUAL 규칙 + `PATTERN_GONE` |
| V5 | topic의 열쇠 칸이 비면 지문이 겹쳐 서로를 닫음 | `normalize_topic`이 필수 칸(`TOPIC_REQUIRED`)이 빈 topic을 general로 내린다 |
| V6 | LLM으로 보내는 범위가 문서보다 넓음(다른 작업 폴더 본문) | 다른 작업 폴더의 본문·메모는 그 폴더의 `llm.base_url`이 같을 때만 보낸다(`SOURCE_ENDPOINT_DIFFERS`). SKILL.md에 실제 범위를 적었다 |
| V7 | few-shot 사례가 모든 선택지에 기본 켜짐으로 붙어 의식 없이 승인됨 | 기본 켜짐은 두되 초안 패널에서 따로 묶어 보여 주고 버튼에 사례 수를 적는다. 규칙·taxonomy 초안이 1개 이상 있어야 확정된다(화면·apply 같은 기준) |
| V8 | Windows에서 포트 대체가 동작하지 않음(같은 포트에 서버 두 개) | 서버 클래스에 `allow_reuse_address = False` |
| V9 | 서버 응답에 클릭재킹·CSP 방어 없음 | `X-Frame-Options`·`Content-Security-Policy`·`X-Content-Type-Options` |
| V10 | 화면의 문장 검사가 qmodel과 달라 붙여 넣은 문장이 apply에서 빠짐 | 화면이 같은 금지 글자·길이를 미리 검사한다 |
| V11 | 그 밖: 이월만 남으면 set_id 유지, `--max 0`, 본문 누락 이중 집계, temperature 덮어쓰기, MANUAL 규칙 ID에 단계·대상 포함, `apply_decision` 묶어 부르기, 화면 실패를 `SCREEN_REBUILD_FAILED`로, 초안 다시 만들기가 고친 초안을 버리지 않게 | 반영 |

하지 않은 것과 이유:
- 300자 안의 지시문 차단(보안 L2): 문장 내용으로는 막을 수 없다. 사람이 확정 전에 전문을 보는 것과 labelbot 프롬프트의 "분류 체계 정의가 우선" 문구에 맡긴다.
- 답 파일의 confirmed를 화면에 있던 초안과 대조(보안 L3): 사람이 고친 초안은 원래와 달라 구분할 수 없다. 답 파일은 사람이 고른 것만 반영한다(SKILL 절차 5-2).
- `taxonomy/labeling_rules.json`의 git 추적 여부(보안 M3): 사용자가 **git 추적**으로 정했다(2026-10-06). 엔지니어가 확정한 판단 기준 문장이 들어가는 파일이므로 커밋 전에 사내 문서 인용이 없는지 본다(규칙 문장은 300자 지침이고 인용은 넣지 않는 것이 원칙이다).
- 저장 뒤 localStorage 비우기(보안 L4): 저장 뒤에도 남은 질문에 이어서 답하므로 진행 상황을 지우지 않는다.

재검증(세 리뷰 모두 승인) 뒤에 더 고친 것:
- 다시 열기의 기준 시각은 답을 반영한 시각이 아니라 그 질문을 만든 시각이다(질문의 `created_at` → asked의 `seen_at`).
  질문을 만든 뒤 답하기 전에 들어온 교정도 새 근거로 친다.
- 다시 열린 질문(`reopened`)은 지금 묶음에서 저장한 답 파일만 받는다(다른 묶음의 옛 답 파일은 `not_open`).
- 사람이 기각한 few-shot 사례는 답에 딸려 와도 승인하지 않는다(`EXAMPLE_REJECTED`).
- 다른 전송처 작업 폴더의 근거 인용·이유도 본문과 같은 조건으로 뺀다(`EVIDENCE_ENDPOINT_DIFFERS`·`EVIDENCE_WS_MISSING`).
- 보드는 S7 행도 `qmodel.TAX_FIELDS`의 칸만 읽는다. `open_matches`는 답·묻지 않음만 센다.

알려진 한계:
- 교정 사례가 새것인지는 labelbot의 반영 시각(`applied_at`)으로만 본다. 질문을 만들기 전에 검수했지만 그 뒤에야 장부에
  들어온(intake) 다른 작업 폴더의 사례는 새 근거로 치지 않는다. 그 사례가 새 규칙 후보(FR-)를 만들면 그때 다시 열린다.

## 10. 저장 즉시 반영 (사용자 결정, 2026-10-06. 앞 절과 다르면 이 절을 따른다)

사용자 요청: "답변 완료 · 저장을 누르면 그것이 트리거가 되어 답 반영까지 전체 마무리". 예전에는 저장 뒤 사람이 Claude에게
"질문 답변 끝났어"라고 알리고, Claude가 답 파일을 `AskUserQuestion`으로 확인받은 뒤 `questions apply`를 돌렸다.

- `questions serve`는 기본으로 반영 콜러블(`questions.make_applier`)을 서버에 넘긴다. 서버는 답 파일을 inbox에 쓴 직후
  같은 파일로 `answers.apply`를 부르고, taxonomy 제안이 새로 생기면 `taxonomy-board`(기본 대상, LLM 0회)를 다시 만든다.
  응답에는 건수·ID·코드만 담는다(`applied`, `apply`, `board`). 콘솔에는 `[questions] 반영: …`·JSON 줄·`[taxonomy-board] …` 줄이 나온다.
- 반영하면 서버는 0.5초 뒤 스스로 닫히고 종료 코드 0으로 끝난다(`[serve] 반영을 마쳐 질문 화면 서버를 닫았다`).
  스킬은 서버를 백그라운드로 띄우므로, 작업 종료 알림이 Claude를 깨워 마무리 보고(SKILL.md 절차 5-A)를 하게 한다.
- 반영이 실패하면(`LEDGER_LOCKED` 등) 답 파일은 저장된 채 서버를 열어 두고 응답에 `apply_code`만 준다. 사람이 다시 저장하면 다시 반영한다.
  반영을 마친 뒤 닫히는 사이에 온 저장은 `409 ALREADY_APPLIED`, 반영 중에 온 저장은 `409 APPLY_BUSY`로 거절한다.
- 화면: `GET /inbox/status`의 `apply`가 참이면 저장 전 확인 창에 "저장하고 바로 반영합니다"를 쓰고, 결과 창(답변 완료 · 반영함)에
  반영 건수·보드 건수·반영하지 못한 답 수를 보여 준다. 반영 결과는 건수·코드만 브라우저에 기억한다.
- 승인: 사람이 화면의 확인 창을 거쳐 누른 **답변 완료 · 저장**을 반영 승인으로 본다(2.절 "반영 전 AskUserQuestion"의 예외).
  서버 없이 저장한 답 파일(내려받기·텍스트 붙여넣기)과 `--no-apply`로 띄운 서버의 답 파일은 예전처럼 확인받고 `questions apply`로 반영한다.
