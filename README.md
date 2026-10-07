# BEOL 비정형 자료 자동 라벨링 (labelbot)

사외 구동 기준(Python 3.14.2, 표준 라이브러리만). 설계는 `PRD.md`, 구현 단계는 `plan.md`, 최우선 규칙은 `CLAUDE.md`를 따른다.

## 구성 (S4 역할 지도)

`docs/project_intro.html`의 S4 슬라이드 역할을 코드에 대응시킨 표다.

| S4 역할 | 위치 |
|---|---|
| Orchestrator | Claude Code 메인 세션. 코드는 없고 아래 skill을 순서대로 부른다 |
| BEOL-labeling / BEOL-labeling-feedback | `labelbot/` + `.claude/skills/BEOL-labeling*` |
| 검수 엔지니어 | `review.html`·`compare.html` 화면(`labelbot review`·`compare`) |
| workspace | `workspaces/` (작업 폴더, 커밋 제외) |
| Domain-Engr-bot (도메인 질문 agent) | `domain_engrbot/` + `.claude/skills/BEOL-labeling-Domain-Engr-bot`. 검수 결과로 엔지니어에게 질문해 확정한 도메인 지식을 규칙·taxonomy 제안으로 돌려준다 |
| Code-Engr-bot (감시 agent) | `code_engrbot/` + `.claude/skills/BEOL-labeling-Code-Engr-bot` |

## 스킬 지도

스킬은 13개이고 `.claude/skills/<이름>/SKILL.md`에 평평하게 둔다(그룹 폴더를 따로 만들지 않는다). 그룹·상하위 관계의 원본은 `.claude/skills/BEOL-labeling-project-html/assets/skill_map.json`이고, 발표 HTML의 Appendix(스킬 지도)도 이 파일로 그린다. 각 `SKILL.md` 제목 아래 `> 그룹:` 줄에 같은 관계를 적었다.

| 그룹 | 스킬 | 한 줄 역할 | 부르는 시점 |
|---|---|---|---|
| ① 라벨링 파이프라인 | `/BEOL-labeling-run-labeling` | 입력 → 라벨링 → 검수 → 적재를 한 번에 잇는다 | 새 자료를 처음부터 적재까지 돌릴 때 |
| | └ `/BEOL-labeling` | 파싱 → 분류 → 라벨링 뒤 검수 화면을 띄우고 멈춘다 | 라벨링 단계만 돌릴 때 |
| | └ `/BEOL-labeling-feedback` | 검수 교정 반영 → 임베딩 → Supabase 적재 | 검수 화면에서 "검수 완료"를 누른 뒤 |
| ② 품질 점검 · 재라벨링 | `/BEOL-labeling-Domain-Engr-bot` | 검수 결과로 엔지니어에게 질문하고, 확정한 답을 규칙·taxonomy 제안으로 보낸다 | 적재가 끝난 뒤 사람이 시작한다 |
| | └ `/BEOL-taxonomy-dashboard` | 흩어진 taxonomy 수정 제안을 모아 확정분을 taxonomy.json에 반영한다 | taxonomy를 고칠 때 |
| | `/BEOL-labeling-Code-Engr-bot` | 코드 검수(읽기 전용)와 축·규칙 변경 감지 | 코드를 고친 뒤, taxonomy·규칙을 바꾼 뒤 |
| | └ `/BEOL-labeling-rules-update` | 라벨링 규칙이 바뀐 범위만 다시 라벨링한다(검수 없음) | Code-Engr-bot이 규칙 변경을 찾으면 자동 |
| | └ `/BEOL-labeling-axis-update` | taxonomy 축이 바뀐 부분만 다시 라벨링한다 | Code-Engr-bot이 축 변경을 찾으면 자동 |
| ③ 화면 · 발표 · 운영 리포트 | `/BEOL-labeling-workflow` | 단계별 workflow HTML(`docs/workflow.html`)을 다시 만든다 | 워크플로 소개를 최신 수치로 바꿀 때 |
| | `/BEOL-labeling-project-html` | 발표 HTML의 파일럿 슬라이드·스킬 지도를 갱신한다 | 새 실행 뒤, 발표 전 |
| | `/BEOL-labeling-change-dashboard` | 세션별 변경 내역 대시보드를 만든다 | 3시간 주기 예약 작업, PM 점검 때 |
| | `/BEOL-labeling-daily-report` | 밤 자동 실행 결과를 아침 할 일 리포트 HTML로 만든다 | 아침에 밤사이 결과를 볼 때 |
| | `/BEOL-labeling-RAG-html` | RAG 대화 화면을 띄우고 답변 서버 함수를 배포한다 | RAG 화면을 열거나 답변 프롬프트를 바꿨을 때 |

- ①의 적재가 끝나면 ②를 시작한다. 품질 점검 스킬은 run-labeling이 자동으로 부르지 않는다.
- 새 스킬을 만들면 `skill_map.json`에 넣는다. 빠지면 발표 HTML에서 '미분류'로 보인다.

## 저장소 구조

| 경로 | 내용 |
|---|---|
| `labelbot/` | 라벨링 본체(수집·파싱·분류·라벨링·검수 화면·임베딩·적재) |
| `domain_engrbot/` | Domain-Engr-bot 본체(도메인 질문·승인 규칙 관리·taxonomy 보드·편집기). 아래 "domain_engrbot (도메인 질문)" 절 |
| `code_engrbot/` | Code-Engr-bot 본체(코드 검수). 결과 `code_engrbot/out/`은 커밋 제외 |
| `tests/` | labelbot 테스트와 외부 계약(`tests/contracts/`). 더미 폴더 위치는 `tests/_dummy.py`가 정한다 |
| `prompts/` | labelbot 프롬프트. 코드가 이 경로를 읽으므로 옮기지 않는다 |
| `taxonomy/` | `taxonomy.json`(원본)과 `labeling_rules.json`(승인 규칙) |
| `injested-file-list/` | 수집 이력. 옮기지 않는다 |
| `rag/` | RAG 대화 화면(`beol_rag.html`)과 Edge Function(`functions/beol-rag-ask/`) |
| `change-dashboard/` | 세션 변경 대시보드. 생성물은 커밋 제외 |
| `docs/` | 발표·문서(`project_intro.html`, `workflow.html`, `supabase_schema.md` 등). 정리 작업에서는 손대지 않는다 |
| `workspaces/` | 작업 폴더(사내 자료 b64·DB 포함, 커밋 제외) |
| `parshing test files/` | `/BEOL-labeling` 기본 입력 폴더 |
| `dummy pprx files_2nd revised/` | 더미 자료 2차 수정본 |
| `CLAUDE.md` · `PRD.md` · `plan.md` | 최우선 규칙 · 설계 · 구현 단계 |
| `DESIGN.md` · `design.md.md` · `PRODUCT.md` | RAG 화면 디자인 · HTML 화면 디자인 토큰 · 제품 맥락(디자인 도구용) |
| `nightly_run.py` · `daily_report.py` | 두 봇을 사람 없이 돌려 아침 할 일을 남김 · 그 결과를 아침 리포트 HTML로 |
| `.claude/` | `skills/`(13개 스킬)와 `launch.json`(미리보기 서버 목록) |
| `.omc/` · `.impeccable/` · `.superdesign/` | 도구 작업 폴더. `.omc/`는 커밋 제외(`.omc/skills/`만 커밋) |

- 2026-10-08 정리에서 참조 없는 잔여물(목업, 지난 도구 산출물, 오래된 검수 결과 등)을 저장소 옆 `../261004 BEOL AX day2 _archive_20261008/`로 옮겼다. 옮긴 파일과 원래 경로는 그 폴더의 `MANIFEST.jsonl`에 있다.

## 준비

1. 키: 코드 폴더의 `.env.example`을 `.env`로 복사하고 `OPENAI_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`를 채운다(셸 환경변수가 있으면 그 값이 우선한다). `.env`는 커밋하지 않는다.
2. 작업 폴더: 코드 폴더의 `workspaces/` 아래에 만든다(예: `workspaces/261004_BEOL_x`, 커밋 제외). 첫 실행 때 기본 `pipeline.json`이 생긴다.
3. taxonomy: 원본은 `taxonomy/taxonomy.json`이다(2026-10-07부터 xlsx 대신 json). 작업 폴더의 `pipeline.json` `taxonomy_path`가 이 파일을 가리킨다. 사람은 Excel이 아니라 taxonomy 보드(`python -m domain_engrbot taxonomy-board --serve --open`)나 편집기(`python -m domain_engrbot taxonomy-editor --open`)로 고친다. 예전 xlsx는 `python -m labelbot taxonomy-migrate`로 한 번 변환한다.
   - 새 축 추가: 축 정의 행 D~G·H, 값 행, questions 행을 채우는 체크리스트는 `.claude/skills/BEOL-taxonomy-dashboard/SKILL.md`의 "새 축 체크리스트"에 있다. `python -m labelbot taxonomy-diff --workspace <작업 폴더>`로 지난 실행과의 차이를 본다. taxonomy를 바꾼 뒤 테스트 자료를 다시 만드는 순서는 아래 "taxonomy를 바꾼 뒤"를 따른다.
4. Supabase 표: `docs/supabase_schema.md`의 SQL을 실행한다.
5. 의존성: 본체는 설치가 필요 없다(`requirements.txt`는 비어 있다). 사외 PoC SDK는 `requirements-poc.txt`.

## 명령

```bash
python -m labelbot selfcheck --workspace <작업 폴더> --probe-llm
python -m labelbot probe --workspace <작업 폴더>
python -m labelbot ingest --workspace <작업 폴더> --input <입력 폴더>
python -m labelbot run --workspace <작업 폴더> --input <입력 폴더>
python -m labelbot compare --workspace <작업 폴더>
python -m labelbot review --workspace <작업 폴더>
python -m labelbot apply --workspace <작업 폴더>
python -m labelbot report --workspace <작업 폴더> --run <실행 ID>
python -m labelbot dashboard --workspace <작업 폴더>
python -m labelbot embed --workspace <작업 폴더>
python -m labelbot push-vectors --workspace <작업 폴더> [--force]
python -m labelbot slide-images --workspace <작업 폴더>
python -m labelbot push-slides --workspace <작업 폴더>
python -m labelbot axis-update --workspace <작업 폴더> [--dry-run]
python -m labelbot axis-board --workspace <작업 폴더> [--run <실행 ID>]
python -m labelbot rules-diff --workspace <작업 폴더>
python -m labelbot rules-update --workspace <작업 폴더> [--dry-run]
python -m labelbot rules-board --workspace <작업 폴더> [--run <실행 ID>]
```

- `probe`: 파일 구조 통계만 낸다(본문 미출력). `ingest`: 수집·파싱·chunk까지만 한다. `dashboard`: 결과 대시보드 화면을 만든다. `serve`: 화면 서버(아래).
- `run`: 수집 → 파싱·chunk → 1차 분류 → 2차 질문 매핑 → 3차 라벨링 → H5 알림 → 4차 불량 목록 → 후보 리포트 → 산출(`out/labeling.sqlite`, `SCHEMA.md`) → 기준선 리포트. `embed`·`push-vectors`는 따로 부른다.
- 화면은 `python -m labelbot serve --workspace <작업 폴더> --port <포트>`로 띄운다. 검수·대조 화면에서 체크하면 `inbox/`에 `.json`이 바로 저장되고, `apply`로 반영한다(로컬 파일로 열었으면 **JSON 저장**으로 내려받아 `inbox/`에 넣는다).
- 검수 화면에서 **검수 완료**를 누르면 화면이 잠기고 "반영·적재 진행 중" 안내만 보인다. 서버의 `GET /inbox/status?run=<실행ID>`가 그 실행의 완료 신호 존재를 알려 줘서 새로고침해도 잠금이 유지된다.
- 같은 입력으로 다시 돌리면 LLM 호출은 0회다(실패 chunk만 재시도).
- `axis-update`·`axis-board`: taxonomy 축이 바뀐(추가·삭제·변경·값 추가·값 삭제) 작업 폴더에서 이전 라벨을 이어받고 바뀐 축만 1차 분류로 다시 라벨링한다(입력 폴더는 다시 읽지 않는다, `--dry-run`은 대상 축·건수만 출력). 이어서 `review`(대상 축만 편집, 나머지 축은 잠금)와 `axis-board`(축별 불량·처리 결과 카드와 슬라이드별 새 축 값 현황판 `screens/axis_update.html`, 기본 `--run`은 최신 라벨 실행이고 axis-update 실행이 아니면 오류)를 만든다. 절차는 `.claude/skills/BEOL-labeling-axis-update/SKILL.md`.
- `slide-images`: 검수 화면과 같은 슬라이드 근사 미리보기를 headless Edge/Chrome으로 JPG 캡처해 `slide_images/<sha256>.b64`에 둔다(`.jpg` 파일은 쓰지 않는다). `out/labeling.sqlite`의 `chunks.slide_image`에 기록한다. 브라우저 경로는 `render.browser_path`. Edge가 포트를 열기 전에 바로 종료하면(`RENDERER_EXITED`, 기존 Edge 인스턴스·정책 때문일 수 있다) 다음 후보인 Chrome으로 자동 전환한다. 둘 다 실패하면 `render.browser_path`에 띄워지는 브라우저 경로를 지정하고, 포트 대기 초과는 `RENDERER_PORT_TIMEOUT`이다. 지정한 `render.browser_path`가 파일이 아니면 `RENDERER_MISSING`이다. 후보를 차례로 시도하므로 최대 대기는 후보 수 × 시작 대기 시간이다.
- 검수 피드백 환류: 생산은 Domain-Engr-bot, 소비는 labelbot이다. `domain_engrbot intake`가 작업 폴더 교정을 장부(`workspaces/_domain_engrbot/ledger/`)로 모으고, `domain_engrbot labeling-rules candidates`가 규칙 후보(축 값 혼동·과잉·누락, 질문 답 뒤집힘)와 few-shot 사례 후보를 `labeling_candidates.md`(본문 없음)로 쓴다. 후보는 Domain-Engr-bot 도메인 질문의 재료가 되고, Domain-Engr-bot 질문 화면에서 엔지니어가 확정한 규칙·사례가 `taxonomy/labeling_rules.json`(승인 시 생성, 본문 없음. 지금은 git이 추적하지 않는다. `questions apply`는 바꾸기 전 본을 `workspaces/_domain_engrbot/questions/rules_history.jsonl`에 남긴다)에 남는다(문장·enabled는 사람이 고칠 수 있다. `labeling-rules approve`·`reject` 명령은 남아 있다). 다음 `labelbot run`은 승인 규칙을 1차 분류·3차 라벨링 프롬프트에 "검수 피드백 지침"으로, 승인 사례를 비슷한 chunk의 1차 분류에 few-shot으로 넣는다. 사례 본문은 원래 작업 폴더의 `work.sqlite`에서 읽기 전용으로 가져온다(그 폴더가 없거나 본문이 바뀌었으면 빠진다. 같은 파일·같은 본문 제외). `run --no-feedback`이면 넣지 않는다.
- `rules-diff`·`rules-update`·`rules-board`: 라벨링 규칙(`taxonomy/labeling_rules.json`)이 바뀐 작업 폴더에서 기준 실행 대비 바뀐 규칙(추가·수정·끄기·기각)을 찾고(`rules-diff`, 규칙 id·건수만 출력), 그 규칙이 닿는 범위만 LLM으로 다시 라벨링한다(`rules-update`, `--dry-run`은 대상만 출력). 축 규칙은 그 축 전체 chunk의 1차 분류만, 답 규칙은 그 질문의 O/X만 다시 매기고, 사람이 교정·확인한 값은 건드리지 않는다. 사람 검수 없이 바로 반영하며 `rules-board`가 규칙별 카드와 값이 바뀐 슬라이드(이전 → 지금) 현황판 `screens/rules_update.html`을 만든다(기본 `--run`은 최신 라벨 실행이고 rules-update 실행이 아니면 오류). 값이 바뀐 비율이 `rules_update.max_change_ratio`(기본 0.3)를 넘으면 Supabase 적재만 `RULES_CHANGE_RATIO_HIGH`로 보류하며, 현황판을 확인한 뒤 `push-vectors --force`로 보낸다. 보류된 실행이 있으면 다음 axis-update·rules-update는 `PREV_PUSH_PENDING`으로 건너뛴다. 절차는 `.claude/skills/BEOL-labeling-rules-update/SKILL.md`.
- `push-slides`: `supabase.storage_enabled=true`이면 JPG를 Storage `BEOL-labeling` 버킷에 올리고 `beol_chunk_embeddings` 행의 `slide_image_*` 열을 채운다. `push-vectors` 다음에 부른다. 스키마는 `docs/supabase_schema.md`.

## 라벨링 규칙 바꾸기

- Domain-Engr-bot 질문 화면에서 엔지니어가 확정한 규칙·사례(또는 승인 규칙 관리의 끄기·수정)가 `taxonomy/labeling_rules.json`을 바꾼다. 규칙 초안에는 대상 축(3차면 `축=값` 또는 질문 id)을 반드시 쓴다.
- Code-Engr-bot이 작업 폴더마다 `taxonomy-diff`와 `rules-diff`를 돌려 규칙이 바뀐 작업 폴더를 찾는다(`/BEOL-labeling-Code-Engr-bot`, "규칙 점검").
- 걸린 폴더는 묻지 않고 `/BEOL-labeling-rules-update`가 자동으로 돈다: 바뀐 규칙 범위만 재라벨링 → 현황판 → 임베딩·Supabase 적재. 사람 검수 대기는 없고, 변경 비율이 상한을 넘으면 적재만 보류한다. 같은 폴더에 축 변경도 있으면 axis-update가 먼저다.
- 대상 축이 없는 규칙(단계 전체 규칙)과 few-shot 사례 변경은 재라벨링하지 않고 건수만 보고한다. 다음 전체 `/BEOL-labeling`에서 반영된다.

## domain_engrbot (도메인 질문)

사람 검수 결과(교정·재검토 요청·검수 등록 동의어)와 누적 교정 장부를 읽고, LLM으로 엔지니어에게 물을 질문 10개 안팎을 만든다. 사람이 질문 화면에서 답하고 초안(규칙 문장·taxonomy 행)을 고쳐 확정한 것만 `taxonomy/labeling_rules.json`(다음 `labelbot run` 프롬프트)과 taxonomy 수정 보드(출처 S7 "엔지니어 답변")로 보낸다. 봇은 결정을 만들지 않는다. taxonomy.json은 사람이 보드에서 확정한 것만 쓴다(2026-10-06 사용자 결정, 2026-10-07 개정). 설계는 `domain_engrbot/docs/plan-question-loop.md`.

```bash
python -m domain_engrbot workspaces                                         # 작업 폴더 목록(JSON): state + question_state(no_review·new·asked) + review_runs, 최상위 questions
python -m domain_engrbot intake --workspace <작업 폴더>                      # 작업 폴더의 사람 교정 → 교정 장부(LLM 0회)
python -m domain_engrbot questions generate --workspace <작업 폴더> [--force] [--max N]
python -m domain_engrbot questions status --workspace <작업 폴더>             # 건수 JSON(열린 질문, inbox 답 파일)
python -m domain_engrbot questions screen --workspace <작업 폴더>             # 질문 화면만 다시 만든다
python -m domain_engrbot questions serve --workspace <작업 폴더> [--port N] [--no-draft] [--no-apply]   # 질문 화면 서버, 답변 완료 · 저장 → qa/inbox에 저장하고 바로 반영, 서버 종료
python -m domain_engrbot questions apply --workspace <작업 폴더> [--answers <답 파일>]
python -m domain_engrbot labeling-rules review|apply|status --workspace <작업 폴더>         # 승인된 규칙·사례 관리
python -m domain_engrbot taxonomy-board [--workspace <작업 폴더>] [--serve] [--open] [--reset]    # taxonomy 수정 보드(제안 통합·카드 편집·최종 완료 시 taxonomy.json 저장, --serve)
python -m domain_engrbot taxonomy-editor [--open]                                      # taxonomy 편집기(axis→value 트리, 미리보기·검증·저장, 127.0.0.1:8796)
```

| 파일 (`workspaces/_domain_engrbot/questions/`) | 내용 |
|---|---|
| `questions.json` · `engr_questions.html` | 지금 열린 질문 묶음과 질문 화면(본문 있음) |
| `answers.jsonl` · `taxonomy_proposals.jsonl` | 답 이력, 보드 출처 S7 입력(본문 있음) |
| `asked.json` · `generate_log.jsonl` · `rules_history.jsonl` | 답함·묻지 않음 지문, 생성 이력, 승인 파일 이전 본 |
| `<작업 폴더>/qa/inbox/engr_answers_<set_id>.json` | 질문 화면이 저장한 답 |

- 하위 명령 전체는 `python -m domain_engrbot --help`로 본다. skill(`BEOL-labeling-Domain-Engr-bot`)은 `workspaces`·`intake`·`questions`·`labeling-rules`·`taxonomy-board`·`ledger`를 쓴다. 새 규칙·사례 후보의 승인은 질문 화면에서 하고, 승인 화면(`workspaces/_domain_engrbot/ledger/labeling_review.html`)에는 승인된 규칙·사례 관리만 남는다. `BEOL-labeling`은 승인 파일을 읽기만 한다.
- 예전 도메인 검수 명령(`run`·`review`·`report`·`serve`·`golden`·`feedback`·`eval`·`baseline`, L0~L6 검사)은 남아 있지만 skill은 쓰지 않는다.
- 작업물은 `domain_engrbot/`와 `workspaces/_domain_engrbot/`에 둔다.

## code_engrbot (코드 검수)

```bash
python -m code_engrbot review --root .
python -m code_engrbot rules
```

- 읽기 전용이다. 저장소 코드와 workflow가 루트 `CLAUDE.md` 규칙(C1 DRM·쓰기, C2 stack, C3 단계 계약, C4 완료 위생)을 지키는지 정적으로 본다.
- skill은 `BEOL-labeling-Code-Engr-bot`이다.
- 정책 파일(`--policy`)의 경로 glob은 대소문자를 구분하고, `*`는 `/`를 넘지 않는다(여러 폴더는 `**`).

## gpt-6-sol 설정 예

이 모델은 temperature 기본값만 받고 `max_tokens` 대신 `max_completion_tokens`를 쓴다.

```json
{"llm": {"model": "gpt-6-sol", "temperature": null, "max_tokens": null,
         "max_tokens_param": "max_completion_tokens", "response_format_json": true, "timeout": 180, "workers": 6},
 "supabase": {"enabled": true, "table": "beol_chunk_embeddings"}}
```

## 테스트

```bash
python -m unittest discover tests            # labelbot (+ tests/contracts 외부 계약)
python -m unittest discover -s domain_engrbot/tests -t .   # domain_engrbot (golden 포함)
python -m unittest discover -s code_engrbot/tests -t .   # code_engrbot
python -m pytest -q -p no:cacheprovider                    # 전체를 pytest로(캐시 폴더를 만들지 않는다)
```

- 더미 pptx 입력은 저장소 밖 `<저장소>/../dummy pptx files`에 고정한다(2026-10-08 이동, 더 옮기지 않는다). 경로는 `tests/_dummy.py` 한 곳에서 정하고, 파일별 gold sha는 `tests/gold/dummy_hashes.jsonl`에 있다.
- 더미 폴더가 없으면 테스트를 건너뛰지 않고 `DUMMY_DIR_NOT_FOUND` 오류로 멈춘다(skip은 핵심 파이프라인 커버리지를 숨긴다).

- 외부 계약 스냅샷(`tests/contracts/snapshots/`)을 의도해서 바꿀 때: `CONTRACT_UPDATE=1`을 붙여 다시 쓴다.
- domain_engrbot 실행 산출물 golden(`domain_engrbot/tests/golden_outputs/`)을 의도해서 바꿀 때: `GOLDEN_UPDATE=1`을 붙여 다시 쓴다.


### taxonomy를 바꾼 뒤

1. taxonomy 보드나 편집기로 `taxonomy/taxonomy.json`을 수정한다.
2. `python tests/tools/dump_taxonomy_fixture.py`로 `tests/fixtures/default_taxonomy_rows.jsonl`을 다시 만든다(`--check`는 최신인지 건수만 보고).
3. `GOLDEN_UPDATE=1 python -m unittest tests.test_golden_run`으로 golden을 다시 쓴다.
4. `python -m unittest discover -s tests -t .`로 전체를 확인한다.
5. 외부 계약이 바뀌었으면 `CONTRACT_UPDATE=1`을 붙여 스냅샷을 다시 쓴다.

## 사외 전송 안전장치

## RAG 화면 (rag/) 여는 법

미리보기 `rag-ui` 항목을 선택하거나:

```bash
python -m http.server 8795 --bind 127.0.0.1 --directory rag
```

그 뒤 http://127.0.0.1:8795/beol_rag.html에서 열 수 있다.

**비밀값 설정**: Supabase 대시보드 → Edge Functions → Secrets에 `OPENAI_API_KEY`를 넣는다. `RAG_CHAT_MODEL`(기본 `gpt-6-sol`)도 선택 설정 가능하다.

**비용**: OpenAI에 월별 사용 한도 설정을 권장한다(이 데모는 호출 제한이 없다).

**SQL 구조**: `docs/supabase_schema.md`의 "RAG 화면용 읽기 창·검색대·피드백 표" 절을 참고한다.

**코드 규칙**: `rag/`는 HTML·Edge Function(TypeScript)이라 Code-Engr-bot 본체 규칙(표준 라이브러리만) 대상에서 뺐다(`code_engrbot/defaults/policy.json`의 `exclude`).

LLM·임베딩·Supabase 호출은 모두 `labelbot/llm.py`의 공용 함수(`check_send`)를 거친다. PoC에서는 사외·사내를 구분하지 않는다(2026-10-05 사용자 결정). 더미 해시 대조는 없고, 호스트를 판정할 수 없는 URL(빈 값, IP 리터럴, http(s) 아님)만 `HOST_UNCERTAIN`으로 막는다. 사내 파일이 사외로 나가는 것을 막는 장치가 없으므로 PoC가 끝나면 되돌린다. 리다이렉트는 따라가지 않는다.
