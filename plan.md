# plan: BEOL 비정형 자료 자동 라벨링 파이프라인 MVP

- 작성일: 2026-10-04
- 상태: pending approval (이 문서는 계획이며, 구현은 별도 승인 후 시작한다)
- 요구사항 원문: `PRD.md`

## 1. 요구사항 요약

사내 pptx 위주 파일 100개를 chunk로 나누고, 봇이 분류 축 8개와 상태 축 2개의 값을 판정하고 open_risk O/X 라벨링을 한 뒤 unknown이 많거나 라벨링이 불량한 chunk를 불량 목록으로 뽑아 사람이 검수·교정해, LLM이 SQL로 조회할 수 있는 SQLite 파일을 만든다. 첫 실행은 기준선 측정이 목적이다.

구현을 좌우하는 제약은 다음과 같다.

- 사외에서 작성해 GitHub에 올리고, 사내에서 zip으로 내려받아 설치 없이 실행한다(`PRD.md` 3절, 9.1절).
- 사내 파일은 DRM이 걸려 있다. Python으로 읽어 base64로 저장하는 것이 첫 단계이고, 이후에는 base64만 읽어 메모리에서 디코딩한다(`PRD.md` FR-0).
- 사내 자료는 코드 폴더 밖 작업 폴더에 둔다(`PRD.md` 9.2절).
- taxonomy·질문·동의어는 사람이 Excel에서 고치는 `taxonomy.xlsx` 하나(필수 시트 4개 + 선택 시트 2개)에 두고, 봇은 읽기만 한다. 후보는 `reports/`의 `.md`·`.jsonl` 리포트로 내고 사람이 붙여넣는다(`PRD.md` 6절).
- 동의어는 `synonyms` 시트에서 치환만 하며, 1차 분류와 3차 라벨링이 같은 시트를 참조한다(`PRD.md` 6.2절).
- 4차는 "4차 불량 목록 추출"이다(`PRD.md` FR-5). LLM을 부르지 않고 이미 저장된 값만으로 사유 코드 6개를 판정해, 걸린 chunk를 상한 없이 전부 목록으로 내고 검수 화면에 올린다. 사내 정확도는 측정하지 않는다.
- `CLAUDE.md`가 우선한다. 원본 경로는 ingest(`read_input`) 한 곳에서만 열고, 봇과 도구는 `.xlsx .csv .txt .pptx` 같은 office·텍스트 확장자를 디스크에 쓰지 않는다. 허용 형식은 `.b64 .sqlite .json .jsonl .html .md .log`다.
- 표준 라이브러리만 쓰고 Python 3.14.2 기준으로 작성한다(사외 구동 기준). 사내 Python 버전은 M7에서 self-check로 확인한다.
- 사외 검증은 `dummy pptx files/` 폴더의 파일(정답표 필수층과 합성 픽스처)과 LLM mock, 테스트 안에서 띄운 `http.server` mock 서버로 한다.
- 지금은 사외 OpenAI API 기준으로 만들고, 사내 반입 후 사용자가 `pipeline.json`의 `llm`, `embedding`, `supabase` 세 블록만 고친다. 사내 자료가 사외 호스트로 나가지 않도록 LLM·임베딩·벡터 적재 호출은 모두 `llm.py`의 공용 호스트 판정 함수를 거친다(`internal_host_suffixes`, 더미 해시 목록, 리다이렉트 거부).

## 2. 디렉터리 구조

### 저장소(코드 폴더)

```
labelbot/
  __main__.py        명령 진입점
  cli.py             명령과 인자 처리
  workspace.py       작업 폴더 경로, 코드 폴더 안 지정 거부
  selfcheck.py       환경 self-check (작업 폴더에 taxonomy.xlsx가 없으면 FAIL), write_roundtrip, 호스트 판정 항목
  probe.py           파일 구조 통계 (본문 미출력)
  ingest.py          0단계: base64 저장, 해시, 실패 목록, 상대 경로와 file_locations 기록. read_input(path, snapshot_dir): 사람 입력 bytes 읽기, 시그니처 확인, inputs/ 보관, 텍스트 인코딩
  ooxml.py           base64 디코딩과 zip·XML 읽기 공통 기능, bytes 기반 xlsx 읽기
  pptx_parser.py     슬라이드 텍스트, 표, 좌표 기반 표 복원, 노트, 이미지, 문서 속성
  docx_parser.py     제목 단위 섹션, 표, 이미지
  chunker.py         chunk 방식 (슬라이드 단위, 제목 단위)
  textnorm.py        반복 문구 제거, 인용 비교용 정규화
  taxonomy.py        taxonomy.xlsx 시트 읽기·검증, 시트별 해시, 버전 (반영 기능 없음)
  synonyms.py        synonyms 시트 치환, 본문 일치 목록
  candidates.py      후보 집계, reports/ 후보·파일 목록·조회 질문 후보 리포트(탭 구분 붙여넣기 행)
  llm.py             OpenAI 호환 호출, 응답 검증·재시도, 캐시, mock, 공용 호스트 판정·더미 해시 확인·리다이렉트 거부 opener·키 읽기
  classify.py        1차 분류(분류 축 8 + 상태 축 2), 새 값 후보
  questions.py       2차 질문 후보 생성, 매핑
  label.py           3차 라벨링, 날짜·담당자 추출
  alerts.py          라벨 분포 점검과 사람 알림 (HITL H5)
  review.py          4차 불량 목록 추출, 검수 화면 생성, 교정 반영
  metrics.py         사외 더미 정답표 대조 지표(축별 완전 일치율, Jaccard, 혼동 행렬). tools/evalgold.py만 쓴다
  export.py          산출 SQLite, SCHEMA.md
  querycheck.py      조회 질문 후보, LLM SQL 조회 검증
  report.py          기준선 리포트 (report --run, 분포만)
  gate.py            M7 게이트 기록 (gate record, reports/gate_<timestamp>.json)
  embed.py           임베딩 (python -m labelbot embed, chunk_embeddings)
  vectorpush.py      Supabase 벡터 적재 (python -m labelbot push-vectors, vector_push_log)
  store.py           작업 DB 스키마와 읽기·쓰기
  screens/           HTML 화면 템플릿 2개 (compare.html, review.html)
prompts/             단계별 프롬프트 (.md)
docs/supabase_schema.md  Supabase(pgvector) 표 정의 SQL 코드 블록 (.sql 파일은 두지 않는다)
defaults/taxonomy.xlsx   기본 taxonomy (더미 동의어 포함)
dummy pptx files/    사외 검증 샘플 원천 (저장소 상대 경로). 어느 파일이든 쓸 수 있고 ingest 바이트 경로로만 읽는다
tests/               단위·통합 테스트, mock 응답
  fixtures/default_taxonomy_rows.jsonl   기본 taxonomy.xlsx 기대 행(기본본 회귀 기준)
  fixtures/synthetic_chunks.jsonl        합성 픽스처 (SYN-01 이후)
  gold/gold_labels.jsonl                 더미 정답표
  gold/dummy_hashes.jsonl                폴더의 pptx sha256 목록 스냅샷
  xlsx_writer.py                         오류 픽스처 xlsx를 io.BytesIO 안에서만 만든다 (디스크에 쓰지 않음)
tools/               개발 전용. labelbot을 import할 수 있지만 labelbot은 tools를 import하지 않는다
  evalgold.py        정답표와 실제 LLM 결과 대조, .md 리포트
  gold_view.py       정답표의 사람 검토용 .md 보기 생성
PRD.md, plan.md, README.md
```

### 작업 폴더(코드 폴더 밖)

```
taxonomy.xlsx   사내 taxonomy (필수 시트 4 + 선택 시트 2). 없으면 실행을 거부한다(defaults/taxonomy.xlsx를 작업 폴더로 복사하라고 안내)
pipeline.json   `taxonomy_path`(기본값: 작업 폴더의 `taxonomy.xlsx`), llm 블록(base_url, chat_path, model, api_key_env, auth_header, extra_headers, ca_file, timeout, temperature, max_tokens, response_format_json, internal_host_suffixes), embedding 블록, supabase 블록, flag 블록(`unknown_ratio_min` 기본 0.5, `confidence_min` 기본 0.7), 임계값, 상한값, 알림 기준값, chunk 방식, 화면 chunk당 이미지 상한(기본 4). 키 값은 넣지 않고 환경변수 이름만 둔다
inputs/         사람 입력(taxonomy.xlsx, 교정 파일)의 base64 보관본 <sha256>.b64
raw/            원본 파일
b64/            base64 텍스트
images/         추출 이미지 (.b64)
work.sqlite     작업 DB (표 목록은 아래 "작업 DB(work.sqlite) 표")
screens/        생성된 HTML 화면 (이미지는 data URL)
inbox/          화면에서 내려받은 교정 파일(.json)을 넣는 곳
out/            labeling.sqlite, SCHEMA.md, images/
reports/        기준선 리포트(.md), alerts.json, candidates.jsonl·candidates.md, file_list.md, query_candidates.md, gate_<timestamp>.json, flagged_<실행ID>.jsonl·flagged_<실행ID>.md(4차 불량 목록. chunk ID, 파일 ID, 사유 코드, 수치만)
logs/           .log (파일 ID와 사유 코드만)
```

### 명령

모든 명령은 `python -m labelbot <명령> --workspace <작업 폴더>`로 부른다. 실행 ID를 발급하지 않는 명령은 최신 실행 ID를 쓰고, `--run <ID>`로 다른 실행을 지정할 수 있다.

| 명령 | 하는 일 | 실행 ID 발급 | 처음 만드는 마일스톤 |
|---|---|---|---|
| `selfcheck` | 환경 점검, `write_roundtrip`, 호스트 판정 | 안 함 | M0 |
| `probe` | 점검 스크립트: 파일 구조 통계(본문 미출력) | 안 함 | M0 |
| `gate record` | M7 게이트 항목별 PASS/FAIL 입력, `reports/gate_<timestamp>.json` | 안 함(시각을 쓴다) | M0 |
| `ingest` | 수집·파싱·chunk만 한다. LLM을 부르지 않는다 | 발급 | M1 |
| `compare` | 파싱 대조 화면 `screens/compare.html` 생성 | 안 함 | M1 |
| `review` | `flagged_chunks` 생성, `reports/flagged_*` 작성, 검수 화면 `screens/review.html` 생성(LLM 호출 0회) | 안 함(검수 기준 실행 ID = 최신 또는 `--run`) | M5 |
| `apply` | `inbox/`의 교정 `.json` 반영 | 안 함(교정 파일의 실행 ID를 쓴다) | M5 |
| `run` | 수집부터 산출·조회 검증·리포트까지 전 단계. `embed`·`push-vectors`는 부르지 않는다 | 발급 | M6 |
| `report --run <ID>` | 기준선 리포트(분포) 재계산(LLM 호출 0회) | 안 함 | M6 |
| `embed` | chunk 임베딩, `chunk_embeddings` | 안 함 | M6b |
| `push-vectors` | Supabase 벡터 적재, `vector_push_log` | 안 함 | M6b |

### ID와 해시 정의

| 이름 | 정의 | 쓰는 곳 |
|---|---|---|
| 실행 ID | `YYYYMMDDTHHMMSS-<4자리 hex>`(UTC). `run`과 `ingest`만 발급한다. 다른 명령은 최신 실행 ID나 `--run`으로 지정한 ID를 쓴다 | `runs`, `first_seen_run`·`last_seen_run`, `flagged_chunks`, `reports/flagged_<실행ID>.*` 파일명 |
| 파일 ID | 원본 bytes의 sha256 | files, `file_locations`, 더미 해시 목록 |
| chunk ID | `<파일 ID 앞 16자>:<part 이름>`. pptx는 `ppt/slides/slideN.xml`의 part 이름, 다른 형식은 그 형식의 구간 식별자(docx는 제목 단위 구간 번호). 같은 파일을 다시 처리하면 같은 ID다. 파일 bytes가 바뀌면 파일 ID가 바뀌므로 chunk ID도 새로 생기며, 교정의 재검수 판정은 chunk ID가 아니라 `text_hash`로 한다 | 전 단계 |
| `text_hash` | `chunks`에 저장된 최종 chunk 본문(동의어 치환 후, `[노트]`·`[차트]` 구간 포함)을 NFC 정규화한 UTF-8의 sha256 | 임베딩 재호출 판정, `flagged_chunks` 기록, 교정의 재검수 판정 |
| `dup_hash` | `text_hash`와 같은 본문에서 공백을 하나로 줄이고 소문자로 바꾼 뒤의 sha256. `dup_group`은 `dup_hash`가 같은 chunk의 묶음이다 | G4 `dup_group`, 검수 화면 묶음 표시 |
| `label_hash` | `{축 ID: 정렬한 값 목록, 질문 ID: 답(O/X/N/A)}`만 넣고 키 순으로 정렬한 JSON(구분자 `(",", ":")` 고정, `ensure_ascii=False`)의 UTF-8 sha256. 확신도, 근거 인용, 검수 상태, 시각은 넣지 않는다. 교정이 있으면 교정 값, 없으면 최신 실행의 봇 값이다. 라벨 실패 chunk는 적재하지 않고 사유 코드를 남긴다 | `vector_push_log`, `push-vectors` |
| `chunk_embeddings` 키 | 기본 키 `(chunk_id, model)`. `text_hash`가 바뀌면 그 행을 교체한다. 벡터는 리틀 엔디언 float32(`struct.pack('<%df' % n, ...)`) | `embed`, `push-vectors` |
| 시트 해시, 캐시 키 | `PRD.md` 9.4절 정의를 따른다(캐시 키는 M2 G8) | 재처리 판정, meta |

### 작업 DB(work.sqlite) 표

`store.py`(M0)가 스키마를 관리한다. `meta` 표에 `schema_version`을 두고, 마이그레이션은 표·열 추가만 허용한다. 기존 열의 의미 변경과 삭제는 하지 않는다. 산출 SQLite의 facet_labels·answers·extracted_values는 `export`가 `labels`와 `corrections`에서 만든다.

| 표 | 주요 열 | 처음 만드는 마일스톤 |
|---|---|---|
| `meta` | 키, 값(`schema_version` 포함) | M0 |
| `llm_cache` | 캐시 키, 응답, 저장 시각(성공 응답만) | M0 |
| `runs` | 실행 ID, 명령, 시작·종료 시각, 설정 해시, 시트 해시, 실제 전송 파라미터, 입력 루트 절대 경로(여기에만 둔다) | M1 |
| `failures` | 단계, 대상 ID(파일 ID 또는 chunk ID), 사유 코드, 실행 ID | M1 |
| `files` | 파일 ID, `file_name`·`rel_path`(NOT NULL), 작성일, 작성자, `near_dup_group` | M1 |
| `file_locations` | 파일 ID, 상대 경로, 파일명, `first_seen_run`, `last_seen_run` | M1 |
| `chunks` | chunk ID, 파일 ID, 순번, part 이름, 유형, 제목, 본문, `text_hash`, `dup_hash`, `dup_group`, 파싱 경고 | M1 |
| `labels` | 실행 ID, chunk ID, 종류(축/질문/추출값), 축·질문·항목 ID, 봇 원답, 근거, 확신도, 시트 해시, 프롬프트 버전, 모델 | M2 |
| `candidates` | 후보 종류(새 값/동의어/질문), 내용, 빈도, 예시 chunk ID, 제안 축·상위값, 출처(봇/검수 등록), 실행 ID | M2 |
| `alerts` | 실행 ID, 조건, 수치, 기준값 | M4 |
| `flagged_chunks` | `run_id`(검수 기준 실행 ID), `chunk_id`, `reason_codes`, `unknown_ratio`, `min_confidence`, `text_hash` | M5 |
| `corrections` | 검수 기준 실행 ID, chunk ID, 축·질문 ID, 사람 값, 봇 원답, 검수 상태(재검수 표시 포함), 질문 문장 해시, 교정 파일 sha256, 반영 시각 | M5 |
| `chunk_embeddings` | chunk ID, 모델, 차원, `text_hash`, 벡터(BLOB), 실행 ID | M6b |
| `vector_push_log` | chunk ID, 모델, `text_hash`, `label_hash`, 대상 호스트 해시, 보낸 시각, `result_code` | M6b |

## 3. 구현 단계와 완료 기준

각 마일스톤의 완료 기준은 테스트로 통과 여부를 판정한다. M0~M6과 M6b는 사외에서, M7은 사내에서 진행한다. `[P0]`은 M7 첫 실행 전에 있어야 하는 항목이고, `[P1]`은 `work.sqlite`와 LLM 캐시만으로 나중에 다시 계산할 수 있어 첫 실행을 막지 않는 항목이다(라벨링 품질 보강 v2 기준). G번호는 v2의 gap ID다. 4차 단계 단순화(2026-10-04)로 G3(표본 추출), G13(검수 행동 기록), G8의 재판정 형식, G1의 사내 정확도 지표, G2의 review_gold·회차 간 답 재사용 부분은 대체되어 뺐다. G1은 사외 더미 정답표 대조(`tools/evalgold.py`)만, G2는 교정 반영 규칙만 남는다.

### M0. 점검 도구와 골격

만드는 파일: `labelbot/__main__.py`, `cli.py`, `workspace.py`, `selfcheck.py`, `probe.py`, `store.py`, `llm.py`(mock 포함), `tests/`

완료 기준:
- [ ] 점검 스크립트를 샘플 1(sha256 `1b275ae9efc9…`)과 샘플 2(sha256 `f073be9c9ade…`)에 돌리면 샘플 1은 9장·차트 0, 샘플 2는 4장·차트 1·그룹 도형 0으로 나온다. 샘플은 파일명이 아니라 부록의 sha256으로 찾는다. 샘플 2는 `dummy pptx files/` 폴더의 임의 파일 중 하나이며, 교체하면 이 기준과 M1 기준의 값만 바꾼다. 차트 1은 M1의 `[차트]` 구간 추출(G15)을 검증하는 대상이다.
- [ ] 점검 스크립트와 로그 출력에 슬라이드 본문 문자열이 하나도 없다(샘플의 제목 문구를 출력에서 검색해 0건).
- [ ] self-check가 항목별 PASS/FAIL을 내고, LLM 주소가 없을 때 그 항목만 FAIL로 나온다.
- [ ] 작업 폴더를 코드 폴더 안으로 지정하면 실행이 거부된다.
- [ ] 코드 폴더를 지우고 다시 만들어도 작업 폴더의 파일이 바이트 단위로 그대로다.
- [ ] 소스 전체가 Python 3.14.2에서 import되고 테스트가 통과한다(사외 구동 기준).
- [ ] `store.py`가 `meta` 표의 `schema_version`으로 스키마를 관리한다. 이전 버전 스키마의 DB를 열면 열이 추가되고 기존 행이 보존된다.

[P0] G18 selfcheck `write_roundtrip`: 작업 폴더의 임시 하위 폴더에 허용 확장자마다(`.b64 .sqlite .json .jsonl .html .md .log`) 알려진 바이트를 쓰고 다시 읽어 sha256을 비교한 뒤 지운다. `.sqlite`는 `PRAGMA integrity_check`와 SELECT까지 확인한다. 원본 경로를 열지 않으므로 `read_input` 단일 경로 규칙의 예외로 명시한다.
- [ ] 정상 환경에서 7개 확장자가 모두 PASS이고 임시 파일이 남지 않는다.
- [ ] 쓰기 함수를 `.jsonl`에 대해서만 다른 바이트를 쓰도록 바꿔치기하면 `.jsonl`만 FAIL이다.
- [ ] `.sqlite` 파일을 쓴 뒤 바이트를 훼손하면 그 항목이 FAIL이다.
- [ ] 출력에 "필요조건일 뿐이며 M7 게이트의 수동 확인이 필요하다"는 문구가 있다.

[P0] G19 LLM 설정과 외부 전송 안전장치: `llm.py`는 OpenAI Chat Completions 호환(`urllib.request`, `POST {base_url}{chat_path}`)이다. `pipeline.json` `llm` 블록의 키와 기본값은 `base_url`, `chat_path`("/chat/completions"), `model`, `api_key_env`("OPENAI_API_KEY"), `auth_header`("Authorization", 값 "Bearer {key}"), `extra_headers`({}), `ca_file`(null), `timeout`(60), `temperature`(0, null이면 보내지 않음), `max_tokens`, `response_format_json`(false), `internal_host_suffixes`([])다. 키 값은 환경변수에서만 읽고 설정 파일, 로그, 캐시 키, DB에 넣지 않는다. 호스트(소문자)가 `internal_host_suffixes`의 접미사와 같거나 "." + 접미사로 끝나면 사내이고, 파싱 실패·빈 호스트·IP 리터럴은 거부한다. 사외 호출은 호출 직전마다 그 호출에 들어가는 chunk의 파일 해시가 모두 `tests/gold/dummy_hashes.jsonl`에 있을 때만 허용하며(taxonomy 조건은 없다), 파일이 0개면 거부한다(self-check의 고정 probe 문장만 예외). 호스트 판정, 더미 해시 확인, 리다이렉트 거부 opener, 키 읽기는 공용 함수 하나로 두고 임베딩(G20)과 벡터 적재(G21)도 같은 함수를 쓴다. 프록시는 `HTTP(S)_PROXY`를 따르되 판정은 `base_url` 기준이다.
- [ ] mock 서버가 받은 요청에서 `temperature: null`이면 temperature 키가 없고 0이면 0이 있다. `response_format_json`이 true일 때만 `response_format`이 있다.
- [ ] `auth_header`, `extra_headers`, `chat_path`, `timeout`을 바꾸면 mock 서버가 받은 헤더·경로가 그에 맞게 바뀐다.
- [ ] 테스트 키 문자열을 작업 폴더 전체와 DB에서 검색하면 0건이다.
- [ ] 공용 호스트 판정 함수에 파일 해시 목록을 인자로 넘기는 단위 테스트: 사외 호스트 설정에서 목록에 더미 해시 밖 해시가 하나라도 있거나 목록이 비어 있으면(probe 문장 제외) 거부하고 사유 코드를 돌려준다.
- [ ] 판정이 불확실한 `base_url`(IP 리터럴, 빈 호스트)과 `evilcorp.com` 같은 접미사 오일치(`corp.com` 등록 시)가 거부된다.
- [ ] mock 서버가 302로 다른 포트를 가리키면 호출이 실패하고, 그 포트의 mock 서버는 요청을 받지 않는다.
- [ ] selfcheck가 호스트 판정 결과(사내/사외/불확실)를 항목으로 출력한다.

### M1. 수집·파싱·chunk와 대조 화면

만드는 파일: `ingest.py`(`read_input` 포함), `ooxml.py`, `pptx_parser.py`, `docx_parser.py`, `chunker.py`, `textnorm.py`, `screens/compare.html`, `tests/gold/dummy_hashes.jsonl`

완료 기준:
- [ ] 샘플 1(sha256 `1b275ae9efc9…`)과 샘플 2(sha256 `f073be9c9ade…`)에서 chunk 13개(9+4, 슬라이드당 1 chunk)가 `presentation.xml`의 슬라이드 순서대로 나온다.
- [ ] 샘플 1의 6번 슬라이드에서 `W01 | Center | 13 | 9.62 | 0.18 | 1.87%` 행이 한 줄로 복원된다.
- [ ] 샘플 2의 3번 슬라이드 표에서 `브릿지 저항` 행이 `FAIL`과 같은 줄에 나온다.
- [ ] 문구 "본 자료의 모든 데이터는 내부 테스트용 더미"가 어떤 chunk에도 없다.
- [ ] 샘플 1의 chunk에는 `[노트]` 구간이 있고, 샘플 2의 chunk에는 없다(노트 4개가 숫자뿐이어서 버려진다).
- [ ] 샘플 2에서 추출 이미지 0개다(이미지 참조가 없다). 샘플 1은 고유 대상 17개 중 장식 규칙 적용 후 값이며, 값은 M1 구현 시 확정한다.
- [ ] 샘플 2의 파일 단위 작성자가 문서 속성에서 "공정 AI팀"으로 읽힌다.
- [ ] 준중복 파일(sha256 `c3860dd2e378…`)은 샘플 1과 슬라이드 XML 9개가 같지만 바이트 해시가 달라 별도 파일로 처리되어 `files` 표에 따로 행이 있다.
- [ ] base64를 디코딩한 바이트의 해시가 원본과 같다.
- [ ] 파싱 실행 후 작업 폴더에 `.pptx`나 `.docx` 파일이 `raw/` 밖에 생기지 않고, 수집·파싱 어느 단계에서도 `.pptx .xlsx .docx .csv .txt` 파일이 새로 쓰이지 않는다(입력 원본 제외).
- [ ] `raw/`를 비운 상태에서도 파싱이 돈다.
- [ ] 디코딩 직후 시그니처로 판정한다. `PK\x03\x04`가 아닌 파일은 `NOT_OOXML`, `D0 CF 11 E0`로 시작하면 `ENCRYPTED`, 구형 OLE 형식은 `OLE_LEGACY` 사유 코드로 그 파일만 실패 목록에 들어가고 나머지는 처리된다.
- [ ] 합성 docx에서 제목 스타일 단위로 chunk가 나뉜다.
- [ ] `read_input(path, snapshot_dir)`가 `open(path,"rb")`로 읽고 시그니처를 확인하며, `snapshot_dir`이 있으면 `inputs/<sha256>.b64`로 보관하고(같은 해시는 재사용) `None`이면 아무것도 쓰지 않는다. 텍스트 입력은 `utf-8-sig`로 읽고 실패하면 `cp949`로 읽는다.
- [ ] `dummy pptx files/` 읽기는 보관을 끈다(`snapshot_dir=None`). 저장소나 cwd에 `.b64`가 쌓이지 않는다.
- [ ] `tests/gold/dummy_hashes.jsonl`(폴더의 `*.pptx` sha256 목록, BytesIO 스크립트로 생성)에 부록의 해시 11개(정답 10 + 준중복 1)가 모두 있다. 더미 파일은 저장소의 `dummy pptx files/`에 모두 있다(2026-10-04 확인, pptx 146개).
- [ ] 대조 화면이 외부 주소를 참조하지 않고(HTML에 `http` 참조 0건), 이상 여부 기록을 파일로 내려받을 수 있다. 이미지는 data URL로 넣고 chunk당 기본 4개까지만 넣는다(설정으로 조정).

[P0] G16 상대 경로와 `file_locations`: ingest가 파일마다 입력 루트 기준 상대 경로(구분자 `/`, NFC)와 파일명을 기록한다. 작업 DB에 `file_locations(file_id, rel_path, file_name, first_seen_run, last_seen_run)`를 두고, files에는 `file_name`과 대표 경로 `rel_path`를 NOT NULL로 둔다. 시그니처 불일치나 `OLE_LEGACY`로 실패한 파일도 기록한다. 입력 루트 절대 경로는 실행 메타에만 한 번 둔다.
- [ ] 샘플 1(sha256 `1b275ae9efc9…`)을 두 하위 폴더에 두면 files 1행, `file_locations` 2행이고 경로 구분자가 `/`다.
- [ ] 수집 후 파일을 다른 폴더로 옮겨 다시 수집하면 위치 행만 늘고 파싱이 다시 돌지 않는다(`chunks` 행 불변).
- [ ] `file_name`이나 `rel_path`가 빈 행은 DB 제약으로 실패한다.
- [ ] `ENCRYPTED`로 실패한 합성 파일도 `file_locations`에 행이 있다.
- [ ] 입력 루트 절대 경로는 실행 메타에만 있다.

[P0] G4 chunk `dup_group`: 정규화한 본문 해시로 chunk `dup_group`을 만든다. 처리는 바꾸지 않고 표시만 한다(6절 결정 4).
- [ ] 준중복 파일(sha256 `c3860dd2e378…`)의 chunk가 샘플 1의 같은 본문 chunk와 같은 `dup_group`을 갖고, 샘플 2(sha256 `f073be9c9ade…`)의 chunk와는 겹치지 않는다.
- [ ] 슬라이드를 하나 끼워 넣은 합성 복사본에서도 나머지 chunk의 `dup_group`이 유지된다.
- [ ] 두 파일 모두 끝까지 처리되어 산출에 남는다.

[P0] G15 차트 텍스트: `pptx_parser.py`가 차트 XML에서 제목·계열·범주 이름을 읽어 `[차트]` 구간으로 chunk에 넣는다. 수치 값은 넣지 않는다. 기준선을 바꾸는 파싱 변경이므로 M7 전에 넣는다.
- [ ] 샘플 2(sha256 `f073be9c9ade…`)의 차트 슬라이드 chunk에 `[차트]` 구간과 범주 이름이 있고, 그 슬라이드에 차트 미처리 경고가 없다.
- [ ] 차트가 없는 샘플 1의 chunk는 G15 반영 전후로 같다.

[P1] G4 파일 `near_dup_group`: 파일 사이 문서빈도가 높은 줄(기본: 파일의 10% 이상에 나오는 줄)을 뺀 뒤 Jaccard(기본 0.8)로 연결 요소를 묶는다. 리포트에는 그룹 ID와 크기 분포만 낸다.
- [ ] 공통 템플릿 줄만 같은 합성 파일 두 개는 묶이지 않는다. A~B, B~C만 기준을 넘으면 A·B·C가 한 그룹이다.

### M2. taxonomy.xlsx, 동의어 시트, 후보 리포트, 1차 분류

만드는 파일: `ooxml.py`(bytes 기반 xlsx 읽기), `taxonomy.py`, `synonyms.py`, `candidates.py`, `classify.py`, `tests/fixtures/default_taxonomy_rows.jsonl`(커밋된 `defaults/taxonomy.xlsx`에서 만든 기대 행. xlsx가 기준이다), `tests/xlsx_writer.py`(메모리 전용), `tests/fixtures/synthetic_chunks.jsonl`, `tests/gold/gold_labels.jsonl`(초안), `tools/gold_view.py`, `prompts/classify.md`

테스트 진입점: `taxonomy.parse_bytes(b)`가 파서 진입점이고, `read_input`은 bytes를 읽어 넘기기만 한다. 오류 픽스처와 규칙 테스트는 `tests/xlsx_writer.py`가 메모리에서 만든 bytes를 `parse_bytes`에 넣는다(디스크에 xlsx를 쓰지 않는다). 읽을 위치는 `pipeline.json`의 `taxonomy_path`(기본값: 작업 폴더의 `taxonomy.xlsx`)이고, 통합 테스트는 `taxonomy_path`를 `defaults/taxonomy.xlsx`로 지정해 복사 없이 읽는다. `defaults/taxonomy.xlsx`는 저장소에 이미 있으며 기본 taxonomy의 기준이다. 이 파일에 의존하는 테스트는 `tests/test_defaults_taxonomy.py`와 통합 테스트 모듈로 분리한다. M2의 나머지 테스트는 `parse_bytes`만으로 통과해야 한다.

완료 기준:
- [ ] 엑셀에서 값을 추가한 `taxonomy.xlsx`를 읽으면, 코드 수정 없이 다음 분류 프롬프트에 그 값이 들어간다.
- [ ] 오류 5종(같은 축 안의 중복 값, 존재하지 않는 상위값, 축 정의 행이 없는 값, 축 속성이 값 행에 적힘, 표준어가 빈 동의어)은 각각 픽스처 1개로 실행을 거부하고, 메시지에 시트 이름과 행 번호가 나온다.
- [ ] 예약어 오류: `해당 없음`, `unknown`과 그 변형(`해당없음`, `Unknown`, `N/A`, `NA`)을 값으로 적은 시트는 거부된다.
- [ ] 시트 누락·머리글 불일치: 필수 시트가 없거나 머리글이 다르면 시트 이름과 기대 머리글을 알려 주고 거부한다. 선택 시트(`files`, `queries`)가 없으면 빈 시트로 처리된다.
- [ ] 중복 동의어 경고: 같은 동의어가 두 행에 있으면 첫 행을 쓰고 경고하며 실행은 계속된다. 경고에는 시트 이름과 행 번호만 있고 표현은 없다.
- [ ] 바이트 불변: 실행 전후로 `taxonomy.xlsx`가 바이트 단위로 같다.
- [ ] 기본본 = jsonl(`tests/test_defaults_taxonomy.py`): 커밋된 `defaults/taxonomy.xlsx`를 `read_input`으로 읽은 행이 `default_taxonomy_rows.jsonl`과 같다. jsonl은 xlsx에서 만든 회귀 기준이며, 부록과 다르면 xlsx가 맞다. Excel에서 저장한 파일이므로 sharedStrings 경로도 함께 검증된다.
- [ ] xlsx 없을 때 거부: `taxonomy_path`가 가리키는 파일(기본값: 작업 폴더의 `taxonomy.xlsx`)이 없으면 실행이 거부되고 "`defaults/taxonomy.xlsx`를 작업 폴더로 복사하라"고 안내하며, 작업 폴더에는 아무것도 복사되지 않는다. self-check에서는 FAIL 항목이다.
- [ ] 숫자 경계: `Via1`이 "Via12"를, `Metal1`이 "Metal12"를 바꾸지 않는다. "단락"은 Short로, "JGV"는 JHV로, "Metal1"은 M1로 정규화된다(mock 기준 불량 모드 = Short).
- [ ] 기본 `synonyms` 시트에 허용 목록(JGV) 외 3자 이하 영문 키가 없다.
- [ ] 시트별 해시: 필수 4개와 선택 2개 시트마다 해시가 나오고, 오른쪽에 추가한 열이나 Excel 재저장(내용 불변)으로는 바뀌지 않으며, 시트가 없으면 빈 시트 해시다.
- [ ] `files`·`queries` 시트: 머리글이 다르면 거부된다. `files`의 파일 ID 중복과 `queries`의 조회 ID 중복은 오류다. 수집 목록에 없는 파일 ID는 경고만 하고 실행은 계속된다. 제외·채택 열은 Y/N/빈칸(빈칸=N) 외 값이면 오류다.
- [ ] `files` 시트의 메모를 1개 고치면 그 파일 chunk에만 1차 호출이 나가고, 제외=Y로 바꾼 파일은 처리 대상에서 빠진다.
- [ ] 3상태: 분류에 성공한 모든 내용 유형 chunk가 분류 축마다(분류 실패 chunk는 빈칸이고 실패 목록에 있다, G6) 값, `해당 없음`, `unknown` 중 하나 이상을 가진다. 결과 축은 다중값을 허용하고, 의사결정 상태는 {adopted, rejected, pending, `해당 없음`, `unknown`} 중 정확히 하나다. 불량 모드에서 상위값(Reliability)만 붙은 라벨이 유효하게 저장되고, 상위·하위가 함께 나오면 하위만 저장된다.
- [ ] 활성 값이 0개인 축(기본본의 제품·세대)은 LLM 호출 없이 `해당 없음`으로 저장되고 `meta`에 비활성 축으로 적힌다.
- [ ] [R1] DRM이 풀리지 않은 xlsx(`D0 CF 11 E0`)나 xlsx가 아닌 파일은 `read_input`이 `ENCRYPTED`/`NOT_OOXML`로 거부하고, 로그에는 파일 ID와 사유 코드만 남는다.
- [ ] [R2] sharedStrings의 run 분할, 한글 윗주(`<rPh>`), inlineStr, `t="str"/"b"/"e"`, 생략된 빈 셀·행, `_xHHHH_` 이스케이프, Strict OOXML 네임스페이스 픽스처를 읽어도 셀이 바른 위치에 바른 값으로 들어간다. 오류 셀은 시트·행 오류로 낸다.
- [ ] [R3] 캐시된 `<v>`가 없는 수식 셀은 "수식 결과 없음, Excel에서 저장 후 다시 실행"이라고 시트·행을 알리고 거부한다.
- [ ] [R4] 숨김 행이나 autoFilter가 있는 시트는 모든 행을 읽고 "숨김 행도 읽는다. 제외는 사용 여부=N"이라고 경고한다.
- [ ] [R5] `<mergeCells>`가 있으면 범위를 알리고 거부한다.
- [ ] [R6] 시트 이름의 대소문자가 다르면 경고하고 찾아 읽으며, 시트 누락과 머리글 불일치는 명시적 오류다.
- [ ] [R7] 값·동의어·표준어 열의 숫자 셀(Excel 자동 변환 의심)은 경고한다. 정수형 float는 정수 문자열로 바꾸고, `rejected`의 기각일은 `date1904`를 반영해 날짜로 바꾼다.
- [ ] mock LLM이 용어 대응을 내면 동의어 후보로 모이고, 같은 대응은 빈도와 예시 chunk로 묶인다. 후보는 `reports/candidates.jsonl`·`candidates.md`에 후보 종류(새 값, 동의어, 질문), 빈도, 예시 chunk, 제안 축·상위값, 근거와 탭 구분 붙여넣기 행으로 나오고, `rejected` 시트에 적힌 후보는 나오지 않는다.
- [ ] mock LLM이 taxonomy에 없는 값을 내면 facet_labels에 저장되지 않고 해당 축이 `unknown`이 되며 새 값 후보로 올라간다.
- [ ] mock LLM이 형식이 틀린 응답을 내면 설정된 횟수만큼 재시도한 뒤 실패로 기록되고, 그 응답은 캐시에 없다.
- [ ] 참고문헌 유형으로 분류된 chunk는 2~3차 대상에서 빠진다.
- [ ] 정답표 초안 `tests/gold/gold_labels.jsonl`이 부록의 39 chunk를 담고 스키마를 만족한다. `tools/gold_view.py`가 사람 검토용 `tests/gold/gold_labels.md`를 만들고, 합성 픽스처 6개(SYN-01~06)가 `synthetic_chunks.jsonl`에 있다.

[P0] G6 분류 응답 완전성: 응답의 축 키 집합이 활성 축 집합과 정확히 같아야 통과한다. 빠진 축에 `해당 없음`이나 `unknown`을 자동으로 넣지 않는다.
- [ ] mock LLM이 활성 축 9개 중 8개만 답하면 재시도하고, 그래도 빠지면 "분류 실패"가 되며 facet_labels에 그 chunk 행이 없다.
- [ ] 분류 실패 chunk에는 2~3차 mock 호출이 0회다.
- [ ] 모르는 축 키는 버리고 사유 코드를 남긴다.

[P0] G8 temperature와 캐시 키: 캐시 키는 한 곳에서 "실제 전송한 요청 전체(`base_url`, `chat_path`, `model`, messages, temperature 전송 여부와 값, `max_tokens`, `response_format`)의 해시"로 정의한다. 헤더와 키는 넣지 않는다. 실제 전송한 파라미터는 meta에도 기록한다.
- [ ] 입력이 같으면 재실행 호출이 0회다(실패 chunk 제외).
- [ ] temperature만 바꾸면 캐시가 맞지 않는다.
- [ ] temperature를 null로 두면 meta에 "미전송"이 기록된다.

[P0] G16 분류 맥락의 경로: 1차 분류 프롬프트에 처음 본 위치(`first_seen_run`의 `rel_path`)를 "참고(인용 불가)"로 고정해서 넣는다.
- [ ] 파일을 옮겨 다시 수집해도 렌더링된 분류 프롬프트가 바이트 단위로 같고 mock 호출이 0회다.
- [ ] 프롬프트에 입력 루트 절대 경로가 없다.

[P0] G19 1차 분류의 외부 전송 차단:
- [ ] 사외 호스트 설정에서 더미 해시 밖 파일의 chunk가 들어가는 1차 분류 호출은 그 호출만 0회로 막히고 사유 코드가 `failures`에 남는다.

### M3. 질문 후보와 매핑

만드는 파일: `questions.py`, `prompts/propose_questions.md`

완료 기준:
- [ ] 후보 생성 전후로 승인된 질문의 내용이 같고, 새로 생긴 질문은 모두 후보 상태다.
- [ ] chunk에 매핑된 질문은 승인된 공통 질문 전부와, 그 chunk의 축 값에 해당하는 승인된 카테고리별 질문뿐이다.
- [ ] 매핑된 질문 수가 상한을 넘으면 우선순위 순으로 잘린다. [P0] G5: 우선순위는 숫자가 작을수록 먼저 들어가고(1이 가장 먼저), 같으면 질문 ID 오름차순이다. 카테고리 질문이 10개 매핑되는 mock chunk에서 `Q-COM-001`(우선순위 1)이 남고 8개로 잘린다. 우선순위 2와 9인 질문이 경합하면 2가 남는다. 잘린 횟수가 질문별로 리포트에 나온다.
- [ ] 승인된 질문이 0개면 `run`의 3차 라벨링이 LLM을 호출하지 않고 안내와 함께 끝난다.
- [ ] 질문 후보가 `reports/candidates.md`에 `questions` 시트의 열 순서(질문 ID, 문장, 적용 대상, 우선순위)대로 탭 구분 행으로 나오고, 사람이 시트에 붙여넣고 재실행하면 매핑된다.

[P1] G11 분류 교정의 전파: 검수에서 분류를 교정하면 그 chunk의 2차를 다시 하고 3차를 chunk 단위로 다시 호출한다. 매핑이 해제된 답 중 사람이 교정하거나 확인한 답은 보존한다.
- [ ] 분류 교정을 반영하고 재실행하면 그 chunk에만 3차 호출이 1회 나간다.
- [ ] 매핑이 해제된 사람 답은 산출 answers에 "매핑 해제(사람 값)"로 남고, 봇 답만 있던 것은 빠진다.

### M4. 3차 라벨링

만드는 파일: `label.py`, `alerts.py`, `prompts/label.md`

완료 기준:
- [ ] 저장된 모든 답이 O, X, N/A 중 하나다.
- [ ] O와 X인 답에는 근거 인용이 비어 있지 않다.
- [ ] mock LLM이 chunk 본문의 날짜를 내면 extracted_values에 chunk 단위 값으로, 근거와 함께 저장된다.
- [ ] 실행 중간에 중단시킨 뒤 다시 돌리면 answers에 중복 행이 없고, 끝난 chunk에 대한 mock 호출이 0회다. 실패 chunk는 끝난 chunk로 보지 않으며 재시도 호출이 나간다(G6).
- [ ] 저장된 답마다 `taxonomy`·`synonyms`·`questions` 시트 해시, 프롬프트 버전, 모델명이 기록되어 있다.
- [ ] 라벨링 프롬프트에는 그 chunk 본문에서 일치한 동의어 시트 항목만 들어가고, 일치하지 않은 항목은 들어가지 않는다.
- [ ] 근거 인용 검사는 사전으로 바꾸지 않은 본문 원문 기준으로 한다.
- [ ] mock LLM이 라벨링 응답에 용어 대응을 내면 1차와 같은 동의어 후보 목록에 합쳐진다.
- [ ] mock LLM이 N/A를 30% 내는 경우 알림이 나오고, 31% 내는 경우 나오지 않는다.
- [ ] 분류 축 중 다중값=Y이고 중복 알림 제외=N인 축만 집계해, 중복 라벨링 비율이 40%면 알림이 나오고 39%면 나오지 않는다. 분모와 분자에서 `unknown`과 `해당 없음`을 뺀다.
- [ ] 결과 축(중복 알림 제외=Y)에 값이 두 개 붙어도 중복 라벨링 비율이 바뀌지 않는다.
- [ ] `taxonomy.xlsx`를 Excel에서 내용 변경 없이 다시 저장해도 시트 해시가 그대로이고, 재실행의 mock 호출이 0회다.
- [ ] 알림이 나오면 콘솔 경고와 `reports/alerts.json`에 실행 ID, 조건, 수치, 기준값이 남고, 라벨링은 멈추지 않고 끝까지 돈다.
- [ ] 콘솔 경고와 `alerts.json`에 chunk 본문 문자열이 없다.
- [ ] 설정 파일에서 기준값을 바꾸면 바뀐 값으로 판정한다.
- [ ] 수집 후 파일을 다른 폴더로 옮겨 다시 돌리면 분류·라벨링 mock 호출이 0회다(G16).

[P0] G6 라벨링 응답 완전성:
- [ ] 매핑된 질문 5개 중 4개만 답하면 재시도하고, 그래도 빠지면 "라벨 실패"가 되며 answers에 N/A 행이 생기지 않는다.
- [ ] 매핑되지 않은 질문 ID의 답은 버리고 사유 코드를 남기며, 같은 질문에 두 번 답하면 형식 오류다.
- [ ] 실패 chunk는 H5 N/A 비율 분모에서 빠지고 실패 수가 따로 기록된다.

[P1] G7 라벨링 맥락, [P1] G14 추출값 검증: 라벨링 프롬프트에 "참고(인용 불가)" 구간을 두고 파일 제목, 슬라이드 제목, 앞뒤 슬라이드 제목, 1차 축 값을 넣는다. 날짜·담당자 규칙은 chunk 본문에서 뽑은 chunk 단위 값에만 적용하고, 파일 단위 값(`PRD.md` 7.3절)과 파일명의 6자리 `YYMMDD_` 접두는 대상이 아니다. 모호한 날짜는 저장하지 않고 사유 코드만 남긴다. 실행일 이후 날짜는 저장하고 표시한다. 담당자는 인용 안에, 인용은 본문 안에 있어야 저장한다. 프롬프트를 바꾸는 항목이므로 M7 전에 넣거나 2회차까지 동결한다(M7 7단계에 기록).
- [ ] 렌더링된 프롬프트의 참고 구간에 위 항목이 있고 앞뒤 슬라이드 본문은 없다.
- [ ] 1차 결과가 바뀐 chunk에만 3차 호출이 나간다.
- [ ] 앞 슬라이드 제목에서만 가져온 인용은 근거 불일치가 된다.
- [ ] "2026.9.3"은 `2026-09-03`으로 저장되고 "26/09/03"은 저장되지 않는다.
- [ ] 인용 밖의 담당자 값은 저장되지 않고, 사유 코드에 이름이 없다.
- [ ] 파일명이 `260807_`로 시작하는 샘플 1의 파일 단위 날짜는 이 규칙으로 거부되지 않는다.

### M5. 4차 불량 목록 추출과 검수 화면

만드는 파일: `review.py`, `screens/review.html`

4차 불량 목록 추출은 LLM을 부르지 않고 3차까지 저장된 값(`labels`, `chunks`의 파싱 경고, `failures`)만으로 판정한다. 기준값은 `pipeline.json`의 `flag` 블록이다. 사유 코드는 다음 6개다.

- `UNKNOWN_HIGH`: 활성 분류 축 중 값이 `unknown`인 축의 비율이 `flag.unknown_ratio_min`(기본 0.5) 이상이다. 비활성 축과 `해당 없음`인 축은 분모에서 뺀다.
- `LOW_CONFIDENCE`: 그 chunk의 답 중 확신도가 `flag.confidence_min`(기본 0.7) 미만인 것이 있다.
- `QUOTE_NOT_FOUND`: 근거 인용이 정규화 후에도 chunk 본문에 없다(G14). 정규화, 짧은 인용 약신호, 생략 인용 규칙은 아래 기준을 따른다. 짧은 인용 약신호는 기록만 하고 사유 코드로 올리지 않는다.
- `PARSE_WARNING`: 파싱 경고가 있다.
- `CLASSIFY_FAILED`, `LABEL_FAILED`: 분류나 라벨링이 실패했다.

`review`는 검수 기준 실행 ID(최신 또는 `--run`)로 `flagged_chunks(run_id, chunk_id, reason_codes, unknown_ratio, min_confidence, text_hash)`를 만들고, `reports/flagged_<실행ID>.jsonl`과 `reports/flagged_<실행ID>.md`(사유 코드별 건수 요약과 목록)를 쓰고, 걸린 chunk 전부를 `screens/review.html`에 올린다. 상한은 없다. 두 리포트 파일에는 chunk ID, 파일 ID, 사유 코드, 수치만 넣고 본문·파일명·경로는 넣지 않는다. 같은 실행 ID로 `review`를 다시 돌리면 그 실행 ID의 `flagged_chunks`를 현재 기준값으로 다시 만든다.

[P0] 불량 판정:
- [ ] mock 결과로 사유 코드 6개가 각각 한 번 이상 걸리는 픽스처에서 `flagged_chunks`가 기대 행과 같다.
- [ ] unknown 비율이 0.49인 chunk는 `UNKNOWN_HIGH`가 걸리지 않고 0.5면 걸린다. 비활성 축은 분모에서 빠진다.
- [ ] 확신도 0.69인 답이 있는 chunk는 `LOW_CONFIDENCE`가 걸리고, 0.7이면 걸리지 않는다.
- [ ] 근거 인용이 본문과 대시 문자(− 와 -)나 µ 문자(U+00B5와 U+03BC)만 다르면 일치로 처리된다.
- [ ] "A … B" 생략 인용은 조각이 순서대로 본문에 있을 때만 일치다.
- [ ] 짧은 인용(한글 2자 이하, 영숫자 4자 이하)은 약신호로 기록되고, 짧은 인용 약신호만 있는 chunk는 `QUOTE_NOT_FOUND`로 걸리지 않는다.
- [ ] `review` 실행 중 LLM mock 호출이 0회다.
- [ ] `flag.unknown_ratio_min`·`flag.confidence_min`을 바꾸고 `review`를 다시 돌리면 LLM 호출 없이 목록이 바뀐다.

[P0] 불량 목록 출력:
- [ ] 걸린 chunk 수, 화면에 올라간 chunk 수, `flagged_<실행ID>.jsonl` 줄 수가 같다(상한 없음).
- [ ] `flagged_<실행ID>.md`에 사유 코드별 건수 요약과 목록이 있다.
- [ ] `flagged_*.jsonl`·`flagged_*.md`에서 chunk 본문, 파일명, 경로를 검색하면 0건이다.

[P0] G16 검수 화면:
- [ ] 화면 목록이 사유 코드가 많이 겹친 순으로 정렬되고, 사유 코드별 필터가 있다.
- [ ] 같은 `dup_group`의 chunk는 묶여서 보이고, 교정은 chunk별로 기록된다.
- [ ] 검수 화면 HTML 데이터에 축 값마다 `taxonomy` 시트의 정의·판정 규칙이 있고, 판정 칸에 "판단 불가" 선택지가 있다.
- [ ] HTML 데이터에 chunk마다 대표 상대 경로, 파일명, 슬라이드 번호가 있고, 교정 파일(`.json`)에는 경로와 파일명이 없다.
- [ ] `CLASSIFY_FAILED`·`LABEL_FAILED` chunk는 봇 값 없이 판정 칸만 나온다(분류 실패면 축 값과 `Q-COM-001`만).
- [ ] 검수 화면이 외부 주소를 참조하지 않는다.
- [ ] 검수 화면은 chunk당 이미지를 기본 4개까지만 data URL로 넣고, 설정으로 조정할 수 있다.
- [ ] "확인, 이상 없음"으로 기록한 건이 검수 상태에 "사람이 확인"으로 남는다.
- [ ] 검수 화면에서 `synonyms` 시트와 일치한 본문 표현이 표시된다.
- [ ] 검수 화면에서 본문 표현을 골라 표준어를 지정한 교정 파일(`.json`)을 반영하면, `reports/candidates.md`에 출처 "검수 등록" 행으로 맨 앞에 나오고 `taxonomy.xlsx`는 바이트 단위로 그대로다.

[P0] G2 교정 반영(`apply`):
- [ ] `flagged_chunks`가 없는 실행 ID의 교정 파일은 반영이 거부된다.
- [ ] `review` 이후 본문(`text_hash`)이나 질문 문장이 바뀐 chunk의 교정은 반영하되 재검수 대상으로 표시된다.
- [ ] 같은 교정 파일을 두 번 반영해도 DB 내용이 같다.
- [ ] 교정 파일을 반영하면 최종 라벨이 사람 값이 되고, 전체를 재실행해도 그대로이며, `corrections`에 봇 원답이 남는다.
- [ ] 재실행 뒤에도 원래 실행 ID의 교정 파일이 반영된다.

### M6. 산출, 조회 검증, 재실행

만드는 파일: `export.py`, `querycheck.py`, `report.py`, `tools/evalgold.py`, `labelbot/metrics.py`(`tools/evalgold.py` 전용 지표), `prompts/propose_queries.md`, `prompts/text_to_sql.md`

완료 기준:
- [ ] 산출 SQLite의 facet_labels, answers, extracted_values에 있는 모든 ID가 대상 표에 존재한다.
- [ ] facet_values에 같은 축과 표준 값의 조합이 두 번 나오지 않는다.
- [ ] 조회 질문 ID는 `QRY-` + 정규화(NFKC·소문자·공백 축약) 문장의 sha256 앞 8자이며 재실행해도 같다.
- [ ] 산출 폴더에 base64 원문과 LLM 캐시가 없다.
- [ ] `SCHEMA.md`에 산출 SQLite의 모든 표와 열이 설명되어 있다(스키마와 문서를 대조하는 테스트).
- [ ] 조회 검증에서 SELECT가 아닌 SQL이나 여러 문장으로 된 SQL은 실행되지 않는다.
- [ ] 채택된 조회 질문마다 SQL, 결과 건수, 정답 포함 여부가 리포트에 나온다.
- [ ] 리포트 첫머리에 N/A 비율, 중복 라벨링 비율, 알림 여부가 나온다.
- [ ] 리포트에 분포 항목이 나온다: 축별 unknown 비율, 질문별 O/X/N/A 분포(n≥20이면서 N/A가 95% 이상이거나 5% 이하인 질문 표시, G9), 중복 라벨링 비율, H5 알림 여부, 사유 코드별 불량 건수와 전체 대비 비율, 실패 chunk 수, `dup_group` 중복 비율, 교정 건수. 비활성 축은 "비활성"으로 표시된다. 일치율·혼동 행렬 같은 정확도 지표는 내지 않는다.
- [ ] 실패 건수 전체가 리포트에 나온다.
- [ ] 교정 반영 후 재실행하고 mock 답을 바꿔도 `report --run <검수 기준 실행 ID>`의 내용이 같고, 새 실행의 리포트에는 "검수 없음"이 나온다(G2).
- [ ] 빈 작업 폴더에서 `run`을 돌리면 사외 호출이 0회다(G19).
- [ ] 리포트에 동의어 시트 항목 수, 시트 항목이 일치한 chunk 비율, 동의어 후보 수, 축별 `unknown / (전체 − 해당 없음)` 비율, 값별 빈도(1% 미만·50% 초과 표시)가 나오고, 비활성 축은 "비활성"으로 표시된다.
- [ ] taxonomy를 바꾸지 않고 전체를 재실행하면 mock 호출이 0회다. 실패 chunk는 끝난 chunk로 보지 않으며 재시도 호출이 나간다(G6).
- [ ] 질문 하나를 추가하고 재실행하면 그 질문이 매핑되는 chunk에 대해서만 라벨링 호출이 나간다.
- [ ] `synonyms` 시트에 동의어 1행을 추가하고 재실행하면, 그 표현이 본문에 있는 chunk에 대해서만 분류·라벨링 호출이 나간다.
- [ ] 산출 SQLite의 aliases 표가 동의어·표준어 2열이고, meta 표에 입력 파일 sha256, 시트별 해시 6개(시트가 없으면 빈 시트 해시), 비활성 축이 있다.
- [ ] `python -m labelbot run`으로 정답표 10개 파일에 전 단계가 mock으로 끝까지 돌고 리포트(`.md`)가 생성된다.
- [ ] `queries` 시트의 채택=Y 행만 조회 검증에 쓰이고, `queries` 시트만 바뀐 재실행에서는 분류·라벨링 호출이 0회다.
- [ ] mock은 정답표에서 mock 응답을 만들어 저장 결과, 3상태 집계, H5 분모를 확인한다(배관 검증).
- [ ] `tools/evalgold.py`(개발 전용)가 실제 LLM 결과를 정답표와 대조해 축별 완전 일치율, Jaccard, 혼동 행렬을 `.md`로 낸다. 합격선은 정하지 않는다.
- [ ] 필수층 미확정이면 실패: 정답표 필수층(합성 픽스처 6개와 파일 4개 18 chunk)에 `confirmed=true`가 하나라도 빠지면 정답표 테스트가 실패한다(skip이 아니다). 커버리지층은 리포트에 확정률만 낸다. 정답표 테스트는 `defaults/taxonomy.xlsx` 의존 테스트처럼 별도 모듈로 분리되어, 확정 전에는 그 모듈만 실패한다.
- [ ] 정답표 확정 절차: 초안 → 필수층 3 chunk 앵커링 측정(사용자가 초안을 보기 전에 따로 라벨링해 초안과의 일치율을 리포트에 낸다) → 사용자가 `gold_labels.md`에서 틀린 칸을 알려 주면 jsonl에 반영하고 `confirmed=true` → 커버리지층은 나중에 확정한다.

[P0] G16 산출 스키마:
- [ ] 산출 SQLite의 files에 `file_name`, `rel_path`(NOT NULL)가 있고 `file_locations` 표가 있으며 모든 `file_id`가 files에 있다.
- [ ] `SCHEMA.md`에 1:N 관계 설명과 경로로 파일을 찾는 예시 SQL이 있다(스키마·문서 대조 테스트에 포함).
- [ ] `out/` 어디에도 입력 루트 절대 경로가 없다.

[P0] G17 금지 확장자 전수 검사: 정답표 10개 파일로 `python -m labelbot run`을 mock으로 끝까지 돌리고, `compare`·`review`로 화면 2개를 생성하고, mock 교정 `.json`을 `apply`로 반영한 뒤 검사한다. 실행 전 작업 폴더의 파일 목록(경로, 크기, 수정 시각)을 저장해 두고 새로 생기거나 바뀐 파일만 검사한다. 입력 전용 경로(`taxonomy.xlsx`, `pipeline.json`, `raw/`, `inbox/`)는 명시적으로 제외한다.
- [ ] 작업 폴더와 `out/`을 재귀로 볼 때 새로 생긴 파일의 확장자가 모두 `CLAUDE.md` 쓰기 규칙의 허용 목록 `.b64 .sqlite .json .jsonl .html .md .log` 안에 있다. 목록 밖이면 파일 목록과 함께 실패한다.
- [ ] 실행이 끝난 뒤 SQLite 저널 파일(`-journal`, `-wal`)이 남아 있지 않다.
- [ ] 통합 테스트는 `taxonomy_path`를 `defaults/taxonomy.xlsx`로 지정해 복사 없이 읽으며, 작업 폴더에 `taxonomy.xlsx`를 두지 않는다.
- [ ] 저장소의 `prompts/`에 `.txt` 파일이 0개다(전부 `.md`).

[P0] G16 로그·리포트 비노출 검사, 원본 경로 단일 열기 검사:
- [ ] 위 통합 실행 뒤 `logs/`, 콘솔 출력, `reports/`(리포트, `alerts.json`, 후보 리포트 제외)에서 정답표 파일명, 테스트 폴더명, 입력 루트 경로를 검색하면 0건이다. 반면 `work.sqlite`와 산출 SQLite에는 상대 경로와 파일명이 있다.
- [ ] 통합 실행 동안 테스트가 `builtins.open`과 `io.open`을 감싸 호출을 기록하고, 입력 루트 아래 경로나 입력 전용 파일(`taxonomy.xlsx`, `defaults/taxonomy.xlsx`, `inbox/*.json`)을 연 호출이 모두 `ingest.read_input`에서 나왔는지 호출 스택으로 확인한다. `write_roundtrip`의 임시 파일은 예외다.

[P1] G12 조회 검증:
- [ ] 결과가 25건이고 정답을 포함하면 K=20 기준 "과다 결과"로 판정된다.
- [ ] 질문마다 라벨 스키마와 라벨 제거 스키마(files, `file_locations`, chunks만) SQL의 판정이 나란히 나온다. 두 경로 모두 읽기 전용 단일 SELECT다.
- [ ] 채택 질문이 10개 이하이면 정답률 전체에 "참고"가 붙는다.

[P1] G1 정답표 대조:
- [ ] `tools/evalgold.py`가 `labelbot/metrics.py`로 더미 정답표 대조 지표를 낸다.

[P1] 리포트 재계산:
- [ ] 같은 `work.sqlite`로 새 코드에서 `report --run <ID>`를 돌리면 LLM 호출 0회로 분포 항목이 다시 계산된다.

[P1] 리포트 요약:
- [ ] 기준선 리포트 첫 20줄 안에 사유 코드별 불량 건수와 전체 대비 비율, 실패 chunk 수, `dup_group` 중복 비율, 교정 건수, H5 알림 여부가 있다.

### M6b. 임베딩과 벡터 적재

만드는 파일: `labelbot/embed.py`, `labelbot/vectorpush.py`, `docs/supabase_schema.md`. 둘 다 chunk가 확정된 뒤 따로 돌리는 명령이며(`PRD.md` FR-9), 분류·라벨링·검수·산출은 이 단계에 의존하지 않는다. 실패는 사유 코드로 기록하고 다른 단계를 막지 않는다. 우선순위는 둘 다 P1이다(chunk에서 다시 만들 수 있다).

[P1] G20 임베딩 (`python -m labelbot embed`): chunk 벡터를 만들어 로컬 `work.sqlite`에 보관한다. 검색, RAG, graph는 만들지 않는다. 설정은 `pipeline.json`의 `embedding` 블록이며 키와 기본값은 `base_url`, `path`("/embeddings"), `model`("text-embedding-3-small"), `api_key_env`("OPENAI_API_KEY"), `auth_header`("Authorization"), `extra_headers`({}), `ca_file`(null), `timeout`(60), `batch_size`(64), `enabled`(true)다. 호출은 `urllib` 기반 OpenAI Embeddings 호환이고, 입력은 chunk의 파싱된 텍스트다(base64 문자열은 넣지 않는다, `CLAUDE.md` "DRM 규칙"). 호스트 판정, 더미 해시 조건, 리다이렉트 거부, 키 비노출은 G19 공용 함수를 쓴다. 저장은 `chunk_embeddings(chunk_id, model, dim, text_hash, vector BLOB, run_id)`이고 키와 직렬화는 2절 "ID와 해시 정의"를 따른다. `text_hash`와 `model`이 같으면 다시 호출하지 않으며, 모델이 다른 벡터는 같은 조회에서 섞지 않는다.
- [ ] mock 서버로 chunk N개를 넣으면 `chunk_embeddings`에 N행이 생기고 `dim`이 응답 벡터 길이와 같다.
- [ ] 같은 입력으로 다시 돌리면 호출이 0회다.
- [ ] `enabled=false`면 `embed` 호출이 0회다. `run`은 `embedding`·`supabase` 설정과 무관하게 끝까지 간다.
- [ ] 사외 호스트 설정에서 더미 해시 밖 파일의 chunk가 있으면 그 호출이 0회로 거부되고 사유 코드가 남는다.
- [ ] mock 서버가 받은 요청 본문에 base64 문자열이 없다.
- [ ] 로그에서 본문, 파일명, 테스트 키를 검색하면 0건이다.
- [ ] mock 서버가 오류를 내도 `embed`는 사유 코드를 남기고 끝나며, 이미 만든 산출과 이후 `run`·`push-vectors` 실행은 영향을 받지 않는다.

[P1] G21 Supabase 벡터 적재 (`python -m labelbot push-vectors`): `chunk_embeddings`의 벡터를 Supabase(Postgres + pgvector) 표에 올리는 데까지만 한다. 검색·RAG·graph는 만들지 않는다. 로컬 `chunk_embeddings`가 원본이고 Supabase는 사본이다.
- 설정: `pipeline.json`의 `supabase` 블록. 키와 기본값은 `enabled`(false), `url`, `table`("chunk_embeddings"), `key_env`("SUPABASE_SERVICE_KEY"), `batch_size`(100), `timeout`(60), `ca_file`(null)이다. 키는 환경변수에서만 읽는다.
- 호출: `urllib`로 `POST {url}/rest/v1/{table}`, 헤더 `apikey`, `Authorization: Bearer`, `Prefer: resolution=merge-duplicates`(chunk ID + 모델 기준 upsert). 리다이렉트 거부 opener와 호스트 판정 함수는 LLM 호출과 같은 것을 쓴다. 호스트가 `internal_host_suffixes`에 없으면 사외이고, 사외에는 파일 해시가 더미 해시 목록에 있는 chunk만 보낸다. 입력이 0개면 호출 0회다.
- 보내는 열: chunk ID, 파일 ID(sha256), chunk 순번, 모델, 차원, 벡터, chunk 본문, 확정 라벨(JSON), 실행 ID. 파일명과 경로는 보내지 않는다.
- 멱등: 로컬 `vector_push_log(chunk_id, model, text_hash, label_hash, target_host_hash, pushed_at, result_code)` 표. `label_hash`는 2절 "ID와 해시 정의"를 따른다. 같은 대상 호스트에 같은 chunk ID·모델·`text_hash`·`label_hash`로 `result_code`가 성공인 기록이 있으면 다시 보내지 않으므로, 같은 내용을 다시 돌리면 호출이 0회다. 확정 라벨이 바뀐 chunk는 `label_hash`가 달라져 그 chunk만 다시 올라간다.
- Supabase 표 정의(pgvector)는 `docs/supabase_schema.md`에 SQL 코드 블록으로 둔다. `.sql` 파일은 허용 형식이 아니므로 만들지 않는다.
- [ ] mock 서버로 N개를 올리면 요청 본문 행 수의 합이 N이고 `vector_push_log`가 N행이다.
- [ ] 검수 교정으로 chunk 1개의 확정 라벨만 바꾸고 `push-vectors`를 다시 돌리면 요청 본문 행 수가 1이고 그 chunk의 라벨이 교정 값이다. 나머지 chunk는 전송이 0건이다.
- [ ] 다시 돌리면 호출이 0회다.
- [ ] 실패 기록 뒤 다시 돌리면 그 chunk만 다시 보낸다.
- [ ] `enabled=false`면 호출이 0회다.
- [ ] 사외 호스트 설정에서 더미 해시 밖 chunk가 있으면 그 chunk의 전송이 0건이고 사유 코드가 남는다.
- [ ] mock 서버가 302를 내면 실패로 기록되고, 새 호스트(다른 포트의 mock 서버)로 요청이 가지 않는다.
- [ ] 로그와 `vector_push_log`에서 chunk 본문, 파일명, 테스트 키를 검색하면 0건이다. 요청 본문에 파일명·경로 열이 없다.
- [ ] 모델이 다른 벡터를 같은 표에 섞어 올리려 하면 호출 전에 거부되고 사유 코드가 남는다.
- [ ] 입력 0개면 호출이 0회다.
- [ ] `docs/supabase_schema.md`에 SQL 코드 블록이 있고 저장소에 `.sql` 파일이 0개다.
- [ ] mock 서버가 오류를 내도 라벨링·산출 단계가 끝까지 간다.

### M7. 사내 반입과 100개 실행

사내에서 사용자가 진행한다. 순서대로 한다. G-1~G-10은 게이트 항목이며(gap ID G1~G21과 구분하려고 하이픈을 붙인다), 7단계(100개 실행) 전에 모두 PASS여야 한다. 같은 업무 PC에서 Python·메모장·브라우저로 여는 확인은 필요조건일 뿐이다(투명 복호화는 같은 PC의 다른 프로그램에도 해당할 수 있다). 사외로 반출하는 형식의 충분조건은 G-10이다.

1. GitHub zip을 내려받아 압축을 풀고 self-check를 돌린다. 이 시점에는 작업 폴더에 `taxonomy.xlsx`가 없으므로 전 항목 PASS는 5단계 뒤에 판정한다. **G-1**: `write_roundtrip` 항목만 PASS다(7개 확장자, 필요조건).
2. `pipeline.json`의 `llm`, `embedding`, `supabase` 세 블록을 사내 값으로 바꾼다(`base_url`·`url`, `model`, `internal_host_suffixes`(사내 도메인), 필요하면 `auth_header`, `extra_headers`, `ca_file`, 경로). 사내에서 벡터 DB(Supabase 또는 사내 Postgres + pgvector)를 쓸 수 있는지 확인하고, 쓸 수 없거나 사내 호스트가 아니면 `supabase.enabled`를 false로 둔다. **G-2**: self-check의 호스트 판정 항목과 LLM 항목만 PASS다(호스트 판정 "사내"). 사내 파일로 LLM·임베딩·벡터 적재를 부르는 어떤 단계보다 먼저 한다.
3. 사내 파일 1개로 `ingest`를 돌려 DRM 해제, base64 저장, 이미지 저장이 되는지 확인한다. **G-3**: 수집 → `.b64` → 디코딩 → 시그니처 검사가 통과한다. **G-4**: 추출 이미지 `.b64`와 `b64/`의 파일을 같은 PC의 메모장으로 열어 base64 평문으로 보인다(필요조건).
4. 점검 스크립트(`probe`)로 100개 파일의 구조 통계를 본다. 처리하지 못하는 요소가 많으면 사유 코드와 통계를 사외로 전달해 파서를 보강한다.
5. `defaults/taxonomy.xlsx`를 작업 폴더로 `taxonomy.xlsx`라는 이름으로 복사하고(봇은 복사하지 않는다), `taxonomy` 시트에 제품·세대 값을, `synonyms` 시트에 사내 동의어를, `files` 시트에 맥락 메모와 제외를 적는다. **G-5**: `taxonomy.xlsx`가 `read_input`으로 읽힌다(`ENCRYPTED`나 `NOT_OOXML` 사유 코드가 아니다). 여기서 self-check를 다시 돌려 전 항목 PASS를 확인한다.
6. 기본본 그대로(승인된 질문은 `Q-COM-001` 하나) 사내 파일 1개로 `run`을 끝까지 돌리고 `compare`·`review`로 화면 2개를 만든다. **G-6**: `screens/*.html`을 브라우저로 열어 내용이 보인다(`review.html`은 불량 목록과 사유 코드 필터가 보인다). **G-7**: `out/labeling.sqlite`를 Python이 아닌 소비자(사내 SQL 도구)에서 열어 조회가 된다. **G-8**: `reports/`의 `.md`·`.json`(`flagged_<실행ID>.jsonl`·`.md` 포함), `alerts.json`, `logs/`의 `.log`, 작업 폴더의 `.jsonl`을 같은 PC의 메모장이나 브라우저로 열어 평문으로 보인다(필요조건). **G-9**: 화면에서 내려받은 `.json`을 `inbox/`에 넣고 `apply`가 성공한다. **G-10**: 사외로 반출하는 형식(기준선 리포트 `.md`, 게이트 기록 `.json`, 필요하면 `.log`)을 실제 반출 경로로 옮긴 뒤, 또는 DRM 에이전트가 없는 PC에서 열어 평문으로 보인다. 이어서 `python -m labelbot gate record`로 항목별 PASS/FAIL을 입력해 `reports/gate_<timestamp>.json`에 남긴다(self-check와 게이트는 실행 ID를 발급하지 않으므로 시각을 쓴다). 경로와 파일명은 넣지 않는다.
7. 전 단계를 실행한다. 중간에 `reports/candidates.md`의 새 값·질문·동의어 후보를 보고 시트에 붙여넣은 뒤 재실행한다. 라벨 분포 알림이 나오면 원인을 점검한다. 프롬프트를 바꾸는 P1 항목(G7, G14)을 이번 회차에 넣을지 2회차까지 동결할지 기록한다.
8. 파싱 대조 5개, 검수, 조회 질문 채택(`queries` 시트에 붙여넣고 채택 열을 Y로 둔다)을 한다. 검수 화면은 프롬프트와 taxonomy를 고정하고 마지막 재실행을 끝낸 뒤 생성하며, 그 시점의 실행 ID가 검수 기준 실행 ID다. 검수 중 발견한 동의어는 교정 파일에 담고, `candidates.md`의 "검수 등록" 행을 시트에 붙여넣는다.
9. 후보와 "검수 등록" 행을 붙여넣은 뒤 재실행해, 바뀐 표현이 있는 chunk만 다시 처리되는지 본다. 기준선 리포트는 `report --run <검수 기준 실행 ID>`로 고정해서 본다. 필요하면 `embed`와 (`supabase.enabled`가 true일 때만) `push-vectors`를 돌린다. 이 두 명령의 실패는 기준선 판정을 막지 않는다.
10. 불량 목록과 분포 리포트를 확인하고, 검수 화면에서 교정한다.

게이트가 FAIL이면 100개 실행을 시작하지 않는다. 실패 보고는 `gate record`의 화면 출력(항목 번호, PASS/FAIL, 형식명, 사유 코드)을 사용자가 손으로 옮겨 적어 사외로 전달한다(`.json` 반출 자체가 실패했을 수 있다). 처리 순서는 "사외에서 대안 반영 → 새 zip → 사내에서 게이트 전체 재실행"이다.

게이트 형식별 실패 시 대안: `.jsonl`·`.json` 내부 상태가 실패하면 `work.sqlite`의 표로 옮긴다. `.md` 리포트가 실패하면 `.html`로 낸다. `.log`가 실패하면 `work.sqlite`의 로그 표와 콘솔만 쓴다. `.b64`가 실패하면 이미지와 원본 base64를 `work.sqlite`에 넣는다. 내려받은 `.json`이 실패하면 텍스트 복사 방식(`PRD.md` FR-7)을 쓴다. G-10만 실패하면 사외 반출을 손으로 옮겨 적는 수치 요약으로 대신한다. `.html`이 실패하면 게이트 결과를 보고 정한다. `.sqlite`는 사내 변환에서 DRM 문제가 없다고 사용자가 확인했으므로 대안을 두지 않는다.

완료 기준:
- [ ] 5단계 뒤 다시 돌린 self-check가 전 항목 PASS다.
- [ ] `reports/gate_<timestamp>.json`에 G-1~G-10이 모두 PASS로 있고, 경로와 파일명이 0건이다.
- [ ] 검수 기준 실행 ID의 `flagged_chunks`와 `reports/flagged_<ID>.jsonl`·`.md`가 작업 폴더에 남고, 교정 파일이 반영되어 `corrections`에 사람 값과 봇 원답이 있다.
- [ ] 산출 SQLite의 모든 files 행에 상대 경로와 파일명이 있고, 같은 해시가 여러 위치에 있으면 `file_locations`에 모두 있다.
- [ ] G17 금지 확장자 검사를 사내에서 한 번 더 돌려 통과한다.
- [ ] `pipeline.json`에서 사내 값으로 바뀐 블록이 `llm`, `embedding`, `supabase` 세 개뿐이고, 벡터 DB 사용 가능 여부와 `supabase.enabled` 값이 게이트 기록에 남는다.
- [ ] 사내 파일 1개에서 chunk가 생성되고 이미지 저장 방식이 확정된다.
- [ ] 100개 실행 후 실패 파일이 사유 코드와 함께 목록화된다.
- [ ] 파싱 대조 5개와 검수가 끝나고 교정이 반영된다.
- [ ] 시트로 옮긴 동의어가 다음 실행에 반영되고 해당 chunk만 재처리된다.
- [ ] `out/`에 SQLite 파일, `SCHEMA.md`, 이미지 폴더가 있다.
- [ ] 기준선 리포트에 분포 항목(사유 코드별 불량 건수 포함)과 조회 정답률이 나온다.

## 4. Human in the loop 지점

`PRD.md` 3.2절의 HITL 지점을 어느 마일스톤에서 구현하는지 정리한다.

| # | 사람이 하는 일 | 진행 | 구현 위치 | 마일스톤 |
|---|---|---|---|---|
| H1 | 대상 파일 확인, 맥락 메모, 제외, 동의어 제공 | 대기 | `taxonomy.py`(`files`·`synonyms` 시트 읽기), `candidates.py`(`reports/file_list.md` 붙여넣기 행) | M2 |
| H2 | 파일 5개 파싱 대조 | 계속 | `screens/compare.html` | M1 |
| H3 | 새 값 후보 처리(값·동의어·기각을 엑셀에 붙여넣기) | 계속(처리 전 후보는 `unknown`으로 둔다) | `candidates.py`, `classify.py` | M2 |
| H4 | 질문 후보 승인(`questions` 시트에 붙여넣기) | 대기 | `candidates.py`, `questions.py` | M3 |
| H5 | 라벨 분포 알림 확인 | 계속 | `alerts.py`, `label.py`, `report.py` | M4, M6 |
| H6 | 불량 목록의 chunk 검수. 건수는 실행마다 다르고 사유 코드 필터로 우선순위를 정한다. 동의어 "검수 등록" | 대기 | `screens/review.html`, `review.py`, `candidates.py` | M5 |
| H7 | 조회 질문 채택(`queries` 시트) | 대기 | `taxonomy.py`(`queries` 시트 읽기), `candidates.py`(`reports/query_candidates.md`), `querycheck.py` | M6 |
| H8 | 동의어 후보 승인(`synonyms` 시트에 붙여넣기) | 계속(처리 전 후보는 시트에 넣지 않는다) | `candidates.py` | M2, M4 |
| 게이트 | 사내 설정 변경(`llm`, `embedding`, `supabase` 블록), 벡터 DB 사용 가능 여부 확인, G-1~G-10 확인과 `gate record` 입력 | 대기(FAIL이면 100개 실행을 시작하지 않는다) | `selfcheck.py`, `gate.py` | M0, M7 |
| 벡터 적재 | `supabase.enabled`를 켤지 정하고 `push-vectors` 실행 | 계속(실패해도 라벨링·산출은 진행한다) | `embed.py`, `vectorpush.py` | M6b, M7 |

게이트와 벡터 적재 행은 `PRD.md` 3.2절의 H1~H8 밖에서 plan이 추가한 운영 지점이다.

H5 알림 조건(1회 실행, 내용 유형 chunk 기준, 둘 중 하나라도 해당하면 알린다):

- 3차 라벨링 답 중 N/A 비율이 30% 이하다.
- 분류 축 중 다중값=Y이고 중복 알림 제외=N인 축의 라벨 40% 이상이 중복 라벨링(한 chunk의 같은 축에 값이 두 개 이상)이다. 분모와 분자에서 `unknown`과 `해당 없음`을 뺀다.

후보 처리 흐름(`PRD.md` 6절): 사람이 만든 `taxonomy.xlsx`로 실행 → 봇이 후보 리포트(`reports/candidates.md` 등)를 낸다(H3·H4·H6·H8) → 사람이 보고 엑셀에 붙여넣는다 → 재실행하면 바뀐 시트 해시에 따라 영향받는 chunk만 재처리된다. 봇은 엑셀을 수정하지 않는다.

## 5. 리스크와 대응

| 리스크 | 대응 | 관련 단계 |
|---|---|---|
| 사내 파일 구조가 샘플과 달라 파서가 텍스트를 놓친다. | 점검 스크립트 통계와 파싱 대조로 확인한다. 차트 제목·계열·범주는 첫 실행 전에 `[차트]` 구간으로 넣고(G15), 그룹 도형 처리는 통계를 본 뒤 보강한다. | M0, M1, M7 |
| 사내 오류를 사외로 가져올 수 없다. | 사유 코드형 로그, self-check, mock으로 재현 가능한 테스트. | M0 |
| 사내 Python이 사외 기준(3.14.2)보다 낮거나 sqlite3가 없다. | self-check에서 먼저 확인한다. 실패하면 구현을 진행하기 전에 대안을 정한다. | M0, M7 |
| 추출 이미지나 허용 형식 파일에 DRM이 다시 걸린다. | 이미지를 `.b64`로 저장하고 화면에는 data URL로 넣는다. `write_roundtrip`(G18)과 M7 게이트 G-1~G-10으로 사용하는 확장자 전부를 100개 실행 전에 확인한다. | M0, M1, M7 |
| `write_roundtrip`과 같은 PC의 확인이 거짓 PASS를 낸다. | 같은 PC의 확인(G-1, G-4, G-6~G-9)은 필요조건으로만 쓰고, 사외로 반출하는 형식은 반출 경로를 거친 뒤나 DRM 에이전트가 없는 PC에서 여는 G-10을 통과해야 진행한다. | M0, M7 |
| 사외 엔드포인트로 사내 자료가 나간다(LLM, 임베딩, 벡터 적재). | 사용자 신고 플래그가 아니라 호스트(`internal_host_suffixes`)와 더미 해시로 판정하고, 불확실하면 거부하며, 리다이렉트를 따라가지 않는다. 엔드포인트 변경을 사내 파일로 호출하는 단계보다 앞(M7 2단계)에 둔다. | M0, M6b, M7 |
| 사내 게이트웨이 형식이 다르다. | 인증 헤더, 추가 헤더, CA, 경로, 타임아웃을 설정 키로 둔다. 그래도 맞지 않으면 사유 코드만 사외로 전달한다. | M0, M7 |
| 경로가 사외로 새어 나간다. | 상대 경로만 저장하고 절대 경로는 실행 메타에만 둔다. 로그, 콘솔, 리포트, `alerts.json`, 교정 파일, 게이트 기록, Supabase 전송 열에서 0건인지 통합 테스트로 본다. | M1, M6, M6b |
| 폴더명이 분류를 끌고 간다. | 참고(인용 불가)로만 넣고 근거는 본문에서 받는다. 처음 본 위치를 고정해 캐시 키를 안정시킨다. | M2 |
| 프롬프트를 바꾸는 P1 항목(G7, G14)은 재계산되지 않는다. | M7 전에 넣거나 2회차까지 동결하고, M7 7단계에 기록한다. | M4, M7 |
| P1 항목이 첫 실행에 없을 수 있다. | `labels`, `failures`, `flagged_chunks`, `corrections`가 남으므로 새 zip으로 호출 0회 재계산이 된다. | M5, M6 |
| 불량 목록이 너무 길다. | 사유 코드 필터와 겹침 순 정렬을 두고, 기준값은 `flag` 블록 설정으로 조정한다. | M5 |
| 사내 정확도는 측정하지 않는다. | 사외 더미 정답표 대조(`tools/evalgold.py`)로만 프롬프트 변경 효과를 본다. | M6 |
| 금지 확장자 검사가 입력 파일 때문에 항상 실패한다. | 실행 전 목록과 비교해 새 파일만 보고, 입력 전용 경로를 명시적으로 뺀다. | M6 |
| 사내에서 임베딩 모델을 바꾸면 차원이 달라진다. | `chunk_embeddings`에 `model`과 `dim`을 두고, 모델이 다른 벡터는 같은 조회에서 섞지 않으며 Supabase 표에 섞어 올리지 않는다. 모델을 바꾸면 그 모델로 다시 만든다. | M6b |
| 사내에서 Supabase나 pgvector를 쓸 수 없다. | `supabase.enabled` 기본값을 false로 두고, 로컬 `chunk_embeddings`를 원본으로 유지한다. M7 2단계에서 사용 가능 여부를 확인해 기록한다. | M6b, M7 |
| Supabase 사본과 로컬 원본이 어긋난다. | `vector_push_log`로 멱등을 보장하고 chunk ID + 모델로 upsert한다. 본문이나 확정 라벨이 바뀐 chunk는 해시가 달라져 다시 올라간다. 어긋나면 로컬 표에서 다시 올린다. | M6b |
| 사내 LLM의 JSON 출력이 불안정하다. | 응답 검증, 재시도, 실패 chunk의 검수 이관. | M2 |
| 좌표 기반 표 복원이 실제 표가 아닌 배치를 표로 오인한다. | 여러 행에서 열 위치가 반복될 때만 표로 본다. 대조 화면에서 확인한다. | M1 |
| HTML 화면 두 개로 구현 범위가 커진다. | 화면은 표시와 기록만 하고 검증과 반영은 Python 쪽에서 한다. 화면 공통 부분(데이터 내장, 내려받기, 텍스트 복사)을 하나로 만든다. chunk당 이미지 상한(기본 4개)으로 HTML 크기를 줄인다. | M1, M5 |
| 봇이 제안한 조회 질문이 지나치게 쉽다. | 본문 표현을 그대로 쓰지 않게 하고, 채택 시 사용자가 문장을 고친다. | M6 |
| 같은 표현이 제품이나 case에 따라 다른 뜻으로 쓰인다. | 동의어는 치환만 하고 범위를 두지 않는다. 검수에서 잘못된 대응을 발견하면 `synonyms` 시트의 행을 사람이 고치거나 지우고, 첫 실행 뒤 필요하면 규칙을 추가한다. | M2, M5 |
| 동의어 부분문자열 오치환(`BM→BM/Liner`는 "RSBM"을 망친다. `Via1`은 "Via12"를 망친다. EM은 SEM 안에서 걸린다). | 한 번에, 긴 키부터 치환하고 표준어 위치를 보호한다. 숫자 경계를 둔다. 기본 시트는 허용 목록 밖의 3자 이하 영문 키를 두지 않고, 사내 시트는 행 번호로 경고한다. | M2 |
| xlsx 파싱 위험: DRM이 풀리지 않은 파일, sharedStrings 계열, 캐시 없는 수식, 숨김 행·필터, 병합 셀, 시트·머리글, Excel 자동 변환. | M2의 R1~R7 태그 체크박스가 위험마다 픽스처로 검증한다. 모든 xlsx 픽스처는 `tests/xlsx_writer.py`가 메모리에서 만든다. | M2 |
| 의사결정 단일값 규칙의 모호성(배경 chunk의 pending 부풀림, 조건부 채택). | 평가 내용이 없으면 `해당 없음`, 조건부 채택은 pending으로 확정했다. SYN-04와 SYN-06으로 고정한다. | M2 |
| 선택 시트 `files`·`queries`의 오입력(ID 오타, 제외 열 값 오류). | 시트·행 오류나 경고를 낸다. 수집 목록에 없는 파일 ID는 경고만 하고 실행은 계속한다. | M2 |
| 정의를 비운 값 때문에 해당 축의 unknown 비율이 높게 나온다. | 기준선 리포트의 축별 unknown 비율로 드러나며, 후보 리포트로 정의를 보강한 뒤 재실행한다. | M6, M7 |
| Excel 재저장만으로 전체가 재처리된다. | 해시를 바이트가 아니라 파싱 값으로 계산한다. | M2, M4 |
| 정답표 범위와 확정 비용이 커진다. | 파일 10개를 고정하고 2계층으로 나눈다. 통과 판정은 필수층만으로 하고, 보충은 합성 픽스처로만 한다. | M2, M6 |
| 사내 v1/v2/final 준중복(바이트 해시가 다름). | chunk `dup_group`으로 표시만 하고 전부 처리한다(확정). 검수 화면에서는 같은 `dup_group`을 묶어 보여 준다. 파일 단위 `near_dup_group`은 리포트에 분포만 낸다. | M1, M5, M7 |

## 6. 검증 단계

1. 마일스톤마다 `python -m unittest discover tests`를 돌려 그 마일스톤의 완료 기준 테스트가 통과하는지 본다.
2. M6 이후 정답표 대상 파일 10개로 전 단계를 mock으로 돌려 산출물과 리포트가 생성되는지 본다. mock은 정답표에서 응답을 만들어 저장 결과, 3상태 집계, H5 분모를 확인한다(배관 검증). `review`로 `flagged_chunks`와 `reports/flagged_*`가 LLM 호출 없이 생성되는지도 본다.
3. M6 이후 같은 통합 실행에서 금지 확장자 전수 검사(G17), 로그·리포트 비노출 검사와 원본 경로 단일 열기 검사(G16)를 돌린다.
4. M6b 이후 테스트 안에서 띄운 `http.server` mock 서버로 `embed`와 `push-vectors`를 돌려 호출 수, `chunk_embeddings`·`vector_push_log` 행 수, 사외 호스트 차단, 302 거부, 키·본문·파일명 비노출을 확인한다. 실제 Supabase로는 사외에서 더미 해시 chunk만 보낼 수 있다.
5. 화면 두 개(파싱 대조, 검수)를 브라우저에서 직접 열어, 데이터가 보이고 사유 코드 필터, 내려받기와 교정 반영이 되는지 확인한다.
6. 사외에서 쓸 수 있는 OpenAI 호환 엔드포인트가 있으면 mock 대신 실제 LLM으로 정답표 파일을 한 번 돌리고, `tools/evalgold.py`로 정답표와 대조해 지표(`labelbot/metrics.py`)를 본다(합격선은 정하지 않는다). 사외 호스트이므로 더미 해시 파일만 호출된다. 없으면 이 단계는 사내에서 한다.
7. 구현 결과를 별도 검토 패스로 점검한다(코드 리뷰, 완료 기준 충족 여부).
8. M7은 사내에서 사용자가 진행한다. 게이트 G-1~G-10이 모두 PASS인 뒤에 100개 실행을 시작하고, 기준선 리포트의 수치(내용 없는 집계)와 게이트 결과(손으로 옮겨 적은 항목 번호, PASS/FAIL, 사유 코드)만 사외로 전달한다.

## 7. 구현 전에 정할 것

- 사외 검증 샘플은 `dummy pptx files/` 폴더의 파일을 쓰며 어느 파일이든 쓸 수 있다. 샘플 2는 현재 `260112_M2 하드마스크 침식 Metal Short 원인.pptx`(sha256 `f073be9c9ade…`)이다. `split_eval_18MP_Ru.pptx`는 없다.
- 사외에서 실제 LLM 검증에 쓸 엔드포인트가 있는지.
- docx 샘플은 폴더에 없으므로 합성 docx로 테스트한다(확정). 실제에 가까운 더미 docx를 받으면 추가한다.
- 임베딩을 내보내기 DB에 넣을지: `chunk_embeddings`를 `out/labeling.sqlite`에도 넣을지. 넣으면 산출 DB가 커지고 `SCHEMA.md`에 벡터 형식 설명이 필요하다. 기본안: `work.sqlite`에만 둔다.
- 임베딩의 용도: 준중복 그룹(G4)에 쓸지, 보관만 할지. 4차 불량 목록 판정에는 쓰지 않는다. 기본안: 보관과 Supabase 사본 적재만 한다.
- 사내에서 Supabase(또는 사내 Postgres + pgvector)를 쓸 수 있는지와 그 주소가 `internal_host_suffixes`에 드는 사내 호스트인지. 기본안: `supabase.enabled=false`로 두고 M7 2단계에서 확인해 게이트 기록에 남긴다.
- 사외 개발용 Supabase 프로젝트를 둘지. 둔다면 사외 호스트이므로 더미 해시 chunk만 올라간다. 기본안: 사외 검증은 mock 서버로만 하고, 실제 Supabase 적재는 선택이다.
- Supabase로 보내는 열에 chunk 본문을 포함할지. 기본안: 포함한다(사본에서 바로 확인할 수 있게). 사내 정책상 본문 사본이 금지되면 본문 열을 빼는 설정을 추가한다.
- 확정된 결정(2026-10-04, `PRD.md` 부록 B): 파일 메모·조회 질문은 선택 시트 `files`·`queries`에 둔다. H4는 "대기"다. 평가 내용이 없는 chunk의 의사결정 상태는 `해당 없음`이다. EUV-SAUP·EUV-SET·ArF-SET는 Patterning 값이고 정의는 비우며, 이에 기대는 정답표 칸은 `unknown`이다. 개발 산출물 확장자 예외는 없다.
- 확정된 결정(2026-10-04, 라벨링 품질 보강 v2 6절, 다시 논의하지 않는다):
  1. 지금은 OpenAI API 기준으로 만들고, 사내 반입 후 사용자가 `pipeline.json`의 `llm`, `embedding`, `supabase` 블록만 고친다.
  2. 정답표 확인에 사용자가 1시간을 쓴다. `tools/gold_view.py`가 만든 `.md`를 보고 틀린 칸만 알린다.
  3. blind 모드는 off로 고정하며 구현하지 않는다. (4차 단계 단순화로 대체됨: 표본 검수가 없어져 이 결정은 쓰지 않는다.)
  4. 준중복은 `dup_group`으로 표시만 하고 전부 처리한다. 이 결정으로 사내 v1/v2/final 준중복 표시 방식의 미결 항목을 닫는다.
  5. 의심 표본은 겹침 순 상위 40과 의심 풀 무작위 10이며, 의심 풀 오답 수 추정식은 "상위 40의 오답 수 + 무작위 10의 오답 수 × (나머지 의심 풀 크기 / 10)"이다. (4차 단계 단순화로 대체됨)
  6. 파일명과 상대 경로 메타데이터는 필수다(G16).
  7. 파이프라인은 `.csv`를 쓰지 않는다. 쓰는 확장자는 `CLAUDE.md` 쓰기 규칙의 허용 목록뿐이다(G17). 프롬프트 파일도 `.md`다.
  8. `.b64`, `.json`, `.sqlite`에 DRM이 다시 걸리지 않는지 100개 실행 전에 사내에서 먼저 확인한다(G18, M7 게이트).
  9. 사외 호출에 taxonomy 조건을 두지 않는다. 사외 호출 허용 조건은 "그 호출에 들어가는 chunk의 파일 해시가 더미 해시 목록에 있음" 하나다.
  10. `internal_host_suffixes` 기본값은 빈 목록이다. 사내 반입 후 사용자가 `pipeline.json`을 직접 고친다.
  11. `.sqlite`는 사내 변환에서 DRM 문제가 없다고 사용자가 확인했다. 게이트 실패 대안은 `.html`에만 두며, 그것도 게이트 결과를 보고 정한다.
  12. G15 차트 텍스트는 첫 실행 전에 넣는다(P0, M1).
  13. 사내 게이트는 기본본 그대로(승인된 질문 `Q-COM-001` 하나)로 돌린다.
  14. 사내 LLM은 도메인 주소로 호출한다. `internal_hosts` 키는 두지 않고 IP 리터럴 거부를 유지한다.
  15. 임베딩은 OpenAI embedding model로 설정하고 결과는 로컬 `work.sqlite`의 `chunk_embeddings`에 보관한다. 외부로 나가는 것은 G21 `push-vectors`의 Supabase 사본뿐이며, 같은 호스트 판정과 더미 해시 조건을 거친다.
- 확정된 결정(2026-10-04, 4차 단계 단순화, 다시 논의하지 않는다):
  1. 4차 단계는 검수 봇이 아니라 "4차 불량 목록 추출"이다(`PRD.md` FR-5). LLM을 부르지 않고 이미 저장된 값만으로 판정한다.
  2. 사유 코드는 `UNKNOWN_HIGH`, `LOW_CONFIDENCE`, `QUOTE_NOT_FOUND`, `PARSE_WARNING`, `CLASSIFY_FAILED`, `LABEL_FAILED` 6개다. 기준값은 `flag.unknown_ratio_min` 0.5, `flag.confidence_min` 0.7이다.
  3. 걸린 chunk는 상한 없이 전부 `flagged_chunks`, `reports/flagged_<실행ID>.jsonl`·`.md`, 검수 화면에 낸다.
  4. 사람이 교정한 값이 최종 라벨이며 재실행해도 덮어쓰지 않는다. 봇 원답은 `corrections`에 남는다.
  5. LLM 독립 재판정, 표본 추출, `review_snapshot`·`review_actions`, `review_gold/`, 사내 정확도 지표는 두지 않는다. 사내 정확도는 측정하지 않고, 프롬프트 변경 효과는 사외 더미 정답표 대조(`tools/evalgold.py`)로만 본다.
- 확정된 결정(2026-10-04, 구현 착수 전 요구사항 정리, 사외 구동 기준). 이 블록이 위의 다른 문구와 충돌하면 이 블록을 따른다.
  1. 현재 구현은 사외 구동 기준이다. Python 버전은 3.14.2 기준으로 한다(1절·M0의 3.8 문법 기준을 대체한다). 사내 Python 버전은 M7에서 self-check로 확인한다.
  2. 벡터 저장소: 사외는 로컬 `chunk_embeddings`(1차)와 사외 Supabase 실제 적재(2차)이며, 오늘 PoC는 실제 Supabase 적재까지 완료 기준에 넣는다(위 "실제 Supabase 적재는 선택"을 대체한다). 사내는 로컬 1차 보관, 2차 사내 DB 저장이며 사내 DB 적재는 이후 범위다. 사내 반입본의 `supabase.enabled` 기본값은 false다.
  3. 키는 코드 폴더 루트 `.env`(`OPENAI_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`)나 셸 환경변수로 넣는다. 셸 값이 우선한다. `.env`는 `.gitignore`로 커밋하지 않고 템플릿 `.env.example`만 커밋한다. `supabase.url`이 비어 있으면 `SUPABASE_URL`을 쓴다.
  4. 의존성: `requirements.txt`는 labelbot 본체용이며 비어 있다(표준 라이브러리만). 사외 PoC SDK(`openai`, `supabase`, `python-dotenv`)는 `requirements-poc.txt`에 두고 labelbot 본체는 import하지 않는다.
  5. 개발 전용 파일 확장자 예외: `.env`, `.env.example`, `requirements*.txt`, `.gitignore`는 사내 데이터를 담지 않는 저장소 파일이므로 허용한다(위 "개발 산출물 확장자 예외는 없다"를 이 파일들에 한해 대체한다). 작업 폴더 금지 확장자 검사(G17)는 그대로다.
  6. 기본 taxonomy의 기준은 커밋된 `defaults/taxonomy.xlsx`다. 부록과 다르면 xlsx가 맞고, `tests/fixtures/default_taxonomy_rows.jsonl`은 xlsx에서 만든다.
  7. 더미 파일은 저장소의 `dummy pptx files/`에 모두 있다(부록 해시 11개 확인).
  8. pptx·docx가 아닌 형식(pdf, hwp, csv, txt, 이미지 등)은 파싱하지 않고 사유 코드 `UNSUPPORTED_FORMAT`으로 실패 목록에 넣는다.
  9. `apply`는 `compare.html`에서 내려받은 파싱 대조 기록 `.json`도 받아 `work.sqlite`에 저장하고, 기준선 리포트에는 대조 파일 수와 이상 슬라이드 건수만 낸다(PRD 8.3·10.2).
  10. HTML 화면 2개는 `design.md.md`를 따른다. 단일 HTML + Vanilla JS, 인라인 CSS 변수 토큰, 시스템 폰트 스택만 쓰고 CDN·외부 폰트는 쓰지 않는다.
  11. 1차 분류 응답은 축 값마다 근거와 확신도(0~1)를 받는다(`LOW_CONFIDENCE`가 축 값과 질문 답을 모두 본다).
  12. 원격 저장소는 `https://github.com/Robonge/BEOL-Datalabeling.git`이다.

## 부록. 기본 taxonomy.xlsx 초기 행

- 기준은 커밋된 `defaults/taxonomy.xlsx`다(2026-10-04 결정). 이 부록은 초기 설계 참고용이며, xlsx와 다르면 xlsx가 맞다. M2 실행자는 xlsx를 `read_input`으로 읽어 `tests/fixtures/default_taxonomy_rows.jsonl`을 만들고, 테스트는 xlsx와 jsonl이 같은지 확인한다. 어떤 도구도 xlsx를 디스크에 쓰지 않는다.
- jsonl은 기본본 회귀 기준이다. 사용자가 xlsx를 고치면 jsonl도 같이 다시 만든다.
- 1행 머리글은 아래 문자열과 순서가 정확히 같아야 한다(`PRD.md` 6.1절과 같다). 기본본에는 선택 시트 `files`·`queries`를 두지 않아도 되며(없으면 빈 시트), 두는 경우 머리글만 둔다.

| 시트 | A | B | C | D | E | F | G | H | I | J | K |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `taxonomy` | 축 | 값 | 상위값 | 다중값 | 계층 | 중복 알림 제외 | 종류 | 정의·판정 규칙 | 포함 예 | 제외 예 | 사용 여부 |
| `questions` | 질문 ID | 문장 | 적용 대상 | 우선순위 | | | | | | | |
| `synonyms` | 동의어 | 표준어 | 메모 | | | | | | | | |
| `rejected` | 종류 | 내용 | 기각일 | 사유 | | | | | | | |
| `files`(선택) | 파일 ID | 파일명 | 제외 | 맥락 메모 | | | | | | | |
| `queries`(선택) | 조회 ID | 문장 | 기대 정답 | 채택 | | | | | | | |

- `taxonomy` 시트는 아래 60행(축 정의 10, 값 50)이다. 쉼표로 묶였던 값도 값마다 한 행으로 펼쳤다. 사용 여부(K)는 모두 비워 Y로 둔다. 사용자가 정의를 주지 않은 값(Mx, Vx, JHV, EUV-SAUP, EUV-SET, ArF-SET)은 정의 칸을 비웠다. 제품·세대 축은 축 정의 행만 있고 값이 없다. ArF-LELE의 정의 문구는 계획이 쓴 초안이고, 사용자가 확정한 것은 Patterning 축 소속뿐이다.
- 의사결정 상태의 "정확히 하나"는 {adopted, rejected, pending, `해당 없음`, `unknown`} 중 정확히 하나로 정의하며, `해당 없음`도 그 하나로 센다.

| 축 | 값 | 상위값 | 다중값 | 계층 | 중복 알림 제외 | 종류 | 정의·판정 규칙 | 포함 예 | 제외 예 | 사용 여부 |
|---|---|---|---|---|---|---|---|---|---|---|
| 구조/레이어 |  |  | Y | N | N | 분류 | 논의 대상 배선층·비아층 |  | barrier/liner(→Material) | |
| 구조/레이어 | M0 |  |  |  |  |  | 해당 번호 금속층 |  |  | |
| 구조/레이어 | M1 |  |  |  |  |  | 해당 번호 금속층 | Metal1(→M1) |  | |
| 구조/레이어 | M2 |  |  |  |  |  | 해당 번호 금속층 |  |  | |
| 구조/레이어 | M3 |  |  |  |  |  | 해당 번호 금속층 |  |  | |
| 구조/레이어 | Mx |  |  |  |  |  |  |  |  | |
| 구조/레이어 | V0 |  |  |  |  |  | 해당 번호 비아층 |  |  | |
| 구조/레이어 | V1 |  |  |  |  |  | 해당 번호 비아층 | Via1(→V1) |  | |
| 구조/레이어 | V2 |  |  |  |  |  | 해당 번호 비아층 |  |  | |
| 구조/레이어 | V3 |  |  |  |  |  | 해당 번호 비아층 |  |  | |
| 구조/레이어 | Vx |  |  |  |  |  |  |  |  | |
| 구조/레이어 | JHV |  |  |  |  |  |  | JGV(오타) |  | |
| 공정 모듈 |  |  | Y | N | N | 분류 | 공정 단계. Patterning·Material과 독립 |  |  | |
| 공정 모듈 | Litho |  |  |  |  |  | 노광·현상·overlay·litho CD | EUV 노광 | 식각 후 CD(→Etch) | |
| 공정 모듈 | Etch |  |  |  |  |  | trench·via 식각, hardmask open, strip | punch-through |  | |
| 공정 모듈 | Dep |  |  |  |  |  | PVD·CVD·ALD, seed, 도금(ECP) | ALD Ru liner |  | |
| 공정 모듈 | CMP |  |  |  |  |  | 금속·barrier 연마 | over-polish |  | |
| 공정 모듈 | Clean |  |  |  |  |  | 식각·CMP 후 세정 | post-CMP clean |  | |
| 제품·세대 |  |  | Y | N | N | 분류 | 사내 제품·세대 코드. 기본본에는 값이 없다 |  |  | |
| REMSPC |  |  | Y | N | N | 분류 | 변경 변수와 원인 범주를 모두 붙인다 | slurry B(→Materials) |  | |
| REMSPC | Reticle |  |  |  |  |  | 마스크·레티클·OPC |  |  | |
| REMSPC | Equipment |  |  |  |  |  | 장비·챔버·하드웨어·PM |  |  | |
| REMSPC | Materials |  |  |  |  |  | 소재 변경 | slurry B |  | |
| REMSPC | Scheme |  |  |  |  |  | integration 구조·공정 순서 | semi-damascene vs DD |  | |
| REMSPC | Process |  |  |  |  |  | 레시피 조건 | anneal 온도 split |  | |
| REMSPC | Controllability |  |  |  |  |  | 산포·재현성·공정 제어 | wafer 내 산포 |  | |
| Patterning |  |  | Y | N | N | 분류 | 패터닝 방식 |  |  | |
| Patterning | EUV-SAUP |  |  |  |  |  |  |  |  | |
| Patterning | EUV-SET |  |  |  |  |  |  |  |  | |
| Patterning | ArF-SET |  |  |  |  |  |  |  |  | |
| Patterning | ArF-LELE |  |  |  |  |  | ArF litho-etch 2회 이중 패터닝 | LELE | SAxP | |
| Material |  |  | Y | N | N | 분류 | 막 재료 범주 |  |  | |
| Material | IMD |  |  |  |  |  | 층간 절연막(low-k, ULK, cap) | ULK |  | |
| Material | BM/Liner |  |  |  |  |  | barrier metal과 liner | TaN/Ta, Ru liner, RSBM |  | |
| Material | Metallization |  |  |  |  |  | 배선 금속 자체 | Cu, Ru, Co, Mo |  | |
| 불량 모드 |  |  | Y | Y | N | 분류 | 전기적 불량 유형. 하위가 불분명하면 상위만 |  |  | |
| 불량 모드 | Open |  |  |  |  |  | 단선 | via open | not open(→물리 현상) | |
| 불량 모드 | Short |  |  |  |  |  | 인접 배선 단락, leakage spec 초과 | 단락 |  | |
| 불량 모드 | Reliability |  |  |  |  |  | 신뢰성 열화 |  |  | |
| 불량 모드 | EM | Reliability |  |  |  |  | 전자이동 |  |  | |
| 불량 모드 | TDDB | Reliability |  |  |  |  | 절연막 시간 의존 파괴 |  |  | |
| 불량 모드 | Parametric |  |  |  |  |  | spec 내 동작하나 전기 특성 이탈 | Rc 상승 |  | |
| 불량 모드 | Rs 산포 | Parametric |  |  |  |  | 배선 저항 산포·상승 |  |  | |
| 물리 현상 |  |  | Y | N | N | 분류 | 물리적 메커니즘. 불량 모드와 별개 |  |  | |
| 물리 현상 | Void |  |  |  |  |  | 충진 내부 공극, seam | 보이드 |  | |
| 물리 현상 | metal bridge |  |  |  |  |  | 금속 잔류로 인접 배선 연결 | 브릿지 |  | |
| 물리 현상 | not open |  |  |  |  |  | 식각 미완으로 하부층 미노출 |  | Open(→불량 모드) | |
| 물리 현상 | unCMP |  |  |  |  |  | 연마 부족 잔류 | residue |  | |
| 물리 현상 | hardmask loss |  |  |  |  |  | hardmask 침식·소실 | MHM erosion |  | |
| 물리 현상 | dishing |  |  |  |  |  | 넓은 배선 상부 과연마 | 디싱 |  | |
| 물리 현상 | CD imbalance |  |  |  |  |  | 인접 패턴 CD 비대칭 | 짝짝이, asymmetry |  | |
| 결과 |  |  | Y | N | Y | 상태 | 조건별로 엇갈리면 모두 붙인다 | SP-01 PASS, SP-02 FAIL(→improved+degraded) |  | |
| 결과 | improved |  |  |  |  |  | 개선 |  |  | |
| 결과 | degraded |  |  |  |  |  | 악화 |  |  | |
| 결과 | neutral |  |  |  |  |  | 차이 없음 |  |  | |
| 결과 | inconclusive |  |  |  |  |  | 판단 불가 |  |  | |
| 의사결정 상태 |  |  | N | N | N | 상태 | 하나라도 채택이면 adopted, 전부 기각이면 rejected, 평가는 있으나 결론 미기재면 pending, 평가 내용이 없으면 해당 없음 |  |  | |
| 의사결정 상태 | adopted |  |  |  |  |  | 채택 |  |  | |
| 의사결정 상태 | rejected |  |  |  |  |  | 기각 |  |  | |
| 의사결정 상태 | pending |  |  |  |  |  | 미결 | 조건부 채택(→pending) |  | |

`questions` 시트 초기 행:

| 질문 ID | 문장 | 적용 대상 | 우선순위 |
|---|---|---|---|
| Q-COM-001 | 이 chunk에 아직 해결되지 않은 위험(추가 확인이 필요한 불량, 미검증 조건, 후속 평가 필요)이 명시되어 있는가. | 공통 | 1 |

`synonyms` 시트 초기 행(메모는 모두 "더미"):

| 동의어 | 표준어 | 메모 |
|---|---|---|
| 단락 | Short | 더미 |
| 단선 | Open | 더미 |
| 보이드 | Void | 더미 |
| 전자이동 | EM | 더미 |
| 일렉트로마이그레이션 | EM | 더미 |
| 짝짝이 | CD imbalance | 더미 |
| asymmetry | CD imbalance | 더미 |
| JGV | JHV | 더미. 3자 영문 허용 목록(`data_labeling_4th.html:405`) |
| Metal1 | M1 | 더미 |
| 1st metal | M1 | 더미 |
| Via1 | V1 | 더미 |
| 디싱 | dishing | 더미 |
| 브릿지 | metal bridge | 더미 |

`bridge→metal bridge`처럼 표준어가 동의어를 포함하는 항목과, 허용 목록 밖의 3자 이하 영문 키는 넣지 않는다. `rejected` 시트는 머리글만 둔다. `rejected`의 내용은 붙여넣기 행의 첫 두 열을 `|`로 이은 문자열이다(예: `물리 현상|erosion`).

## 부록. 더미 정답표 대상과 형식

- 원천: `dummy pptx files/`(저장소 상대 경로). 폴더 안 어느 파일이든 쓸 수 있고, ingest 바이트 경로(`read_input`)로만 읽는다. 폴더의 `rename_mapping.csv`는 샘플이 아니며, 테스트는 폴더의 `*.pptx`만 읽는다.
- 파일 10개 고정, 39 chunk. 키는 sha256 파일 ID다(`PRD.md` FR-0). 파일명은 표시용이다. 같은 주제의 쌍 중 하나만 골랐고 준중복은 뺐다.

| 구분 | 현재 파일명 | 장 | sha256 앞 12자 | 짝(제외) |
|---|---|---|---|---|
| 샘플 1·필수 | `260807_M2 RSBM ALD BM vs PVD BM 평가.pptx` | 9 | `1b275ae9efc9` | - |
| 샘플 2·필수 | `260112_M2 하드마스크 침식 Metal Short 원인.pptx` | 4 | `f073be9c9ade` | `260317_M2 MHM 마모 Metal Short 경로.pptx` |
| 필수 | `260415_unCMP 잔류물 누설 슬러리 불균형.pptx` | 3 | `237519b54ccc` | `260319_unCMP 잔류물 측면 누설 EBAC 평가.pptx` |
| 필수 | `260828_DD 결함 평가 통합 일정 보드.pptx` | 2 | `55d07aa5c796` | `260521_DD 불량 평가 칸반 일정 보드.pptx` |
| 커버리지 | `260819_overCMP Dishing Erosion EM 파급.pptx` | 5 | `48bd6820df19` | `260806_overCMP Dishing Erosion EM 리스크.pptx` |
| 커버리지 | `260703_V1 비아 챔퍼 붕괴 Cu Void.pptx` | 3 | `a6f913246622` | `260602_V1 숄더 손실 핀치오프 Void 배리어 단절.pptx` |
| 커버리지 | `260521_ULK TDDB 변동성 LER 스펙 16nm HP.pptx` | 4 | `d3b61c7262df` | - |
| 커버리지 | `260630_Rs 증가 Black 방정식 EM overCMP.pptx` | 3 | `5f485c8cf38f` | `260907_선저항 EM Black 방정식 overCMP.pptx` |
| 커버리지 | `260914_M1 스캐터로메트리 14nm HP 계측 ML.pptx` | 3 | `7a42eba3ac6d` | - |
| 커버리지 | `260127_열 모델링 DFT BTE FEM 결합 프레임워크.pptx` | 3 | `f5e20defcbe1` | - |
| 준중복(제외) | `260601_M2 RSBM 배경 목적 Cu 스케일링 한계.pptx` | 9 | `c3860dd2e378` | 샘플 1과 슬라이드 XML 9개 동일 |

전체 sha256(`tests/gold/dummy_hashes.jsonl` 스냅샷의 기대값):

- `260807_M2 RSBM ALD BM vs PVD BM 평가.pptx`: `1b275ae9efc944b3fff9b10151a857775c70d3c595b072c2cdc1528b1e9e7450`
- `260112_M2 하드마스크 침식 Metal Short 원인.pptx`: `f073be9c9ade8071bdac4bb8bf2a1e525e0ebf7f5a40bc82a69cc27d019a90c2`
- `260415_unCMP 잔류물 누설 슬러리 불균형.pptx`: `237519b54cccd84a1dcee6d14a2fc5b59aca0f4a65b689099586f255e23aee46`
- `260828_DD 결함 평가 통합 일정 보드.pptx`: `55d07aa5c7964a3053a29cb1e2898321a1bd670d00025f930c769ff846451206`
- `260819_overCMP Dishing Erosion EM 파급.pptx`: `48bd6820df19bfdb14fdc89e8f3d6625f2063bf553787173111a117a89f77ef8`
- `260703_V1 비아 챔퍼 붕괴 Cu Void.pptx`: `a6f913246622b01f8885eb4a68d3e1048639fdba27377150591ce80429bbce29`
- `260521_ULK TDDB 변동성 LER 스펙 16nm HP.pptx`: `d3b61c7262df45bfd865df76390abca1b38e37cac2d1fdad136d6d8b9b54a02e`
- `260630_Rs 증가 Black 방정식 EM overCMP.pptx`: `5f485c8cf38f36b7a653b8b88f71f0acfec822da9fefae173dadae6786b092a7`
- `260914_M1 스캐터로메트리 14nm HP 계측 ML.pptx`: `7a42eba3ac6da0d906ae160fad3fea488f5016a190dd4f5255540c478bf4003f`
- `260127_열 모델링 DFT BTE FEM 결합 프레임워크.pptx`: `f5e20defcbe1f2dc447285c7756484ea7fc523cb0f2dca818d0090c75d37c1cf`
- `260601_M2 RSBM 배경 목적 Cu 스케일링 한계.pptx`: `c3860dd2e378530c1ccaa7471e82ac904e5ca4b644924578aa73f63e5e74cacf`

- 폴더 재확인 단계: 정답표 초안과 M1 테스트 전에 BytesIO 스크립트로 폴더의 `*.pptx` sha256 목록을 `tests/gold/dummy_hashes.jsonl`(`{"file_id","name"}`)로 만든다. 위 해시 11개(정답 10 + 준중복 1)가 모두 있는지 확인한다. 2026-10-04에 `dummy pptx files/`에서 11개 모두 있음을 확인했다.
- 층: 필수층은 파일 4개 18 chunk에 합성 6개를 더한 것이고, 커버리지층은 파일 6개 21 chunk다(표의 구분 열).
- 합성 픽스처 `tests/fixtures/synthetic_chunks.jsonl`(키는 `fixture_id`): SYN-01 "단락" 치환, SYN-02 상위값만(Reliability), SYN-03 결과 엇갈림, SYN-04 채택+기각 혼재, SYN-05 `Via12`/`Metal12` 숫자 경계, SYN-06 평가 없는 배경 문단. 커버리지가 안 되는 값은 SYN-07 이후로 추가하고, 파일 목록은 바꾸지 않는다.
- 형식 `tests/gold/gold_labels.jsonl`, chunk당 한 줄, `ensure_ascii=False`:
  `{"file_id":"<sha256>", "file_name":"표시용", "slide_no":n, "tier":"required|coverage", "chunk_type":..., "labels":{"구조/레이어":[...], ... 10축}, "Q-COM-001":"O|X|N/A", "note":..., "confirmed":false}`
  - 축 값은 배열이고, 원소는 값·`해당 없음`·`unknown` 중 하나다. 제품·세대는 비활성 축이므로 모두 `["해당 없음"]`이다. 평가 내용이 없는 chunk의 의사결정 상태는 `["해당 없음"]`이다. 정의를 비운 값에 기대야 하는 칸(Mx·Vx의 범위 판단, EUV-SAUP·EUV-SET·ArF-SET의 구분, anneal·hardmask·erosion의 귀속)은 `["unknown"]`으로 두고 `note`에 사유를 적는다.
  - `tools/gold_view.py`가 사람 검토용 `tests/gold/gold_labels.md`를 만든다.
- 절차: (1) 결정 반영 완료 → (2) 실행자가 BytesIO 스크립트로 읽어 모든 칸을 채운 초안을 쓴다 → (3) 사용자가 초안을 보기 전에 필수층 3 chunk를 따로 라벨링하고, 초안과의 일치율을 앵커링 측정으로 리포트에 낸다 → (4) 사용자가 `.md` 보기에서 틀린 칸만 알려 주면 실행자가 jsonl에 반영하고 `confirmed=true`로 바꾼다 → (5) 커버리지층은 나중에 확정한다.
- 통과 기준: 필수층과 합성 픽스처가 모두 `confirmed=true`여야 M6 정답표 테스트가 통과한다. 하나라도 빠지면 실패다. 커버리지층은 리포트에 확정률만 낸다.
- 연결: mock은 정답표에서 mock 응답을 만들어 저장 결과와 3상태 집계, H5 분모를 확인한다(배관 검증). 실제 LLM이 있으면 `tools/evalgold.py`가 축별 완전 일치율, Jaccard, 혼동 행렬을 `.md`로 낸다. 합격선은 정하지 않는다.

## 변경 이력

- 2026-10-04 라벨링 품질 보강(v2) 반영: `.omc/plans/labeling-quality-review-v2.md`의 4절(마일스톤별 반영 제안), 6절(확정 결정), 8절(리스크)과 G21 Supabase 벡터 적재 명세를 반영했다. 반영한 gap ID는 G1, G2, G3, G4(chunk `dup_group`, 파일 `near_dup_group`), G5, G6, G7, G8, G9(G1 안의 N/A 편중 표시), G11, G12, G13, G14, G15, G16, G17, G18, G19, G20, G21이다. 바뀐 곳은 1절(외부 전송 제약), 2절(디렉터리 구조: `metrics.py`, `gate.py`, `embed.py`, `vectorpush.py`, `docs/supabase_schema.md`, `prompts/*.md`, 작업 폴더의 `pipeline.json` 세 블록·`review_gold/`·`gate_<timestamp>.json`), 3절 M0(G18, G19), M1(G16, G4, G15), M2(3상태 기준 수정, G6, G8, G16), M3(G5, G11), M4(재실행 기준 수정, G6, G7, G14), M5(시드·실행 ID 거부·리포트 기준 수정, G3, G2, G13, G16, G1, G8 재판정 형식), M6(재실행 기준 수정, G16, G17, G12, 리포트 요약), 신설 M6b(G20, G21), M7(게이트 G-1~G-10을 끼워 10단계로 다시 매김, 사내 설정 세 블록, 벡터 DB 사용 가능 여부 확인, 완료 기준 추가), 4절 HITL 표(H6 보강, 게이트·벡터 적재 행), 5절 리스크, 6절 검증 단계, 7절(v2 7절 미결 항목과 G21 결정 항목을 기본안과 함께 추가, 준중복 미결 항목 닫음, v2 6절 확정 결정 15개 추가)이다. taxonomy 재설계로 정해진 내용(분류 축 8 + 상태 축 2, `taxonomy.xlsx` 읽기 전용, 화면 2개, 더미 정답표 10개 파일 39 chunk, `tools/evalgold.py`)은 바꾸지 않았다.
- 2026-10-04 구현 착수 리뷰 반영: 2절에 "명령", "ID와 해시 정의", "작업 DB(work.sqlite) 표"를 추가했다(실행 ID 발급은 `run`·`ingest`, `schema_version`과 추가 전용 마이그레이션, `taxonomy_path`). M2에 `taxonomy.parse_bytes` 진입점과 `defaults/taxonomy.xlsx` 의존 테스트 분리를 적었다. M6b의 `run`·`embed` 관계와 `result_code` 성공 기준 멱등을 고쳤다. 역방향 의존 기준을 옮겼다: M0의 더미 해시 밖 chunk 차단 → M2(M0에는 공용 함수 단위 테스트), M0의 빈 작업 폴더 `run` → M6, M1의 위치 이동 시 분류·라벨링 호출 0회 → M4, M5의 리포트 지표·실패 건수·`report --run`·`evalgold.py`=`report.py` → M6. M1의 "리포트에 적힌다"는 `files` 표로 바꿨다.
- 2026-10-04 4차 단계 단순화: 사용자 결정에 따라 4차를 검수 봇에서 "4차 불량 목록 추출"(`PRD.md` FR-5)로 바꿨다. LLM 호출 없이 사유 코드 6개(`UNKNOWN_HIGH`, `LOW_CONFIDENCE`, `QUOTE_NOT_FOUND`, `PARSE_WARNING`, `CLASSIFY_FAILED`, `LABEL_FAILED`)로 판정하고, 걸린 chunk를 상한 없이 `flagged_chunks`, `reports/flagged_<실행ID>.jsonl`·`.md`, 검수 화면에 낸다. 뺀 것은 LLM 독립 재판정(`prompts/rejudge.md`, G8 재판정 형식), 표본 추출 전부(G3), `review_snapshot`·`review_actions` 표와 검수 행동 기록(G13), blind 문장, `review_gold/`와 `report --compare-review-gold`, 회차 간 답 재사용(G2 일부), 사내 리포트의 정확도 지표(G1 사내 부분), M7의 합격선 결정과 review_gold 보관이다. 사외 더미 정답표 대조(`tools/evalgold.py`, `labelbot/metrics.py`)는 남기고 `metrics.py`는 M6에서 만든다. 바뀐 곳은 1절, 2절(디렉터리 구조, `pipeline.json`의 `flag` 블록, 명령 표, ID와 해시 정의, 작업 DB 표), 3절 머리말, M4(G7 문구), M5(전면 재작성), M6(리포트 분포 항목, G1 블록), M7(10단계, G-6·G-8 문구, 완료 기준), 4절 H6, 5절 리스크, 6절 검증 단계, 7절(임베딩 용도, 대체된 결정 표시, 새 확정 결정)이다. 백업은 `.omc/backups/plan.pre-flag-step.md`다.
