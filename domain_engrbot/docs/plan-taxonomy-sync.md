> 2026-10-06 이름 변경: Engr-bot → Domain-Engr-bot(`domain_engrbot`), code-bot → Code-Engr-bot(`code_engrbot`). 아래 본문은 이력이라 옛 이름을 그대로 둔다.

# engrbot ↔ 최신 taxonomy.xlsx 동기화 계획

- 상태: **완료** (2026-10-05 실행. engrbot 219개 OK, verifier PASS. labelbot `test_serve`/`test_slides` 4개 실패는 이번 변경과 무관하며 다른 세션이 작업 중인 영역)
- 작성: 2026-10-05
- 출처: "Taxonomy helper" 세션의 engrbot 수정 요청 중 **2번(새 taxonomy에 맞게 engrbot 테스트 데이터를 다시 맞춤)**을 채택하고, 그 위에 "엑셀을 고칠 때마다 engrbot이 최신 `taxonomy/taxonomy.xlsx`를 본다"는 요구를 더했다.
- 실행 예산: **10분 이내**(수정 파일 1~2개, 테스트 1회 약 16초).

## 1. 현재 상태(사실)

| 경로 | taxonomy를 어디서 읽나 | 최신 xlsx를 따라가나 |
|---|---|---|
| 런타임(engrbot run) | `engrbot/adapters/labelbot_ws.py:88-92` `taxonomy_path()` → `pipeline.json`의 `taxonomy_path` | 따라간다. `init_workspace.py:29`가 `taxonomy_path`를 저장소 `taxonomy/taxonomy.xlsx` 절대경로로 쓰고, 어댑터는 `labelbot.ingest.read_input` → `labelbot.taxonomy.parse_bytes` → `snapshot()`(`labelbot_ws.py:95-115`)으로 매번 새로 읽는다. |
| 테스트(fixture) | `engrbot/tests/fixturegen.py:18,47-79` → `tests/fixtures/default_taxonomy_rows.jsonl` | 간접적이다. jsonl을 누가 다시 만들어야 반영되고, 스냅샷 조립 코드도 런타임 `snapshot()`과 따로 있다. |

**8개 테스트가 실패하는 원인**(2026-10-05 실행, 215개 중 8개 FAIL, 15.7초):
- 모두 같은 깨끗한 fixture 레코드 1건(`…:ppt/slides/slide8.xml`)에서 `L2_UNKNOWN_OVERUSE`가 나서 생긴다. evidence는 `{"unknown": 1, "denominator": 2}`다.
- 규칙(`engrbot/checks/l2_taxonomy.py:74-83`): 분류 축 중 na를 뺀 분모에서 unknown 비율이 `policy.json` `l2.unknown_ratio_major`(0.5) 이상이면 major다.
- 생성기(`fixturegen.py:160-170`)는 슬라이드마다 unknown을 1개까지만(`unknown_budget = 1`) 허용하지만, **비율**은 보지 않는다. 그래서 na가 많이 뽑힌 슬라이드에서는 1/2 = 0.5가 된다. 값 개수가 바뀌면 난수 순서가 밀려 이런 슬라이드가 우연히 생긴다.
- 실패 테스트: `test_harness`(2), `test_integration.test_clean_batch_all_pass`, `test_judge`(2), `test_queue_screen`(3). 모두 "깨끗한 fixture는 전부 PASS"라는 불변식을 쓴다. 기대 건수가 하드코딩된 것은 아니다.

**taxonomy를 바꾸면 깨질 수 있는 곳(잠재)**:
- `fixturegen.py:23-34` `AXIS_TEMPLATES`가 축 이름으로 문장 틀을 고정한다. xlsx에 새 축이 생기면 `KeyError`가 난다.
- `fixturegen.py:160` 루프가 비활성 축(값 0개)까지 돌기 때문에, 비활성 축이 생기면 `rng.sample([], 1)`에서 실패한다.
- `engrbot/tests/test_layers.py:216-237`이 `EM`, `Reliability`, `M1` 같은 값을 하드코딩한다. xlsx에서 이 값을 지우거나 이름을 바꾸면 실패한다. 이 실패는 정당한 신호이므로 계획에서는 그대로 둔다.

## 2. 요구사항

1. 새 taxonomy(현재 xlsx, 축 10개, 값 61개)로 engrbot 테스트 215개가 모두 통과한다.
2. engrbot 테스트는 jsonl 사본이 아니라 **`taxonomy/taxonomy.xlsx`를 직접**, 런타임과 **같은 코드 경로**(`labelbot_ws.load_taxonomy`·`snapshot`)로 읽는다. xlsx를 저장하면 다음 테스트 실행부터 바로 반영된다.
3. 깨끗한 fixture는 taxonomy 내용과 상관없이 L2 규칙을 만족하도록 **생성 단계에서 보장**한다. 시드 운에 맡기지 않는다.
4. 축 추가·비활성화·값 증감에도 fixture 생성기가 죽지 않는다.
5. CLAUDE.md DRM 규칙을 지킨다. xlsx는 `labelbot.ingest.read_input`으로만 열고 경로 기반 파서는 쓰지 않는다. 표준 라이브러리만 쓴다.
6. 다른 세션이 손대는 중인 파일(`engrbot/cli.py`, `engrbot/io.py`, `engrbot/tests/test_adapter.py`에 커밋되지 않은 변경이 있다)은 건드리지 않는다.

## 3. 구현 단계

### 단계 1 — fixture가 최신 xlsx를 런타임과 같은 경로로 읽기 (`engrbot/tests/fixturegen.py`)
- `TAXONOMY_ROWS`(jsonl) 대신 `TAXONOMY_XLSX = REPO_ROOT/taxonomy/taxonomy.xlsx`를 쓴다.
- `taxonomy_snapshot(path=TAXONOMY_XLSX)`를 `labelbot_ws.snapshot(labelbot_ws.load_taxonomy(dir, {"taxonomy_path": path}))`로 바꾼다. 결과 dict 모양(`version`, `axes`, `questions`, `synonyms`, `reserved`)은 지금과 같다(`labelbot_ws.py:95-115`와 `fixturegen.py:68-79`를 대조해 확인했다).
- 모듈 docstring 첫 줄의 "jsonl에서 만든다(xlsx를 읽지 않는다)"를 "저장소 taxonomy/taxonomy.xlsx를 어댑터와 같은 경로로 읽는다"로 고친다.
- 호출부(`test_layers.py:11`, `fixturegen.generate`)는 인자 없이 부르므로 고칠 필요가 없다.

### 단계 2 — 깨끗한 레코드의 L2 불변식을 생성 단계에서 보장 (`fixturegen._content_slide`)
- 활성 축이고 값이 1개 이상인 축만 돈다(`ax["active"] and ax["values"]`).
- unknown 판정은 루프 안에서 확정하지 않고 후보로만 둔다. 루프가 끝난 뒤 분류 축(`kind == "분류"`) 기준으로 `unknown / (분류 축 수 − na 수)`를 계산한다. 임계값은 `engrbot/defaults/policy.json`의 `l2.unknown_ratio_major`를 읽는다. 비율이 임계 이상이면 unknown 후보를 일반 값 축으로 바꾼다(같은 `rng`로 값을 고르고 문장을 넣는다. 시드가 같으면 결과도 같다).
- 분류 축이 모두 na가 되는 경우(`L2_ALL_NOT_APPLICABLE`)도 같은 후처리에서 막는다. 첫 분류 축을 값 축으로 바꾼다.
- 결과: 깨끗한 fixture에서는 taxonomy와 상관없이 `L2_UNKNOWN_OVERUSE`·`L2_ALL_NOT_APPLICABLE`이 나오지 않는다.

### 단계 3 — 새 축에 대비한 기본 문장 틀
- `AXIS_TEMPLATES.get(name)`이 없으면 `GENERIC_TEMPLATES`(예: `"{v} 항목 기준으로 검토 진행"`, `"{v} 관련 결과 정리"`)를 쓴다.
- 기본 틀 문장이 동의어 치환에 걸리지 않는지(`synt.apply(틀) == 틀`)는 생성 시점에 확인한다. 걸리는 틀은 후보에서 뺀다.

### 단계 4 — 회귀 테스트 1개 추가 (`engrbot/tests/test_core.py` 또는 새 `test_fixture_taxonomy.py`)
- `fixturegen.taxonomy_snapshot()["version"]`이 어댑터로 바로 읽은 `taxonomy/taxonomy.xlsx`의 `sheet_hashes["taxonomy"]`와 같다. 이것으로 "engrbot 테스트가 최신 xlsx를 본다"를 고정한다.
- 활성 축 이름 하나를 가짜로 추가한 스냅샷으로 `generate(n_files=2)`가 예외 없이 돌고, 깨끗한 레코드에 L2 이슈가 없다(기본 틀 경로와 후처리를 검증한다).

### 단계 5 — 문서 한 줄
- `engrbot/engrbot_plan.md`의 fixture 설명에서 jsonl을 언급하는 곳이 있으면 xlsx로 고친다. 이 파일은 다른 세션이 수정 중이므로 **해당 줄만** 고친다.

## 4. 수용 기준(검증 가능)

- [ ] `python -m unittest discover -s engrbot/tests -t .` → `Ran 216+ tests … OK` (현재 FAILED 8)
- [ ] `python -m unittest discover -s tests -t .` → labelbot 214개 OK 유지(jsonl과 xlsx 회귀 테스트는 그대로 둔다)
- [ ] `grep -n "default_taxonomy_rows" engrbot/` → 결과 0줄
- [ ] `grep -nE "load_workbook|Presentation\(|zipfile.ZipFile\([^i]" engrbot/tests/fixturegen.py` → 0줄(DRM 규칙)
- [ ] 같은 시드로 `fixturegen.generate()`를 두 번 부르면 `bundle_hash()`가 같다(결정성)
- [ ] 수정 파일이 `engrbot/tests/fixturegen.py`, 새 테스트 1개, (선택) `engrbot/engrbot_plan.md` 1줄에 그친다. `git diff --stat`으로 확인한다.
- [ ] 수동 확인: xlsx에 값 1개를 임시로 추가하고 engrbot 테스트를 돌리면 OK, 되돌리고 돌려도 OK다(선택, 1분 이내).

## 5. 위험과 대응

| 위험 | 대응 |
|---|---|
| fixture 결과가 바뀌어 `test_queue_screen`의 `10 + 20` 같은 건수 가정이 깨진다 | 그 숫자는 reviewfix 시나리오의 역할 수와 표본 크기다. 깨끗한 레코드가 모두 PASS면 유지된다. 깨지면 기대값을 고치지 않고 생성기 쪽을 고친다. |
| xlsx를 직접 읽으면서 labelbot 파서 경고·오류가 engrbot 테스트로 번진다 | 맞는 동작이다. 잘못된 xlsx는 labelbot `test_defaults_taxonomy`에서도 실패한다. 오류는 `ADAPTER_TAXONOMY_INVALID`로 나타난다. |
| `test_layers.py`에 하드코딩된 값(EM, Reliability, M1)이 xlsx에서 빠진다 | 이번 범위 밖이다. 실패 메시지가 바로 원인을 가리키므로 그대로 둔다. 후속 과제로 남긴다. |
| 다른 세션("검수 화면 다중 슬라이드 표시", 실행 중)과 같은 파일을 동시에 고친다 | 수정 대상은 `fixturegen.py`와 새 테스트 파일뿐이다. 실행 직전에 `git status --short engrbot/tests`로 `fixturegen.py`가 깨끗한지 확인한다. |
| unknown 후보를 값으로 바꾸면서 난수 소비가 늘어 다른 슬라이드 내용이 바뀐다 | 시드가 같으면 결정적이고, 테스트는 불변식만 본다. 커밋된 해시 기대값은 없다(`engrbot/tests`에 데이터 파일이 없다). |

## 6. 검증 순서(실행 시간 약 3분)

1. `git status --short engrbot/tests` — `fixturegen.py`가 다른 세션 때문에 수정 중이 아닌지 확인한다.
2. 단계 1~4를 적용한다.
3. engrbot 테스트 → labelbot 테스트 순서로 실행한다(각 약 16초).
4. 수용 기준의 grep 2줄과 `git diff --stat`을 확인한다.
5. verifier 패스로 diff를 검토한다(작성과 검토는 다른 패스).

## 7. 결정 기록

- **결정**: 요청 2번을 채택한다(engrbot 테스트 데이터를 새 taxonomy에 맞춘다). 방식은 고정 사본이 아니라 "최신 xlsx를 직접 읽고 + 생성기가 불변식을 보장"이다.
- **고려한 대안**: (1) engrbot 전용 taxonomy 사본 고정은 사용자가 고르지 않았고 최신 xlsx를 따라가지 못한다. (2) 시드만 바꿔 통과시키면 엑셀을 고칠 때마다 같은 문제가 다시 생긴다. (3) jsonl을 유지하고 재생성 스크립트를 두면 중간 사본과 별도 조립 코드가 남고, 런타임 경로와 어긋날 수 있다.
- **결과**: 앞으로 엑셀만 고치면 engrbot 런타임과 테스트가 모두 같은 내용을 본다. jsonl은 labelbot 회귀 테스트용으로만 남는다.
