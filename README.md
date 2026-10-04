# BEOL 비정형 자료 자동 라벨링 (labelbot)

사외 구동 기준(Python 3.14.2, 표준 라이브러리만). 설계는 `PRD.md`, 구현 단계는 `plan.md`, 최우선 규칙은 `CLAUDE.md`를 따른다.

## 준비

1. 키: 코드 폴더의 `.env.example`을 `.env`로 복사하고 `OPENAI_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`를 채운다(셸 환경변수가 있으면 그 값이 우선한다). `.env`는 커밋하지 않는다.
2. 작업 폴더: 코드 폴더 **밖**에 만든다. 첫 실행 때 기본 `pipeline.json`이 생긴다.
3. taxonomy: `defaults/taxonomy.xlsx`를 작업 폴더에 `taxonomy.xlsx`로 복사하거나, `pipeline.json`의 `taxonomy_path`로 가리킨다.
4. Supabase 표: `docs/supabase_schema.md`의 SQL을 실행한다.
5. 의존성: 본체는 설치가 필요 없다(`requirements.txt`는 비어 있다). 사외 PoC SDK는 `requirements-poc.txt`.

## 명령

```bash
python -m labelbot selfcheck --workspace <작업 폴더> --probe-llm
python -m labelbot run --workspace <작업 폴더> --input <입력 폴더>
python -m labelbot compare --workspace <작업 폴더>
python -m labelbot review --workspace <작업 폴더>
python -m labelbot apply --workspace <작업 폴더>
python -m labelbot report --workspace <작업 폴더> --run <실행 ID>
python -m labelbot embed --workspace <작업 폴더>
python -m labelbot push-vectors --workspace <작업 폴더>
```

- `run`: 수집 → 파싱·chunk → 1차 분류 → 2차 질문 매핑 → 3차 라벨링 → H5 알림 → 4차 불량 목록 → 후보 리포트 → 산출(`out/labeling.sqlite`, `SCHEMA.md`) → 기준선 리포트. `embed`·`push-vectors`는 따로 부른다.
- 화면은 `python -m labelbot serve --workspace <작업 폴더> --port <포트>`로 띄운다. 검수·대조 화면에서 체크하면 `inbox/`에 `.json`이 바로 저장되고, `apply`로 반영한다(로컬 파일로 열었으면 **JSON 저장**으로 내려받아 `inbox/`에 넣는다).
- 같은 입력으로 다시 돌리면 LLM 호출은 0회다(실패 chunk만 재시도).

## gpt-6-sol 설정 예

이 모델은 temperature 기본값만 받고 `max_tokens` 대신 `max_completion_tokens`를 쓴다.

```json
{"llm": {"model": "gpt-6-sol", "temperature": null, "max_tokens": null,
         "max_tokens_param": "max_completion_tokens", "response_format_json": true, "timeout": 180, "workers": 6},
 "supabase": {"enabled": true, "table": "beol_chunk_embeddings"}}
```

## 테스트

```bash
python -m unittest discover tests
```

## 사외 전송 안전장치

LLM·임베딩·Supabase 호출은 모두 `labelbot/llm.py`의 공용 함수를 거친다. 호스트가 `internal_host_suffixes`에 없으면 사외이고, 사외에는 파일 해시가 `tests/gold/dummy_hashes.jsonl`에 있는 chunk만 보낸다. 리다이렉트는 따라가지 않는다.
