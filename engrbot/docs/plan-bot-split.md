# plan: 검수봇 분리 — labeling-Engr-bot(도메인) / labeling-codebot(기술·workflow)

- 상태: **1차 구현 완료**(2026-10-05, team 실행). 결과는 `engrbot/docs/plan-bot-split-exec.md` 10절에 있다. 남은 단계(L4B, S6, C5, C6 등)는 미착수다
- 작성: 2026-10-05
- 변경 1: 2026-10-05 도메인 봇의 이름을 labeling-qabot에서 **labeling-Engr-bot**으로 바꿨다(사용자 결정).
- 변경 2: 2026-10-05 1차 구현 뒤 패키지 폴더를 `qabot/`에서 **`engrbot/`**으로 바꿨다(사용자 결정). 폴더 이름에 `-`를 쓰면 Python이 import하지 못해서 `Engr-bot`이 아니라 `engrbot`으로 했다. **이 문서 본문의 `qabot/…` 경로와 `python -m qabot`은 `engrbot/…`, `python -m engrbot`으로 읽는다.** 계획서 `qabot/qabot_plan.md`는 `engrbot/engrbot_plan.md`가 됐다.
- 기준 문서: `CLAUDE.md`(충돌 시 우선), `PRD.md`, `qabot/qabot_plan.md`
- 검토: Architect/Critic 합의 검토는 거치지 않았다(계획 작성 예산 20분). 실행 전에 plan `--review`로 한 번 돌릴 수 있다.
- 위치: 검수봇 작업물은 `qabot/`에 둔다는 규칙에 따라 `.omc/plans/`가 아니라 여기에 둔다.

## 1. 현재 qabot의 성격(사실)

현재 qabot은 **라벨 산출물(데이터)의 구조·형식 정합성을 규칙으로 보는 검수봇**이다. 도메인 지식 검수도, 코드 검수도 하지 않는다.

| 층 | 하는 일 | 성격 | 근거 |
|---|---|---|---|
| L0 (16개 코드) | 파서 출력과 독립 추출의 대조(커버리지, 표·이미지 유실, 시그니처) | 기술(파싱 충실도) | `qabot/checks/l0_parse.py`, `qabot/docs/issue_codes.md:10-29` |
| L1 (12개) | 필수 필드, 타입, 허용값, 패턴, 포맷 정규화 | 기술(스키마) | `qabot/checks/l1_schema.py` |
| L2 (8개) | 값이 taxonomy에 있는지, 한 축 안의 구조 규칙 | 기술(참조 무결성) | `qabot/checks/l2_taxonomy.py:1` "축 사이 조합은 L4의 일이다" |
| L3A (6개) | 근거 인용이 본문에 실재하는지(문자열 대조) | 기술(근거 실재) | `qabot/checks/l3a_span.py` |
| L3B (4개) | LLM judge. 인용문만 보고 라벨을 지지하는지 | 근거 지지(도메인 판단 아님) | `qabot/prompts/qa_judge.md:1-2`, `qabot/judge.py:5` |
| L6 (6개) | 배치 분포, unknown 비율, 미매핑 용어 | 통계(taxonomy 결함 신호) | `qabot/checks/l6_batch.py` |
| L4, L5 | 도메인 규칙, 문서 간 일관성 | **미구현. 확장점만 있다** | `qabot/qabot_plan.md:90`, `:990-1005` |

- 도메인 판단은 설계에서 일부러 뺐다: judge는 "문서 전체에 비추어 라벨이 옳은지는 판단하지 않는다"(`qa_judge.md:1`), 동의어 해석은 "L4의 일"(`qabot_plan.md:506`), 도메인 상호배타 쌍은 빈 목록(`qabot/defaults/policy.json:13`).
- 코드를 검수하는 기능은 없다. qabot의 입력은 `work.sqlite` 표뿐이다(`qabot/adapters/labelbot_ws.py:20-30`).
- 규모: 코드·테스트 약 8,000줄, 테스트 219개 통과(`qabot/docs/plan-taxonomy-sync.md:3`).

## 2. 분리 후 개념

| | labeling-Engr-bot | labeling-codebot |
|---|---|---|
| 관점 | BEOL 도메인 지식 | 기술 stack, workflow |
| 묻는 것 | "이 라벨이 공정 지식으로 옳은가" | "이 구현과 workflow가 규칙·stack·단계 계약을 지키는가" |
| 대상 | 라벨 레코드(chunk + 라벨 + 근거) | 소스 코드, 설정, skill 정의, 실행 흔적(건수·사유 코드) |
| 산출 형식 | 레코드 판정(PASS/AUTO_FIX/REVIEW/REJECT), 검토 대기열, 피드백 묶음 | code review finding(`file:line`, 규칙 ID, severity, 수정 제안), review 판정(APPROVE/COMMENT/REQUEST_CHANGES) |
| 지식 원천 | `taxonomy/taxonomy.xlsx`, 도메인 규칙 파일, 도메인 노트, 골든셋 | `CLAUDE.md` 규칙, `PRD.md` 4·9절, 단계 사이 계약(표·열, CLI 명령) |
| 패키지 / 실행 | `qabot/` 유지 / `python -m qabot` | `codebot/` 신규 / `python -m codebot` |
| skill | `.claude/skills/labeling-Engr-bot/` | `.claude/skills/labeling-codebot/` |
| 돌리는 때 | 라벨링 실행 뒤, 사람 검수 앞 | 코드를 고친 뒤, 커밋·사내 반입 앞 |

두 봇 모두 `CLAUDE.md`를 따른다: 표준 라이브러리만, Python 3.14.2, 쓰기는 `.json .jsonl .md .html .sqlite .b64 .log`만, 로그에는 ID와 사유 코드만.

## 3. 핵심 결정 D1: 기존 구조 층(L0~L3B, L6)을 어디에 두는가

| 안 | 내용 | 장점 | 단점 |
|---|---|---|---|
| **A. 대상 기준(권장)** | 기존 층은 qabot에 "구조 게이트"로 남긴다. qabot에 도메인 층(L4, L4B, L5)을 더한다. codebot은 새로 만들고 코드·workflow만 본다 | 기존 219개 테스트와 판정 엔진·검토 화면·골든셋·피드백 루프를 그대로 쓴다. 레코드 하나의 판정이 한 봇에서 나온다. 설계된 확장점(`qabot_plan.md:996-1003`)을 그대로 쓴다 | qabot이 순수 도메인 봇은 아니다(구조 게이트를 품는다) |
| B. 관점 기준 | L0·L1·L2·L3A를 codebot으로 옮기고 qabot은 도메인 층만 가진다 | "도메인 / 기술" 구분이 이름 그대로다 | 레코드 판정이 두 봇에 갈라져 병합 규칙이 새로 필요하다. critical이면 judge를 건너뛰는 단락(`qabot/engine.py:138-139`)이 봇 경계를 넘는다. 대기열·화면·골든셋·하네스·테스트를 다시 배선한다 |

A를 택하는 이유: 도메인 검수는 구조가 성한 레코드에서만 의미가 있고, 사람 검토 대기열은 레코드 단위 판정 하나를 받아야 한다. codebot은 레코드를 판정하지 않고, qabot 구조 게이트의 **집계**(코드별 건수)를 기술 신호로 읽어 코드 위치와 잇는다(5.2절 C5).

A에서 qabot의 정체성을 도메인 쪽으로 옮기는 장치: issue code에 `class`(`structural` / `domain`)를 달고, 리포트와 검토 화면의 앞자리를 도메인 이슈에 준다(S1, S6).

## 4. labeling-Engr-bot 설계(도메인)

### 4.1 층 구성

| 층 | 범위 | 내용 | 신규 파일 |
|---|---|---|---|
| L0~L3B, L6 | 기존 | 구조 게이트. 동작을 바꾸지 않는다 | - |
| **L4** 도메인 규칙(결정론) | record | 규칙 파일로 축 조합, 제목 관례와 라벨 대조, 질문 답 사이 의존, 추출값 의미, 동의어 표준값 제안을 검사한다 | `qabot/checks/l4_domain.py`, `qabot/defaults/domain_rules.json` |
| **L4B** 도메인 judge(LLM) | record | chunk 본문 + 라벨 + taxonomy 정의 + 도메인 노트를 보고 "공정 지식으로 이 라벨이 맞는가"를 `agree / doubt / disagree`로 판정한다. critical이 있는 레코드는 건너뛴다 | `qabot/checks/l4b_domain_judge.py`, `qabot/domain_judge.py`, `qabot/prompts/qa_domain_judge.md`, `qabot/docs/domain_notes.md` |
| **L5** 문서 간 일관성 | batch(레코드에 붙는다) | 같은 `dup_group`, 같은 lot의 chunk끼리 라벨이 어긋나는지 본다 | `qabot/checks/l5_crossdoc.py` |

엔진이 이미 받는 구조다: `model.LAYERS`에 L4·L5가 있고(`qabot/model.py:10`), batch 검사가 `record_id`를 달면 그 레코드 판정을 다시 계산한다(`qabot/engine.py:153-166`). 고칠 곳은 `L4B`를 `model.LAYERS`와 `engine.RECORD_LAYERS`(`engine.py:13`)에 더하고, 단락 조건(`engine.py:138`)에 `L4B`를 넣고, `registry.BUILTIN_MODULES`(`qabot/registry.py:6-13`)에 모듈 3개를 더하는 것이다. 기존 테스트가 `layer="L4"` 가짜 검사를 쓰므로(`qabot/tests/test_core.py:61`) `L4` 이름은 그대로 둔다.

### 4.2 도메인 지식의 형태

`qabot/defaults/domain_rules.json`(규칙 하나가 한 객체, 아래 값은 **형식 예시**이고 내용은 도메인 담당자가 정한다):

```json
{"version": "2026-10-05.1", "rules": [
  {"id": "DR001", "type": "axis_combo", "status": "draft", "severity": "major",
   "when": {"axis": "불량 모드", "value": "Via Rc high"},
   "expect": {"axis": "layer", "value_in": ["V0", "V1", "V2", "V3", "Vx"]}},
  {"id": "DR002", "type": "title_label", "status": "draft", "severity": "major",
   "title_pattern": "(M[0-3x]|V[0-3x]|JHV)", "axis": "layer"}
]}
```

- 규칙 유형 5개: `axis_combo`, `title_label`, `answer_dependency`, `extract_semantics`, `synonym_suggest`.
- `status`가 `draft`인 규칙은 info로만 기록하고 판정을 바꾸지 않는다. `approved`만 판정에 반영한다.
- `synonym_suggest`는 `suggested_fix`만 내고 AUTO_FIX하지 않는다(`qabot_plan.md:1002`).
- 규칙 초안은 봇이 taxonomy와 더미 pptx에서 뽑아 `draft`로 내고, 사람이 승인한다. qabot은 taxonomy와 규칙 파일을 직접 고치지 않는다(`qabot_plan.md:18`).

### 4.3 issue code(추가분)

| code | severity | 설명 |
|---|---|---|
| `L4_AXIS_COMBO_VIOLATION` | major | 승인된 축 조합 규칙에 어긋난다 |
| `L4_TITLE_LABEL_MISMATCH` | major | 제목 관례에서 읽은 값과 라벨이 다르다 |
| `L4_ANSWER_DEPENDENCY` | major | 질문 답 사이 의존 규칙에 어긋난다 |
| `L4_EXTRACT_SEMANTICS` | minor | 추출값이 의미상 맞지 않는다(예: 문서 날짜보다 늦은 날짜) |
| `L4_SYNONYM_SUGGEST` | info | 표준값 제안 |
| `L4_RULE_DRAFT_HIT` | info | 초안 규칙에 걸렸다(판정 영향 없음) |
| `L4_JUDGE_DISAGREE` | major | 도메인 judge가 라벨에 동의하지 않는다 |
| `L4_JUDGE_DOUBT` | minor | 도메인 judge가 의심한다 |
| `L4_JUDGE_FAILED` / `L4_JUDGE_SKIPPED` | major(fail-safe) | 호출 실패 또는 미실행 |
| `L5_DUP_GROUP_DISAGREE` | major | 중복 문서 묶음 안에서 라벨이 다르다 |
| `L5_SAME_LOT_DISAGREE` | minor | 같은 lot 문서 사이에 축 값이 다르다 |

도메인 이슈는 REJECT를 내지 않는다(최대 major → REVIEW). 도메인 판단의 최종 결정은 사람이 한다.

### 4.4 지켜야 할 기존 원칙

- 라벨러와 프롬프트·판정 로직을 공유하지 않는다(`qabot_plan.md:20`). 도메인 judge 프롬프트는 `prompts/classify.md`·`label.md`를 읽지 않고 따로 쓴다.
- 도메인 judge는 본문을 보내므로 기존 L3B보다 전송량이 크다. 전송은 기존 경로(`qabot/llm_http.py` → `labelbot/llm.py`)만 쓰고, 사외 호스트에는 더미 해시 파일의 chunk만 보낸다. 막히면 `L4_JUDGE_SKIPPED`다.
- `policy.json`의 기본 `layers`(`qabot/defaults/policy.json:3`)에는 L4B를 넣지 않는다(opt-in). 지금 실행 결과가 바뀌지 않는다.

## 5. labeling-codebot 설계(기술 stack·workflow)

### 5.1 원칙

- 읽기 전용이다. 저장소와 작업 폴더를 고치지 않고 자기 출력 폴더에만 쓴다.
- 소스는 **텍스트로 읽어 `ast`로 분석**한다. labelbot·qabot을 import하지 않는다(실행 부작용 차단).
- 결정론 규칙이 본체이고 LLM 리뷰는 선택이다. LLM finding은 최대 major다.
- 리포트에 소스 경로와 줄 번호는 쓴다(코드는 사내 자료가 아니다). 작업 폴더의 본문·파일명·base64는 쓰지 않는다.
- qabot의 등록·카탈로그 방식(`qabot/registry.py`, `qabot/codes.py`)을 본떠 자체 구현한다. 공용 core 추출은 두 봇이 안정된 뒤의 후속 과제로 둔다.

### 5.2 규칙 층

| 층 | 관점 | 규칙(ID 접두) | 근거 |
|---|---|---|---|
| **C1** governing rule | DRM·쓰기·로그 | `C1_PATH_PARSER`(경로 기반 파서 호출), `C1_OPEN_OUTSIDE_INGEST`(ingest 밖 원본 open), `C1_NONSTDLIB_IMPORT`, `C1_WRITE_EXT_FORBIDDEN`(office·텍스트 확장자 쓰기), `C1_LOG_CONTENT`(로그에 본문·파일명·base64), `C1_B64_TO_LLM`, `C1_SIGNATURE_CHECK_MISSING` | `CLAUDE.md` DRM 규칙, 쓰기 규칙 |
| **C2** stack | 런타임·전송·저장 | `C2_PY314_SYNTAX`, `C2_TRANSPORT_BYPASS`(`labelbot/llm.py` 공용 함수를 거치지 않는 외부 호출), `C2_REDIRECT_FOLLOW`, `C2_SQLITE_NOT_RO`(qabot 쪽 쓰기 가능 연결), `C2_SECRET_LITERAL`, `C2_REQUIREMENTS_NOT_EMPTY` | `PRD.md` 9절, `README.md` 사외 전송 안전장치 |
| **C3** workflow 계약 | 단계 사이 약속 | `C3_CLI_REF_MISSING`(skill·README가 부르는 명령이 `cli.py`에 없다), `C3_TABLE_CONTRACT_DRIFT`(`labelbot_ws.py:20-30`의 표·열이 `labelbot/store.py` 정의에 없다), `C3_IMPORT_BOUNDARY`(qabot의 labelbot import 허용 모듈 3개, `labelbot_ws.py:6`), `C3_CODE_CATALOG_DRIFT`(코드에서 쓰는 issue code가 카탈로그에 없다), `C3_STAGE_ORDER`(`pipeline.py` 단계 순서와 `PRD.md` 4절) | `PRD.md` 4절, `.claude/skills/BEOL-labeling*/SKILL.md` |
| **C4** 완료 위생 | 테스트·미완성 | `C4_TEST_SKIP`, `C4_PLACEHOLDER`(TODO·stub·`NotImplementedError`), `C4_MODULE_UNTESTED`, `C4_TESTS_FAILING`(`--run-tests`) | 전역 `CLAUDE.md` "No fake completion" |
| **C5** 실행 흔적(선택) | workflow 실행 건강도 | `failures` 표와 qabot `report.json`의 코드별 건수를 담당 모듈에 잇는다(예: `L0_TABLE_LOST` 다발 → `labelbot/pptx_parser.py`) | `--workspace`를 줄 때만. 건수와 코드만 읽는다 |
| **C6** LLM 리뷰(선택) | diff 의미 검토 | `git diff` 범위의 로직 결함·경계 조건 | `--llm`. 전송 내용은 소스 diff뿐이다 |

휴리스틱 규칙(`C1_OPEN_OUTSIDE_INGEST`, `C1_LOG_CONTENT`, `C1_B64_TO_LLM`, `C1_SIGNATURE_CHECK_MISSING`)은 major로 시작한다. 오탐은 줄 끝 주석 `# codebot: allow <규칙 ID> <사유>`로 누르고, 누른 건수를 리포트에 낸다.

### 5.3 산출과 명령

- finding 한 건: `{"rule", "layer", "severity", "path", "line", "symbol", "message", "suggested_fix", "source": "static|llm", "suppressed"}`
- 판정: critical ≥ 1 → `REQUEST_CHANGES`(종료 코드 1), major ≥ 1 → `COMMENT`, 그 밖 → `APPROVE`.
- 출력: `<out>/<review_id>/findings.jsonl`, `review.md`, `manifest.json`. 기본 `<out>`은 `--workspace`가 있으면 그 아래 `codebot/`, 없으면 저장소 `codebot/out/`(커밋 제외).
- 명령: `python -m codebot review [--paths …] [--diff <base>] [--layers C1,C2] [--workspace <폴더>] [--run-tests] [--llm]`, `python -m codebot rules`(규칙 카탈로그 `.md` 생성), `python -m codebot eval`(심은 위반 탐지율·오탐률).

### 5.4 폴더

```
codebot/
  __init__.py  __main__.py  cli.py  registry.py  model.py  rules.py(카탈로그)
  scan.py(소스 수집, ast 색인)  report.py  llm_review.py(선택)
  checks/ c1_governing.py  c2_stack.py  c3_workflow.py  c4_hygiene.py  c5_runhealth.py
  defaults/ rules.json  policy.json(대상 경로, 허용 목록, severity 조정)
  prompts/ code_review.md
  docs/ rules.md
  tests/ test_c1.py … test_cli.py  (위반 예시는 테스트 파일 안 문자열로 둔다)
```

## 6. 구현 단계

단계마다 끝에 테스트를 돌리고, 작성과 승인은 다른 lane으로 한다(executor → verifier).

| 단계 | 내용 | 손대는 파일 | 완료 조건 |
|---|---|---|---|
| **S0** 개념 고정 | `qabot_plan.md` 1.1·1.5·11절을 새 개념으로 고치고 `PRD.md` 변경 필요 항목을 통보 목록으로 낸다 | `qabot/qabot_plan.md` | 두 봇의 범위 표가 이 문서 2절과 같다 |
| **S1** qabot 정리 | issue code에 `class` 필드, `L4B` 층 추가, 리포트를 구조/도메인 두 구역으로 | `qabot/defaults/issue_codes.json`, `codes.py`, `model.py:10`, `engine.py:13,138`, `report.py` | 기존 테스트 219개 통과. 합성 fixture(seed 7)의 판정이 변경 전과 같다 |
| **S2** 도메인 자산 | 규칙 파일 스키마와 검증기, 초안 규칙, 도메인 노트 | `qabot/defaults/domain_rules.json`, `qabot/policy.py`, `qabot/docs/domain_notes.md` | 스키마 위반 규칙 파일은 `PolicyError`. 초안은 전부 `status: draft` |
| **S3** L4 | 규칙 유형 5개, 뮤테이터, 테스트 | `qabot/checks/l4_domain.py`, `harness.py`, `tests/test_l4.py`, `tests/fixturegen.py` | 유형마다 탐지·비탐지 테스트 1쌍 이상. 깨끗한 fixture 오탐 0건. L4 뮤테이터 탐지율 ≥ 0.95. draft 규칙은 판정을 바꾸지 않는다 |
| **S4** L4B | 도메인 judge, 프롬프트, mock, 캐시, fail-safe | `qabot/domain_judge.py`, `checks/l4b_domain_judge.py`, `prompts/qa_domain_judge.md`, `llm.py`, `tests/test_domain_judge.py` | mock으로 agree/doubt/disagree 3경로 통과. 사외 호스트 + 더미 아님 → 전송 0회, `L4_JUDGE_SKIPPED`. 기본 `layers`에 없어 기존 실행 결과 동일 |
| **S5** L5 | dup_group·lot 묶음 대조 | `qabot/checks/l5_crossdoc.py`, `tests/test_l5.py` | 어긋난 쌍에만 이슈가 붙고 그 레코드 판정이 다시 계산된다 |
| **S6** 화면·피드백 | 검토 화면에 도메인 이슈 필터와 규칙 ID, 규칙 승인 제안 집계 | `qabot/screen.py`, `screens/qa_review.html`, `proposals.py`, `feedback.py` | 화면에서 도메인 이슈만 걸러 볼 수 있다. 사람이 확정한 결정으로 `draft → approved` 제안 목록이 나온다 |
| **S7** codebot 골격 + C1 | 패키지, 등록, finding 모델, CLI, 리포트, C1 규칙 7개 | `codebot/**` | 규칙마다 위반·정상 예시 1쌍 이상 통과. 현 저장소 대상 실행이 10초 안에 끝나고 출력 폴더 밖에 쓰지 않는다 |
| **S8** C2~C4 | stack, workflow 계약, 완료 위생 | `codebot/checks/c2_stack.py`, `c3_workflow.py`, `c4_hygiene.py` | 위와 같은 예시 테스트. `labelbot_ws.REQUIRED`에서 열 하나를 지운 사본으로 `C3_TABLE_CONTRACT_DRIFT`가 난다 |
| **S9** C5, C6(선택) | 실행 흔적 연결, LLM 리뷰 | `codebot/checks/c5_runhealth.py`, `llm_review.py`, `prompts/code_review.md` | C5 출력에 본문·파일명이 없다(테스트로 확인). `--llm` 없이는 호출 0회 |
| **S10** skill·통합 | skill 2개, `README.md` 명령 절, 통합 실행 | `.claude/skills/labeling-Engr-bot/SKILL.md`, `.claude/skills/labeling-codebot/SKILL.md`, `README.md` | 더미 작업 폴더에서 qabot(L4·L5 포함) 실행, 저장소에서 codebot 실행이 각각 리포트를 낸다. critical finding은 전부 수정했거나 사유를 적었다 |

순서: S0 → S1 → (S2~S6)과 (S7~S9)는 서로 독립이라 병렬로 할 수 있다 → S10.

## 7. 리스크와 대응

| # | 리스크 | 대응 |
|---|---|---|
| R1 | 틀린 도메인 규칙이 정상 레코드를 대량으로 REVIEW에 올린다 | `draft`는 판정에 영향이 없다. 도메인 이슈는 REJECT를 내지 않는다. 규칙별 적중·기각 건수를 리포트에 내 승인 근거로 쓴다 |
| R2 | 도메인 judge가 본문을 사외로 보낸다 | 기존 전송 경로와 더미 해시 조건을 그대로 쓴다. 차단 테스트를 S4 완료 조건에 넣었다 |
| R3 | 도메인 judge가 라벨러와 같은 오류를 반복한다(독립성) | 프롬프트를 따로 쓰고, 입력에 라벨러의 확신도와 근거 설명을 넣지 않는다. 골든셋으로 judge 일치율을 잰다 |
| R4 | L4B fail-safe 때문에 judge를 끄면 PASS가 0건이 된다 | 기존 L3B와 같은 정책이다. 기본 `layers`에서 빼 두고 측정 뒤에 켠다 |
| R5 | codebot 휴리스틱 오탐(자체 `.b64`·`.json` 읽기를 원본 open으로 본다) | 허용 목록(`policy.json`)과 줄 단위 억제 주석. 휴리스틱은 major로 시작한다 |
| R6 | 다른 세션이 labelbot을 고치는 중이다(작업 트리에 미커밋 변경 다수) | 이 계획은 `labelbot/`을 고치지 않는다. codebot은 읽기만 한다. C3 계약 검사가 labelbot 변경으로 깨지면 finding으로 보고한다 |
| R7 | `model.LAYERS` 변경이 기존 테스트를 깬다 | `L4`는 그대로 두고 `L4B`만 더한다. S1 완료 조건이 기존 테스트 전체 통과다 |
| R8 | 사내에 git이 없어 `--diff`가 안 된다 | `--paths`가 기본 경로다. `--diff`는 git이 있을 때만 쓴다 |

## 8. 검증

1. `python -m unittest discover qabot/tests`, `python -m unittest discover codebot/tests`, `python -m unittest discover tests` 전부 통과.
2. `python -m qabot eval --golden synthetic:7`: 기존 층 탐지율이 변경 전보다 낮지 않고, L4·L5 탐지율 ≥ 0.95, 오탐률 0.
3. `python -m codebot eval`: 규칙별 탐지율 1.0(심은 위반), 정상 예시 오탐 0.
4. `python -m codebot review --paths labelbot qabot codebot`: 종료 코드와 `review.md`를 확인하고 critical을 분류한다.
5. codebot으로 codebot·qabot 변경분을 검수한다(자기 규칙 준수 확인).
6. verifier lane에서 완료 조건을 단계별로 대조한다. 변경 파일에 TODO·skip·stub이 없는지 본다.

## 9. 사용자 결정 항목(기본값으로 진행한다)

| # | 항목 | 기본값 | 바꾸면 |
|---|---|---|---|
| D1 | 기존 구조 층의 소유 | A안: qabot에 구조 게이트로 남긴다 | B안이면 S1 앞에 층 이전 단계가 생기고 판정 병합 규칙을 새로 설계한다 |
| D2 | 도메인 규칙을 누가 쓰나 | 봇이 `draft`로 뽑고 사람이 승인한다 | 사람이 직접 쓰면 S2의 초안 추출을 뺀다 |
| D3 | codebot 대상 범위 | `labelbot/`, `qabot/`, `codebot/`, `.claude/skills/**/scripts`, `tests/` | 범위를 줄이면 `policy.json`의 대상 경로만 바뀐다 |
| D4 | 이름 | 패키지 `qabot`(유지)·`codebot`(신규), skill `labeling-Engr-bot`·`labeling-codebot` | - |
| D5 | codebot 작업물 위치 | 저장소 루트 `codebot/`(qabot 규칙을 그대로 적용) | - |
| D6 | LLM 층(L4B, C6) | 구현하되 기본은 꺼 둔다 | 켜면 judge 미실행 시 PASS 0건 정책이 적용된다 |

## 10. 손대지 않는 것

- `labelbot/` 코드, `PRD.md`, 루트 `plan.md`(통보 목록만 낸다).
- 기존 L0~L3B·L6의 판정 동작과 기본 정책 값.
- 4차 불량 목록(`labelbot/review.py`)과 기존 `BEOL-labeling*` skill의 흐름.
