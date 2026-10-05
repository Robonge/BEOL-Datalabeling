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
| Engr-bot (감시 agent) | `engrbot/` + `.claude/skills/labeling-Engr-bot` |
| code-bot (감시 agent) | `codebot/` + `.claude/skills/labeling-codebot` |

## 준비

1. 키: 코드 폴더의 `.env.example`을 `.env`로 복사하고 `OPENAI_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`를 채운다(셸 환경변수가 있으면 그 값이 우선한다). `.env`는 커밋하지 않는다.
2. 작업 폴더: 코드 폴더의 `workspaces/` 아래에 만든다(예: `workspaces/261004_BEOL_x`, 커밋 제외). 첫 실행 때 기본 `pipeline.json`이 생긴다.
3. taxonomy: `taxonomy/taxonomy.xlsx`를 작업 폴더에 `taxonomy.xlsx`로 복사하거나, `pipeline.json`의 `taxonomy_path`로 가리킨다.
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
python -m labelbot push-vectors --workspace <작업 폴더>
python -m labelbot slide-images --workspace <작업 폴더>
python -m labelbot push-slides --workspace <작업 폴더>
```

- `probe`: 파일 구조 통계만 낸다(본문 미출력). `ingest`: 수집·파싱·chunk까지만 한다. `dashboard`: 결과 대시보드 화면을 만든다. `serve`: 화면 서버(아래).
- `run`: 수집 → 파싱·chunk → 1차 분류 → 2차 질문 매핑 → 3차 라벨링 → H5 알림 → 4차 불량 목록 → 후보 리포트 → 산출(`out/labeling.sqlite`, `SCHEMA.md`) → 기준선 리포트. `embed`·`push-vectors`는 따로 부른다.
- 화면은 `python -m labelbot serve --workspace <작업 폴더> --port <포트>`로 띄운다. 검수·대조 화면에서 체크하면 `inbox/`에 `.json`이 바로 저장되고, `apply`로 반영한다(로컬 파일로 열었으면 **JSON 저장**으로 내려받아 `inbox/`에 넣는다).
- 같은 입력으로 다시 돌리면 LLM 호출은 0회다(실패 chunk만 재시도).
- `slide-images`: 검수 화면과 같은 슬라이드 근사 미리보기를 headless Edge/Chrome으로 JPG 캡처해 `slide_images/<sha256>.b64`에 둔다(`.jpg` 파일은 쓰지 않는다). `out/labeling.sqlite`의 `chunks.slide_image`에 기록한다. 브라우저 경로는 `render.browser_path`.
- 검수 피드백 환류: 생산은 Engr-bot, 소비는 labelbot이다. `engrbot intake`가 작업 폴더 교정을 장부(`workspaces/_engrbot/ledger/`)로 모으고, `engrbot labeling-rules candidates`가 규칙 후보(축 값 혼동·과잉·누락, 질문 답 뒤집힘)와 few-shot 사례 후보를 `labeling_candidates.md`(본문 없음)로 쓴다. `approve`·`reject`(`--ids FR-…,EX-…`, `--all`, `--examples all`)로 사람이 고른 것만 `taxonomy/labeling_rules.json`(승인 시 생성)(본문 없음, git 추적)에 남는다(문장·enabled는 사람이 고칠 수 있다). 다음 `labelbot run`은 승인 규칙을 1차 분류·3차 라벨링 프롬프트에 "검수 피드백 지침"으로, 승인 사례를 비슷한 chunk의 1차 분류에 few-shot으로 넣는다. 사례 본문은 원래 작업 폴더의 `work.sqlite`에서 읽기 전용으로 가져온다(그 폴더가 없거나 본문이 바뀌었으면 빠진다. 같은 파일·같은 본문 제외, 사외 가드 통과 파일만). `run --no-feedback`이면 넣지 않는다.
- `push-slides`: `supabase.storage_enabled=true`이면 JPG를 Storage `BEOL-labeling` 버킷에 올리고 `beol_chunk_embeddings` 행의 `slide_image_*` 열을 채운다. `push-vectors` 다음에 부른다. 스키마는 `docs/supabase_schema.md`.

## engrbot (도메인 검수)

```bash
python -m engrbot run --workspace <작업 폴더>
python -m engrbot intake --workspace <작업 폴더>
python -m engrbot review|report|ledger|eval|golden|feedback|baseline|codes ...
python -m engrbot labeling-rules candidates|status --workspace <작업 폴더>
python -m engrbot labeling-rules approve --workspace <작업 폴더> --all --examples all
```

- 하위 명령 전체는 `python -m engrbot --help`로 본다. skill(`labeling-Engr-bot`)은 `intake`·`run`·`review`·`report`·`eval`·`ledger`·`labeling-rules`를 쓴다.
- 구조 게이트(L0~L3B, L6) 위에 도메인 규칙 층 L4와 중복 문서 일관성 층 L5를 켜서 라벨링 결과를 검수한다.
- 작업물은 `engrbot/`와 `workspaces/_engrbot/`에 둔다.

## codebot (코드 검수)

```bash
python -m codebot review --root .
python -m codebot rules
```

- 읽기 전용이다. 저장소 코드와 workflow가 루트 `CLAUDE.md` 규칙(C1 DRM·쓰기, C2 stack, C3 단계 계약, C4 완료 위생)을 지키는지 정적으로 본다.
- skill은 `labeling-codebot`이다.

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
python -m unittest discover -s engrbot/tests -t .   # engrbot (golden 포함)
python -m unittest discover -s codebot/tests -t .   # codebot
```

- 외부 계약 스냅샷(`tests/contracts/snapshots/`)을 의도해서 바꿀 때: `CONTRACT_UPDATE=1`을 붙여 다시 쓴다.
- engrbot 실행 산출물 golden(`engrbot/tests/golden_outputs/`)을 의도해서 바꿀 때: `GOLDEN_UPDATE=1`을 붙여 다시 쓴다.

## 사외 전송 안전장치

LLM·임베딩·Supabase 호출은 모두 `labelbot/llm.py`의 공용 함수를 거친다. 호스트가 `internal_host_suffixes`에 없으면 사외이고, 사외에는 파일 해시가 `tests/gold/dummy_hashes.jsonl`에 있는 chunk만 보낸다. 리다이렉트는 따라가지 않는다.
