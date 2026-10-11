# local-transformation.md — Supabase 제거 · 사내 LLM 전환 가이드 (에이전트용)

> **이 문서를 읽는 에이전트(사내 Roo Code 또는 Claude Code)에게**
> 이 저장소는 지금 Supabase(벡터 DB·Storage·Edge Function)와 OpenAI(채팅·임베딩)를 쓴다. 이 문서대로 고쳐서
> **① Supabase를 완전히 지우고 모든 출력·벡터 DB·RAG 데이터를 로컬 폴더에 저장·조회**하고,
> **② 모든 LLM·임베딩 호출을 사용자가 §1에 붙인 사내 LLM 호출 코드로 바꾼다.**
> 순서는 §6을 따른다. 단계마다 확인 명령을 돌리고, 실패하면 다음 단계로 가지 않는다. 고친 내용은 §13 "적용 기록"에 한 줄씩 남긴다.

- 기준: 브랜치 `LLM-added`, 커밋 `dd1126f` + 2026-10-11 작업 트리. 줄 번호는 이 기준이며 **어긋나면 `앵커:` 문자열로 찾는다.**
- 앵커 형식은 `앵커: \`경로\` :: \`문자열\``이다. 문자열은 그 파일에 **정확히 한 번** 나온다. §6-1 스크립트가 이것을 검사한다.
- 사내 전환은 이 문서 하나만 기준으로 한다.
- **§1이 비어 있으면 아무것도 고치지 말고 사용자에게 사내 LLM 호출 코드를 붙여 달라고 한다.**

---

## 0. 반드시 지킬 규칙

1. **루트 `CLAUDE.md`가 이 문서보다 우선한다.** DRM 규칙(사내 파일은 `open(path,"rb")` → base64 → `.b64`, 원본 경로를 여는 곳은 ingest 하나)과 쓰기 규칙(`.b64 .sqlite .json .jsonl .html .md .log`만 쓴다)은 바꾸지 않는다. 로컬 저장소도 이 형식만 쓴다. JPG는 `.b64`로만 저장하고 `.jpg` 파일을 디스크에 쓰지 않는다.
2. **본체는 표준 라이브러리만 쓴다(Python 3.14).** 사내 코드가 SDK(`requests`, `openai`, 사내 패키지)를 쓰면 §3-3 경우 C를 따른다. 사용자 승인 없이 패키지를 설치하거나 import하지 않는다.
3. **사내 LLM 코드는 `labelbot/inhouse_llm.py` 한 파일에만 둔다.** 나머지 코드는 이 파일의 계약 함수(§3)만 부른다. 네트워크 저수준 호출(`urllib`, `http.client`, `socket`)은 `labelbot/llm.py`와 `labelbot/inhouse_llm.py`에서만 쓴다(예외: 테스트가 가짜 서버를 부르는 코드).
4. **키·사내 주소 값은 이 문서 §1-5와 `.env`에만 둔다.** 코드, `pipeline.json` 템플릿, 그 밖의 문서, 산출물(`work.sqlite`의 `sent_params`, export 메타)에는 쓰지 않는다. 코드는 환경변수로 읽고, 설정에는 **환경변수 이름만** 적는다. 키 값을 화면 출력·로그·§13 기록에 옮기지 않는다. 로그·출력에는 파일 ID·건수·사유 코드만 남긴다. 질문·답변·본문은 로그에 쓰지 않는다.
5. **사내에서 고친 결과는 공개 원격(GitHub)에 push하지 않는다.**
6. TLS 검증을 끄지 않는다. 사내 코드에 `verify=False`가 있어도 따라 하지 않고 사내 루트 인증서 경로를 쓴다.
7. 기존 Supabase·OpenAI 코드는 **설정으로 끄는 것이 아니라 지운다.** 남겨도 되는 것은 §11-2 목록뿐이다.
8. 검수는 맨 끝에 한 번만 한다: `python -m code_engrbot review --root . --paths <바꾼 파일>`. critical만 고치고 major·minor는 한 줄로 보고한다(루트 `CLAUDE.md` 임시 지침).
9. 테스트는 `python -m pytest -p no:cacheprovider -q -rf`로 돌린다. 전환 전부터 실패하던 테스트는 §12에 있다. 그 밖의 실패가 생기면 전환이 깨뜨린 것이다.
10. 사내 PC에 `python` 명령이 없고 `py`만 있으면 이 문서의 `python`을 모두 `py -3.14`로 바꿔 실행한다. `git`이 없으면 0단계에서 저장소 폴더 전체를 다른 이름으로 복사해 두는 것으로 브랜치를 대신한다(§9).

---

## 1. [사용자 입력] 사내 LLM 호출 코드

사용자가 아래 칸을 채운다. 사내에서만 쓰는 문서이므로 키·주소를 실제 값 그대로 적어도 된다(§1-5). 에이전트는 §1-5의 값을 `.env`에 옮겨 쓰고, 코드는 지금처럼 환경변수로 읽는다(§6 1단계).

<!-- USER_INPUT:INHOUSE_LLM BEGIN -->
### 1-1. 채팅(대화) 호출 코드

```text
(여기에 사내 LLM 채팅 호출 예시 코드를 붙여 넣는다. 요청을 만드는 부분과 응답에서 답 문장을 꺼내는 부분이 모두 보여야 한다)
```

### 1-2. 임베딩 호출 코드

```text
(여기에 사내 임베딩 호출 예시 코드를 붙여 넣는다. 여러 문장을 한 번에 보낼 수 있는지가 보이면 좋다)
```

### 1-3. 응답 예시 (값은 가린다)

```text
(채팅 정상 응답 JSON 1개, 임베딩 정상 응답 JSON 1개(벡터는 앞 3개 숫자만 남기고 "..."), 오류 응답 1개를 붙인다)
```

### 1-4. 값 표 (모르면 비워 둔다)

| 항목 | 값 |
|---|---|
| 채팅 모델 이름 | |
| 임베딩 모델 이름 | |
| 임베딩 차원(숫자) | |
| 임베딩이 채팅과 같은 주소·키를 쓰는지 | |
| 임베딩 한 번에 보낼 수 있는 문장 수 | |
| 임베딩 최대 입력 길이(토큰 또는 글자) | |
| 채팅 최대 출력 토큰 매개변수 이름(예: max_tokens) | |
| 채팅 최대 출력 토큰 상한(숫자) | |
| `system` 역할 메시지 지원 여부 | |
| 스트리밍(SSE)으로만 응답하는지 | |
| temperature 지원 여부 | |
| JSON 응답 모드 지원 여부 | |
| 응답이 잘렸는지 알려 주는 값(finish_reason 등) 제공 여부 | |
| 인증 방식(헤더 키 / 토큰 발급 / 사내 SSO 등) | |
| 키·주소를 넣을 환경변수 이름 | |
| 사내 루트 인증서(.pem) 경로 | |
| 프록시 필요 여부 | |
| 동시 호출 제한(초당·동시 개수) | |
| SDK 사용 여부와 패키지 이름 | |
### 1-5. 키·주소 값 (실제 값)

에이전트는 이 표의 값을 저장소 루트 `.env`에 `이름=값` 줄로 옮긴다(환경변수 이름은 1-4 표의 이름, 비었으면 아래 기본 이름). 임베딩이 채팅과 같은 주소·키를 쓰면 임베딩 칸은 비워 둔다.

| 항목 | 환경변수 이름(기본) | 값 |
|---|---|---|
| 채팅 LLM API 주소(base URL) | `INHOUSE_LLM_BASE_URL` | |
| 채팅 LLM API 키 | `INHOUSE_LLM_API_KEY` | |
| 임베딩 API 주소(다를 때만) | `INHOUSE_EMBED_BASE_URL` | |
| 임베딩 API 키(다를 때만) | `INHOUSE_EMBED_API_KEY` | |
| 그 밖에 인증에 필요한 값(토큰 발급 ID·시크릿, 테넌트 헤더 등) | (사내 코드에 맞춰 정한다) | |
<!-- USER_INPUT:INHOUSE_LLM END -->

---

## 2. 바뀌는 구조 한눈에 보기

```text
[지금]
  labelbot 1·2·3차 LLM, 검증 질문 ─┐
  domain_engrbot judge·질문 생성  ─┼─ labelbot/llm.py (OpenAI /chat/completions, /embeddings)
  labelbot embed                  ─┘
  push-vectors ─→ Supabase 표 beol_chunk_embeddings (pgvector)
  push-slides  ─→ Supabase Storage 버킷 + 행 PATCH
  rag/beol_rag.html ─→ Supabase REST(facets·count·feedback·Storage) + Edge Function beol-rag-ask(Deno, OpenAI)

[바뀐 뒤]
  모든 LLM·임베딩 ─→ labelbot/llm.py(캐시·재시도) ─→ labelbot/inhouse_llm.py(사내 코드, §1)
  push-vectors ─→ 로컬 저장소 <store>/rag_store.sqlite 표 beol_chunk_embeddings (+ rag_config.json)
  push-slides  ─→ <store>/slides/<sha256>.b64 + 같은 표의 slide_image_* 열
  rag/beol_rag.html ─→ 같은 출처의 로컬 서버 python -m labelbot.ragsrv (labelbot/raglib.py, labelbot/ragsearch.py)
  <store> 기본값 = <저장소>/workspaces/_rag_store  (git 무시 경로, 환경변수 BEOL_RAG_STORE로 바꿀 수 있다)
```

### 2-1. 이미 정해진 결정 (바꾸지 않는다)

| ID | 결정 | 이유 |
|---|---|---|
| D1 | 사내 LLM 코드는 `labelbot/inhouse_llm.py` 하나에 두고 `chat`·`embed`·`endpoint_id`·`check_config` 네 함수만 밖에 드러낸다(§3) | 사내 코드 형태가 바뀌어도 이 파일만 고친다 |
| D2 | `labelbot/llm.py`의 `ChatClient`(캐시·재시도·검증)와 mock 전송은 그대로 두고 전송 계층만 바꾼다 | 1·2·3차 라벨링과 테스트 20여 곳이 이 계약에 기댄다 |
| D3 | CLI 명령 이름 `push-vectors`·`push-slides`는 유지하고 대상만 로컬 저장소로 바꾼다 | skill·테스트·멱등 기록(`vector_push_log`, `slide_image_push_log`)을 그대로 쓴다 |
| D4 | 설정 블록 `supabase`는 지우고 `vector_store`를 새로 둔다 | §4-B1 |
| D5 | 로컬 저장소는 작업 폴더와 따로 둔 SQLite 한 개(`rag_store.sqlite`) + 슬라이드 `.b64` 폴더다. 행 키는 `(chunk_id, model)`이고 나중에 적재한 것이 이긴다 | Supabase upsert와 같은 의미. RAG 서버는 작업 폴더를 몰라도 된다 |
| D6 | RAG 답변 서버는 표준 라이브러리 `http.server`로 `labelbot/ragsrv.py`에 둔다. 화면과 API를 **같은 출처**에서 내므로 CORS·키가 필요 없다 | `rag/**`는 Code-Engr-bot 검수 제외 경로라 Python 코드는 `labelbot/`에 둔다 |
| D7 | Edge Function의 순수 함수(`lib.ts`)는 `labelbot/raglib.py`로 1:1 옮기고, SQL 검색 함수 `beol_rag_search`는 `labelbot/ragsearch.py`로 옮긴다(벡터 코사인 + 단어 검색 + RRF) | 응답 JSON 계약이 같으면 화면 렌더 코드를 고치지 않아도 된다 |
| D8 | 단어 검색은 Postgres `simple` 설정을 순수 Python으로 근사한다. 순위가 조금 달라질 수 있음을 받아들인다 | FTS5 같은 빌드 옵션에 기대지 않는다 |
| D9 | domain_engrbot judge의 tool calling 모드는 지우고 JSON 모드만 둔다. judge `transport` 값 `"http"`는 `"inhouse"`의 옛 이름으로 계속 받는다 | tool 모드는 OpenAI `tools` 형식 전용이다. `"http"`를 남기면 domain_engrbot CLI·테스트·스냅샷을 거의 안 바꾼다 |
| D10 | 임베딩 모델이 바뀌므로 모든 작업 폴더를 다시 임베딩하고 다시 적재한다(§7) | 차원이 다른 벡터는 섞을 수 없다 |

---

## 3. 사내 LLM 어댑터 계약 — `labelbot/inhouse_llm.py` (새 파일)

### 3-1. 밖에 드러내는 함수 (이름·인자·반환을 바꾸지 않는다)

```python
"""사내 LLM·임베딩 호출의 유일한 자리. 나머지 코드는 이 네 함수만 부른다.

키·주소는 cfg["options"]에 적힌 환경변수 이름으로 읽는다. 키·주소·본문·응답은 출력하지 않는다.
여러 스레드에서 동시에 불린다(llm.workers). 재시도는 하지 않는다(부르는 쪽이 한다).
"""
import collections

from labelbot.llm import CallFailed

ChatResult = collections.namedtuple("ChatResult", "text finish_reason")


def endpoint_id(cfg):
    """캐시 키와 '같은 전송처' 비교에 쓰는 안정된 문자열. 키와 주소 원문은 넣지 않는다.
    = "inhouse:" + sha256(주소 환경변수 값의 호스트 소문자)[:16] + ":" + cfg.get("model", "")
    options가 없거나 환경변수가 비면 예외 없이 "inhouse:" + cfg.get("model", "")을 돌려준다(mock 설정에서도 불린다)."""


def check_config(cfg):
    """selfcheck용. 반환 (ok: bool, detail: str). 모델 이름·필수 환경변수가 있는지만 본다(네트워크 호출 없음).
    detail에는 환경변수 '이름'만 적고 값은 적지 않는다."""


def chat(cfg, messages, max_tokens=None, temperature=None, json_mode=False, timeout=None):
    """messages: [{"role": "system"|"user"|"assistant", "content": str}, ...]
    max_tokens: None이면 보내지 않는다. 사내 매개변수 이름은 이 함수 안에서 정한다. 사내 상한(§1-4)보다 크면 상한으로 줄인다.
    temperature: None이면 보내지 않는다(RAG 답변은 None으로 부른다). 사내가 지원하지 않으면 항상 보내지 않는다.
    json_mode: True면 사내 API가 지원할 때만 JSON 모드를 켠다. 지원하지 않으면 무시한다(부르는 쪽이 extract_json으로 읽는다).
    timeout: 초. None이면 cfg["timeout"] 또는 60.
    반환: ChatResult(text=답 문자열, finish_reason="stop"|"length"|None). 잘렸는지 모르면 None.
    실패: CallFailed(사유 코드) — §3-2 표의 코드만 쓴다."""


def embed(cfg, texts, timeout=None):
    """texts: [str, ...] (1개 이상, cfg["batch_size"] 이하)
    반환: 입력과 같은 순서·같은 개수의 [float, ...] 목록. 모든 벡터의 길이가 같아야 한다.
    한 번에 하나만 받는 API면 이 함수 안에서 반복 호출한다.
    실패: CallFailed(사유 코드)."""
```

- `cfg`는 `pipeline.json`의 `llm` 블록 또는 `embedding` 블록을 기본값과 합친 dict다(§4-A1).
- 사내 전용 값(주소 환경변수 이름, 키 환경변수 이름, 인증서 경로, 추가 헤더 이름 등)은 `cfg["options"]`(dict) 안에만 둔다. 기본값은 A1에 직접 적는다: `{"base_url_env": "<§1-4 이름>", "api_key_env": "<§1-4 이름>", "ca_file": None}`. 임베딩이 다른 주소·키를 쓰면(§1-4) `embedding.options`에 다른 이름을 적는다.
- `labelbot/llm.py`는 이 모듈을 **함수 안에서만** import한다(§4-A2). 이 파일 맨 위의 `from labelbot.llm import CallFailed`는 순환 import가 되지 않는다. 반대로 `labelbot/llm.py` 맨 위에 `from labelbot import inhouse_llm`을 넣으면 순환 import가 되므로 넣지 않는다.
- 사내 API 특성별 처리(모두 이 파일 안에서 한다):
  - `system` 역할을 지원하지 않으면: system 메시지 내용을 첫 user 메시지 앞에 빈 줄로 이어 붙인다.
  - 스트리밍으로만 응답하면: 스트림을 끝까지 읽어 조각을 이어 붙인 문자열을 `text`로, 마지막 조각의 종료 사유를 `finish_reason`으로 돌려준다.
  - 잘림 표시가 없으면 `finish_reason=None`. 그러면 RAG의 `LLM_TRUNCATED`·`TRUNCATED` 판정은 생기지 않는다(정상).

### 3-2. 사유 코드 (CallFailed에 넣는 값)

| 코드 | 언제 |
|---|---|
| `CONFIG_MISSING` | 모델 이름·주소 환경변수 등 설정이 비었다. SDK import 실패도 이것 |
| `KEY_MISSING` | 키 환경변수가 비었다 |
| `HTTP_<숫자>` | HTTP 오류 응답(예: `HTTP_401`, `HTTP_429`, `HTTP_500`) |
| `HTTP_REDIRECT_REFUSED` | 3xx(새 주소로 따라가지 않는다) |
| `TIMEOUT` | 시간 초과 |
| `NETWORK_ERROR` | 연결 실패·끊김·TLS 오류 |
| `RESPONSE_NOT_JSON` | 응답이 JSON이 아니다 |
| `RESPONSE_SHAPE` | 응답 모양이 예상과 다르다(답 문장·벡터를 못 찾음, 개수·차원 불일치) |

SDK 예외는 이 표의 코드로 바꿔서 `CallFailed`로 다시 던진다. 예외 메시지·응답 본문을 그대로 출력하지 않는다.

### 3-3. §1의 코드를 이 파일로 옮기는 방법 (세 경우 중 하나)

먼저 §1을 읽고 아래 표를 채워 사용자에게 보여 준 뒤 시작한다.

| 뽑을 것 | §1에서 찾는 곳 | 옮길 곳 |
|---|---|---|
| 주소 | §1-5, URL 문자열, `base_url=`, 사내 클라이언트 생성자 | `.env`(값) + `options.base_url_env`(이름) |
| 인증 | §1-5, 헤더(`Authorization`, `api-key`, 사내 토큰 헤더), 토큰 발급 함수 | `.env`(값) + `options.api_key_env` 등(이름) |
| 요청 본문 | 모델·메시지·최대 토큰·temperature 필드 이름 | `chat()`·`embed()` 안 |
| 응답에서 답 꺼내기 | `resp[...]` 경로(§1-3 응답 예시로 확인) | `chat()` 안. 잘림 표시가 있으면 `finish_reason`으로 |
| 임베딩 응답 | 벡터 목록 경로, 순서(index) 처리 | `embed()` 안 |
| 인증서·프록시 | `verify=`, `proxies=` | `options.ca_file`, 프록시는 환경변수 `HTTPS_PROXY`(urllib가 읽는다) |

- **경우 A — OpenAI와 같은 주소·본문·응답(경로 `/chat/completions`, `/embeddings`)**: `labelbot.llm.post_json(url, headers, payload, timeout, ca_file)`로 보낸다. 채팅 답은 `resp["choices"][0]["message"]["content"]`, 잘림은 `resp["choices"][0].get("finish_reason")`, 임베딩은 `resp["data"]`를 `index`로 정렬해 `embedding`을 꺼낸다(지금 `labelbot/llm.py`의 `HttpChatTransport`·`HttpEmbedTransport`와 같은 동작).
- **경우 B — 표준 라이브러리로 부를 수 있는 사내 HTTP API(모양만 다름)**: 역시 `labelbot.llm.post_json`으로 보내고, 본문·응답 경로만 §1대로 바꾼다. 토큰 발급이 따로 있으면 `_token(cfg)` 함수를 이 파일에 두고 만료 전까지 메모리에 캐시한다(`threading.Lock` 사용, 토큰 값은 출력하지 않는다).
- **경우 C — 사내 SDK(pip 패키지)를 꼭 써야 함**: **멈추고 사용자에게 묻는다.** "루트 CLAUDE.md는 표준 라이브러리만 허용합니다. 사내 SDK `<패키지>`를 `labelbot/inhouse_llm.py` 한 파일에서만, 함수 안 지연 import로 쓰도록 예외를 둘까요?" 승인을 받으면:
  - import는 `chat()`·`embed()` 함수 안에서 하고 `ImportError`는 `CallFailed("CONFIG_MISSING")`으로 바꾼다.
  - 그 import 줄 끝에 `# code_engrbot: allow C1_NONSTDLIB_IMPORT`를 단다.
  - `code_engrbot/defaults/policy.json`의 `"c2": {"transport_modules": [...]}`에 `"labelbot/inhouse_llm.py"`를 넣는다.
  - 패키지 이름은 `requirements-poc.txt`에만 적는다(`requirements.txt`는 비워 둔다. Code-Engr-bot `C2_REQUIREMENTS_NOT_EMPTY`).
  - SDK 클라이언트가 스레드 안전하지 않으면 `threading.local()`로 스레드마다 만든다.
  - 앵커: `code_engrbot/defaults/policy.json` :: `"transport_modules": ["labelbot/llm.py"]`
- 경우 A·B에서 이 파일이 `urllib`를 직접 쓰지 않으면 `transport_modules`는 바꾸지 않는다.

### 3-4. 어댑터 단위 테스트 — `tests/test_inhouse_llm.py` (새 파일)

- `127.0.0.1`에 띄운 가짜 HTTP 서버(`http.server`, 스레드)가 **§1-3 응답 예시와 같은 모양**을 돌려주게 하고, `chat()`이 `ChatResult`를, `embed()`가 입력 순서대로 같은 차원의 벡터를 돌려주는지 본다.
- 401·500·지연(시간 초과)·잘못된 모양 응답이 각각 `HTTP_401`, `HTTP_500`, `TIMEOUT`, `RESPONSE_SHAPE`가 되는지 본다.
- 키 환경변수가 비면 `KEY_MISSING`, 모델이 비면 `check_config`가 `(False, ...)`, `endpoint_id`가 options 없는 cfg에서도 예외 없이 문자열을 내고 주소 원문을 담지 않는지 본다.
- 테스트용 키는 실행 중에 조립한다(`"test-" + "key"`). 실제 키 모양 문자열 리터럴을 쓰지 않는다(Code-Engr-bot `C2_SECRET_LITERAL`).
- 경우 C(SDK)면 SDK 호출 함수를 `unittest.mock.patch`로 바꿔 같은 항목을 본다.

---

## 4. 적용 지도 — 어느 파일을 어떻게

절 머리의 **[n단계]**는 §6의 몇 단계에서 하는지다. 같은 단계 안의 항목은 모두 끝낸 뒤 그 단계의 확인을 돌린다.

### A. 사내 LLM 전환 [3단계]

**A1. 기본 설정** — `labelbot/workspace.py:14-43`
- 앵커: `labelbot/workspace.py` :: `"chat_path": "/chat/completions",`
- 앵커: `labelbot/workspace.py` :: `"path": "/embeddings",`
- `llm`·`embedding` 블록을 아래로 바꾼다(지우는 키: `base_url`, `chat_path`, `path`, `api_key_env`, `auth_header`, `extra_headers`, `ca_file`, `max_tokens_param`).
  ```python
  "llm": {
      "transport": "inhouse",      # "inhouse" | "mock"(테스트). 그 밖의 값도 inhouse로 본다
      "model": "",                 # 채팅 모델(§1-4). init_workspace.py가 채운다
      "options": {"base_url_env": "<§1-4 이름>", "api_key_env": "<§1-4 이름>", "ca_file": None},
      "timeout": 60,
      "temperature": 0,            # §1-4에서 temperature 미지원이면 None
      "max_tokens": None,
      "response_format_json": False,
      "max_retries": 2,
      "workers": 4,
  },
  "embedding": {
      "enabled": True,
      "transport": "inhouse",
      "model": "<§1-4 임베딩 모델 이름>",
      "options": {"base_url_env": "<§1-4 이름>", "api_key_env": "<§1-4 이름>", "ca_file": None},
      "timeout": 60,
      "batch_size": 64,            # §1-4 '한 번에 보낼 수 있는 문장 수'가 더 작으면 그 값
  },
  ```
- 모델 이름에 차원이 없으면 §13 기록에 차원을 적는다(옛 벡터와 섞일 때 원인 추적용).

**A2. 전송 계층 교체** — `labelbot/llm.py`
- 모듈 설명 1-5줄을 "사내 LLM 어댑터(`labelbot/inhouse_llm.py`) 위의 캐시·재시도 계층과 공용 HTTP 함수"로 바꾼다.
  - 앵커: `labelbot/llm.py` :: `"""OpenAI 호환 호출과 외부 전송 안전장치.`
- **남기는 것**: `CallFailed`, `DUMMY_HASHES_PATH`(테스트 fixture 경로. `tests/test_golden_run.py`·`tests/test_slides.py`가 쓴다), `_NoRedirect`, `build_opener`, `read_key`, `post_json`, `_open`, `auth_headers`, `DuplicateKey`, `extract_json`, `ChatClient`.
- **3단계에서 지우는 것**: `HttpChatTransport`, `HttpEmbedTransport`, `ChatClient.url` 프로퍼티.
  - 앵커: `labelbot/llm.py` :: `class HttpChatTransport:`
  - 앵커: `labelbot/llm.py` :: `class HttpEmbedTransport:`
  - 앵커: `labelbot/llm.py` :: `return self.cfg["base_url"].rstrip("/") + self.cfg["chat_path"]`
  - `ChatClient.url`을 쓰는 곳이 있는지 `grep -rn "\.url\b" labelbot domain_engrbot`로 확인하고, 있으면 `inhouse_llm.endpoint_id(cfg)`로 바꾼다.
- **5단계 끝(B6)에서 지우는 것**: `host_hash`, `post_bytes`, `patch_json`, `get_json`, `class SupabaseSinkBase`. 이것들은 `vectorpush.py`·`slidepush.py`·`selfcheck.py`가 아직 import하므로 3단계에서 지우면 ImportError가 난다.
- **새로 넣는 것**:
  ```python
  class InhouseChatTransport:
      def __init__(self, cfg):
          self.cfg = cfg

      def send(self, body, hint=None):
          from labelbot import inhouse_llm  # 함수 안 import(맨 위에 두면 순환 import)

          r = inhouse_llm.chat(self.cfg, body["messages"], max_tokens=body.get("max_tokens"),
                               temperature=body.get("temperature"), json_mode=bool(body.get("json_mode")),
                               timeout=self.cfg.get("timeout"))
          return r.text


  class InhouseEmbedTransport:
      def __init__(self, cfg):
          self.cfg = cfg

      def embed(self, texts):
          from labelbot import inhouse_llm

          return inhouse_llm.embed(self.cfg, texts, timeout=self.cfg.get("timeout"))
  ```
- `ChatClient.__init__`: `transport = HttpChatTransport(cfg)` → `InhouseChatTransport(cfg)`.
  - 앵커: `labelbot/llm.py` :: `transport = HttpChatTransport(cfg)`
- `build_body`는 사내 형식이 아니라 **중립 dict**를 만든다(캐시 키 재료):
  ```python
  def build_body(self, messages):
      cfg = self.cfg
      body = {"model": cfg["model"], "messages": messages}
      if cfg.get("temperature") is not None:
          body["temperature"] = cfg["temperature"]
      if cfg.get("max_tokens"):
          body["max_tokens"] = cfg["max_tokens"]
      if cfg.get("response_format_json"):
          body["json_mode"] = True
      return body
  ```
  - 앵커: `labelbot/llm.py` :: `body[cfg.get("max_tokens_param") or "max_tokens"] = cfg["max_tokens"]`
- `sent_params`와 `cache_key`(둘 다 함수 안에서 `from labelbot import inhouse_llm`):
  ```python
  def sent_params(self):
      from labelbot import inhouse_llm

      cfg = self.cfg
      return {
          "endpoint": inhouse_llm.endpoint_id(cfg),
          "model": cfg["model"],
          "temperature": cfg["temperature"] if cfg.get("temperature") is not None else "미전송",
          "max_tokens": cfg.get("max_tokens") or "미전송",
          "json_mode": "켬" if cfg.get("response_format_json") else "미전송",
      }

  def cache_key(self, body):
      """사내 전송처 식별자(endpoint_id)와 중립 body의 해시. 헤더와 키는 넣지 않는다."""
      from labelbot import inhouse_llm

      key = {"endpoint": inhouse_llm.endpoint_id(self.cfg), "body": body}
      transport = self.cfg.get("transport") or "inhouse"
      if transport != "inhouse" or not isinstance(self.transport, InhouseChatTransport):
          key["transport"] = transport if transport != "inhouse" else type(self.transport).__name__
      return util.hash_obj(key)
  ```
  - 앵커: `labelbot/llm.py` :: `"chat_path": cfg["chat_path"],`
  - 앵커: `labelbot/llm.py` :: `key = {"base_url": self.cfg["base_url"], "chat_path": self.cfg["chat_path"], "body": body}`
  - 캐시 키가 바뀌므로 옛 `llm_cache`는 적중하지 않는다. 정상이다(사내 모델로 다시 부른다).
- `ChatClient.chat_json`의 재시도·검증·캐시 흐름은 바꾸지 않는다.

**A3. 임베딩** — `labelbot/embed.py`
- 앵커: `labelbot/embed.py` :: `from labelbot.llm import CallFailed, HttpEmbedTransport`
- 앵커: `labelbot/embed.py` :: `transport = HttpEmbedTransport(cfg)`
- 앵커: `labelbot/embed.py` :: `model, url = cfg["model"], cfg["base_url"].rstrip("/") + cfg["path"]`
- import와 기본 전송을 `InhouseEmbedTransport`로 바꾸고, 40줄은 `model = cfg["model"]`만 남긴다(`url`을 쓰는 곳이 있으면 함께 지운다).
- 받은 벡터 수가 입력 수와 다르거나 차원이 섞이면 그 묶음을 `RESPONSE_SHAPE` 실패로 남긴다(지금 실패 기록 방식을 따른다).
- 사내 임베딩 최대 입력이 짧으면(§1-4) 설정 `embedding.max_input_chars`를 추가하고 보내기 전에 자른다. 잘랐다는 사실은 사유 코드 `EMBED_INPUT_TRUNCATED`와 chunk ID로만 로그에 남긴다.

**A4. 설정 점검** — `labelbot/selfcheck.py`
- 앵커: `labelbot/selfcheck.py` :: `item("llm_config", bool(llm.get("base_url") and llm.get("model")), "model=%s" % (llm.get("model") or "(없음)"))`
- 앵커: `labelbot/selfcheck.py` :: `item("llm_key_env", llm.get("transport") == "mock" or bool(read_key(llm.get("api_key_env"))), llm.get("api_key_env") or "")`
- `llm_config`는 `bool(llm.get("model"))`, `llm_key_env` 줄은 `llm_adapter` 항목으로 바꿔 `inhouse_llm.check_config(llm)` 결과를 쓴다(mock이면 PASS). `embedding_adapter` 항목도 같은 방식으로 추가한다.
- **import 줄(`from labelbot.llm import CallFailed, get_json, read_key`)은 3단계에서 바꾸지 않는다.** `get_json`은 B5에서 `_check_supabase`와 함께 없앤다.
- `--probe-llm`(`_probe_llm`)은 그대로 둔다(채팅 왕복 확인). 임베딩 왕복은 §6 4단계의 별도 명령으로 확인한다.

**A5. domain_engrbot judge·질문 생성** — `domain_engrbot/llm_http.py`, `judge.py`, `questions.py`, `policy.py`
- `domain_engrbot/llm_http.py`: 파일 이름은 유지한다(`code_engrbot/defaults/policy.json`의 `labelbot_import_allowed`에 있다). 클래스 `OpenAICompatJudgeLLM`을 `InhouseJudgeLLM`으로 바꾼다.
  - 앵커: `domain_engrbot/llm_http.py` :: `class OpenAICompatJudgeLLM(JudgeLLM):`
  - 앵커: `domain_engrbot/llm_http.py` :: `body["tools"] = [{"type": "function", "function": {`
  - 앵커: `domain_engrbot/llm_http.py` :: `out = msg["tool_calls"][0]["function"]["arguments"] if self.mode == "tool" else msg["content"]`
  - `__init__(self, cfg, chat=None)`: `chat`은 테스트에서 바꿔 끼우는 함수이고 기본값은 `labelbot.inhouse_llm.chat`이다(`post=` 인자는 지운다).
  - `build_body`: `TOOL_NAME`·`TOOL_PARAMETERS`·tool 분기를 지우고 A2와 같은 중립 dict를 만든다(`json_mode`는 `cfg.get("response_format_json")`).
  - `request_identity`: `{"endpoint": endpoint_id(cfg), "body": self.build_body(messages)}`.
  - `complete`: `self.chat(cfg, messages, max_tokens=..., temperature=..., json_mode=..., timeout=cfg.get("timeout") or 60).text`를 돌려준다. `CallFailed`는 `LLMError(e.reason_code)`로, `KEY_MISSING`·`CONFIG_MISSING`은 `LLMError(code, sent=False)`로 바꾼다.
  - `sent_params`: `"transport": "inhouse"`, `"endpoint": endpoint_id(cfg)`, `model`, `mode`(항상 `"json"`), `temperature`, `max_tokens`, `response_format`.
  - 이 파일에 `def endpoint_id(cfg): return inhouse_llm.endpoint_id(cfg)`를 둔다. domain_engrbot의 다른 파일은 `labelbot`을 직접 import하지 않고 이 함수를 쓴다(Code-Engr-bot `C3_IMPORT_BOUNDARY`: labelbot import는 `labelbot_import_allowed`의 세 파일만 허용).
  - 모듈 설명의 "OpenAI 호환"을 "사내 LLM"으로 바꾼다.
    - 앵커: `domain_engrbot/llm_http.py` :: `"""OpenAI 호환 judge adapter(7.1절).`
- `domain_engrbot/judge.py`: `base_url` 확인을 `model` 확인으로 바꾸고 import·생성자를 `InhouseJudgeLLM`으로 바꾼다.
  - 앵커: `domain_engrbot/judge.py` :: `if not llm_cfg or not llm_cfg.get("base_url"):`
  - 앵커: `domain_engrbot/judge.py` :: `llm = OpenAICompatJudgeLLM(cfg)`
- `domain_engrbot/questions.py`:
  - `make_llm`의 설정 확인을 `if not c.get("model"):`로, 반환을 `return InhouseJudgeLLM(c)`로 바꾼다(import 줄도 같이).
  - 앵커: `domain_engrbot/questions.py` :: `if not c.get("base_url") or not c.get("model"):`
  - 앵커: `domain_engrbot/questions.py` :: `return OpenAICompatJudgeLLM(c)`
  - `_endpoint(ws_root)`는 `llm.base_url` 대신 그 작업 폴더 `llm` 블록을 `labelbot` 기본값과 합친 dict의 `llm_http.endpoint_id(...)`를 돌려준다. **같은 사내 설정이면 같은 문자열이 나와야 한다.** 다르면 다른 작업 폴더 사례가 모두 `SOURCE_ENDPOINT_DIFFERS`로 빠진다. 이제 "다른 전송처"는 `options.base_url_env`가 가리키는 호스트 또는 `model`이 다를 때만 생긴다(의도한 변화).
    - 앵커: `domain_engrbot/questions.py` :: `url = (labelbot_ws.read_config(ws_root).get("llm") or {}).get("base_url")`
  - `make_llm` 설명의 "OpenAI 호환 LLM"과 `_Sources` 설명의 "llm.base_url"을 사내 표현으로 바꾼다.
- `domain_engrbot/policy.py`: judge `transport` 허용값을 `("mock", "http", "inhouse")`로 넓히고(`"http"`는 `"inhouse"`의 옛 이름), `mode` 허용값은 `("json",)`으로 줄인다. `domain_engrbot/cli.py`의 `--judge` 선택지 `("mock", "http")`와 `transport="http"`는 그대로 둔다.
  - 앵커: `domain_engrbot/policy.py` :: `if j["transport"] not in ("mock", "http"):`
  - 앵커: `domain_engrbot/policy.py` :: `if j["mode"] not in ("json", "tool"):`
- `labelbot/questions.py:164` 주석 "gpt-6-sol은 temperature를 받지 않아"는 "사내 모델이 temperature를 받지 않으면"으로 바꾼다.
  - 앵커: `labelbot/questions.py` :: `gpt-6-sol은 temperature를 받지 않아`

**A6. 새 작업 폴더 설정** — `.claude/skills/BEOL-labeling/scripts/init_workspace.py:35-51`
- 앵커: `.claude/skills/BEOL-labeling/scripts/init_workspace.py` :: `"model": "gpt-6-sol",`
- 앵커: `.claude/skills/BEOL-labeling/scripts/init_workspace.py` :: `"base_url": _D["llm"]["base_url"],`
- 앵커: `.claude/skills/BEOL-labeling/scripts/init_workspace.py` :: `"max_tokens_param": "max_completion_tokens",`
- `PIPELINE["llm"]`은 `{"model": "<§1-4 채팅 모델>", "options": _D["llm"]["options"], "temperature": <지원하면 0, 아니면 None>, "max_tokens": _D["llm"]["max_tokens"], "response_format_json": <§1-4 JSON 모드 지원 여부>, "timeout": 180, "workers": <§1-4 동시 호출 제한 이하, 기본 6>}`로 바꾼다.
- 주소·키는 여기에 쓰지 않는다(환경변수).
- `supabase` 블록은 B1에서 바꾼다(5단계).

**A7. 환경변수 템플릿과 의존성**
- `.env.example`: OpenAI 절(6-8줄)을 사내 LLM 절로 바꾸고(A1 `options`의 환경변수 이름, 값은 비움), Supabase 절(10-16줄)은 지운다. 실제 값은 `.env`(git 무시)나 셸에 넣는다.
  - 앵커: `.env.example` :: `# --- OpenAI (1~3차 LLM, 임베딩) ---`
  - 앵커: `.env.example` :: `SUPABASE_SERVICE_KEY=`
- `requirements-poc.txt`: `openai>=1.40`, `supabase>=2.0`, `python-dotenv>=1.0`을 지운다. 경우 C에서 승인받은 사내 SDK만 남긴다. 남길 것이 없으면 파일 주석만 남긴다.
  - 앵커: `requirements-poc.txt` :: `openai>=1.40`
- `requirements.txt` 9줄 주석에서 "OpenAI, Supabase"를 지운다.
  - 앵커: `requirements.txt` :: `# 사외 PoC에서 쓰는 SDK(OpenAI, Supabase, dotenv)는 requirements-poc.txt에 있다.`

**A8. 3단계에서 같이 고치는 테스트**

| 파일 | 할 일 |
|---|---|
| `tests/test_pipeline.py` 234-302줄 | `build_body` 단언(`b["max_completion_tokens"]` 등)을 중립 body(`max_tokens`, `json_mode`)로, `cache_key` 단언을 `endpoint` 기준으로 바꾼다. http/mock/custom 전송 키 구분 단언은 `inhouse`/`mock`/custom으로. `llm.post_json`의 리다이렉트·시간 초과 테스트는 그대로(함수가 남는다) |
| `domain_engrbot/tests/test_judge.py` | `OpenAICompatJudgeLLM(cfg, post=...)` → `InhouseJudgeLLM(cfg, chat=...)`. URL `/chat/completions` 단언은 가짜 `chat`이 받은 `messages`·`max_tokens` 단언으로. `mode="tool"`을 쓰는 351-357줄·405줄 테스트는 지운다(D9). `_policy(transport="http")`는 그대로 둔다 |
| `domain_engrbot/tests/test_ledger_consume.py` 299-326줄 | 위와 같은 생성자·단언 변경 |
| `domain_engrbot/tests/test_questions.py` 174-200줄 | 189줄 주소 정규화 예제를 `endpoint_id` 비교로. `test_other_source_body_only_with_same_endpoint`의 `other_ws(...)`는 `base_url` 대신 `llm.options.base_url_env`를 받게 바꾼다. 같은 경우는 기본 이름 그대로, 다른 경우는 다른 환경변수 이름을 주고 `unittest.mock.patch.dict(os.environ, {...})`로 그 변수에 다른 호스트를 넣어 `SOURCE_ENDPOINT_DIFFERS`를 확인한다. 437·444줄의 `base_url` 키는 무시되므로 그대로 둔다 |
| `tests/test_inhouse_llm.py` | 새 파일(§3-4, 2단계에 이미 만듦) |

### B. 로컬 저장소 (Supabase 표·Storage 대체) [5단계]

**B1. 설정 블록 `supabase` → `vector_store`** — `labelbot/workspace.py:44-56`
- 앵커: `labelbot/workspace.py` :: `"url_env": "SUPABASE_URL",`
- 블록 전체를 지우고 같은 자리에 둔다:
  ```python
  # push-vectors·push-slides가 쓰는 로컬 RAG 저장소(labelbot/localstore.py). path가 비면 환경변수 BEOL_RAG_STORE,
  # 그것도 없으면 <코드 폴더>/workspaces/_rag_store. 기본 꺼짐(테스트가 실제 저장소에 쓰지 않게). init_workspace.py가 켠다.
  "vector_store": {"enabled": False, "path": "", "batch_size": 100, "slides_enabled": False},
  ```
- `Workspace.supabase_url()`(204-206줄)은 지운다.
  - 앵커: `labelbot/workspace.py` :: `def supabase_url(self):`
- 88줄 주석 "push-vectors가 적재를 멈춘다"는 "push-vectors가 로컬 저장소 적재를 멈춘다"로 바꾼다.
- init_workspace.py의 `supabase` 블록(48-50줄)을 `"vector_store": {"enabled": True, "slides_enabled": True},`로 바꾼다(`_D["supabase"]` 참조가 남으면 import할 때 KeyError).
  - 앵커: `.claude/skills/BEOL-labeling/scripts/init_workspace.py` :: `"supabase": {"enabled": True, "table": "beol_chunk_embeddings",`
  - 앵커: `.claude/skills/BEOL-labeling/scripts/init_workspace.py` :: `# storage_enabled: 슬라이드 JPG를 Storage에 올린다(push-slides).`
- `enabled`는 push-vectors, `slides_enabled`는 push-slides를 켠다(지금의 `supabase.enabled`·`storage_enabled`와 같은 분리).

**B2. 새 모듈 `labelbot/localstore.py`**
- 역할: 로컬 저장소 경로 결정, 스키마 생성, 행 upsert, 슬라이드 `.b64` 저장, RAG 설정 기록. 네트워크 없음.
- 경로: `store_root(vs_cfg)` = `vs_cfg["path"]` → 없으면 환경변수 `BEOL_RAG_STORE` → 없으면 `os.path.join(CODE_ROOT, "workspaces", "_rag_store")`. 절대경로로 바꿔 돌려준다.
- 파일 배치(모두 허용 형식):
  ```text
  <store>/rag_store.sqlite     표 meta, beol_chunk_embeddings, beol_rag_feedback
  <store>/slides/<jpg_sha256>.b64
  <store>/rag_config.json      마지막 push-vectors가 쓴 llm·embedding 블록(환경변수 '이름'만, 값 없음)
  ```
- 스키마(`connect(root)`가 폴더·파일이 없으면 만든다. `PRAGMA journal_mode=WAL`):
  ```sql
  CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);   -- store_id(uuid4)를 처음 만들 때 한 번 넣는다
  CREATE TABLE IF NOT EXISTS beol_chunk_embeddings(
    chunk_id TEXT NOT NULL, model TEXT NOT NULL, file_id TEXT NOT NULL, file_name TEXT, seq INTEGER,
    dim INTEGER NOT NULL, embedding BLOB NOT NULL,          -- little-endian float32 (labelbot.embed.pack 형식)
    content TEXT, labels TEXT,                                -- labels: JSON {axes, answers, doc_meta?}
    run_id TEXT, updated_at TEXT,
    slide_image_bucket TEXT, slide_image_path TEXT, slide_image_sha256 TEXT,
    slide_image_width INTEGER, slide_image_height INTEGER,
    PRIMARY KEY(chunk_id, model));
  CREATE INDEX IF NOT EXISTS ix_bce_file ON beol_chunk_embeddings(file_id, seq);
  CREATE TABLE IF NOT EXISTS beol_rag_feedback(
    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, session_id TEXT, question TEXT NOT NULL, answer TEXT NOT NULL,
    evidence TEXT NOT NULL DEFAULT '[]', verdict TEXT NOT NULL CHECK(verdict IN ('good','bad')), comment TEXT);  -- comment는 null 허용
  ```
- 대상 해시: `target_hash(con)` = `util.sha256_text("local:" + meta.store_id)[:16]`. `vector_push_log`·`slide_image_push_log`의 `target_host_hash` 열에 이 값을 쓴다(열 이름은 그대로 둔다. work.sqlite 스키마 스냅샷을 바꾸지 않기 위해서다). **저장소 폴더를 지우고 다시 만들면 store_id가 바뀌어 모든 작업 폴더가 처음부터 다시 적재된다.**
- `upsert_rows(con, rows)`: `rows`는 B3의 dict 행이다. 여기서 `embedding`(float 목록)을 `embed.pack`으로, `labels`(dict)를 `json.dumps(..., ensure_ascii=False, sort_keys=True)`로 바꿔 `INSERT ... ON CONFLICT(chunk_id, model) DO UPDATE SET` **벡터·본문·라벨 열만**(file_id, file_name, seq, dim, embedding, content, labels, run_id, updated_at) 갱신한다. `slide_image_*` 열은 건드리지 않는다(Supabase `merge-duplicates`와 같은 의미).
- `put_slide(root, sha, data)`: `data`(JPG bytes)를 `<store>/slides/<sha>.b64`에 base64로 쓴다. 이미 있으면 건너뛴다. 임시 파일(`.b64.tmp`가 아니라 같은 폴더의 `<sha>.part.b64`)에 쓰고 `os.replace`로 바꾼다.
- `patch_slide(con, chunk_id, fields)`: `con`은 **저장소 연결**(work.sqlite 아님). `UPDATE beol_chunk_embeddings SET slide_image_*=? WHERE chunk_id=?`, 갱신 행 수를 돌려준다.
- `write_rag_config(root, llm_cfg, emb_cfg)`: 두 블록을 `rag_config.json`으로 쓴다(임시 파일 → `os.replace`).
- 테스트 `tests/test_localstore.py`: 임시 폴더로 스키마 생성·store_id 1회 생성, upsert 두 번(같은 키는 한 행, slide 열 유지), `put_slide` 멱등, `patch_slide` 행 수, 폴더 재생성 시 `target_hash`가 바뀌는지.

**B3. `labelbot/vectorpush.py` — Supabase 대신 로컬 저장소**
- 앵커: `labelbot/vectorpush.py` :: `class SupabaseSink(SupabaseSinkBase):`
- 앵커: `labelbot/vectorpush.py` :: `from labelbot.llm import CallFailed, SupabaseSinkBase, host_hash, post_json, read_key`
- 앵커: `labelbot/vectorpush.py` :: `sb = ws.config["supabase"]`
- 앵커: `labelbot/vectorpush.py` :: `print("[push-vectors] SUPABASE_URL 또는 키 환경변수가 없습니다.")`
- `SupabaseSink`를 `LocalSink(root)`로 바꾼다. `send(rows)`는 저장소를 열어 `localstore.upsert_rows`를 부른다.
- 정적 메서드 `row()`는 **지금처럼 dict를 돌려준다**: `labels`는 dict, `embedding`은 float 목록(지금의 `"[...]"` 문자열 대신 `list(vec)`), `updated_at` 추가. 직렬화는 `LocalSink.send` 안(`upsert_rows`)에서 한다. 그래야 가짜 sink를 쓰는 테스트(`r["labels"]["axes"]`)가 그대로 동작한다. `row()`를 부르는 곳(`SupabaseSink.row(...)`)은 `LocalSink.row(...)`로 바꾼다.
- `push()`: `ws.config["vector_store"]`를 읽는다. `enabled`가 거짓이면 `[push-vectors] vector_store.enabled=false: 저장하지 않습니다.`를 출력하고 지금과 같은 0 결과를 돌려준다. 키·URL 확인 분기는 지운다. 대상 해시는 `localstore.target_hash(...)`.
- `write_rag_config`는 **`sink is None`일 때(실제 LocalSink를 이 함수가 만들었을 때)만** 부른다. 테스트가 가짜 sink를 넣으면 쓰지 않는다.
- `unpushed()`: `ws.supabase_url()` 대신 `vector_store.enabled`가 거짓이면 0, 참이면 저장소의 `target_hash`로 같은 계산을 한다(저장소가 아직 없으면 만들지 말고 "모두 미적재"로 센다).
  - 앵커: `labelbot/vectorpush.py` :: `target, model = host_hash(url), ws.config["embedding"]["model"]`
- rules-update 변경 비율 차단(`RULES_CHANGE_RATIO_HIGH`, `--force`, 출력 문구 `[push-vectors] 차단 ...`·`FORCED`)과 `MODEL_DIM_MIX` 거부는 **그대로 둔다.**
- 모듈 설명 1-4줄을 "로컬 RAG 저장소 적재"로 바꾼다.
  - 앵커: `labelbot/vectorpush.py` :: `"""Supabase(Postgres + pgvector) 벡터 적재(python -m labelbot push-vectors). Supabase는 사본이다.`
- 저장소에 다른 `model`의 행이 이미 있으면 지우지 않고 경고 한 줄(`[push-vectors] 저장소에 다른 임베딩 모델 행 n개`)만 낸다. RAG 서버는 `rag_config.json`의 모델 행만 쓴다.

**B4. `labelbot/slidepush.py` — Storage 대신 로컬 저장소**
- 앵커: `labelbot/slidepush.py` :: `class StorageSink(SupabaseSinkBase):`
- 앵커: `labelbot/slidepush.py` :: `from labelbot.llm import CallFailed, SupabaseSinkBase, host_hash, patch_json, post_bytes, read_key`
- 앵커: `labelbot/slidepush.py` :: `print("[push-slides] supabase.storage_enabled=false: 호출하지 않습니다.")`
- `StorageSink`를 `LocalSlideSink(root)`로 바꾼다. 생성할 때 저장소 연결을 **스스로** 연다. `upload(bucket, path, data)`는 `localstore.put_slide(root, sha256(data), data)`, `patch_row(chunk_id, fields)`는 `localstore.patch_slide(저장소 연결, ...)`.
- `push()`: `vector_store.slides_enabled`가 참일 때만 동작한다. 아니면 `[push-slides] vector_store.slides_enabled=false: 저장하지 않습니다.`. 버킷 값은 상수 `LOCAL_BUCKET = "local"`. 대상 해시는 `localstore.target_hash(...)`.
- `STAGE = "push_slides"`, `row_fields`, `_send`의 sha256·JPEG 시그니처 검사, `slide_image_push_log` 기록, `ROW_MISSING`(벡터 행이 아직 없음)은 그대로 둔다.
- 모듈 설명 1-6줄의 "Supabase Storage"를 "로컬 저장소 slides/"로 바꾼다.

**B5. 그 밖의 `supabase` 참조**
- `labelbot/selfcheck.py`: `_check_supabase` 함수와 부르는 곳을 지우고, `vector_store.enabled`일 때 `vector_store` 항목(저장소 폴더 쓰기 가능 여부)을 추가한다. import 줄에서 `get_json`을 뺀다. `import urllib.parse`가 더 쓰이지 않으면 지운다.
  - 앵커: `labelbot/selfcheck.py` :: `def _check_supabase(ws, item, out):`
  - 앵커: `labelbot/selfcheck.py` :: `if ws.config["supabase"].get("enabled"):`
  - 앵커: `labelbot/selfcheck.py` :: `from labelbot.llm import CallFailed, get_json, read_key`
- `labelbot/export.py:106`: `bucket = slidepush.LOCAL_BUCKET if (ws.config.get("vector_store") or {}).get("slides_enabled") else None`. 40줄 SCHEMA 설명 문구(`bucket, object_path`)는 "로컬 저장소 slides/에 저장된 경우"로 바꾼다.
  - 앵커: `labelbot/export.py` :: `bucket = ws.config["supabase"].get("storage_bucket")`
- `labelbot/slideimg.py`: `slide_image_meta`는 그대로 쓰고 207줄 주석과 `object_path` 설명의 "Storage"를 "로컬 저장소"로 바꾼다.
  - 앵커: `labelbot/slideimg.py` :: `# Storage에 실제로 올라간(push-slides OK) 경우에만 객체 위치를 적는다.`
- `labelbot/runchain.py:72-81`: `supabase.enabled` → `vector_store.enabled`. 설명의 "supabase를 쓰는데"도 바꾼다.
  - 앵커: `labelbot/runchain.py` :: `if not (ws.config.get("supabase") or {}).get("enabled"):`
- `labelbot/rulesboard.py:36`: `if not (ws.config.get("vector_store") or {}).get("enabled"):`. 설명의 "Supabase 꺼짐·URL 없음"을 "로컬 저장 꺼짐"으로.
  - 앵커: `labelbot/rulesboard.py` :: `if not (ws.config.get("supabase") or {}).get("enabled") or not ws.supabase_url():`
- `labelbot/dashboard.py`, `labelbot/axisboard.py`, `labelbot/rulesupdate.py`, `labelbot/pipeline.py`: 설명·주석의 "Supabase"를 "로컬 저장소"로 바꾼다(`grep -n -i supabase <파일>`).
- 화면 문구: `labelbot/screens/results.html`, `labelbot/screens/axis_update.html`, `labelbot/screens/rules_update.html`의 "Supabase 적재"·"Supabase 꺼짐"을 "로컬 저장"·"로컬 저장 꺼짐"으로 바꾼다.
  - 앵커: `labelbot/screens/results.html` :: `'Supabase 적재'`
  - 앵커: `labelbot/screens/axis_update.html` :: `text:"Supabase 적재"`
  - 앵커: `labelbot/screens/rules_update.html` :: `text:"Supabase 꺼짐"`
- `labelbot/cli.py` 명령 설명(31·33줄): `("push-vectors", "로컬 RAG 저장소에 벡터 적재")`, `("push-slides", "슬라이드 JPG를 로컬 RAG 저장소에 저장하고 행에 slide_image_* 기록")`. 명령 이름·인자는 바꾸지 않는다.
  - 앵커: `labelbot/cli.py` :: `("push-vectors", "Supabase 벡터 적재")`
  - 앵커: `labelbot/cli.py` :: `("push-slides", "슬라이드 JPG를 Supabase Storage에 올리고 행에 slide_image_* 기록")`
- `.claude/skills/BEOL-labeling/scripts/summary.py:87,89`: 키 `supabase_enabled`를 `vector_store_enabled`로 바꾸고 `cfg.get("vector_store", {})`를 읽는다. BEOL-labeling-feedback SKILL.md의 같은 이름도 바꾼다(F1).
  - 앵커: `.claude/skills/BEOL-labeling/scripts/summary.py` :: `out["supabase_enabled"] = bool(cfg.get("supabase", {}).get("enabled"))`

**B6. 5단계 끝: Supabase 공용 함수 삭제** — `labelbot/llm.py`
- B3~B5를 마치고 `grep -rn "host_hash\|post_bytes\|patch_json\|get_json\|SupabaseSinkBase" labelbot domain_engrbot tests .claude`가 `labelbot/llm.py` 정의만 남겼을 때 지운다.
  - 앵커: `labelbot/llm.py` :: `def host_hash(url):`
  - 앵커: `labelbot/llm.py` :: `class SupabaseSinkBase:`

**B7. 5단계에서 같이 고치는 테스트**

| 파일 | 할 일 |
|---|---|
| 공통 | 로컬 저장소에 쓰는 테스트는 모두 `vector_store.path`를 `tempfile.mkdtemp()`로 주고, `setUp`에서 환경변수 `BEOL_RAG_STORE`도 임시 폴더로 고정한다(`unittest.mock.patch.dict(os.environ, ...)`). **실제 `workspaces/_rag_store`에 쓰면 안 된다** |
| `tests/test_axis_update.py` | 공유 헬퍼 `SUPABASE`(설정 dict, 30줄)를 `VECTOR_STORE`(임시 path 포함)로, `Sink`(75-82줄)를 가짜 sink 그대로 두거나 로컬 저장소 기반으로. 108줄·580-591줄의 `supabase` 설정·`vectorpush.unpushed` 사용도 바꾼다. **이 헬퍼를 `tests/test_rules_update.py`·`tests/test_rules_board.py`가 import하므로 세 파일을 같이 고친다** |
| `tests/test_rules_update.py` | 17·21줄 import, 85줄 합성 설정, 274-302줄과 663-667줄의 `ws.config["supabase"]` 조작(293줄 `cfg["supabase"] = dict(SUPABASE)` 포함)을 `vector_store`로. `[push-vectors] 차단 ... limit=0.30`, `FORCED` 문구 단언은 그대로 |
| `tests/test_rules_board.py` | 60·66-71줄: `push.state` 판정을 `vector_store.enabled` 기준으로 |
| `tests/test_new_axis_flow.py` | 55줄 합성 설정, 192-199줄 `vectorpush.push(sink)` |
| `tests/test_pipeline.py` | 54줄 합성 설정, 198-220줄 멱등 적재(임시 저장소에 두 번 적재해 두 번째가 건너뜀) |
| `tests/test_slides.py` | 146줄 합성 설정에 `vector_store: {"enabled": True, "slides_enabled": True, "path": <임시>}`. 318-365줄 `SlidePushTests`·`FakeSink`를 `LocalSlideSink` 기준으로. 렌더 테스트는 그대로 |
| `tests/test_golden_run.py` | 76줄 합성 설정의 `supabase` → `vector_store` |
| `tests/test_feedback.py:35`, `tests/test_run_axes.py:43`, `tests/test_taxdiff.py:130`, `domain_engrbot/tests/test_adapter.py:87` | 합성 설정의 `"supabase": {"enabled": False}` → `"vector_store": {"enabled": False}` |
| `tests/test_localstore.py` | 새 파일(B2) |

남은 곳은 `grep -rn -i "supabase\|vectorpush\|slidepush\|SUPABASE\|Sink" tests domain_engrbot/tests`로 찾는다.

### C. RAG 화면을 로컬 서버로 (Edge Function 대체) [6·7단계]

**C1. `labelbot/raglib.py` (새 파일, 6단계) — `rag/functions/beol-rag-ask/lib.ts`를 1:1로 옮긴다**
- **lib.ts를 지우기 전에** 옮긴다. 상수(`MAX_K` … `NO_EVIDENCE_FILTERED_ANSWER`), 문구, `REWRITE_SYSTEM_PROMPT`, `answerSystemPrompt`의 시스템 프롬프트 문장은 **글자 하나 바꾸지 않고** 복사한다.
  - 앵커: `rag/functions/beol-rag-ask/lib.ts` :: `export const REWRITE_SYSTEM_PROMPT =`
  - 앵커: `rag/functions/beol-rag-ask/lib.ts` :: `function answerSystemPrompt(n: number, askConfirm: boolean): string {`
  - 앵커: `rag/functions/beol-rag-ask/lib.ts` :: `export function finalizeAnswer(answer: string, n: number) {`
- 옮길 함수(Python 이름, 인자 순서도 같게): `validate_input(body)`, `needs_rewrite(messages)`, `no_evidence_answer(filters)`, `title_of(content)`, `strip_citations(text)`, `build_evidence(rows, image_urls)`, `attach_siblings(evidence, sibling_rows, image_urls)`, `answer_system_prompt(n, ask_confirm)`, `strip_trailing_question_citations(text)`, `build_answer_messages(...)`, `fix_citations(answer, n)`, `finalize_answer(answer, n)` (+ 비공개 `_evidence_item`, `_axes_summary`, `_doc_meta_summary`, `_cite_numbers`). `corsHeaders`·`toVectorLiteral`은 옮기지 않는다.
- 지울 상수: `EMBED_MODEL`, `EMBED_DIM`(모델·차원은 `rag_config.json`과 저장소 행에서 읽는다).
- JS → Python 주의:
  - `\p{Extended_Pictographic}`는 `re`가 모른다. 이모지 범위 문자 클래스(예: `[☀-➿\U0001F300-\U0001FAFF]️?`)로 근사한다.
  - JS 정규식 끝의 `$`(줄 끝)는 Python에서 `\Z`로 쓴다(Python `$`는 끝 개행 앞에서도 맞는다). 치환 문자열의 `$1`은 `\1`로.
  - JS 문자열 길이는 UTF-16 단위다. 1000자·4000자 상한은 Python `len()`(코드 포인트)로 둔다. 차이는 받아들인다.
  - `Math.random() < CONFIRM_QUESTION_RATE`는 `random.random()`. 테스트에서 바꿔 끼울 수 있게 인자(`rand=random.random`)로 받는다.
  - `trim()`은 `strip()`으로 옮긴다.
- 입력 오류는 예외 `RagInputError(code)`(`BAD_INPUT`)로 낸다.
- 테스트 `tests/test_raglib.py`: `tests/test_rag_ui.py`의 `RagLibRunTest` 사례(같은 파일의 `LIB_CASES_JS`)를 **같은 입력·같은 기대값**으로 옮긴다. 사례 수가 같아야 한다.

**C2. `labelbot/ragsearch.py` (새 파일, 6단계) — SQL `beol_rag_search`를 Python으로**
- 입력: 저장소 연결, 질의 벡터, 질의 문장, `filters`, `k`, 임베딩 모델 이름. 출력: 아래 열을 가진 dict 목록. 모듈 설명에 이 절의 사양을 옮겨 적는다(`docs/supabase_schema.md`를 지운 뒤의 원본이다).
- **완전한 행**(`is_complete(row, model)`, 검색·형제·facets·count·이미지가 같이 쓴다): `model == rag_config 임베딩 모델` 그리고 `labels.axes["Patterning/scheme"]`가 비어 있지 않은 목록 그리고 `labels`에 `doc_meta` 키가 있고 값이 null이 아님 그리고 `slide_image_path`가 있음.
- **filters**: dict가 아니거나 값이 목록이 아니면 `BAD_FILTER`. 축 안은 OR(값 하나라도 `labels.axes[축]`에 있으면 통과, 문자열 완전 일치·대소문자 구분), 축끼리는 AND, 빈 목록 축은 무시, 그 축이 없는 행은 제외. 순위를 매기기 **전에** 거른다.
- **벡터 순위**: 코사인 거리(1 − cos) 오름차순, 동점은 `chunk_id`, 상위 200. 질의 벡터는 `round(x, 7)` 한다. 문서 벡터의 노름은 저장소를 읽을 때 미리 계산해 둔다(수백~수천 행은 순수 Python 전수 계산으로 충분하다).
- **단어 검색**(Postgres `simple` 근사):
  1. 질의 전처리: `"`를 공백으로, 낱말 앞 `-`를 지우고(`(^|\s)-+` → `\1`), 앞뒤 공백 제거. 비면 단어 검색 없음.
  2. 토큰화(문서·질의 같은 함수): 소문자로 바꾸고 `[0-9a-z가-힣_]+(?:-[0-9a-z가-힣_]+)*`로 자른다. 하이픈 낱말은 전체와 각 부분을 모두 토큰으로 넣는다. 어간 처리는 하지 않는다(`저항이` ≠ `저항`).
  3. 질의 토큰은 모두 OR이다. 하나라도 문서 토큰에 있으면 후보.
  4. 점수 `text_score` = 문서에 나온 질의 토큰 출현 수의 합 ÷ (1 + 문서 토큰 수/100). 내림차순, 동점은 `chunk_id`, 상위 200.
  5. 알려진 차이(D8 범위, 고치지 않는다): `ts_rank_cd` 값과 다르다(RRF에는 순위만 쓰인다), `µ`·`Ω` 같은 기호는 토큰에서 빠진다, 하이픈 낱말을 구(phrase)가 아니라 OR로 본다.
- **결합**: `rrf = 1/(60+vector_pos) + 1/(60+text_pos)`(없는 쪽은 0). 정렬 `rrf` 내림차순 → `text_pos`(없으면 뒤) → `vector_pos`(없으면 뒤) → `chunk_id`. 개수는 `min(max(k or 5, 1), 8)`.
- **반환 열**: `chunk_id, file_id, seq, content, labels(dict), slide_image_bucket, slide_image_path, slide_image_width, slide_image_height, vector_similarity(=1−거리), text_score, vector_pos, text_pos, rrf_score`.
- `siblings(con, file_ids, model)`: 같은 파일의 완전한 행 전체를 `file_id, seq` 순으로.
- `facets(con, model)`: 완전한 행의 `labels.axes`에서 목록 값을 펼쳐 `(axis, value, n=서로 다른 chunk 수)`, 정렬 `axis` 오름차순 → `n` 내림차순.
- `count(con, model)`: 완전한 행 수.
- 테스트 `tests/test_ragsearch.py`: 작은 가짜 저장소로 필터 AND/OR, 빈 필터 축 무시, 축 없는 행 제외, 불완전 행 제외, RRF 순서·동점 처리, k 범위, 하이픈 토큰.

**C3. `labelbot/ragsrv.py` (새 파일, 7단계) — 화면 + API 서버**
- 실행: `python -m labelbot.ragsrv --port 8795 --bind 127.0.0.1 --directory <저장소>/rag [--store <경로>] [--chat-model <이름>]`. `--bind` 기본 `127.0.0.1`. `ThreadingHTTPServer`를 쓴다(답변이 수십 초 걸린다).
- 시작할 때 `<store>/rag_config.json`을 읽어 `llm`·`embedding` 블록을 `DEFAULT_CONFIG`와 합친다. 없으면 `[ragsrv] rag_config.json 없음: 먼저 push-vectors를 실행하세요`를 내고 종료 코드 2. 채팅 모델은 `--chat-model` → 환경변수 `RAG_CHAT_MODEL` → `llm.model` 순.
- `labelbot/cli.py`처럼 시작할 때 `.env`를 읽는다(같은 `load_env_file()` 재사용).
- **요청 검사**(`labelbot/serve.py`의 `_local_host`·`_same_origin`과 같은 방식):
  - 모든 요청에서 `Host` 헤더의 이름(포트 제외)이 `127.0.0.1`·`localhost`가 아니면 403(DNS 재바인딩 방어).
  - POST는 `Origin`이 있고 `Origin`의 `scheme://` 뒤가 `Host`와 같고 `Content-Type`이 `application/json`으로 시작할 때만 받는다. 아니면 403.
  - CORS 허용 헤더(`Access-Control-Allow-*`)는 보내지 않는다. `OPTIONS`는 405.
- 정적 파일: `--directory` 아래만 내보낸다(`SimpleHTTPRequestHandler`, `/`는 `beol_rag.html`로). 경로 이탈(`..`)은 404.
- API(모두 같은 출처, JSON은 `application/json; charset=utf-8`):

| 메서드·경로 | 대체하는 것 | 요청 | 응답 |
|---|---|---|---|
| `POST /api/ask` | Edge Function `beol-rag-ask` | `{messages, filters, k}` (본문 204800바이트 이하) | 200 `{answer, rewritten_query, cited, evidence, warnings?}` / 오류 `{error: CODE}` |
| `GET /api/facets` | 뷰 `beol_rag_facets` | — | 200 `[{axis, value, n}]` |
| `GET /api/stats` | `beol_rag_chunks` 행 수(Content-Range) | — | 200 `{count}` |
| `GET /slides/<file_id16>/<seq4>.jpg` | Storage 서명 URL·authenticated 경로 | — | 200 `image/jpeg` / 404 |
| `POST /api/feedback` | 표 `beol_rag_feedback` | `{session_id, question, answer, evidence, verdict, comment}` | **201** `{}` / 400 `{error}` |
| 그 밖의 메서드(OPTIONS 포함) | — | — | 405 `{error: "METHOD_NOT_ALLOWED"}` |

- `/api/ask` 처리 순서(Edge Function `index.ts`와 같다. 전체 예산 80초, 단계 시간 = min(단계 상한, 남은 시간), 남은 시간이 3초 미만이면 그 단계 실패):
  1. 본문 크기·JSON 파싱 → 실패 400 `BAD_REQUEST_JSON`. `raglib.validate_input` → 실패 400 `BAD_INPUT`.
  2. 후속 질문이면(`needs_rewrite`, 남은 시간 60초 이상) `[system: REWRITE_SYSTEM_PROMPT, ...대화]`로 고쳐 쓰기를 부른다. 대화의 assistant 메시지 내용은 `strip_citations(content)[:MAX_CONTEXT_ASSISTANT_CHARS]`로 바꿔 넣는다(index.ts 167-170줄과 같다). 호출은 `inhouse_llm.chat(..., max_tokens=400, temperature=None, timeout=min(20, 남은))`. 결과의 공백을 하나로 줄이고 앞뒤 공백을 지운다. 비었거나 400자 초과·실패면 원문 질문을 쓰고 경고 `REWRITE_FAILED`.
  3. 질의 임베딩 `inhouse_llm.embed(emb_cfg, [검색 질문], timeout=min(20, 남은))` → 실패 502 `EMBED_FAILED`, 차원이 저장소 행과 다르면 502 `EMBED_DIM_MISMATCH`, 유한수가 아니면 `EMBED_FAILED`.
  4. `ragsearch.search(...)` → 실패 502 `SEARCH_FAILED`. 0행이면 200 `{answer: no_evidence_answer(filters), rewritten_query, cited: [], evidence: []}`.
  5. 형제 슬라이드 `ragsearch.siblings(...)`에서 hit의 chunk_id를 뺀 나머지가 `extra`. 실패면 `extra=[]`, 경고 `SIBLINGS_FAILED`, 계속.
  6. 이미지 URL 맵: `urls = {p: "/slides/" + p for p in (rows + extra의 slide_image_path)}`. 서명이 없으므로 `SIGN_FAILED`는 생기지 않는다.
  7. `evidence = attach_siblings(build_evidence(rows, urls), extra, urls)` → `build_answer_messages(...)` → `inhouse_llm.chat(..., max_tokens=6000(환경변수 RAG_MAX_COMPLETION_TOKENS로 바꿀 수 있음), temperature=None, timeout=min(45, 남은))`. 실패 502 `LLM_FAILED`.
  8. 답이 비었는데 `finish_reason == "length"`면 502 `LLM_TRUNCATED`, 그냥 비었으면 502 `LLM_EMPTY`. 답이 있는데 `"length"`면 경고 `TRUNCATED`.
  9. `finalize_answer(text, len(evidence))` 후 200.
  10. 그 밖의 예외는 500 `INTERNAL`.
- `/slides/...`: 경로를 `^[0-9a-f]{16}/\d{4}\.jpg$`로 검사하고, 파일 시스템 경로로 바로 잇지 않는다. 저장소 표에서 `slide_image_path`가 같은 완전한 행을 찾아 `slide_image_sha256` → `<store>/slides/<sha>.b64`를 읽어 메모리에서 디코딩하고, sha256과 `FF D8 FF` 시그니처를 확인한 뒤 보낸다. 디스크에 `.jpg`를 쓰지 않는다.
- `/api/feedback` 검사(Supabase 표 제약과 같다): `question` 1~2000자, `answer` 1~8000자, `evidence`는 목록·9개 이하·JSON 16384바이트 이하, `verdict`는 `good`/`bad`, `comment`는 null 또는 1000자 이하, `session_id` 100자 이하. 통과하면 `beol_rag_feedback`에 `id=uuid4`, `created_at`과 함께 넣는다(쓰기는 잠금 하나로 직렬화).
- 로그: 요청마다 `[ragsrv] <경로> <코드> <ms> k=<k> n=<근거 수>` 한 줄만. 질문·답·본문·파일명은 쓰지 않는다.
- 저장소 읽기: 요청마다 읽기 전용으로 열거나(`pathlib.Path(...).as_uri() + "?mode=ro"`. 경로에 공백이 있다), 시작 시 메모리에 올리고 `rag_store.sqlite` 수정 시각이 바뀌면 다시 읽는다.
- 테스트 `tests/test_ragsrv.py`: 임시 저장소 + `inhouse_llm.chat`·`embed`를 가짜로 바꿔 끼우고 서버를 스레드로 띄워 확인한다.
  - `/api/ask`: 정상·NO_EVIDENCE·BAD_INPUT·LLM_TRUNCATED. 답변 호출에 `temperature=None`, `max_tokens=6000`이 전달되는지(옛 `RagFunctionTest`가 보던 것).
  - `/api/facets`, `/api/stats`, `/slides/...`(정상·잘못된 경로 404·이탈 시도 404), `/api/feedback`(201·400).
  - Host가 다른 요청 403, Origin 없는 POST 403, OPTIONS 405.

**C4. `rag/beol_rag.html` — 같은 출처 API로 (7단계)**
- CSP: `connect-src`를 `'self'`로, `img-src`를 `'self' blob: data:`로 바꾼다(Supabase 호스트 제거). `media-src 'self'`는 그대로.
  - 앵커: `rag/beol_rag.html` :: `Content-Security-Policy`
- 설정 상수(10-12줄): `SUPABASE_URL`·`ANON_KEY` 줄을 지우고 `const API_BASE = "";`, `const FUNCTION_URL = API_BASE + "/api/ask";`로 둔다. anon 키 문자열이 파일에 남지 않아야 한다.
  - 앵커: `rag/beol_rag.html` :: `const SUPABASE_URL = `
  - 앵커: `rag/beol_rag.html` :: `const ANON_KEY = `
  - 앵커: `rag/beol_rag.html` :: `const FUNCTION_URL = `
- 인증 헤더(478줄): `var HDR = {};`(apikey·Bearer 제거). `authHeaders()`는 그대로 둬도 된다.
  - 앵커: `rag/beol_rag.html` :: `var HDR = {`
- facets(699줄): `fetch(API_BASE + "/api/facets", ...)`. 응답 모양은 같다.
  - 앵커: `rag/beol_rag.html` :: `/rest/v1/beol_rag_facets?select=axis,value,n&order=axis,n.desc`
- 건수 배지(720-735줄 `loadBadge`): `GET /api/stats`의 `{count}`를 쓰도록 바꾼다(`Content-Range` 해석과 `Prefer`·`Range` 헤더 제거).
  - 앵커: `rag/beol_rag.html` :: `function loadBadge() {`
  - 앵커: `rag/beol_rag.html` :: `"Prefer": "count=exact", "Range": "0-0"`
- 이미지 대체 경로(741-750줄 `viaStorage`): `API_BASE + "/slides/" + path`로 바꾼다.
  - 앵커: `rag/beol_rag.html` :: `function viaStorage() {`
  - 앵커: `rag/beol_rag.html` :: `/storage/v1/object/authenticated/`
- 피드백(1292줄): `fetch(API_BASE + "/api/feedback", ...)`, `Prefer` 헤더 제거. 성공 판정 `r.status === 201`은 그대로(서버가 201을 준다).
  - 앵커: `rag/beol_rag.html` :: `/rest/v1/beol_rag_feedback`
- fetch는 같은 출처라 브라우저가 `Origin`을 붙인다. `Content-Type: application/json`이 빠진 POST가 있으면 넣는다(C3 요청 검사).
- 오류·경고 문구(1322-1324줄)는 코드가 같으므로 그대로 둔다.
- `function renumber(`(830줄)는 테스트가 잘라서 실행하므로 고치지 않는다.
- 응답 JSON을 그리는 코드는 고치지 않는다(계약이 같다).

**C5. 테스트 `tests/test_rag_ui.py` 갱신 (7단계)**
- 지우는 테스트·상수: `test_jwt_payload_role_is_anon`, `test_openai_key_name_only_in_env_get`, `test_no_service_role_key_name`, `test_page_has_exactly_one_jwt_anon_for_project`, `class RagFunctionTest`(lib.ts·index.ts 대상, `test_single_console_call` 포함), `class RagSchemaDocTest`(docs/supabase_schema.md 대상), 상수 `SUPABASE_HOST`·`PROJECT_REF`·`SCHEMA_MD`와 lib.ts·index.ts 경로 상수. `rag_sources()`·`test_sources_exist`가 index.ts·lib.ts를 목록에 넣고 있으면 `rag/beol_rag.html`만 보도록 고친다.
  - 앵커: `tests/test_rag_ui.py` :: `class RagFunctionTest(unittest.TestCase):`
  - 앵커: `tests/test_rag_ui.py` :: `class RagSchemaDocTest(unittest.TestCase):`
  - 앵커: `tests/test_rag_ui.py` :: `def test_page_has_exactly_one_jwt_anon_for_project(self):`
- 바꾸는 테스트:
  - `test_page_has_no_web_url_except_backend` → 페이지에 `http(s)://` 주소가 하나도 없음.
  - `test_page_has_csp_meta_with_supabase_connect_src` → CSP에 `connect-src 'self'`가 있고 Supabase 호스트가 없음.
    - 앵커: `tests/test_rag_ui.py` :: `def test_page_has_csp_meta_with_supabase_connect_src(self):`
  - `test_page_has_config_constants` → `API_BASE`, `FUNCTION_URL` 확인.
  - `test_no_external_resources`(100줄 근처)의 `.replace(SUPABASE_HOST, "")`를 지운다(상수를 지우면 NameError).
  - 새 테스트: 페이지에 JWT(`eyJ`로 시작하는 토큰)·`apikey` 헤더·Supabase 문자열이 없음. 검사 문자열은 `"supa" + "base"`처럼 나눠 써서 §11-1 grep에 걸리지 않게 한다.
- `class RagLibRunTest`(node로 lib.ts 실행)는 C1의 `tests/test_raglib.py`로 옮긴 뒤 지운다(사례 원본은 같은 파일의 `LIB_CASES_JS`).
  - 앵커: `tests/test_rag_ui.py` :: `class RagLibRunTest(unittest.TestCase):`
- 그대로 두는 테스트: `test_no_openai_key_shape`(이름만 `test_no_api_key_shape`로 바꾼다. §11-1 grep), `test_no_new_style_secret_key_anywhere_in_rag`, `test_page_has_no_inner_html`, `test_mockups_do_not_fetch`, `test_launch_json_rag_ui`, `test_policy_excludes_rag`, `test_readme_has_rag_section`, `RagOldNameTest`, `PageRenumberTest`.
- `PageRenumberTest`는 node가 필요하다. 사내 PC에 node가 없어 0단계 기준선에서 이미 실패·건너뜀이면 그 상태를 §12에 적어 둔다(새 실패로 보지 않는다).

**C6. 실행 설정** — `.claude/launch.json` (7단계)
- `rag-ui` 항목의 `"runtimeArgs"`를 `["-m", "labelbot.ragsrv", "--port", "8795", "--bind", "127.0.0.1", "--directory", "<저장소 절대경로>/rag"]`로 바꾼다(`runtimeExecutable`은 `python` 그대로). 이름 `rag-ui`, 포트 `8795`, `--bind`·`127.0.0.1`·`--directory` 인자는 `test_launch_json_rag_ui`가 요구하므로 유지한다.
  - 앵커: `.claude/launch.json` :: `"name": "rag-ui",`
- `python -m labelbot.ragsrv`는 저장소 루트에서 실행해야 `labelbot`을 찾는다. launch.json은 프로젝트 폴더에서 실행된다. 터미널에서 띄울 때는 먼저 저장소 루트로 이동한다.

### D. 지우는 파일·코드 [8단계]

| 대상 | 처리 |
|---|---|
| `rag/functions/` 폴더 전체(`beol-rag-ask/index.ts`, `lib.ts`) | C1 포팅이 끝나고 `tests/test_raglib.py`가 통과한 **뒤** 지운다 |
| `docs/supabase_schema.md` | 지운다. 검색 사양은 `labelbot/ragsearch.py` 모듈 설명으로 옮겼다(C2) |
| `labelbot/llm.py`의 OpenAI·Supabase 전용 함수 | A2(3단계), B6(5단계)에서 이미 지웠는지 확인 |
| `labelbot/workspace.py`의 `supabase` 블록·`supabase_url()` | B1에서 이미 지웠는지 확인 |
| `requirements-poc.txt`의 `openai`, `supabase`, `python-dotenv` / `.env.example`의 `OPENAI_API_KEY`, `SUPABASE_*` | A7에서 이미 지웠는지 확인 |

### E. 스냅샷 다시 만들기 [9단계]

계약 스냅샷은 `CONTRACT_UPDATE=1`, golden은 `GOLDEN_UPDATE=1`로 다시 쓴다(두 변수는 다르다).

```bash
CONTRACT_UPDATE=1 python -m pytest -p no:cacheprovider -q tests/contracts
GOLDEN_UPDATE=1 python -m pytest -p no:cacheprovider -q tests/test_golden_run.py
```

PowerShell에서는 `$env:CONTRACT_UPDATE="1"; python -m pytest -p no:cacheprovider -q tests/contracts; Remove-Item Env:CONTRACT_UPDATE`처럼 한다(`GOLDEN_UPDATE`도 같다). 다시 쓴 뒤 변수를 지우고 **한 번 더 그냥 돌려** 통과하는지 본다.

| 스냅샷 | 예상되는 변경(이것 말고 바뀌면 원인을 찾는다) |
|---|---|
| `tests/contracts/snapshots/constants.json` | `DEFAULT_CONFIG`의 `llm`·`embedding`(키 정리, `options`), `supabase` → `vector_store`. `labelbot.slidepush.STAGE`는 그대로 |
| `tests/contracts/snapshots/cli_labelbot.json` | `"labelbot"` 키의 push-vectors·push-slides 설명 두 줄만 |
| `tests/contracts/snapshots/labelbot_symbols_used_by_domain_engrbot.json` | domain_engrbot이 쓰는 labelbot 기호(`post_json`·`auth_headers`·`read_key` 대신 `inhouse_llm` 기호) |
| `tests/contracts/snapshots/schema_work_sqlite.json` | **바뀌지 않아야 한다**(work.sqlite 스키마는 그대로) |
| `tests/golden_run/snapshot.json` | `push-vectors`·`push-slides` 출력 문구, selfcheck 항목(`llm_adapter`, `embedding_adapter`, `vector_store`) |

`git diff tests/contracts/snapshots tests/golden_run`으로 위 표와 대조한다.

### F. skill·문서 갱신 [10단계]

**F1. skill (`.claude/skills/`)** — "Supabase 적재"는 "로컬 저장소 적재", "Storage"는 "로컬 저장소 slides/", 배포 절차는 "로컬 서버 재시작"으로 바꾼다. 명령 이름(`push-vectors`, `push-slides`)은 그대로라 명령 줄은 바꾸지 않는다.

각 파일에서 `grep -n -i -E "supabase|openai|gpt-6-sol|text-embedding|edge function|beol-rag-ask|배포" <파일>`로 남은 곳을 모두 찾아 고친다. 파일별 핵심:

- `BEOL-labeling-RAG-html/SKILL.md` — **거의 새로 쓴다.** description에서 Edge Function·배포·트리거("RAG 배포", "edge function 배포", "beol-rag-ask 배포")를 빼고 "로컬 RAG 서버(labelbot.ragsrv)를 띄운다"로. 구성표의 서버 함수 행 → `labelbot/ragsrv.py`·`raglib.py`·`ragsearch.py`. "### 3. Edge Function 배포" 절 전체 삭제. 답변 프롬프트를 고치면 `labelbot/raglib.py`를 고치고 서버를 다시 띄우면 된다고 적는다. `<store>/rag_config.json`이 없으면 push-vectors부터 하라고 안내한다. 키 비출력 규칙은 "사내 LLM 키 환경변수"로 바꾼다.
  - 앵커: `.claude/skills/BEOL-labeling-RAG-html/SKILL.md` :: `### 3. Edge Function 배포`
  - 앵커: `.claude/skills/BEOL-labeling-RAG-html/SKILL.md` :: `/functions/v1/beol-rag-ask`
- `BEOL-labeling-feedback/SKILL.md` — 4단계 제목·설명, 진행표, 보고 예시("적재: Supabase n행"), `supabase.enabled=false` 설명 → `vector_store.enabled=false`, `storage_enabled` → `vector_store.slides_enabled`, `docs/supabase_schema.md` 안내 삭제, summary 키 `supabase_enabled` → `vector_store_enabled`, Storage 버킷 설명 → 로컬 저장소 slides/.
  - 앵커: `.claude/skills/BEOL-labeling-feedback/SKILL.md` :: `### 4. 임베딩, 슬라이드 JPG, Supabase 적재`
- `BEOL-labeling/SKILL.md` — 모델 설명 줄(`gpt-6-sol`, `.env` 키) → 사내 LLM 어댑터 설명. "Supabase 적재는 이 스킬에서 하지 않는다", 보고 예시 "Supabase: 아직 적재하지 않음", 안내 문장 2곳.
  - 앵커: `.claude/skills/BEOL-labeling/SKILL.md` :: `Supabase 적재는 이 스킬에서 하지 않는다.`
- `BEOL-labeling-run-labeling/SKILL.md` — description·범위·흐름도의 "Supabase 적재" 3곳.
  - 앵커: `.claude/skills/BEOL-labeling-run-labeling/SKILL.md` :: `범위는 **Supabase 적재까지**다.`
- `BEOL-labeling-axis-update/SKILL.md` — description, 흐름, 규칙표, `PREV_PUSH_PENDING` 설명("supabase를 쓰는데" → "로컬 저장을 켰는데"), 단계표·보고 형식 등 9곳.
- `BEOL-labeling-rules-update/SKILL.md` — description, 흐름, `PREV_PUSH_PENDING` 설명, "Supabase 적재만", 단계표·보고 형식. 명령 줄(`push-vectors ... [--force]`)은 그대로.
- `BEOL-labeling-Code-Engr-bot/SKILL.md`, `BEOL-labeling-Domain-Engr-bot/SKILL.md` — "사람 검수 반영과 Supabase 적재: BEOL-labeling-feedback" 등.
- `BEOL-labeling-workflow/SKILL.md`, `BEOL-labeling-workflow/assets/workflow_template.html` — 단계 12 이름, 예시 화면의 `llm_probe PASS gpt-6-sol`·`supabase_table PASS` 줄, "text-embedding-3-small · 1536차원 → push-vectors → Supabase" 흐름, 단계 B 설명·산출물.
- `BEOL-labeling-project-html/assets/skill_map.json` — run-labeling lead, feedback role, RAG-html role("답변 서버 함수 배포" → "로컬 답변 서버 실행").

**F2. 최상위 문서**

- `README.md` — feedback 설명, `rag/` 구성(Edge Function → `labelbot.ragsrv`), `supabase_schema.md` 언급 삭제, 환경변수 안내(사내 LLM 이름으로), "Supabase 표: SQL 실행" 삭제, 명령 설명, 설정 예(`gpt-6-sol`, `supabase` 블록 → 사내 모델, `vector_store`). `## RAG 화면 (rag/) 여는 법` 절은 **남기고**(테스트가 본다) 실행 명령을 `python -m labelbot.ragsrv --port 8795 --bind 127.0.0.1 --directory rag`로 바꾸고, Edge Function secret 안내는 지운다.
  - 앵커: `README.md` :: `## RAG 화면 (rag/) 여는 법`
- `PRD.md` — FR-9(임베딩·적재) 절, mermaid의 `Supabase pgvector` 도형 → 로컬 저장소, 호스트 판정 대상(`supabase` 블록 제외), LLM 설정의 `OPENAI_API_KEY`.
- `plan.md` — 모듈 목록(`vectorpush.py`, `slidepush.py` 설명), `docs/supabase_schema.md` 언급, CLI 표(M6b·M6c 설명), 설정 블록 설명(`llm`·`embedding`·`vector_store`), `gpt-6-sol`.
- `PRODUCT.md` — "백엔드: Supabase(...)" 줄과 결정 기록. 결정 기록은 지우지 말고 "결정(2026-10-11): Supabase를 지우고 로컬 저장소 + 로컬 서버(labelbot.ragsrv), LLM은 사내 어댑터"를 새 줄로 더한다.
- `CLAUDE.md` — 바꾸지 않는다.

skill을 고친 뒤 `tests/contracts/test_contract_skill_commands.py`로 SKILL.md의 명령이 CLI에 모두 있는지 확인한다(§6 10단계). 문서를 고칠 때 옛 봇 이름(`tests/test_rename_guard.py`가 막는 이름)을 되살리지 않는다.

`docs/` 아래 HTML(발표·흐름도·스냅샷)은 손으로 고치지 않는다. 필요하면 나중에 해당 skill(`/BEOL-labeling-project-html`, `/BEOL-labeling-workflow`)로 다시 만든다.

---

## 5. 기존 작업 폴더 설정 옮기기 (작업 폴더가 있을 때만)

`workspaces/<작업 폴더>/pipeline.json`은 git이 추적하지 않으므로 코드 수정으로 바뀌지 않는다. 사내 PC에 이미 작업 폴더가 있으면 **저장소 루트에서** 아래를 한 번 돌린다. 원본은 같은 폴더에 `pipeline.prev.json`으로 남긴다(`.json`만 허용. 이미 있으면 덮어쓰지 않는다).

```python
import glob, json, os, shutil
CHAT_MODEL = "<§1-4 채팅 모델>"; EMBED_MODEL = "<§1-4 임베딩 모델>"
for p in glob.glob(os.path.join("workspaces", "*", "pipeline.json")):
    if os.path.basename(os.path.dirname(p)).startswith("_"):
        continue
    prev = p[:-len("pipeline.json")] + "pipeline.prev.json"
    if not os.path.exists(prev):
        shutil.copyfile(p, prev)
    with open(p, encoding="utf-8") as f:
        cfg = json.load(f)
    for name, drop in (("llm", ("base_url", "chat_path", "api_key_env", "auth_header", "extra_headers", "max_tokens_param")),
                       ("embedding", ("base_url", "path", "api_key_env", "auth_header", "extra_headers"))):
        blk = cfg.setdefault(name, {})
        ca = blk.pop("ca_file", None)
        for k in drop:
            blk.pop(k, None)
        if ca:
            blk.setdefault("options", {})["ca_file"] = ca
    cfg["llm"]["model"] = CHAT_MODEL
    cfg["embedding"]["model"] = EMBED_MODEL
    sb = cfg.pop("supabase", {}) or {}
    cfg["vector_store"] = {"enabled": bool(sb.get("enabled")), "slides_enabled": bool(sb.get("storage_enabled"))}
    with open(p, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print("migrated", os.path.basename(os.path.dirname(p)))
```

---

## 6. 적용 순서와 확인 명령

| 순서 | 할 일 | 확인 (통과해야 다음으로) |
|---|---|---|
| 0 | 작업 브랜치를 만든다: `git switch -c local-transform`(git이 없으면 §0-10). §6-1 앵커 점검 스크립트를 돌린다(고치기 **전에만**. 고치기 시작하면 앵커가 사라지는 것이 정상이다). 기준선 `python -m pytest -p no:cacheprovider -q -rf`를 돌려 `FAILED` 테스트 이름을 §12와 비교한다. 다르면(예: node 없음, 사내 환경 차이) 측정한 목록을 §12 아래에 "사내 기준선"으로 적고 사용자에게 보여 준 뒤 진행한다 | 앵커 `bad=0`(아니면 코드가 이 문서 기준과 다르므로 사용자에게 알리고 멈춘다), 기준선 기록 |
| 1 | §1을 읽고 §3-3 추출표를 채워 사용자에게 보여 준다(키 값은 보여 주지 않고 "입력됨/비어 있음"만). 경우 A/B/C를 정한다. 경우 C면 승인을 받는다. §1-5의 값을 저장소 루트 `.env`에 `이름=값`으로 쓴다(이미 같은 이름이 있으면 바꾼다. `.env`는 git이 무시한다) | 사용자 확인, `.env`에 §1-5의 이름이 모두 있음 |
| 2 | `labelbot/inhouse_llm.py` + `tests/test_inhouse_llm.py`(§3) | `python -m pytest -p no:cacheprovider -q tests/test_inhouse_llm.py` |
| 3 | A1~A8 | `python -m pytest -p no:cacheprovider -q -rf tests/test_pipeline.py tests/test_feedback.py domain_engrbot/tests` → `FAILED`가 §12 목록에 있는 것뿐 |
| 4 | 실제 사내 왕복. 작업 폴더가 없으면 `python .claude/skills/BEOL-labeling/scripts/init_workspace.py --input "<입력 폴더>"`로 하나 만들고(출력에 작업 폴더 경로가 나온다), 있으면 그 `pipeline.json`의 `llm.model`이 사내 모델인지 확인한다(§5) | ① `python -m labelbot selfcheck --workspace <작업 폴더> --probe-llm` → `llm_probe`, `llm_adapter`, `embedding_adapter` PASS ② 임베딩 왕복: `python -c "from labelbot.workspace import DEFAULT_CONFIG as D, load_env_file; load_env_file(); from labelbot import inhouse_llm as m; v=m.embed(D['embedding'], ['probe']); print(len(v), len(v[0]))"` → `1 <§1-4 임베딩 차원>`(벡터 값은 출력하지 않는다). ※ 이 시점의 작업 폴더는 아직 `supabase` 블록이 켜져 있어(B1은 5단계) selfcheck의 `supabase_*` 항목 FAIL과 종료 코드 1이 나올 수 있다. 정상이다. ※ `init_workspace.py`는 `.claude/launch.json`에 화면 서버 항목을 더한다. 그대로 두되 C6에서 `rag-ui` 항목만 고친다 |
| 5 | B1~B7 | `python -m pytest -p no:cacheprovider -q tests/test_localstore.py tests/test_slides.py tests/test_axis_update.py tests/test_rules_update.py tests/test_rules_board.py tests/test_new_axis_flow.py tests/test_pipeline.py tests/test_golden_run.py tests/test_feedback.py tests/test_run_axes.py tests/test_taxdiff.py domain_engrbot/tests/test_adapter.py` → 새 실패 0(golden은 9단계에서 스냅샷을 다시 쓰기 전이라 출력 문구 비교만 실패할 수 있다. 그 실패만 허용) |
| 6 | C1 + `tests/test_raglib.py`, C2 + `tests/test_ragsearch.py` | 두 테스트 통과. `RagLibRunTest`와 같은 사례 수 |
| 7 | C3 + `tests/test_ragsrv.py`, C4, C5, C6 | `python -m pytest -p no:cacheprovider -q tests/test_ragsrv.py tests/test_rag_ui.py` |
| 8 | D(삭제) | `git status`에 `rag/functions/`, `docs/supabase_schema.md` 삭제가 보임 |
| 9 | E(스냅샷) | 변수 없이 `python -m pytest -p no:cacheprovider -q tests/contracts tests/test_golden_run.py` 통과, `git diff`가 E 표와 맞음 |
| 10 | F(skill·문서), §5(작업 폴더가 있으면) | `python -m pytest -p no:cacheprovider -q tests/contracts/test_contract_skill_commands.py tests/test_rename_guard.py` |
| 11 | §7 데이터 다시 만들기 + 화면 확인 | §7의 확인 |
| 12 | 전체 테스트 | `python -m pytest -p no:cacheprovider -q -rf` → `FAILED` 이름이 §12(또는 0단계 사내 기준선)와 같음(새 실패 0) |
| 13 | 잔여 확인 §11 | §11-1 명령 결과 0줄 |
| 14 | 검수 1회 | `python -m code_engrbot review --root . --paths <바꾼 파일>` → critical 0 |
| 15 | §13 기록. 커밋은 사내 저장소에만. **push하지 않는다** | — |

### 6-1. 앵커 점검 스크립트 (0단계)

아래를 `workspaces/_anchor_check.py`(git 무시 경로)로 저장하고 저장소 루트에서 `python workspaces/_anchor_check.py`로 돌린다. 끝나면 지워도 된다.

```python
import os, re, sys
ANCHOR = re.compile(r"앵커: `([^`]+)` :: `(.+)`$")
text = open("local-transformation.md", encoding="utf-8").read()
found = [m.groups() for m in (ANCHOR.search(l.rstrip()) for l in text.splitlines()) if m]
bad = []
for path, s in found:
    full = os.path.join(*path.split("/"))
    n = open(full, encoding="utf-8").read().count(s) if os.path.isfile(full) else -1
    if n != 1:
        bad.append((n, path, s))
for tag in ("USER_INPUT:INHOUSE_LLM BEGIN", "USER_INPUT:INHOUSE_LLM END"):
    if tag not in text:
        bad.append(("NO_SLOT", tag, ""))
print("anchors=%d bad=%d" % (len(found), len(bad)))
for b in bad:
    print("BAD", *b)
sys.exit(1 if bad else 0)
```

`-1`은 파일 없음, `0`은 문자열 없음, `2` 이상은 여러 번 나옴이다.

---

## 7. 데이터 다시 만들기 (임베딩 모델이 바뀌었으므로)

작업 폴더마다 **오래된 것부터** 아래를 돌린다(같은 chunk는 나중 작업 폴더가 이긴다. Supabase upsert와 같은 의미).

```bash
python -m labelbot embed --workspace "<작업 폴더>"
python -m labelbot push-vectors --workspace "<작업 폴더>"
python -m labelbot push-slides --workspace "<작업 폴더>"
```

- `--run`을 안 주면 각 명령은 끝난 최신 실행을 쓴다. 특정 실행이면 `--run <실행 ID>`.
- `push-vectors`가 `[push-vectors] 차단 RULES_CHANGE_RATIO_HIGH`를 내면 사용자에게 보여 주고, 사용자가 확인한 뒤에만 `--force`를 붙인다.
- 확인:
  - `[embed]` 실패 0, `[push-vectors] ... 전송 n행`, `[push-slides] ... 실패 0`(`ROW_MISSING`이 있으면 push-vectors를 먼저 했는지 본다).
  - `<store>/rag_config.json`이 있고 `embedding.model`이 사내 모델이다.
  - RAG 서버: 저장소 루트에서 `python -m labelbot.ragsrv --port 8795 --bind 127.0.0.1 --directory rag` → 브라우저 `http://127.0.0.1:8795/beol_rag.html`에서 필터 목록과 건수 배지가 보이고, 질문 하나에 답·근거 카드·슬라이드 그림이 나오고, 👍/👎 피드백이 저장된다(`beol_rag_feedback` 행 수 증가). 질문·답 내용은 로그·기록에 옮기지 않는다.

---

## 8. 막혔을 때

| 증상 | 사유 코드 | 할 일 |
|---|---|---|
| 키 없음 | `KEY_MISSING` | `options`에 적은 환경변수 이름으로 셸 또는 `.env`에 값을 넣는다 |
| 설정 없음 | `CONFIG_MISSING`, `LLM_CONFIG_MISSING`, `LLM_MODEL_MISSING` | `llm.model`, `embedding.model`, 주소 환경변수 확인. 경우 C면 SDK 설치 여부 |
| 401·403 | `HTTP_401`, `HTTP_403` | 인증 방식(§3-3 추출표) 확인 |
| 429 | `HTTP_429` | `llm.workers`를 줄인다(§1-4 동시 호출 제한) |
| 응답 모양이 다름 | `RESPONSE_SHAPE`, `RESPONSE_NOT_JSON` | `inhouse_llm.chat`·`embed`의 응답 경로를 §1-3 예시와 대조 |
| 인증서 오류 | `NETWORK_ERROR` | `options.ca_file`(사내 루트 인증서) |
| JSON이 아닌 답 | `JSON_PARSE`, `FORMAT_INVALID` | JSON 모드 미지원이면 `response_format_json=false`로 두고 프롬프트 지시만으로 받는다(`extract_json`이 코드 블록도 읽는다) |
| 임베딩 차원 불일치 | `MODEL_DIM_MIX`, `EMBED_DIM_MISMATCH` | 모든 작업 폴더를 같은 모델로 다시 `embed` → `push-vectors` |
| 화면에 데이터 없음 | 건수 0 | `push-vectors`를 했는지, `rag_config.json`의 임베딩 모델과 행의 `model`이 같은지, `Patterning/scheme` 축·`doc_meta`·슬라이드가 있는지(완전한 행 조건, C2) |
| 그림 안 나옴 | `/slides/...` 404 | `push-slides`를 했는지, `slide_image_path`가 채워졌는지 |
| 화면이 403 | — | 주소창이 `127.0.0.1` 또는 `localhost`인지(C3 요청 검사) |
| 다른 작업 폴더 사례가 빠짐 | `SOURCE_ENDPOINT_DIFFERS` | `endpoint_id`가 같은 설정에서 같은 문자열을 내는지(A5) |
| 사례 유사도가 이상함 | — | `feedback.min_similarity.embedding`(0.5)은 옛 OpenAI 임베딩 기준값이다. 사내 모델로 사례가 너무 많이·적게 잡히면 사용자와 다시 정한다 |

---

## 9. 되돌리기

- 코드: `git switch -` 로 원래 브랜치로 돌아간다. 0단계 브랜치에서만 고쳤으므로 원래 브랜치는 그대로다. git이 없으면 0단계에서 복사해 둔 폴더로 바꾼다.
- 데이터: 로컬 저장소는 `<store>`(기본 `workspaces/_rag_store`) 폴더 하나다. 사용자 확인 후 지우면, 다음 `push-vectors`·`push-slides` 때 새 store_id로 모든 작업 폴더가 처음부터 다시 적재된다(B2).
- 작업 폴더 설정: §5가 남긴 `pipeline.prev.json`을 `pipeline.json`으로 되돌린다.
- 각 작업 폴더 `work.sqlite`의 `chunk_embeddings`에는 모델별로 벡터가 쌓인다(옛 모델 행은 지우지 않는다). `llm_cache`도 지우지 않는다.

---

## 10. 하지 않는 일

- 사내 SDK·외부 패키지를 사용자 승인 없이 설치·import하지 않는다(§3-3 경우 C).
- 사내 주소·키를 코드·추적 파일·산출물·로그에 쓰지 않는다. `endpoint_id`에도 주소 원문 대신 해시를 쓴다.
- RAG 서버를 `127.0.0.1` 밖으로 열지 않는다(`--bind 0.0.0.0` 금지). 다른 PC에서 써야 하면 사용자에게 먼저 묻는다.
- `docs/`의 발표·흐름도 HTML을 손으로 고치지 않는다.
- 응답 JSON 계약(§4-C3 표, `answer`/`evidence`/`cited` 필드)을 바꾸지 않는다. 바꾸면 화면 렌더 코드도 바꿔야 한다.
- 질문·답·슬라이드 본문을 로그·적용 기록에 옮기지 않는다.
- 공개 원격에 push하지 않는다.

---

## 11. 완료 판정

### 11-1. 잔여 문자열 0건

```bash
git grep --untracked -n -i -E "supabase|openai|text-embedding-3|gpt-6-sol|SUPABASE_|OPENAI_|beol-rag-ask|/functions/v1|/rest/v1|/storage/v1" -- labelbot domain_engrbot code_engrbot tests .claude rag README.md PRD.md plan.md PRODUCT.md .env.example requirements.txt requirements-poc.txt nightly_run.py daily_report.py ':!domain_engrbot/docs' ':!domain_engrbot/domain_engrbot_plan.md'
```

결과가 0줄이어야 한다. 남으면 §11-2에 해당하는지 보고, 아니면 고친다.

### 11-2. 남아도 되는 것

- `docs/`, `domain_engrbot/docs/`, `domain_engrbot/domain_engrbot_plan.md`, `change-dashboard/`, `.omc/`, `local-transformation.md`(이 문서) — 기록·설계 문서라 grep 대상에서 뺐다.
- 테스트가 "없어야 한다"를 확인하는 문자열은 `"supa" + "base"`처럼 나눠 써서 위 grep에 걸리지 않게 한다.

### 11-3. 그 밖

- 전체 테스트: `FAILED` 이름이 §12(또는 0단계 사내 기준선)와 같다(새 실패 0).
- `python -m labelbot selfcheck --workspace <작업 폴더> --probe-llm` 전 항목 PASS, §6 4단계 임베딩 왕복 확인.
- §7 화면 확인 완료.
- Code-Engr-bot critical 0.

---

## 12. 테스트 기준선 (전환 전부터 실패하던 것)

2026-10-11 사외 PC(Python 3.14.2)에서 `python -m pytest -p no:cacheprovider -q -rf`로 측정했다. 결과: `35 failed, 1130 passed, 407 subtests passed`(약 19분). 35건은 아래 테스트 10개와 하위 테스트(subtest) 실패 25건이다.

```text
domain_engrbot/tests/test_harness.py::FullHarnessTest::test_all_layers_recall_one
domain_engrbot/tests/test_harness.py::FullHarnessTest::test_failsafe_never_pass
domain_engrbot/tests/test_integration.py::ZeroLayerAndNoJudgeTest::test_eval_command_writes_json_and_md
domain_engrbot/tests/test_integration.py::ZeroLayerAndNoJudgeTest::test_layers_without_l3b_never_pass
domain_engrbot/tests/test_integration.py::ZeroLayerAndNoJudgeTest::test_no_judge_zero_pass
domain_engrbot/tests/test_judge.py::CleanAndMutationTest::test_label_swap_detected
domain_engrbot/tests/test_judge.py::CleanAndMutationTest::test_partial_is_minor_and_reason_verbatim
domain_engrbot/tests/test_judge.py::FailSafeTest::test_http_without_llm_config_is_skipped
domain_engrbot/tests/test_judge.py::FailSafeTest::test_no_judge_zero_pass
tests/test_defaults_taxonomy.py::DefaultTaxonomyTest::test_default_synonyms_have_no_short_ascii_keys
```

- 비교는 **실패한 테스트 이름 목록**으로 한다(`-rf` 출력의 `FAILED` 줄). 하위 테스트 수는 사례 수가 바뀌면 달라질 수 있다.
- A8에서 `test_http_without_llm_config_is_skipped`를 고치거나 이름을 바꿨다면 그 사실을 §13에 적고, 여전히 전환 전과 같은 단언에서만 실패하는지 확인한다.
- 전환 중 새로 만든 테스트(`test_inhouse_llm.py`, `test_localstore.py`, `test_raglib.py`, `test_ragsearch.py`, `test_ragsrv.py`)는 모두 통과해야 한다.
- 사외 PC에는 node가 있어 `PageRenumberTest`·`RagLibRunTest`가 통과했다. 사내 PC에 node가 없으면 0단계에서 다르게 나올 수 있다(0단계 사내 기준선에 적는다).

---

## 13. 적용 기록

에이전트는 고친 내용을 한 줄씩 남긴다. 키·실제 주소·질문·답은 적지 않는다. 임베딩 모델 이름에 차원이 없으면 차원을 여기에 적는다.

| 날짜 | 항목(§) | 파일 | 바꾼 내용 요약 | 확인 결과 |
|---|---|---|---|---|
| | | | | |
