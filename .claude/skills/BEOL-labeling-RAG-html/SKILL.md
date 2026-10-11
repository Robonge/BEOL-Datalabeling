---
name: BEOL-labeling-RAG-html
description: BEOL 슬라이드 RAG 대화 화면(rag/beol_rag.html)을 로컬 RAG 서버(python -m labelbot.ragsrv)로 띄운다. 화면과 답변 API가 같은 서버(127.0.0.1:8795)에서 나온다. 답변 시스템 프롬프트(labelbot/raglib.py)나 검색 로직(labelbot/ragsearch.py)을 고쳤으면 서버를 다시 띄워 반영한다. 로컬 저장소(rag_config.json)가 없으면 push-vectors부터 하라고 안내한다. 사용자가 "RAG 화면 띄워줘", "beol_rag 실행", "RAG html 켜줘", "RAG 서버 재시작", "시스템 프롬프트 바꿨어 반영해줘"라고 하거나 /BEOL-labeling-RAG-html을 부르면 이 스킬을 쓴다.
---

# BEOL-labeling-RAG-html

> 그룹: ③ 화면 · 발표 · 운영 리포트 · 상위: 없음 · 하위: 없음 · 전체 지도: README.md "스킬 지도"

RAG 대화 화면과 그 뒤에서 답을 만드는 로컬 서버를 한 번에 다룬다.

| 구성 | 위치 | 역할 |
|---|---|---|
| 화면 | `rag/beol_rag.html` | 질문 입력·답 표시. 로컬 RAG 서버가 정적 파일로 내준다 |
| 로컬 서버 | `labelbot/ragsrv.py` | 화면 제공과 답변 API. 질문 → 검색 → LLM 답변 |
| 답변 프롬프트 | `labelbot/raglib.py` | 답변 말투·형식·근거 번호 규칙, 후속 질문 고쳐 쓰기 |
| 검색 | `labelbot/ragsearch.py` | 로컬 저장소(`rag_store.sqlite`)에서 벡터 검색. 검색 규격은 이 파일 docstring에 있다 |
| 로컬 저장소 | `workspaces/_rag_store` (환경변수 `BEOL_RAG_STORE`로 바꿈) | `rag_store.sqlite`, `slides/<sha>.b64`, `rag_config.json` |

화면은 같은 서버의 답변 API로 `messages`·`filters`·`k`를 보낸다. 시스템 프롬프트는 화면에 없고 `labelbot/raglib.py`에만 있으므로, 프롬프트·검색 로직을 고치면 서버를 다시 띄워야 반영된다. 배포 절차는 없다. 화면(HTML·CSS) 수정은 새로고침이면 된다.

## 규칙

- 키는 출력하지 않는다. `OPENAI_API_KEY` 값을 답변·로그에 적지 않는다. 환경변수나 `.env`는 이 스킬이 건드리지 않는다.
- 서버는 `127.0.0.1`에만 묶는다. `--bind`에 외부 주소를 쓰지 않는다.
- 본문·답변 내용은 로그에 남기지 않는다. 건수·버전·사유 코드만 전한다.

## 절차

### 1. 무엇을 바꿨는지 가른다

`git status --short rag/ labelbot/`와 `git diff --stat rag/ labelbot/`로 확인한다.

- `rag/beol_rag.html`만 바뀜 → 서버가 떠 있으면 새로고침만 안내한다.
- `labelbot/raglib.py`·`labelbot/ragsearch.py`·`labelbot/ragsrv.py`가 바뀜 → 2번에서 서버를 다시 띄운다.
- 로컬 저장소에 `rag_config.json`이 없으면 적재가 한 번도 안 된 것이다. `/BEOL-labeling-feedback`의 `push-vectors`부터 하라고 안내하고 멈춘다.

### 2. 서버 실행

```bash
python -m labelbot.ragsrv --port 8795 --bind 127.0.0.1 --directory rag
```

`.claude/launch.json`의 `rag-ui`로 `preview_start {name: "rag-ui"}`를 써도 된다. 이미 떠 있으면(`preview_list`) 코드를 고쳤을 때만 멈추고 다시 띄운다. 주소는 `http://127.0.0.1:8795/beol_rag.html`이다.

- 8795가 이미 다른 서버(예: taxonomy 보드 서버)로 쓰이고 있으면 충돌을 알리고, 다른 포트로 같은 명령을 띄운다.
- 파일을 `file://`로 직접 열면 답변 API를 부를 수 없으므로 서버 주소로 연다.

### 3. 마무리 보고

한 줄씩만 전한다.

- 화면: 주소와 서버 상태
- 서버: 재시작 여부, 로컬 저장소 경로
- 화면에서 같은 질문을 한 번 던져 새 프롬프트가 반영됐는지 확인해 보라고 안내한다(답 내용은 로그·보고에 옮기지 않는다).

## 하지 않는 일

- 답변 내용(시스템 프롬프트 문구) 수정은 이 스킬이 하지 않는다. 사용자가 문구를 정해 주면 `labelbot/raglib.py`를 고친 뒤 이 스킬로 서버를 다시 띄운다.
- 슬라이드 적재·임베딩은 `BEOL-labeling-feedback`이 맡는다.

## 관계

- 라벨링 실행은 BEOL-labeling, 라벨링 결과 적재는 BEOL-labeling-feedback이 맡는다.
