> 2026-10-06 이름 변경: Engr-bot → Domain-Engr-bot(`domain_engrbot`), code-bot → Code-Engr-bot(`code_engrbot`). 아래 본문은 이력이라 옛 이름을 그대로 둔다.

> 이력 문서다(2026-10-06 이전 개념). Engr-bot의 현재 개념은 `engrbot/docs/plan-question-loop.md`를 본다.

# 작업공간 전체 코드리뷰와 수정 계획 (2026-10-05)

- 대상 브랜치: `refactor/s4-cleanup` (커밋 안 된 수정 약 60개 파일 포함)
- 범위: `labelbot/` `engrbot/` `codebot/` `.claude/skills/` `tests/` `change-dashboard/`, 저장소 위생
- 방법: 영역별 리뷰 4개(labelbot · engrbot · codebot·skill·테스트 · 보안·DRM 전수 grep)를 병렬로 돌리고 전체 테스트를 실행했다. 코드는 고치지 않았다(읽기 전용).
- 종합 판정: **REQUEST CHANGES**. CLAUDE.md DRM 규칙 위반은 0건이다. 다만 테스트 20건이 빨간불이고, PoC 가드 제거 뒤처리가 덜 됐으며, 승인 파일을 원자적으로 쓰지 않는다.

## 0. 테스트 현황

`python -m pytest -q` 결과: **46 failed(서브테스트 포함, 테스트 케이스로는 20건) / 674 passed / 285 subtests passed** (4분 52초)

| 파일 | 실패 | 추정 원인 |
|---|---|---|
| `tests/test_defaults_taxonomy.py` | 1 | `taxonomy/taxonomy.xlsx`에 층 값 M4·Fx·Dx·Sx가 들어갔는데 defaults jsonl은 그대로다 |
| `tests/test_golden_run.py` | 3 | 위 변경과 CONTROL_O 집계 추가가 golden snapshot·SCHEMA.md·baseline_run.md에 반영되지 않았다 |
| `engrbot/tests/test_judge.py` | 9 | 새 층 값이 `L1_PATTERN_MISMATCH`로 걸려 clean fixture가 PASS를 내지 못한다. 일부는 `internal_host_suffixes`·send-gate 제거와 관련된 것으로 보인다 |
| `engrbot/tests/test_harness.py` | 2 | 같은 원인(L1 층 패턴)으로 recall·오탐 수가 바뀐다 |
| `engrbot/tests/test_queue_screen.py` | 3 | 같은 원인으로 verdict 분포가 바뀐다 |
| `engrbot/tests/test_integration.py` | 1 | 같은 원인 |
| `engrbot/tests/test_golden_feedback.py` | 1 | AUTO_FIX 대상 record 수가 2건에서 1건으로 바뀐다 |

> 원인 가설: `taxonomy.xlsx` 편집 하나가 연쇄로 퍼졌다. 그 xlsx를 사람이 고쳤는지, 코드가 다시 썼는지부터 확인해야 한다. 코드가 썼다면 CLAUDE.md의 "office 확장자로 쓰기 금지"를 어긴 것이다.

## 1. 발견 사항 (심각도순)

### P0 — 머지 전에 반드시

| ID | 위치 | 문제 | 실패 시나리오 |
|---|---|---|---|
| P0-1 | 위 표 | 테스트 20건 실패 | CI가 빨간불이라 회귀를 구분할 수 없다 |
| P0-2 | `git ls-files "parshing test files"` (커밋 `cb5616b`, `5cc6e88`, 원격 GitHub) | lot ID 형식의 원본 pptx 9건이 이력에 남아 있다. 작업 트리에서 삭제했지만 아직 커밋하지 않았다 | 사내 문서라면 원격을 볼 수 있는 사람은 누구나 받을 수 있다 (**더미인지 사람이 확인해야 한다**) |
| P0-3 | `engrbot/labeling_rules.py:316-317` `save_rules`, `decide`, `engrbot/labeling_review.py:197-265` | git이 추적하는 `taxonomy/labeling_rules.json`을 `open(w)`로 바로 덮어쓰고, load→수정→save 구간을 잠그지 않는다 | 쓰다가 중단되면 JSON이 잘려 `labelbot run`이 PipelineError로 멈춘다. `apply`와 `approve`를 동시에 돌리면 한쪽 승인이 사라진다 |
| P0-4 | `labelbot/review.py:485,512` vs `labelbot/finals.py:64-65`, `export.py` | `_apply_review`의 `qtext`에 승인 질문만 들어가서 Q-GEN 교정의 `question_hash`가 빈 문자열 해시가 된다 | 사람이 교정한 생성 질문 답이 export에서 늘 "재검수 필요"로 표시된다 |

### P1 — 이번 스프린트 안에

| ID | 위치 | 문제 |
|---|---|---|
| P1-1 | `labelbot/llm.py:43-87`, `engrbot/llm_http.py:58-65`, `selfcheck.py:123` | `check_send`를 지운 뒤 URL scheme·host 검사가 하나도 없다. `http://`로 설정하면 OpenAI·Supabase service_role 키가 평문으로 나간다. PoC 결정과 별개로 **https 강제는 최소한 되살린다** |
| P1-2 | `tests/test_slides.py:321-331`, `tests/test_pipeline.py:226`, 스냅샷 3종 | "더미가 아닌 파일도 전송된다"가 테스트 계약으로 굳었다. 사내 반입 때 가드 복원을 잊어도 CI는 초록이다 |
| P1-3 | `.claude/skills/BEOL-labeling/SKILL.md:40`, `BEOL-labeling-feedback/SKILL.md:238`, `README.md:101`, `labelbot/llm.py:1-4`, `feedback.py:430`, `docs/workflow.html:420` | 문서가 코드에 없는 `HOST_UNCERTAIN`·`check_send`·`EXTERNAL_NON_DUMMY` 차단을 안내한다 |
| P1-4 | 루트 `CLAUDE.md` | PoC 동안 송신 가드를 없앤 예외가 governing 문서에 적혀 있지 않다. PRD.md에만 있다 (CLAUDE.md가 우선한다) |
| P1-5 | `codebot/scan.py:310-317`, `codebot/cli.py:34-48` | 없는 경로나 .py가 아닌 대상을 받아도 APPROVE·exit 0을 낸다. `--paths`로 범위를 좁히면 C3 CLI 대조가 통째로 꺼진다 (재현함) |
| P1-6 | `labelbot/prompts.py:26-28` | 순차 `replace` 때문에 문서 제목·본문에 들어 있는 `{{...}}`나 `<!-- USER -->`가 템플릿처럼 펼쳐진다. system/user 경계가 깨진다 (prompt injection) |
| P1-7 | `labelbot/review.py:502-520` | 교정 값의 형식을 검증하지 않는다(축 허용 값, 질문 ID, 대조 질문 key). 잘못된 값이 export와 Supabase까지 그대로 간다 |
| P1-8 | `labelbot/screens/results.html:245` | answer 값이 escape 없이 `class` 속성에 들어간다(XSS). P1-7과 같이 막는다 |
| P1-9 | `engrbot/labeling_review.py:224-265`, `:309` | apply가 도중에 실패하면 반쯤만 반영된다. 그 뒤 digest가 바뀌어 같은 결정 파일로 다시 시도할 수 없다. OSError는 traceback으로 그대로 새어 나온다 |
| P1-10 | `engrbot/labeling_review.py:199-203→228` | digest를 확인한 뒤 반영하기 전에 intake가 돌면, 사람이 보지 않은 count·문장이 승인된다 |

### P2 — 다음 정리 주기

| ID | 위치 | 문제 |
|---|---|---|
| P2-1 | `engrbot/judge.py:399-406` | 재시도에 백오프가 없고 401·400까지 다시 보낸다. 429는 지수 백오프로만 재시도해야 한다 |
| P2-2 | `labelbot/ingest.py:103-104`, `util.py:67-72` | `.b64` 쓰기가 원자적이지 않다. 반쯤 쓴 파일이 남으면 그 파일은 영구 `B64_MISMATCH`가 된다 |
| P2-3 | `labelbot/questions.py:143` | 대조 질문을 요청하지 않았는데 `controls: null`이 오면 질문 생성 전체가 실패한다 |
| P2-4 | `engrbot/labeling_rules.py:56,251`, `defaults/policy.json:30` | `min_evidence=1` 때문에 근거 열이 없는 기존 장부의 후보가 알림 없이 0개가 된다 |
| P2-5 | `.gitignore` | `.omc/*`는 루트에만 걸려 `tests/.omc/`가 추적될 위험이 있다. `injested-file-list/`(파일명과 개인 절대경로), `dummy pprx files_2nd revised/`, `.claude/launch.json`(개인 경로)도 정리해야 한다 |
| P2-6 | `codebot/checks/c1_governing.py:130,219-239` | `"br"`·`read_bytes()`·`io.open`·`shutil.copy`로 C1 탐지를 피해 간다 |
| P2-7 | `codebot/checks/c3_workflow.py:131,267` | 하위 명령·옵션·스크립트 호출은 대조하지 않는다. 지금 불일치는 0건이다 |
| P2-8 | `tests/test_screens.py` `test_review_has_evidence` | JS 소스 문자열과 들여쓰기에 기대는 정규식으로 단언한다 |
| P2-9 | `engrbot/tests/test_labeling_review.py` | 빠진 테스트: `enable`, `edit` 단독, INVALID_TEXT, 반영 중 예외, 잠금, OSError. `test_uncertain_hosts_blocked`는 삭제됐다 |

### P3 — 여유 있을 때

- `labelbot/selfcheck.py:26-35`: 예외가 나면 sqlite 커넥션이 닫히지 않는다(`contextlib.closing`).
- `embed.py`·`vectorpush.py`·`slidepush.py`의 `blocked` 카운터가 늘 0이다. 지우거나 반입 때 되돌릴 표식을 단다.
- 데드 코드: `llm.DUMMY_HASHES_PATH`, `chat_json(probe=)`, `feedback._resolve_examples(chat=)`.
- `review.EVIDENCE_QUOTE_MIN = 2`는 너무 짧다. 4~6자로 올린다.
- N+1 조회: `review._file_ctx`, `recheck`·`file_of`, `finals.corrections()`.
- 승인 규칙 문장 안의 건수가 오래된 값으로 남는다(`labeling_rules.py:309-313`). CONFIRMED도 "근거 있음"으로 센다(`ledger.py:502`).
- `labeling_review.html:120`은 digest마다 localStorage를 따로 쓰므로 intake 뒤에는 검수 진행분이 사라진다.
- `change-dashboard/collect.py:118,141`이 프롬프트 원문을 산출물에 넣는다. 비밀을 마스킹해야 한다.
- `codebot` `_SKIP_DIRS`에 `workspaces`·`.omc`가 없다. C4는 `pytest.skip/xfail`을, C2는 `urllib.request` import를 놓친다.
- `engrbot/llm_http.py:60` 공백 오타, `test_judge.py:16` 가짜 키 접두어(비밀 스캐너 오탐).

### 확인 결과 문제없음

- DRM: 원본 `open(path,"rb")`는 `labelbot/ingest.py:44` 한 곳뿐이다. OOXML은 모두 `ZipFile(BytesIO)`로 연다.
- 금지 확장자 쓰기는 0건이다(`util.check_ext` 화이트리스트가 막는다). 본체의 서드파티 import도 0건이다.
- 로그에는 ID와 사유 코드만 남는다. SQL은 모두 바인딩한다. `shell=True`는 없다. `serve.py`는 127.0.0.1에만 bind하고 Host·Origin을 검사한다.
- SKILL.md가 언급하는 CLI 명령과 옵션은 모두 실제로 있다.

## 2. 수정 계획

### 단계 A — 초록 불 되돌리기 (P0-1, 예상 1~2시간)
1. `git diff --stat taxonomy/taxonomy.xlsx`와 수정 시각으로 누가 바꿨는지 확인한다. 코드가 썼다면 그 경로를 찾아 막는다.
2. 새 층 값(M4·Fx·Dx·Sx)을 정식으로 받아들이면 다음을 동기화한다.
   - taxonomy defaults jsonl(`tests/test_defaults_taxonomy.py`가 비교하는 파일)
   - engrbot L1 층 패턴(`L1_PATTERN_MISMATCH` 정의가 있는 정책·규칙)
   - golden 산출물: `tests/golden_run/` snapshot·SCHEMA.md·baseline_run.md를 **원인을 확인한 뒤** 다시 만든다. 무작정 갱신하지 않는다
   - engrbot fixture의 expected verdict
3. 남는 `test_judge` 실패는 `internal_host_suffixes` 제거와 맞춘다.
4. 완료 기준: `python -m pytest -q`가 0 failed다.

### 단계 B — 데이터 무결성 (P0-3, P0-4, P1-9, P1-10, P2-2, 예상 반나절)
1. `labeling_rules.save_rules`를 `ledger.replace_text`(tmp → `os.replace`)로 바꾼다.
2. `decide`를 "doc을 받아 바꾸기만 하는 순수 함수"와 "저장"으로 나눈다. `apply`는 메모리에서 approve·reject·edit·enable을 모두 적용한 뒤 한 번만 저장한다.
3. digest 확인부터 저장까지를 `ledger.locked(d)` 하나로 감싼다. 재진입 문제는 잠금을 쥔 채 호출하는 내부 함수로 푼다.
4. `labeling_review.main_cli`가 OSError를 사유 코드로 바꿔 알리게 한다.
5. `review._apply_review`의 `qtext`를 `questions.all_questions(con, tax)` 기준으로 만든다. Q-GEN 교정 회귀 테스트를 추가한다.
6. `ingest`의 `.b64`를 tmp에 쓴 뒤 replace한다. 기존 파일이 mismatch면 원본 bytes로 다시 쓴다.
7. 테스트: 반쯤 반영되는 경우, 동시 approve·apply, OSError, Q-GEN 교정 export 상태.

### 단계 C — 송신 안전과 문서 정합 (P1-1~P1-4, 예상 2~3시간)
1. `labelbot/llm.py`에 `_require_https(url)`를 추가한다(https가 아니거나 host가 비면 `INSECURE_URL`). opener는 HTTPSHandler만 남긴다. engrbot `llm_http`도 이 경로를 거친다. `test_uncertain_hosts_blocked`를 되살린다.
2. 루트 CLAUDE.md에 "PoC 예외: 사내/사외 송신 가드 해제(2026-10-05), 사내 반입 전 복원"을 한 줄 추가한다. 이 단계는 **사용자 승인이 필요하다**.
3. 반입 체크리스트를 만든다(PRD 또는 README). 가드 복원과 함께 `test_non_dummy_is_sent`를 `test_non_dummy_blocked`로 되돌리는 항목을 넣는다. PoC 플래그 상수를 두고 그 값이 False면 실패하는 테스트를 추가한다.
4. 문서를 실제 동작에 맞게 고친다: README:101, SKILL.md 2곳, `llm.py` docstring, `feedback.py:430`. workflow.html은 `/BEOL-labeling-workflow`로 다시 만든다.

### 단계 D — 입력 검증과 주입 방어 (P1-6~P1-8, P2-3, 예상 2시간)
1. `prompts.fill`: 먼저 `<!-- USER -->`로 나눈 뒤 `re.sub(r"\{\{(\w+)\}\}", ...)`로 한 번에 치환한다. `feedback._defang`은 필요 없어지므로 지운다. 문서 제목에 `{{chunk_text}}`를 넣은 테스트를 추가한다.
2. `review._apply_review`: 축 값은 `tax.axis(key).values`로, 질문 key는 `all_questions` ID로 거른다. 대조 질문 key는 거부한다. 걸러낸 건수는 `CORRECTION_UNKNOWN_TARGET`으로 센다.
3. `results.html:245`의 class 값을 화이트리스트(`{O,X,'N/A'}`)로 바꾼다.
4. `questions.py:143`: `want_ctl`이 비면 `controls`를 검사하지 않고 `or []`로 받는다.

### 단계 E — codebot 신뢰도 (P1-5, P2-6, P2-7, 예상 2시간)
1. `scan.build`가 찾지 못한 대상을 errors로 돌려준다. 색인한 파일이 0개면 COMMENT나 exit 2로 끝낸다.
2. C3 CLI 선언은 색인 범위와 상관없이 직접 읽는다.
3. C1: 모드는 `set(mode) >= {"r","b"}`로 비교한다. `read_bytes`·`io.open`·`shutil.copy*` 대상 확장자도 검사한다.
4. C3: AST에서 `add_argument`·`choices`를 모아 옵션과 하위 명령까지 대조한다.
5. `_SKIP_DIRS`에 `workspaces`, `.omc`를 추가한다.

### 단계 F — 저장소 위생 (P0-2, P2-5, 예상 30분, 사람 확인 필요)
1. **사람 확인**: `parshing test files/`의 이력 pptx 9건과 새 untracked pptx 6건이 더미인지 확인한다. 사내 문서라면 `git filter-repo`로 이력을 정리하고 force push한 뒤 원격이 private인지 확인한다(파괴적 작업이라 별도 승인이 필요하다).
2. `.gitignore`에 `**/.omc/*`, `!/.omc/skills/`, `injested-file-list/`, `.claude/launch.json`을 추가한다(또는 launch.json에서 상대경로를 쓴다). `tests/.omc/`는 지운다.
3. `dummy pprx files_2nd revised/`는 커밋할지 무시할지 정한다.

### 단계 G — 정리 (P2-1, P2-4, P2-8, P2-9, P3, 다음 주기)
- judge 재시도 정책(4xx는 바로 중단, 429·5xx·TIMEOUT은 지수 백오프+jitter)
- `min_evidence` 때문에 제외된 후보 수를 status에 보여 준다
- 화면 테스트를 DATA 단언 방식으로 옮긴다
- P3 목록을 deslop 한 번에 처리한다

## 3. 진행 순서와 검증

```
A(초록 불) → B(무결성) → C(송신·문서) → D(입력 검증) → E(codebot) → F(위생, 사람 확인 병행) → G
```

- 단계마다 `python -m pytest -q`가 0 failed여야 하고 `python -m codebot review`가 APPROVE여야 한다.
- B와 C가 끝나면 `/BEOL-labeling-code-bot`과 독립 verifier로 다시 검수한다.
- F-1과 C-2는 사용자 결정이 필요하다. 나머지는 바로 진행할 수 있다.
