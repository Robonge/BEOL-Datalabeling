---
name: BEOL-labeling-RAG-html
description: BEOL 슬라이드 RAG 대화 화면(rag/beol_rag.html)을 로컬 서버로 띄우고, 답변을 만드는 Supabase Edge Function beol-rag-ask(rag/functions/beol-rag-ask/)를 배포한다. 화면 모양만 고쳤으면 화면 실행만, 답변 시스템 프롬프트(lib.ts의 answerSystemPrompt)·검색 로직을 고쳤으면 배포까지 한다. 배포는 서버를 바꾸는 일이라 사용자에게 확인받고 한다. 사용자가 "RAG 화면 띄워줘", "beol_rag 실행", "RAG html 켜줘", "RAG 배포", "edge function 배포", "beol-rag-ask 배포", "시스템 프롬프트 바꿨어 반영해줘"라고 하거나 /BEOL-labeling-RAG-html을 부르면 이 스킬을 쓴다.
---

# BEOL-labeling-RAG-html

> 그룹: ③ 화면 · 발표 · 운영 리포트 · 상위: 없음 · 하위: 없음 · 전체 지도: README.md "스킬 지도"

RAG 대화 화면과 그 뒤에서 답을 만드는 서버 함수를 한 번에 다룬다.

| 구성 | 위치 | 역할 |
|---|---|---|
| 화면 | `rag/beol_rag.html` | 질문 입력·답 표시. 로컬에서 정적 서버로 연다 |
| 서버 함수 | `rag/functions/beol-rag-ask/` (`index.ts`, `lib.ts`) | 질문 → 검색 → LLM 답변. Supabase Edge Function `beol-rag-ask` |
| 시스템 프롬프트 | `lib.ts`의 `answerSystemPrompt`(후속 질문 고쳐 쓰기는 `REWRITE_SYSTEM_PROMPT`) | 답변 말투·형식·근거 번호 규칙 |

화면은 `SUPABASE_URL/functions/v1/beol-rag-ask`로 `messages`·`filters`·`k`를 보낸다. 시스템 프롬프트는 화면에 없고 서버 함수에만 있으므로, 프롬프트·검색 로직을 고치면 배포해야 반영된다. 화면(HTML·CSS) 수정은 배포 없이 새로고침이면 된다.

## 규칙

- 키는 출력하지 않는다. `beol_rag.html`의 `ANON_KEY`, 함수 환경변수(`OPENAI_API_KEY` 등)를 답변·로그에 적지 않는다. 함수 환경변수(secret)는 이 스킬이 건드리지 않는다.
- 배포는 외부 서버를 바꾸는 일이다. 바뀐 파일과 대상(프로젝트 ref, 함수 이름)을 보여 주고 사용자의 명확한 승인을 받은 뒤에만 한다. 이전 대화의 승인은 이번 배포에 적용되지 않는다.
- 배포 대상은 `rag/functions/beol-rag-ask/`의 파일뿐이다. 다른 함수·DB·secret은 건드리지 않는다.
- 본문·답변 내용은 로그에 남기지 않는다. 건수·버전·사유 코드만 전한다.

## 절차

### 1. 무엇을 바꿨는지 가른다

`git status --short rag/`와 `git diff --stat rag/`로 확인한다.

- `rag/beol_rag.html`만 바뀜 → 2번(화면 실행)만 한다. 배포는 필요 없다고 알린다.
- `rag/functions/beol-rag-ask/` 파일이 바뀜 → 3번(배포)까지 한다.
- 사용자가 "화면만" 또는 "배포만"이라고 하면 그 단계만 한다.

### 2. 화면 실행

`.claude/launch.json`의 `rag-ui`(Python `http.server`, 127.0.0.1:8795, 폴더 `rag/`)를 `preview_start {name: "rag-ui"}`로 띄운다. 이미 떠 있으면(`preview_list`) 재사용한다. 주소는 `http://127.0.0.1:8795/beol_rag.html`이다.

- 8795가 이미 다른 서버(예: taxonomy 보드 서버)로 쓰이고 있으면 충돌을 알리고, 다른 포트로 `python -m http.server <포트> --bind 127.0.0.1 --directory rag`를 띄운다.
- 파일을 `file://`로 직접 열어도 보이지만 함수 호출은 CORS·origin 때문에 서버로 여는 쪽이 안전하다.

### 3. Edge Function 배포

1. 변경 확인: 바뀐 파일 목록과 `lib.ts` diff 요약(어느 줄이 바뀌었는지)을 사용자에게 보여 준다.
2. 현재 배포본 확인: Supabase MCP `get_edge_function`(프로젝트 ref는 `beol_rag.html`의 `SUPABASE_URL` 호스트 앞부분)으로 현재 `verify_jwt` 값과 버전을 읽는다. 배포 때 `verify_jwt`는 현재 값을 그대로 유지한다.
3. 승인 질문: "프로젝트 `<ref>`의 `beol-rag-ask`를 `index.ts`·`lib.ts`로 교체 배포할까요?" 하고 yes를 기다린다.
4. 승인 뒤 Supabase MCP `deploy_edge_function`으로 배포한다. `name`은 `beol-rag-ask`, `entrypoint_path`는 `index.ts`, `files`는 `index.ts`와 `lib.ts` 둘 다(두 파일은 `./lib.ts`로 이어진다).
5. 검증: `get_edge_function`을 다시 읽어 버전이 올라갔는지, 본문에 바뀐 줄이 들어 있는지 확인하고 상태(`ACTIVE`)를 확인한다. 가능하면 `get_logs`/`query_logs`로 배포 직후 오류가 없는지 본다.
6. Supabase MCP를 못 쓰는 환경이면 배포하지 말고 사유(인증 필요 등)와 사용자가 직접 할 명령을 알린다. Supabase CLI는 `supabase/functions/<이름>/` 구조를 요구하므로 `rag/functions/`를 그대로 가리키지 못한다. 임시 복사나 폴더 이동은 사용자 승인 없이 하지 않는다.

### 4. 마무리 보고

한 줄씩만 전한다.

- 화면: 주소와 서버 상태
- 배포: 대상, 새 버전, 상태(`ACTIVE`) 또는 "배포 안 함(사유)"
- 화면에서 같은 질문을 한 번 던져 새 프롬프트가 반영됐는지 확인해 보라고 안내한다(답 내용은 로그·보고에 옮기지 않는다).

## 하지 않는 일

- 답변 내용(시스템 프롬프트 문구) 수정은 이 스킬이 하지 않는다. 사용자가 문구를 정해 주면 `lib.ts`를 고친 뒤 이 스킬로 배포한다.
- 슬라이드 적재·임베딩은 `BEOL-labeling-feedback`이 맡는다.

## 관계

- 라벨링 실행은 BEOL-labeling, 라벨링 결과 적재는 BEOL-labeling-feedback이 맡는다.
