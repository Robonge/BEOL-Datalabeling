> 2026-10-06 이름 변경: Engr-bot → Domain-Engr-bot(`domain_engrbot`), code-bot → Code-Engr-bot(`code_engrbot`). 아래 본문은 이력이라 옛 이름을 그대로 둔다.

> 이력 문서다(2026-10-06 이전 개념). Engr-bot의 현재 개념은 `engrbot/docs/plan-question-loop.md`를 본다.

# Engr-bot 교정 장부(ledger): 사람 검수 결과 → Engr-bot 입력

작성 2026-10-05 · autopilot spec·계획 · 사용자 결정 반영

## 0. 배경과 사용자 결정

지금은 사람의 검수 교정이 Engr-bot에 넘어가지 않는다. 교정은 각 작업 폴더 `work.sqlite`의 `corrections`에만 쌓인다. Engr-bot은 `run`을 돌릴 때만 그 표를 읽고, 그것도 `human_reviewed` 표시(대기열 제외)와 `golden add`(그 작업 폴더 안)에만 쓴다.

| 항목 | 결정 (2026-10-05) |
|---|---|
| 용도 | ① 누적 골든셋 자동 추가 ② 도메인 규칙(L4) 후보 생성 ③ L3b judge 판정 예시로 주입. "선례 검사 층(L7)"은 만들지 않는다 |
| 입력 출처 | 작업 폴더 `work.sqlite`를 직접 읽는다(읽기 전용, adapter 경계 안). `labelbot/feedback.py`·`workspaces/_feedback/`은 쓰지 않는다 |
| 전달 시점 | `/BEOL-labeling-feedback` 4단계 `apply` 직후 `python -m engrbot intake`를 자동으로 부른다. `engrbot run`도 시작할 때 그 작업 폴더를 intake한다 |
| 기존 labelbot 루프 | 그대로 두고 병행한다(`labelbot/feedback.py`, `prompts/*`, labelbot 코드는 이 작업에서 고치지 않는다) |

```
검수 화면 → labelbot apply → work.sqlite(corrections, revisit_requests, candidates[review])
   └─(자동) python -m engrbot intake --workspace <WS> ──→ 교정 장부 workspaces/_engrbot/ledger/
                                                          ├ golden.jsonl         → eval --golden ledger
                                                          ├ judge_examples.jsonl → L3b judge 프롬프트 예시
                                                          └ rule_candidates.json → L4 draft 규칙(판정 영향 없음) → 사람이 approved로 옮김
```

## 1. 지켜야 할 것

- 루트 `CLAUDE.md`: 표준 라이브러리만, Python 3.14. 쓰기 확장자는 `.json .jsonl .md .html .log .sqlite .b64`만 쓴다(`io.write_*`가 검사). 사람 입력은 `io.read_input`, 봇이 쓴 파일은 `io.read_own_*`으로 읽는다.
- Engr-bot에서 labelbot을 import할 수 있는 곳은 `engrbot/adapters/labelbot_ws.py`, `engrbot/io.py`, `engrbot/llm_http.py`뿐이다(codebot C3). labelbot DB를 SQL로 직접 읽는 코드는 adapter에만 둔다.
- `work.sqlite`는 `mode=ro`로만 연다(`labelbot_ws.connect_ro`).
- 콘솔, 로그, `manifest.json`, `report.md`에는 건수, ID, 사유 코드, 축·값 이름만 쓴다. 본문·인용·파일명·경로는 쓰지 않는다. 장부 파일 중 인용 발췌를 담는 것은 `golden.jsonl`과 `judge_examples.jsonl`뿐이다. 장부는 `workspaces/` 아래(gitignore)에 둔다.
- 사외 전송 안전장치: judge 호출에 다른 파일의 인용(예시)을 넣으면 그 예시 출처의 `file_id`도 `complete(messages, file_ids, …)`에 넣는다. 사외 호스트에서 허용되지 않는 출처의 예시는 보내기 전에 빼고 사유 코드로 센다. `labelbot/llm.py`·`tests/gold/dummy_hashes.jsonl`은 고치지 않는다.
- 봇은 어떤 규칙도 approved로 올리지 않는다. 후보는 별도 파일에 draft로만 쓰고, `engrbot/defaults/domain_rules.json`은 고치지 않는다.
- 장부가 비어 있으면 기존 동작과 출력이 바이트 단위로 같아야 한다. judge 메시지(캐시 키)와 L4 규칙 집합이 이에 해당한다. 기존 테스트는 모두 통과해야 한다.

## 2. 장부 위치

`ledger.ledger_dir(ws_root, policy)`:
1. `policy["ledger"]["dir"]`가 있으면 그 경로(상대 경로면 `<CODE_ROOT>/workspaces/` 기준)
2. 작업 폴더가 `<CODE_ROOT>/workspaces/` 아래이면 `<CODE_ROOT>/workspaces/_engrbot/ledger`
3. 그 밖(테스트의 임시 폴더 등)은 `<ws_root>/qa/ledger`. 테스트끼리 섞이지 않는다.

`_engrbot`은 `workspaces/261004_BEOL_*` glob에 걸리지 않는다. 장부 위치는 `<CODE_ROOT>/workspaces/` 또는 `<ws_root>/qa/` 안이어야 한다. 밖이면 `LEDGER_DIR_OUTSIDE_WORKSPACES`로 거부한다(동기화 폴더·공유 드라이브로 인용이 나가는 일을 막는다, 보안 검토 반영). 쓰기는 `.ledger.lock.json` 잠금(30초 대기, 600초 지나면 오래된 잠금)을 잡고, 파일마다 pid가 붙은 임시 파일에 쓴 뒤 `os.replace`로 바꾼다. 내용이 같으면 쓰지 않는다.

## 3. 장부 파일 (모두 정렬된 jsonl, `io.dumps` 한 줄)

| 파일 | 행 | 키·정렬 | 본문 |
|---|---|---|---|
| `sources.jsonl` | 작업 폴더 하나 | `source_ws` | 없음. `{source_ws, labeler_runs[], corrections_sha, taxonomy_version, intake_at, counts{cases, confirmed, corrected, golden, examples, synonyms, revisits}, skipped{코드:n}}` |
| `cases.jsonl` | (작업 폴더, 실행, 레코드, 필드) | `case_id` | 없음. `{case_id, source_ws, labeler_run_id, record_id, file_id, text_hash, field("axis:<축>"/"answer:<질문 ID>"), kind(corrected/confirmed), bot_value, human_value, gen_axis, gen_value, applied_at}` |
| `records.jsonl` | 사람이 본 내용 레코드 | `(record_id, text_hash)` | 없음. `{source_ws, labeler_run_id, record_id, file_id, text_hash, final_axes{축:[값]}, corrected_axes[], added{축:[값]}, removed{축:[값]}, title_hits{축:[값]}}` |
| `golden.jsonl` | (레코드, 작업 폴더) | `(golden_id, source_ws)` | 인용(확인 필드의 봇 인용). `golden.py`와 같은 형식 + `source_ws`, `labeler_run_id` |
| `judge_examples.jsonl` | (라벨, 인용, 작업 폴더) | `(example_id, source_ws)` | 인용(≤ `ledger.quote_chars`). `{example_id, source_ws, labeler_run_id, record_id, file_id, text_hash, kind(axis/answer), axis, value, qid, generated, answer, quote, verdict(supported/unsupported), origin(confirmed/corrected)}` |
| `synonyms.jsonl` | (alias, canonical) | `(alias, canonical)` | 용어만. `{alias, canonical, axis, count, sources[]}` |
| `revisits.jsonl` | (작업 폴더, 사유, 대상) | 정렬 | 없음. `{source_ws, reason, target_kind, target_key, count}`. 메모·값은 읽지 않는다 |
| `rule_candidates.json` | — | — | 없음. `domain_rules.validate`를 통과하는 `{"version": "ledger-<hash12>", "rules": [...]}`. 모두 `status: draft`, id는 `cand-` 접두 |
| `rule_candidates.md` | — | — | 없음. 후보 표(id, 유형, 축·값, 지지, 근거 교정 수, 옮기는 법) |

- `case_id = model.hash_obj([source_ws, labeler_run_id, record_id, field])[:16]`
- `golden_id = model.hash_obj([record_id, text_hash])[:32]`(`golden.py`와 같다).
- `example_id = model.hash_obj([kind, axis, value, qid, answer, text_hash, quote])[:16]`(사람 판정은 넣지 않는다).
- 장부 파일에는 작업 폴더마다 행을 다 남기고, 이긴 행은 읽을 때 고른다(`read_golden`: labeler_run_id가 큰 쪽, `read_examples`: labeler_run_id가 큰 쪽의 판정). 그래야 한 작업 폴더를 지우거나 다시 넣어도 다른 작업 폴더 몫이 사라지지 않고, 사람이 나중에 뒤집은 판정이 이긴다(검토 반영).

## 4. intake (`ledger.intake(ws_root, policy, labeler_run_id=None)`)

1. `labelbot_ws.correction_runs(ws_root)`로 `corrections`의 `review_run_id` 목록을 얻는다. 인자(`--run`)를 주면 그 실행만 보고, 장부에서도 그 (작업 폴더, 실행) 행만 바꾼다. 교정이 0건이면 그 작업 폴더의 장부 행을 지우고 `NO_CORRECTIONS`로 끝낸다.
2. 실행마다 `labelbot_ws.load(ws_root, run_id)`로 번들을 읽는다(레코드의 봇 라벨·인용, units의 text_hash·title, taxonomy 스냅샷, `meta["corrections"]`).
3. 레코드마다 교정 행을 분류한다.
   - `recheck=1` 이거나 행의 `text_hash`가 unit과 다르면 `SKIP_RECHECK`
   - `chunk/status` 행: `"confirmed"`이면 그 레코드의 모든 축·답 필드를 confirmed 사례로 만든다. 사람 값은 봇 값과 같다. `"undecidable_image"`이면 레코드 전체를 `SKIP_UNDECIDABLE_IMAGE`로 처리한다. 그 밖의 상태는 `SKIP_STATUS_OTHER`
   - `axis`/`answer` 행: 사람 값이 `판단 불가`(축 `["판단 불가"]`, 답 `"판단 불가"`)이면 `SKIP_UNDECIDABLE`. 사람 값과 봇 값이 같으면(축은 정렬 비교) confirmed. 다르면 corrected. 축의 사람 값이 taxonomy에 없는 값이고 예약어(`해당 없음`, `unknown`)도 아니면 `SKIP_VALUE_UNKNOWN`
   - 필드 교정은 같은 레코드의 confirmed보다 우선한다
   - `chunk_type`이 내용(schema `content_chunk_type`)이 아닌 레코드는 `SKIP_NOT_CONTENT`
   - Q-GEN 답(`tax.questions[qid].generated`)은 `gen_axis`/`gen_value`를 채운다. 목표를 못 찾으면 `SKIP_GEN_UNRESOLVED`
4. 산출물을 만든다(그 작업 폴더 몫만).
   - `golden`: 사례 전부로 labels를 만든다. evidence는 confirmed 필드의 봇 인용만 넣는다(corrected는 인용 없음. `golden.py` `_from_corrections`와 같다)
   - `records`: final_axes는 봇 축 값 위에 corrected 축을 덮은 것이다. added/removed는 실제 값(예약어 제외)의 차집합이다. title_hits는 added 값 중 unit title에 `llm.term_in`으로 나오는 값이다(제목 원문은 저장하지 않는다)
   - `judge_examples`
     - confirmed 축(status value, 인용 있음): 값마다 supported
     - corrected 축: 봇 인용이 있을 때 봇 값 중 사람이 뺀 실제 값은 unsupported, 남긴 실제 값은 supported
     - confirmed 답(O/X, 인용 있음): supported. corrected 답(봇 O/X → 사람 다른 값, 인용 있음): unsupported
     - Q-GEN은 `generated=true`, axis/value = 목표로 둔다
     - 인용이 `quote_chars`(기본 300)를 넘으면 `SKIP_LONG_QUOTE`로 예시를 만들지 않는다(잘린 인용은 판정 뜻이 바뀐다)
     - 승인 질문 답은 교정 때의 `question_hash`가 지금 질문 문장의 해시와 다르면 예시를 만들지 않는다(`SKIP_QUESTION_CHANGED`)
   - `synonyms`: `labelbot_ws.review_synonyms(ws_root)`가 `candidates`의 `source='review'`, `kind='synonym'` 행에서 `content`를 `alias|canonical`로 나눈 값을 준다. `axis`는 canonical이 정확히 한 축의 값이면 그 축, 아니면 `""`
   - `revisits`: `labelbot_ws.revisit_counts(ws_root)`가 `revisit_requests`의 `(reason, target_kind, target_key)`별 COUNT를 준다. 표가 없으면 빈 목록. memo와 값 열은 읽지 않는다
5. 장부의 그 `source_ws` 행을 모두 새 행으로 바꾸고(다른 작업 폴더 행은 그대로), golden·examples·synonyms를 합친 뒤 후보를 다시 만든다(§5). `sources.jsonl`에 기록한다.
6. 반환 dict: `{"source_ws", "runs", "cases", "confirmed", "corrected", "golden", "examples", "synonyms", "revisits", "skipped": {코드: n}, "changed": bool, "totals": status()}`.

`corrections_sha`는 교정 행(정렬, `applied_at` 포함)의 해시다. 같은 입력으로 다시 돌리면 장부 파일이 바이트 단위로 같다. `intake_at`은 corrections_sha가 바뀔 때만 갱신한다.

## 5. 규칙 후보 (`ledger.build_candidates(ledger_dir, policy, tax_values=None)`) — LLM 0회

입력은 `records.jsonl`(같은 `(record_id, text_hash)`는 labeler_run_id가 큰 것 하나)과 `synonyms.jsonl`이다. 설정은 `policy["ledger"]["candidates"]`에서 읽는다.

| 유형 | 조건 | 규칙 |
|---|---|---|
| axis_combo expect | A≠B, 실제 값 v. `R = {final A ∋ v}`가 `min_support`(3) 이상이고, `R` 중 `axis:B`가 교정된 레코드가 `min_corrected`(1) 이상이다. `W = {B의 실제 값 w : |R ∩ B∋w| / |R| ≥ min_confidence(0.9)}`가 비어 있지 않다 | `when {A:[v]} expect {B: sorted(W)}`, severity major |
| axis_combo forbid | `R` 안에서 봇이 B에 x를 붙였고 사람이 뺀(removed) 레코드가 `min_forbid`(2) 이상이고, `R` 안에 final B ∋ x인 레코드가 0이며, `R` 밖에는 final B ∋ x인 레코드가 1건 이상 있다(없으면 A=v 조건이 무의미한 무조건 규칙이다) | `when {A:[v]} forbid {B:[x]}`, severity major |
| title_label | 축 A에서 `title_hits`에 나온 값들의 레코드 수 합이 `min_title`(2) 이상이다 | 패턴 `(?<![A-Za-z0-9])(<값들 re.escape, 길이 내림차순 \|>)(?![A-Za-z0-9])`, axis A, severity minor |
| synonym_suggest | 축 A로 해석된 검수 등록 동의어가 1건 이상이다 | `axis A`, severity minor |

- axis_combo(expect·forbid)는 근거 레코드의 서로 다른 파일 수가 `min_files`(2) 이상이어야 한다. 한 파일의 슬라이드끼리는 라벨이 같이 움직여 우연한 동시 출현이 규칙처럼 보이기 때문이다(실데이터 1차 시험에서 확인, 2026-10-05).
- 정렬: 작업 폴더 수 내림차순 → 지지 수 내림차순 → 유형 순서(expect, forbid, title, synonym) → id. 최대 `max_rules`(30)개. 유형 순서를 먼저 두면 expect가 상한을 다 채운다.
- id: `cand-<유형 약어>-<hash_obj(규칙 핵심)[:8]>`.
- note(한국어 한 문장, 300자 이내): 지지 n/m건(작업 폴더 k곳), 근거 교정 c건, "승인하려면 engrbot/defaults/domain_rules.json에 옮기고 status를 approved로 바꾼다".
- 결과 문서는 `domain_rules.validate`를 반드시 통과해야 한다(테스트로 확인).

## 6. 소비

### 6-1. judge 예시 (L3b)

- `runner.make_judge`가 judge를 만든 뒤, `policy.ledger.enabled`이고 `judge_examples.enabled`이고 paths가 있으면 `j.set_examples(ledger.read_examples(dir))`를 부른다.
- `Judge.set_examples(rows)`: 키별 색인을 만든다.
  - 축: `("axis", axis, value)`
  - 승인 질문 답: `("answer", qid, answer)`
  - Q-GEN 답: `("gen", axis, value, answer)`
- 선택 `Judge.select_examples(items, target)`
  - 항목마다 같은 키의 예시 중 `file_id == target.file_id` 또는 `text_hash == 대상 unit text_hash`이면 뺀다(`SAME_SOURCE`).
  - `self.llm.allows(file_id)`가 False이면 뺀다(`EXTERNAL_BLOCKED`).
  - unsupported를 먼저, 그다음 supported를 example_id 순으로 고른다. 항목당 `k_per_item`(2)개, 호출당 `max_per_call`(6)개, 예시 중복은 없앤다.
- 메시지: 예시가 있으면 user 메시지 맨 앞에 아래 블록과 빈 줄을 붙인다. 예시가 없으면 메시지가 지금과 같다(템플릿 `qa_judge.md`는 고치지 않는다).
  ```
  ## 사람 검수 사례 (판정 참고용. 판정 대상이 아니며 응답과 reason에 사례 인용을 옮기지 않는다)
  - 라벨: 축 "<축>"의 값 "<값>"
    인용문(JSON 문자열): "<줄바꿈을 공백으로 바꾼 인용, JSON escape>"
    사람 판정: unsupported(사람이 이 라벨을 뺐다) | supported(사람이 이 라벨을 확인했다)
  ```
  - 승인 질문: `라벨: 질문 "<현재 taxonomy 문장 또는 qid>"의 답 "<O|X>"`
  - Q-GEN: `라벨: 검증 질문의 답 "<O|X>"(인용문이 축 "<축>"의 값 "<값>"를 뒷받침한다|반박한다)`
  - 예시 인용은 다른 문서 내용이므로 한 줄짜리 JSON 문자열로 넣어 항목·헤더 구조를 만들 수 없게 한다(보안 검토 반영).
- 전송: `self.llm.complete(messages, [target.file_id] + 예시 file_id(정렬, 중복 제거), hint)`. hint는 바꾸지 않는다(mock은 items만 본다).
- `JudgeLLM.allows(file_id)`는 기본 False다(fail-closed). `MockJudgeLLM`만 True다. `OpenAICompatJudgeLLM.allows`는 `lb_llm.check_send(self.url, [file_id], suffixes)`가 통과하면 True이고, `SendBlocked`이면 False다.
- 통계 `Judge.example_stats = {"loaded", "calls_with_examples", "used", "excluded_same_source", "excluded_external"}`(잠금으로 보호). runner의 `_judge_stats`가 `manifest["judge"]["examples"]`에 넣는다.

### 6-2. L4 후보 규칙

- `checks/l4_domain.rules_for(policy, ledger_dir=None)`: 기본 규칙 파일에, `(policy.get("l4") or {}).get("include_candidates", True)`이고 `<ledger_dir>/rule_candidates.json`이 있으면 후보 규칙을 더한다.
  - 후보는 `status`를 강제로 `draft`로 둔다.
  - id가 기본 규칙과 겹치면 후보 쪽을 뺀다.
  - 후보 파일은 봇이 쓴 파일이므로 `io.read_own_json`으로 읽고 `domain_rules.validate`로 검증한다. 실패하면 후보만 버리고 기본 규칙은 그대로 쓴다.
  - 캐시 키는 두 파일의 (경로, mtime, 크기)다.
- `DomainRuleCheck.run`은 `getattr(ctx, "ledger_dir", None)`을 넘긴다. runner의 `execute`가 `ctx.ledger_dir`를 설정한다.
- draft 후보는 `L4_RULE_DRAFT_HIT`(info)만 내므로 판정에 영향이 없다. 리포트 L4 절의 draft 적중 건수가 승인 판단의 근거가 된다.

### 6-3. 골든셋

- `python -m engrbot eval --workspace <WS> --golden ledger`: `ledger`이면 장부의 `golden.jsonl`을 쓴다. `golden.to_bundle`은 그 작업 폴더 번들에 있는 레코드만 쓴다.
- `golden add`(작업 폴더 골든셋)는 그대로다.

### 6-4. run과 리포트

- `runner.run`에서 번들을 labelbot 작업 폴더에서 읽는 경우(`bundle_dir` 없음)이고 `ledger.enabled`, `ledger.auto_intake`가 켜져 있으면, `load_bundle` 전에 `ledger.intake(paths.root, pol)`를 부른다.
  - 실패(`LedgerError`·`BundleError`)는 run을 멈추지 않는다. 로그에 사유 코드를 남기고 `manifest["ledger"]["intake_error"]`에 적는다.
- `manifest["ledger"] = {"dir": "<부모 이름>/<이름>", "intake": intake 반환의 건수 부분 또는 None, "intake_error": 코드 또는 None, "examples_loaded": n, "examples_sha": 로드한 예시 ID 해시, "candidates_loaded": 실제로 L4에 들어간 후보 수, "candidates_version": 후보 문서 version, "golden_total": n}`. 장부는 작업 폴더를 가로질러 공유되므로, 같은 reviewer 버전이라도 예시·후보 집합이 바뀔 수 있다. 이 두 해시로 판정 변화의 원인을 추적한다(경로 전체를 쓰지 않는다)
- `report.md`의 요약 절에 manifest ledger가 있을 때만 한 줄을 넣는다. 없으면 리포트가 지금과 같다.
  `- 교정 장부: 이번 intake 사례 n(교정 n, 확인 n), 누적 골든 n, judge 예시 사용 n(제외 n), L4 후보 n`

## 7. 정책 (`engrbot/defaults/policy.json`에 추가)

```json
"ledger": {"enabled": true, "dir": null, "auto_intake": true, "quote_chars": 300,
           "judge_examples": {"enabled": true, "k_per_item": 2, "max_per_call": 6},
           "candidates": {"min_support": 3, "min_files": 2, "min_confidence": 0.9, "min_corrected": 1, "min_forbid": 2,
                          "min_title": 2, "max_rules": 30}}
```
- `("ledger", "dir")`는 NULLABLE이다.
- RATIO_KEYS에 `("ledger","candidates","min_confidence")`를 넣는다.
- MIN_ONE에 `quote_chars`, `k_per_item`, `max_per_call`, `min_support`, `min_files`, `min_corrected`, `min_forbid`, `min_title`, `max_rules`를 넣는다.

## 8. CLI

- `python -m engrbot intake --workspace <WS> [--run <라벨러 실행 ID>]` (LLM 0회)
  ```
  [intake] 교정 n건 → 사례 n(교정 n, 확인 n), 골든 n, judge 예시 n, 동의어 n, 재검토 n / 건너뜀 CODE n, …
  [ledger] 누적 작업 폴더 n, 사례 n, 골든 n, judge 예시 n, L4 후보 n → _engrbot/ledger
  ```
- `python -m engrbot ledger --workspace <WS> status|rebuild`: status는 `[ledger] …` 줄 하나와 sources별 건수 줄을 낸다. rebuild는 후보를 다시 만든다.
- 오류(`LedgerError`)는 `[오류] <코드>`로 출력하고 종료 코드 1을 돌려준다.

## 9. 작업 패키지

| WP | 파일(소유) | 내용 |
|---|---|---|
| A 장부·intake | `engrbot/ledger.py`(새), `engrbot/adapters/labelbot_ws.py`(helper 3개), `engrbot/cli.py`, `engrbot/runner.py`, `engrbot/policy.py`, `engrbot/defaults/policy.json`, `engrbot/tests/test_ledger.py`(새) | §2~5, §6-3, §6-4의 run·manifest, §7, §8 |
| B 소비 | `engrbot/judge.py`, `engrbot/llm.py`, `engrbot/llm_http.py`, `engrbot/checks/l4_domain.py`, `engrbot/report.py`, `engrbot/tests/test_ledger_consume.py`(새) | §6-1, §6-2, §6-4의 리포트 줄 |
| C 문서 | `.claude/skills/BEOL-labeling-Engr-bot/SKILL.md`, `.claude/skills/BEOL-labeling-feedback/SKILL.md`(4단계 뒤 한 단계 + 보고 줄), `engrbot/engrbot_plan.md`(변경 이력 한 줄) | lead가 한다 |

공용 인터페이스(A가 정의하고 B가 쓴다):
```python
# engrbot/ledger.py
class LedgerError(Exception): reason_code
def ledger_dir(ws_root, policy) -> str
def golden_path(d) -> str; def examples_path(d) -> str; def candidates_path(d) -> str
def read_examples(d) -> list[dict]                 # judge_examples.jsonl 행(없으면 [])
def intake(ws_root, policy, labeler_run_id=None) -> dict
def build_candidates(d, policy) -> dict            # 후보 문서
def status(d) -> dict
# engrbot/judge.py (B)
Judge.set_examples(rows); Judge.example_stats: dict
# engrbot/checks/l4_domain.py (B)
def rules_for(policy, ledger_dir=None) -> list
# runner (A): ctx.ledger_dir = ledger.ledger_dir(paths.root, pol) if paths else None
```

## 10. 수용 기준

1. `python -m unittest discover -s engrbot/tests -t .`가 기존 243개를 포함해 모두 통과한다. `tests/`와 `codebot/tests`에는 새로운 실패가 없다(기준선: `tests/test_slides.py` 3건은 기존 실패).
2. `python -m codebot review`에서 새 critical·major가 0건이다(기준선: `labelbot/cdp.py` major 2).
3. 장부가 비어 있으면 judge 메시지와 L4 규칙 목록이 지금과 같다(테스트로 확인).
4. intake는 멱등이다. 같은 입력으로 다시 돌리면 장부 파일 바이트가 같다. 다른 작업 폴더 행은 바뀌지 않는다. 교정을 바꿔 다시 apply하면 그 작업 폴더 행만 바뀐다.
5. 건너뜀 코드 각각(RECHECK, UNDECIDABLE, UNDECIDABLE_IMAGE, NOT_CONTENT, VALUE_UNKNOWN, LONG_QUOTE)이 테스트된다.
6. 후보 문서가 `domain_rules.validate`를 통과하고 결정적이다. 후보는 `L4_RULE_DRAFT_HIT`만 내고 판정을 바꾸지 않는다.
7. judge 예시는 같은 파일·같은 본문에서는 빠지고, `allows`가 False이면 빠진다. 호출 `file_ids`에 예시 출처가 들어 있다.
8. 실제 데이터: 작업 폴더 6곳을 intake하고 034316에서 `engrbot run`을 돌려, manifest·report에 장부 줄이 나오고 L4 후보 draft 적중이 집계되는지 확인한다(건수만 보고).

## 11. 검토 반영 이력 (2026-10-05)

- 실데이터 1차 시험: L4 후보가 한 파일 슬라이드끼리의 동시 출현에 끌려 30개 상한을 expect로만 채웠다 → `min_files`, forbid의 R 밖 출현 조건, 작업 폴더 수 우선 정렬을 더했다.
- Phase-4 검토(architect·security·code) 반영: 작업 폴더별 행 보존과 읽을 때 고르기, `--run`은 그 실행 행만 교체, 장부 위치 제한, 예시 인용 JSON 한 줄 렌더, `allows` 기본 거부, auto-intake 예외 범위 확대, 장부 쓰기 잠금, 승인 질문 문장 변경 시 예시 제외, manifest에 `examples_sha`·`candidates_version`.
