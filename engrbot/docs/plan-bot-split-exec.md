# 실행계획: labeling-Engr-bot / labeling-codebot 1차 구현 (team, 20분)

- 상태: **실행 완료**(2026-10-05 02:55~03:17, 사용자 승인 뒤 team 실행). 결과는 10절에 있다
- 실행 뒤 변경: 패키지 폴더를 `qabot/`에서 **`engrbot/`**으로 바꿨다(사용자 결정). **이 문서 본문의 `qabot/…` 경로와 `python -m qabot`은 `engrbot/…`, `python -m engrbot`으로 읽는다.**
- 작성: 2026-10-05
- 상위 계획: `qabot/docs/plan-bot-split.md` (개념·전체 단계 S0~S10)
- 실행 방식: `/oh-my-claudecode:team` — worker 7명 병렬 → 검증 2명 → 수정 1회
- 실행 예산: **20분**. "20분"은 구현 실행 시간으로 읽었다. 그래서 상위 계획 전체가 아니라 20분에 들어가는 1차 범위만 잡았다.
- 기준선: `python -m unittest discover -s qabot/tests -t .` → 219개 OK, 19.6초(2026-10-05 확인)

## 1. 이름과 위치

| 항목 | 값 |
|---|---|
| 도메인 검수 봇 | 표시·skill 이름 `labeling-Engr-bot`. Python 패키지는 `qabot/` 그대로(실행 `python -m qabot`). 패키지 개명은 이번 범위 밖이다 |
| 코드 검수 봇 | 표시·skill 이름 `labeling-codebot`. 새 패키지 `codebot/`(실행 `python -m codebot`) |
| skill | `.claude/skills/labeling-Engr-bot/SKILL.md`, `.claude/skills/labeling-codebot/SKILL.md` |

## 2. 20분 범위

| | 이번에 한다 | 다음 회차로 미룬다 |
|---|---|---|
| Engr-bot | **L4** 도메인 규칙(유형 3개: `axis_combo`, `title_label`, `synonym_suggest`), 규칙 파일과 검증기, **L5** 중복 묶음 일관성, issue code 5개, 테스트, skill | L4B 도메인 judge(LLM), 규칙 유형 `answer_dependency`·`extract_semantics`, `L5_SAME_LOT_DISAGREE`, 검토 화면·피드백 반영(S6), 하네스 뮤테이터, `qabot_plan.md` 개정(S0), issue code `class` 필드(S1) |
| codebot | 골격(등록, 소스 색인, finding, 판정, 리포트, CLI `review`·`rules`), **C1** 4개, **C2** 4개, **C3** 3개, **C4** 2개 규칙, 테스트, skill | C1 휴리스틱 3개(`LOG_CONTENT`, `B64_TO_LLM`, `SIGNATURE_CHECK_MISSING`), `C2_REDIRECT_FOLLOW`·`C2_SQLITE_NOT_RO`, `C3_STAGE_ORDER`·`C3_CODE_CATALOG_DRIFT`, `C4_MODULE_UNTESTED`·`--run-tests`, C5 실행 흔적, C6 LLM 리뷰, `eval` |

기존 동작은 바꾸지 않는다: `qabot/defaults/policy.json:3`의 기본 `layers`에 L4·L5를 넣지 않는다. Engr-bot skill이 `--layers L0,L1,L2,L3A,L3B,L4,L5,L6`을 붙여 부른다(`qabot/cli.py:27`). 엔진·모델은 고치지 않는다(L4·L5는 이미 `qabot/model.py:10`, `qabot/engine.py:13,153-166`, `qabot/policy.py:19`가 받는다).

## 3. Lane

모든 worker는 같은 작업 트리에서 일한다(미커밋 변경이 많아 worktree 분리를 쓰지 않는다). 그래서 **파일 소유를 겹치지 않게** 나눴다. 커밋·푸시는 하지 않는다. `labelbot/`, `PRD.md`, `plan.md`, `README.md`는 아무도 고치지 않는다.

| worker | agent | 소유 파일(이 밖은 읽기만) | 산출 | 완료 조건 |
|---|---|---|---|---|
| **E1** | executor(opus) | `qabot/checks/l4_domain.py`, `qabot/domain_rules.py`, `qabot/defaults/domain_rules.json`, `qabot/tests/test_l4.py`. 공유: `issue_codes.json`·`registry.py`에 **자기 줄만** | L4 검사 | 4.1절 명세 통과. 유형마다 탐지·비탐지 테스트 1쌍 이상. draft 규칙은 판정을 바꾸지 않는다. 기존 219개 통과 |
| **E2** | executor(sonnet) | `qabot/checks/l5_crossdoc.py`, `qabot/tests/test_l5.py`. 공유: 위와 같이 자기 줄만 | L5 검사 | 4.2절 명세 통과. 어긋난 묶음의 레코드에만 이슈가 붙고 판정이 다시 계산된다 |
| **C0** | executor(sonnet) | `codebot/__init__.py`, `__main__.py`, `model.py`, `registry.py`, `scan.py`, `report.py`, `cli.py`, `defaults/policy.json`, `checks/__init__.py`, `tests/__init__.py`, `tests/test_core.py`, `tests/test_cli.py`, `.gitignore`(한 줄 추가) | codebot 골격 | 5절 계약 그대로. **시작 5분 안에 `model`·`registry`·`scan`을 먼저 쓰고 lead에 알린다.** `python -m codebot review`가 리포트 3개를 쓰고 종료 코드를 낸다 |
| **C1** | executor(sonnet) | `codebot/checks/c1_governing.py`, `codebot/tests/test_c1.py` | C1 규칙 4개 | 규칙마다 위반·정상 예시 1쌍 이상 통과 |
| **C2** | executor(sonnet) | `codebot/checks/c2_stack.py`, `codebot/checks/c4_hygiene.py`, `codebot/tests/test_c2.py`, `test_c4.py` | C2 4개, C4 2개 | 위와 같다 |
| **C3** | executor(sonnet) | `codebot/checks/c3_workflow.py`, `codebot/tests/test_c3.py` | C3 규칙 3개 | 위와 같다. `REQUIRED`에서 열 하나를 더한 사본 소스로 `C3_TABLE_CONTRACT_DRIFT`가 난다 |
| **D1** | writer(haiku) | `.claude/skills/labeling-Engr-bot/SKILL.md`, `.claude/skills/labeling-codebot/SKILL.md` | skill 2개 | 기존 `BEOL-labeling*` skill과 같은 형식. 적힌 명령이 실제 CLI에 있다 |

공유 파일 규칙(E1·E2): `qabot/defaults/issue_codes.json`과 `qabot/registry.py:6-13`은 Edit로 자기 줄만 더하고, 더하기 직전에 다시 읽는다. Write로 통째로 덮어쓰지 않는다. issue code 5개(L5 포함)는 E1이 시작 직후 한 번에 넣고 `python -m qabot codes`로 `qabot/docs/issue_codes.md`를 만든다. E2는 카탈로그를 고치지 않고 `registry.py`에 자기 줄만 더한다.

시간이 모자랄 때 버리는 순서: ① C2의 C4 규칙 ② E2(L5) ③ C2 전체. E1, C0, C1, C3, D1은 필수다.

## 4. Engr-bot 명세

### 4.1 L4 도메인 규칙 (E1)

- 검사 클래스: `layer="L4"`, `scope="record"`, `@register`(`qabot/checks/l2_taxonomy.py:92-99`와 같은 꼴). `registry.BUILTIN_MODULES`에 `qabot.checks.l4_domain`을 더한다.
- 규칙 파일: `policy["l4"]["rules_path"]`가 있으면 그 경로, 없으면 `qabot/defaults/domain_rules.json`. 형식은 `{"version": str, "rules": [...]}`.
- 규칙 공통 필드: `id`(고유), `type`, `status`(`draft` | `approved`), `severity`(`major` | `minor`), `note`(선택). 검증 실패는 `PolicyError`(`qabot/policy.py:32`)로 멈춘다.
- 유형:
  - `axis_combo`: `when: {axis, value_in}` + `expect: {axis, value_in}` 또는 `forbid: {axis, value_in}`. when 축의 값이 `value_in`에 있을 때, expect 축의 값이 하나도 `value_in`에 없거나 forbid 축의 값이 하나라도 `value_in`에 있으면 위반이다. expect 축이 예약어(`해당 없음`, `unknown`)뿐이면 위반으로 보지 않는다.
  - `title_label`: `title_pattern`(정규식, 그룹 1이 값) + `axis`. chunk 제목에서 뽑은 값이 `tax.canonical_value(axis, 값)`으로 그 축의 값인데 라벨에 없으면 위반이다.
  - `synonym_suggest`: 축 값이 taxonomy 밖이고 `tax.synonyms`의 alias와 같으면(`model.norm_key` 기준) 표준값을 `suggested_fix`로 낸다. AUTO_FIX하지 않는다.
- 판정 영향: `approved`는 유형별 코드에 규칙의 severity를 쓴다. `draft`는 `L4_RULE_DRAFT_HIT`(info)만 낸다.
- 건너뛰기: `target.broken`에 든 필드, `chunk_type`이 내용이 아닌 레코드(`axis_combo`, `title_label`).
- evidence에는 `rule_id`와 값(40자 절단)만 넣는다. 제목·본문 원문은 넣지 않는다.
- 기본 규칙 파일에는 형식 예시 3개를 전부 `draft`로 넣는다. 규칙 내용은 도메인 담당자가 정한다.

추가 issue code(`qabot/defaults/issue_codes.json`):

| code | layer | scope | severity |
|---|---|---|---|
| `L4_AXIS_COMBO_VIOLATION` | L4 | record | major / minor |
| `L4_TITLE_LABEL_MISMATCH` | L4 | record | major / minor |
| `L4_SYNONYM_SUGGEST` | L4 | record | info |
| `L4_RULE_DRAFT_HIT` | L4 | record | info |
| `L5_DUP_GROUP_DISAGREE` | L5 | record | major |

### 4.2 L5 중복 묶음 일관성 (E2)

- 검사 클래스: `layer="L5"`, `scope="batch"`. 대상은 `BatchTarget`(`qabot/engine.py:49-54`)이다. `registry.BUILTIN_MODULES`에 `qabot.checks.l5_crossdoc`을 더한다.
- 묶음: `bundle.units[record_id]["dup_group"]`(`qabot/adapters/labelbot_ws.py:205`)이 같은 레코드. 내용 chunk만, critical 이슈가 있는 레코드는 뺀다.
- 판정: 묶음에 레코드가 2개 이상이고 분류 축(`tax.classification_axes()`)의 값 집합이 서로 다르면, 그 묶음의 모든 레코드에 `model.issue("L5_DUP_GROUP_DISAGREE", field="axis:<축>", record_id=…)`를 낸다. evidence는 `{"group_size", "variants"}`뿐이다.
- 엔진이 `record_id`가 달린 batch 이슈를 레코드에 붙이고 판정을 다시 계산한다(`engine.py:158-166`). 테스트는 `qabot/tests/test_core.py:17-25`의 `small_bundle()`·`run(bundle, layers)` 방식을 쓴다.

## 5. codebot 계약 (C0가 구현, C1~C3가 이 계약에 맞춰 쓴다)

```python
# codebot/model.py
SEVERITIES = ("critical", "major", "minor", "info")
LAYERS = ("C1", "C2", "C3", "C4", "C5", "C6")
def decide(findings): ...   # suppressed 제외. critical≥1 → "REQUEST_CHANGES", major≥1 → "COMMENT", 그 밖 → "APPROVE"

# codebot/registry.py
class Check:
    layer = None            # "C1" …
    scope = "file"          # "file": run(SourceFile, ctx), "repo": run(RepoIndex, ctx)
    rules = {}              # {"C1_PATH_PARSER": {"severity": "critical", "desc": "…"}}
    def run(self, target, ctx): ...          # → list[finding]
    def finding(self, rule, path, line, message, suggested_fix=None, symbol=None): ...
        # → {"rule","layer","severity","path","line","symbol","message","suggested_fix","source":"static","suppressed":False}
def register(cls): ...      # 데코레이터
def checks(layer=None, scope=None): ...
def load_builtin(): ...     # pkgutil로 codebot/checks/ 아래 모듈을 전부 import한다(목록 파일 없음)
def all_rules(): ...        # {rule_id: {"layer","severity","desc"}}

# codebot/scan.py
class SourceFile:           # .py 한 개
    path                    # 저장소 기준 경로, '/' 구분
    text, lines             # 원문, 줄 목록
    tree                    # ast.Module 또는 None
    syntax_error            # (lineno, msg) 또는 None
    def allowed(self, rule, line): ...   # 그 줄에 "# codebot: allow <rule>" 주석이 있나
class RepoIndex:
    root, files             # files: list[SourceFile]
    def get(self, path): ...             # SourceFile 또는 None
    def read_text(self, rel_path): ...   # .md·.json 등. 없으면 None
    def glob(self, pattern): ...         # 저장소 기준 경로 목록
def build(root, targets, exclude): ...   # → RepoIndex. 소스를 import하지 않고 텍스트로 읽는다

# ctx
ctx.policy                  # codebot/defaults/policy.json (+ --policy 덮어쓰기)
ctx.root

# 생성자와 실행 진입점(테스트가 디스크 없이 쓸 수 있게 고정한다)
SourceFile(path, text)                  # text를 받아 lines, tree, syntax_error를 채운다. tree의 모든 노드에 parent 속성을 단다(루트는 None)
RepoIndex(root, files, texts=None)      # texts: {저장소 기준 경로: 내용}. 있으면 read_text·glob이 디스크보다 texts를 먼저 본다
codebot.model.default_policy()          # codebot/defaults/policy.json을 읽은 dict
codebot.model.Ctx(policy=None, root=".")  # policy가 None이면 default_policy()
codebot.review.run(index, ctx, layers=None)
    # 검사 실행 → severity_overrides → 억제(줄 주석, policy["allow"]) → 정렬
    # → {"findings": [...], "verdict": "...", "counts": {"critical": n, "major": n, "minor": n, "info": n, "suppressed": n}}
```

- 억제와 허용: `SourceFile.allowed()`가 참이거나 `policy["allow"]`(`{"rule","path","reason"}`)에 맞으면 엔진이 `suppressed=True`로 바꾼다. 억제 건수는 리포트에 낸다.
- CLI: `python -m codebot review [--root .] [--paths …] [--layers C1,C2] [--out DIR] [--policy FILE]`. 콘솔에는 review ID, 판정, severity별 건수만 낸다. `REQUEST_CHANGES`면 종료 코드 1, 그 밖은 0. `python -m codebot rules [--out codebot/docs/rules.md]`는 등록된 규칙에서 카탈로그를 만든다.
- 출력: `<out>/<review_id>/findings.jsonl`, `review.md`, `manifest.json`. 기본 `<out>`은 `codebot/out/`이고 `.gitignore`에 넣는다.
- `policy.json` 블록(C0가 한 번에 쓴다):
  - `targets`: `["labelbot", "qabot", "codebot", "tests", ".claude/skills"]`, `exclude`: `["**/__pycache__/**", "codebot/out/**"]`, `layers`: `["C1","C2","C3","C4"]`, `severity_overrides`: `{}`, `allow`: `[]`
  - `c1`: `ingest_modules`(`["labelbot/ingest.py"]`), `forbidden_write_exts`(`.pptx .xlsx .docx .csv .txt .pdf .hwp .ppt .doc .xls`), `local_packages`(`["labelbot","qabot","codebot","tests"]`), `test_globs`(`["tests/**", "qabot/tests/**", "codebot/tests/**"]`)
  - `c2`: `transport_modules`(`["labelbot/llm.py"]`)
  - `c3`: `cli_modules`(`{"labelbot": "labelbot/cli.py", "qabot": "qabot/cli.py", "codebot": "codebot/cli.py"}`), `doc_globs`(`[".claude/skills/*/SKILL.md", "README.md"]`), `contract`(`{"required": "qabot/adapters/labelbot_ws.py", "tables": "labelbot/store.py"}`), `labelbot_import_allowed`(`["qabot/adapters/labelbot_ws.py", "qabot/io.py", "qabot/llm_http.py"]`)

### 규칙 (이번 범위)

| 규칙 | severity | 잡는 것 | 근거 |
|---|---|---|---|
| `C1_PATH_PARSER` | critical | `Presentation(…)`, `load_workbook(…)`, `pd.read_*(…)`, `csv.reader(open(…))`, 인자가 `io.BytesIO`가 아닌 `zipfile.ZipFile(…)` | `CLAUDE.md` DRM 규칙 |
| `C1_NONSTDLIB_IMPORT` | critical | `sys.stdlib_module_names`에도 `local_packages`에도 없는 import | `CLAUDE.md` "표준 라이브러리만" |
| `C1_WRITE_EXT_FORBIDDEN` | critical | 쓰기 모드 `open`의 경로 리터럴이 금지 확장자로 끝난다(테스트 경로 제외) | `CLAUDE.md` 쓰기 규칙 |
| `C1_OPEN_OUTSIDE_INGEST` | major | `ingest_modules` 밖의 `open(…, "rb")` (휴리스틱, 억제 주석 허용) | `CLAUDE.md` "원본 경로를 여는 코드는 ingest 한 곳" |
| `C2_PY314_SYNTAX` | critical | `ast.parse` 실패 | `CLAUDE.md` Python 3.14.2 |
| `C2_TRANSPORT_BYPASS` | major | `transport_modules` 밖의 `urlopen`, `build_opener`, `http.client`, `socket` 사용 | `README.md` 사외 전송 안전장치, `labelbot/llm.py:119-163` |
| `C2_SECRET_LITERAL` | critical | 키·토큰 꼴 문자열 리터럴(`sk-…`, `eyJ…` 등) | `README.md` 준비 1항 |
| `C2_REQUIREMENTS_NOT_EMPTY` | major | `requirements.txt`에 패키지 줄이 있다 | `README.md` 준비 5항 |
| `C3_CLI_REF_MISSING` | major | `doc_globs`의 `python -m <패키지> <명령>`이 그 패키지 `cli.py`에 없다. labelbot은 `add("이름", …)`와 튜플 반복문으로 명령을 만든다(`labelbot/cli.py:15-36`) | skill·README와 CLI의 약속 |
| `C3_IMPORT_BOUNDARY` | major | `qabot/`(테스트 제외)에서 허용 모듈 3개 밖의 `labelbot` import | `qabot/adapters/labelbot_ws.py:6`, `qabot/tests/test_core.py:14` |
| `C3_TABLE_CONTRACT_DRIFT` | critical | `labelbot_ws.REQUIRED`(`labelbot_ws.py:20-30`)의 표·열이 `store.TABLES`(`labelbot/store.py:6`)에 없다. 두 dict를 `ast.literal_eval`로 읽는다 | 단계 사이 표 계약 |
| `C4_TEST_SKIP` | major | `unittest.skip*`, `@skip`, `self.skipTest` | 전역 `CLAUDE.md` "No fake completion" |
| `C4_PLACEHOLDER` | minor | `TODO`·`FIXME` 주석, 본문이 `pass`·`...`·`raise NotImplementedError`뿐인 함수(추상 기반 클래스의 `run` 제외) | 위와 같다 |

테스트의 위반 예시는 파일로 두지 않고 테스트 파일 안 문자열로 둔다.

## 6. 시간표

| 시각 | 단계 | 내용 |
|---|---|---|
| 0~1분 | 준비 | team 상태 기록, 작업 목록, worker 7명 동시 생성 |
| 1~11분 | team-exec | 병렬 구현. C0는 5분 안에 `model`·`registry`·`scan`을 먼저 낸다. 11분에 끝나지 않은 lane은 3절의 순서로 버린다 |
| 11~12분 | 통합 | E1: `python -m qabot codes` + qabot 전체 테스트. C0: `python -m codebot rules`, `python -m codebot review --root .` |
| 12~16분 | team-verify | verifier(sonnet)와 code-reviewer(opus)를 병렬로. 읽기만 한다 |
| 16~20분 | team-fix | 수정 1회, 실패한 항목만 다시 검증 |
| 20분 | 종료 | 남은 결함은 고치지 않고 목록으로 보고한다 |

## 7. 검증 게이트 (team-verify)

1. `python -m unittest discover -s qabot/tests -t .` — 기존 219개와 새 테스트 전부 통과.
2. `python -m unittest discover -s codebot/tests -t .` — 전부 통과.
3. `python -m unittest discover tests` — 실행 전후 실패 목록이 같다(다른 세션 작업으로 이미 실패하는 것은 이번 변경과 무관하다고 적는다).
4. `python -m qabot run … --layers …L4,L5…`을 합성 fixture로 돌려 기본 규칙(draft)에서 판정이 L4·L5 없이 돌린 것과 같다.
5. `python -m codebot review --root .` — 리포트 3개가 생기고 출력 폴더 밖 파일은 바뀌지 않는다. critical finding은 항목별로 "실제 위반 / 오탐"을 분류해 보고한다(고치는 것은 이번 범위가 아니다).
6. 새 코드가 스스로 규칙을 지킨다: codebot이 `codebot/`과 `qabot/` 새 파일에서 C1 critical을 내지 않는다.
7. 변경 파일에 TODO, skip, stub이 없다. `git status`에서 소유 표 밖 파일이 바뀌지 않았다.

## 8. 리스크

| # | 리스크 | 대응 |
|---|---|---|
| R1 | C0가 늦으면 C1~C3가 테스트를 못 돌린다 | 계약을 5절에 코드 수준으로 고정했다. C0는 계약 파일 3개를 먼저 낸다. 그동안 C1~C3는 검사 코드와 예시를 쓴다 |
| R2 | E1·E2가 `issue_codes.json`·`registry.py`를 함께 고친다 | 자기 줄만 Edit, 직전에 다시 읽기. 카탈로그 문서는 통합 단계에서 한 번만 만든다 |
| R3 | 20분 안에 수정 루프가 끝나지 않는다 | 수정은 1회로 제한한다. 남은 결함은 보고서에 적고 멈춘다 |
| R4 | 다른 세션이 `labelbot/`을 고치는 중이다 | 아무도 `labelbot/`을 고치지 않는다. codebot의 finding은 보고만 한다 |
| R5 | codebot이 현 저장소에서 critical을 내 종료 코드 1이 된다 | 정상 동작이다. 게이트 5에서 분류만 한다 |
| R6 | 도메인 규칙 내용이 비어 있다 | 이번에는 장치와 형식 예시(draft)만 만든다. 규칙 내용은 사용자가 정한 뒤 `approved`로 올린다 |

## 9. 승인할 때 확인할 것

- 패키지 이름은 `qabot/` 그대로 두고 표시 이름만 `labeling-Engr-bot`으로 바꾼다.
- 기본 `layers`는 그대로 두고 skill이 `--layers`로 L4·L5를 켠다.
- 기존 구조 층은 Engr-bot(`qabot/`)에 남긴다(상위 계획 D1의 A안).

## 10. 실행 결과 (2026-10-05)

아래 경로는 개명 뒤 기준(`engrbot/`)이다.

| 단계 | 시각 | 결과 |
|---|---|---|
| team-exec | 02:55~03:01 | worker 7명 모두 완료. 버린 lane 없음 |
| team-verify | 03:04~03:10 | verifier: 반드시 고칠 것 1건(`--paths` 형식). code-reviewer: critical 0, major 7, minor 5 |
| team-fix(1회) | 03:11~03:17 | codebot 결함 11건 수정(CLI, 억제 범위, 검사 오류 처리, C1~C4 오탐·미탐) |
| 폴더 개명 | 03:18~03:25 | `qabot/` → `engrbot/`, 참조 59개 파일 치환, 독립 검증 12항목 통과 |

20분 예산을 2~3분 넘겼다(수정 뒤 재확인이 03:18에 끝났다).

검증 수치:
- `python -m unittest discover -s engrbot/tests -t .` → 243개 OK(기존 219 + L4 17 + L5 7)
- `python -m unittest discover -s codebot/tests -t .` → 87개 OK
- `python -m unittest discover tests` → 215개 중 3개 실패. 모두 `tests/test_slides.py`(다른 세션이 작업 중인 `labelbot` 슬라이드 기능)이고 `engrbot`·`codebot`을 참조하지 않는다
- `python -m codebot review --root .` → `COMMENT`, critical 0, major 2, minor 3, 억제 2

codebot이 현재 저장소에서 낸 finding(고치지 않고 남겼다):
- major `C2_TRANSPORT_BYPASS` `labelbot/cdp.py:8`, `:12` — 127.0.0.1 전용 브라우저 DevTools 연결이라 실질 위험은 낮다. `allow`에 넣을지는 labelbot 담당이 정한다
- minor `C4_PLACEHOLDER` `tests/test_pipeline.py:265`, `:276`, `:296` — 로그를 끄려는 빈 `log_message`
- 억제 2건(`codebot/defaults/policy.json`의 `allow`): `engrbot/tests/test_judge.py`의 테스트용 가짜 키, `labelbot/selfcheck.py`의 왕복 확인 파일 읽기

고치지 않고 남긴 리뷰 지적:
- L4 규칙 파일 검증이 실행 시작이 아니라 첫 레코드 검사 때 일어난다. `l4.rules_path`가 상대 경로면 현재 폴더 기준으로 풀린다(`engrbot/checks/l4_domain.py`)
- L5가 붙인 이슈가 같은 batch 단계의 L6 지표에 반영되는 순서(`engrbot/engine.py:156-166`)는 확인하지 못했다
- L5는 어긋난 축마다 이슈를 낸다. 묶음이 크면 이슈 수가 많아진다

확인하지 못한 것: 실제 작업 폴더에서 `python -m engrbot run … --layers …L4,L5…`을 끝까지 돌려 보지 않았다(단위·통합 테스트와 합성 fixture까지만 확인했다).

다음에 할 일: 도메인 규칙 내용을 정해 `engrbot/defaults/domain_rules.json`에서 `approved`로 올리기, 2절 오른쪽 열의 미룬 항목.
