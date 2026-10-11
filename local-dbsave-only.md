# local-dbsave-only.md — 저장만 로컬로 (OpenAI는 그대로) 시험 계획 (에이전트용)

> **이 문서를 읽는 에이전트에게**
> 이 폴더(`Desktop/local-pc-dbsave-local-only`, 브랜치 `local-pc-dbsave-local-only`)에서 **Supabase만 지우고 로컬 폴더 저장으로 바꾼다.** LLM·임베딩은 **지금의 OpenAI 호출을 그대로 둔다.**
> 본 설계는 같은 폴더의 `local-transformation.md`(이하 **LT**)를 그대로 쓴다. 이 문서는 LT에서 **무엇을 건너뛰고, 무엇을 바꿔 적용하는지**만 적는다. 이 문서와 LT가 다르면 **이 문서를 따른다.**
> 순서는 §4를 따른다. 단계마다 확인 명령을 돌리고, 실패하면 다음 단계로 가지 않는다.

- 기준: 브랜치 `local-pc-2nd`의 커밋 `69cf3af`에서 갈라졌다. LT의 줄 번호·앵커는 이 커밋에서도 그대로 맞다.
- 원본 폴더 `Desktop/261004 BEOL AX day2`는 **건드리지 않는다.** 모든 명령은 이 폴더 루트에서 실행한다.
- 목적은 **사외 PC에서 로컬 저장소 + 로컬 RAG 서버가 실제 데이터로 동작하는지 시험**하는 것이다. 사내 LLM 전환(LT의 A단계)은 나중에 사내 PC에서 한다.

---

## 0. 반드시 지킬 규칙

1. LT §0의 규칙 1·2·6·8·9·10을 그대로 따른다. 루트 `CLAUDE.md`의 DRM·쓰기 규칙이 가장 우선한다.
2. LT §0-3·§0-4는 이 문서에서 이렇게 읽는다.
   - 네트워크 저수준 호출(`urllib`, `http.client`, `socket`)은 **`labelbot/llm.py`에만** 쓴다. RAG 서버(`labelbot/ragsrv.py`)는 `labelbot/llm.py`의 함수만 부른다.
   - OpenAI 키는 지금처럼 `.env`의 `OPENAI_API_KEY`로 읽는다. 키 값을 코드·문서·로그·출력에 쓰지 않는다.
3. LT §0-5("push하지 않는다")는 이렇게 바꾼다. 이 브랜치는 공개 원격에 push할 수 있다. 다만 **사용자가 시킬 때만** 한다. 커밋도 사용자가 시킬 때만 한다.
4. LT §0-7("OpenAI 코드는 지운다")은 **적용하지 않는다.** 지우는 것은 Supabase 코드뿐이다.

---

## 1. 범위

| LT 절 | 처리 | 비고 |
|---|---|---|
| §1 사용자 입력, §3 어댑터 계약 | **건너뜀** | `labelbot/inhouse_llm.py`, `tests/test_inhouse_llm.py`를 만들지 않는다 |
| §4-A (A1~A8) | **건너뜀** | `llm`·`embedding` 설정, `HttpChatTransport`·`HttpEmbedTransport`, domain_engrbot judge는 그대로 둔다 |
| §4-A7 | **일부만** | `.env.example`의 Supabase 절(`SUPABASE_*`)만 지운다. `requirements-poc.txt`는 `supabase>=2.0` 한 줄만 지운다. `requirements.txt` 주석은 "OpenAI, dotenv"만 남긴다 |
| §4-B (B1~B7) | **그대로 적용** | 아래 §3-1의 작은 차이만 지킨다 |
| §4-C1, C2 | **그대로 적용** | |
| §4-C3 | **바꿔서 적용** | LLM 호출 두 곳을 OpenAI로 바꾼다(§2) |
| §4-C4, C5, C6 | **그대로 적용** | C6의 경로는 이 폴더의 절대경로 |
| §4-D | **일부만** | `rag/functions/`, `docs/supabase_schema.md`만 지운다. OpenAI 함수는 지우지 않는다 |
| §4-E | **바꿔서 적용** | 예상 변경이 줄어든다(§3-3) |
| §4-F | **바꿔서 적용** | Supabase·Edge Function 문구만 고친다. OpenAI·`gpt-6-sol`·`text-embedding-3-small` 문구는 그대로 둔다(§3-4) |
| §5 작업 폴더 설정 옮기기 | **바꿔서 적용** | `supabase` → `vector_store`만 바꾼다(§3-5) |
| §7 데이터 다시 만들기 | **바꿔서 적용** | 임베딩 모델이 그대로이므로 다시 임베딩하지 않는다(§3-6) |
| §11 완료 판정 | **바꿔서 적용** | grep 패턴이 줄어든다(§5) |
| §12 기준선 | **그대로 씀** | 같은 커밋이므로 기준선 실패 10개가 같다 |

---

## 2. RAG 서버의 LLM 호출 — LT §4-C3에서 바뀌는 곳

LT C3는 `inhouse_llm.chat`·`inhouse_llm.embed`를 부른다. 이 시험판에서는 아래처럼 바꾼다. 응답 JSON 계약, 오류 코드, 시간 예산(전체 80초, 단계 상한), 로그 형식은 LT C3 그대로다.

**2-1. `labelbot/llm.py`에 함수 하나를 더한다** (`HttpChatTransport` 바로 아래)

Edge Function `index.ts`의 `chat()`과 같은 동작이다. 캐시·재시도 없이 한 번 부르고, `finish_reason`도 돌려준다. temperature는 보내지 않는다(Edge Function과 같다).

```python
def chat_once(cfg, messages, max_tokens, timeout):
    """RAG 답변용 단발 채팅 호출(labelbot.ragsrv). (본문, finish_reason)을 돌려준다. 캐시·재시도·temperature 없음."""
    key = read_key(cfg.get("api_key_env"))
    if not key:
        raise CallFailed("KEY_MISSING")
    url = cfg["base_url"].rstrip("/") + cfg["chat_path"]
    body = {"model": cfg["model"], "messages": messages, "max_completion_tokens": max_tokens}
    status, resp = post_json(url, auth_headers(cfg, key), body, timeout, cfg.get("ca_file"))
    try:
        choice = resp["choices"][0]
        text = choice["message"].get("content") or ""
        reason = choice.get("finish_reason")
    except (TypeError, KeyError, IndexError, AttributeError):
        raise CallFailed("RESPONSE_SHAPE")
    return text, (reason if isinstance(reason, str) else None)
```

- 토큰 상한 매개변수 이름은 `max_completion_tokens`로 고정한다(Edge Function과 같다. `gpt-6-sol`은 `max_tokens`를 받지 않는다).
- `tests/test_pipeline.py`의 `post_json` 가짜 서버 방식으로 단위 테스트를 하나 더한다: 정상(본문·`"stop"`), `finish_reason="length"`, `choices` 없음 → `RESPONSE_SHAPE`, 키 없음 → `KEY_MISSING`. 테스트 이름은 `ChatOnceTest`.

**2-2. `labelbot/ragsrv.py`는 모듈 수준 함수 두 개로만 LLM을 부른다** (테스트가 바꿔 끼운다)

```python
def _chat(llm_cfg, messages, max_tokens, timeout):
    return llm.chat_once(llm_cfg, messages, max_tokens, timeout)          # (text, finish_reason)


def _embed(emb_cfg, texts, timeout):
    return llm.HttpEmbedTransport(dict(emb_cfg, timeout=timeout)).embed(texts)
```

- LT C3의 `/api/ask` 처리 순서에서
  - 2단계(고쳐 쓰기): `inhouse_llm.chat(..., max_tokens=400, temperature=None, timeout=...)` → `_chat(llm_cfg, msgs, 400, timeout)`. 결과는 `[0]`(본문)만 쓴다.
  - 3단계(질의 임베딩): `inhouse_llm.embed(emb_cfg, [q], timeout=...)` → `_embed(emb_cfg, [q], timeout)`.
  - 7·8단계(답변): `inhouse_llm.chat(..., max_tokens=6000, ...)` → `text, finish = _chat(llm_cfg, msgs, max_tokens, timeout)`. 8단계의 `finish_reason == "length"` 판정은 `finish`로 한다.
- 채팅 모델: `--chat-model` → 환경변수 `RAG_CHAT_MODEL` → `rag_config.json`의 `llm.model` → 그것도 비면 `"gpt-6-sol"`(Edge Function의 `DEFAULT_CHAT_MODEL`과 같다). 정한 모델은 `llm_cfg = dict(llm_cfg, model=<정한 모델>)`로 넣는다.
- `rag_config.json`의 `llm`·`embedding` 블록에는 `base_url`, `chat_path`/`path`, `api_key_env`가 들어 있다(값이 아니라 이름이다). 키는 시작할 때 `load_env_file()`로 읽은 `.env`의 `OPENAI_API_KEY`에서 온다. 키가 없으면 시작할 때 `[ragsrv] OPENAI_API_KEY 없음` 한 줄을 내고 종료 코드 2로 끝난다(키 값은 출력하지 않는다).
- `ragsrv.py`는 `urllib`·`http.client`·`socket`을 import하지 않는다(서버 쪽 `http.server`는 예외).
- `tests/test_ragsrv.py`는 `unittest.mock.patch("labelbot.ragsrv._chat")`, `patch("labelbot.ragsrv._embed")`로 바꿔 끼운다. LT C3 테스트 목록 중 "답변 호출에 `temperature=None`, `max_tokens=6000`이 전달되는지"는 "`_chat`이 `max_tokens=6000`으로 불렸는지"로 바꾼다.

---

## 3. 그 밖에 LT와 다른 점

**3-1. B단계**
- B1의 `init_workspace.py`는 `supabase` 블록(LT 앵커 2개)만 `"vector_store": {"enabled": True, "slides_enabled": True},`로 바꾼다. `llm` 블록(`gpt-6-sol`, `max_completion_tokens`)은 그대로 둔다.
- B6에서 지우는 것은 LT와 같다: `host_hash`, `post_bytes`, `patch_json`, `get_json`, `SupabaseSinkBase`. `post_json`, `auth_headers`, `read_key`, `_open`, `build_opener`, `HttpChatTransport`, `HttpEmbedTransport`는 **남긴다.**
- B5의 selfcheck: `_check_supabase`만 지우고 `vector_store` 항목을 더한다. `llm_config`, `llm_key_env`, `--probe-llm`은 그대로 둔다.

**3-2. C5의 `tests/test_rag_ui.py`**
- `test_no_openai_key_shape`는 이름을 바꾸지 않는다(OpenAI 문자열이 남아도 된다).
- `test_openai_key_name_only_in_env_get`은 LT대로 지운다(대상 `index.ts`가 없어진다).

**3-3. E단계(스냅샷) 예상 변경**

| 스냅샷 | 예상되는 변경 |
|---|---|
| `tests/contracts/snapshots/constants.json` | `DEFAULT_CONFIG`의 `supabase` → `vector_store` **만**. `llm`·`embedding`은 그대로 |
| `tests/contracts/snapshots/cli_labelbot.json` | push-vectors·push-slides 설명 두 줄만 |
| `tests/contracts/snapshots/labelbot_symbols_used_by_domain_engrbot.json` | **바뀌지 않아야 한다** |
| `tests/contracts/snapshots/schema_work_sqlite.json` | **바뀌지 않아야 한다** |
| `tests/golden_run/snapshot.json` | `push-vectors`·`push-slides` 출력 문구, selfcheck의 `supabase_*` 항목 → `vector_store` 항목 |

이것 말고 바뀌면 원인을 찾는다.

**3-4. F단계(문서)**
- 각 파일에서 `grep -n -i -E "supabase|storage|edge function|beol-rag-ask|배포"`로 찾아 Supabase·Edge Function·Storage 문구만 고친다. 모델 이름·OpenAI 키 안내는 그대로 둔다.
- `BEOL-labeling-RAG-html/SKILL.md`의 키 비출력 규칙은 "`OPENAI_API_KEY` 값을 출력하지 않는다"로 쓴다.
- `PRODUCT.md`의 결정 기록 새 줄: "결정(2026-10-11, 시험 브랜치 local-pc-dbsave-local-only): Supabase를 지우고 로컬 저장소 + 로컬 서버(labelbot.ragsrv). LLM은 OpenAI 유지".

**3-5. 작업 폴더 설정 옮기기 (LT §5 대신)**

이 폴더 루트에서 한 번 돌린다. 원본은 `pipeline.prev.json`으로 남긴다.

```python
import glob, json, os, shutil
for p in glob.glob(os.path.join("workspaces", "*", "pipeline.json")):
    if os.path.basename(os.path.dirname(p)).startswith("_"):
        continue
    prev = p[:-len("pipeline.json")] + "pipeline.prev.json"
    if not os.path.exists(prev):
        shutil.copyfile(p, prev)
    with open(p, encoding="utf-8") as f:
        cfg = json.load(f)
    sb = cfg.pop("supabase", {}) or {}
    cfg["vector_store"] = {"enabled": bool(sb.get("enabled")), "slides_enabled": bool(sb.get("storage_enabled"))}
    with open(p, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print("migrated", os.path.basename(os.path.dirname(p)))
```

**3-6. 데이터 적재 (LT §7 대신)**

임베딩 모델(`text-embedding-3-small`, 1536차원)이 그대로이므로 `work.sqlite`의 벡터를 그대로 쓴다. Supabase에 있던 행을 내려받지 않고, 작업 폴더에서 로컬 저장소로 다시 적재한다.

- 작업 폴더마다 **오래된 것부터**(이름의 날짜순):
  ```bash
  python -m labelbot push-vectors --workspace "workspaces/<작업 폴더>"
  python -m labelbot push-slides --workspace "workspaces/<작업 폴더>"
  ```
- `push-vectors`가 "임베딩 없음"으로 0행이면 그 작업 폴더만 `python -m labelbot embed --workspace ...`를 먼저 돌린다(OpenAI 호출이 생긴다. 이미 있는 chunk는 건너뛴다).
- `[push-vectors] 차단 RULES_CHANGE_RATIO_HIGH`가 나오면 멈추고 사용자에게 보여 준다. 사용자가 확인한 뒤에만 `--force`를 붙인다.
- 저장소는 이 폴더의 `workspaces/_rag_store/`에 생긴다(원본 폴더와 섞이지 않는다).

---

## 4. 적용 순서와 확인 명령

| 순서 | 할 일 | 확인 (통과해야 다음으로) |
|---|---|---|
| 0 | **준비.** ① 원본 폴더의 `.env`와 `workspaces/` 폴더를 이 폴더로 복사한다(둘 다 git 무시 경로. 약 205MB). PowerShell: `Copy-Item "..\261004 BEOL AX day2\.env" .env`, `robocopy "..\261004 BEOL AX day2\workspaces" workspaces /E` (robocopy 종료 코드 1은 정상). `.env`의 `SUPABASE_*` 줄은 지운다. ② LT §6-1 앵커 스크립트를 돌린다(A단계 앵커도 그대로 맞아야 한다. 같은 커밋이다). ③ 기준선은 LT §12를 그대로 쓴다(다시 재지 않아도 된다) | 앵커 `bad=0`, `.env`에 `OPENAI_API_KEY` 이름이 있음(값은 출력하지 않는다: `python -c "import re;print(bool(re.search(r'^OPENAI_API_KEY=.+', open('.env',encoding='utf-8').read(), re.M)))"` → `True`) |
| 1 | §2-1 `chat_once` + `ChatOnceTest` | `python -m pytest -p no:cacheprovider -q tests/test_pipeline.py` → 새 실패 0 |
| 2 | LT B1~B7 (§3-1) | LT §6 5단계 확인 명령 → 새 실패 0(golden 출력 문구 비교만 허용) |
| 3 | LT C1 + `tests/test_raglib.py`, C2 + `tests/test_ragsearch.py` | 두 테스트 통과. `RagLibRunTest`와 같은 사례 수 |
| 4 | LT C3(§2-2로 바꿔서) + `tests/test_ragsrv.py`, C4, C5(§3-2), C6 | `python -m pytest -p no:cacheprovider -q tests/test_ragsrv.py tests/test_rag_ui.py` |
| 5 | LT D(§1의 일부만), A7 일부(§1) | `git status`에 `rag/functions/`, `docs/supabase_schema.md` 삭제가 보임 |
| 6 | LT E(§3-3) | 변수 없이 `python -m pytest -p no:cacheprovider -q tests/contracts tests/test_golden_run.py` 통과, `git diff tests/contracts/snapshots tests/golden_run`이 §3-3 표와 맞음 |
| 7 | LT F(§3-4), §3-5 작업 폴더 설정 옮기기 | `python -m pytest -p no:cacheprovider -q tests/contracts/test_contract_skill_commands.py tests/test_rename_guard.py` |
| 8 | §3-6 데이터 적재 | `[push-vectors] ... 전송 n행`, `[push-slides] ... 실패 0`, `workspaces/_rag_store/rag_config.json`이 있음 |
| 9 | **화면 시험.** 이 폴더 루트에서 `python -m labelbot.ragsrv --port 8795 --bind 127.0.0.1 --directory rag`(원본 폴더의 RAG 서버가 8795를 쓰고 있으면 먼저 끈다) → `http://127.0.0.1:8795/beol_rag.html` | 필터 목록·건수 배지가 보임, 질문 1개에 답·근거 카드·슬라이드 그림이 나옴, 후속 질문 1개도 답이 나옴, 👍/👎 후 `beol_rag_feedback` 행 수 증가. 질문·답 내용은 로그·기록에 옮기지 않는다 |
| 10 | 전체 테스트 | `python -m pytest -p no:cacheprovider -q -rf` → `FAILED` 이름이 LT §12와 같음(새 실패 0) |
| 11 | 잔여 확인 §5 | §5 명령 결과 0줄 |
| 12 | 검수 1회 | `python -m code_engrbot review --root . --paths <바꾼 파일>` → critical 0 |
| 13 | §6 적용 기록. 커밋·push는 사용자가 시킬 때만 | — |

---

## 5. 완료 판정 (LT §11 대신)

```bash
git grep --untracked -n -i -E "supabase|SUPABASE_|beol-rag-ask|/functions/v1|/rest/v1|/storage/v1" -- labelbot domain_engrbot code_engrbot tests .claude rag README.md PRD.md plan.md PRODUCT.md .env.example requirements.txt requirements-poc.txt nightly_run.py daily_report.py ':!domain_engrbot/docs' ':!domain_engrbot/domain_engrbot_plan.md'
```

- 결과가 0줄이어야 한다. 남아도 되는 것은 LT §11-2와 같다(`local-transformation.md`, 이 문서 포함).
- `openai`, `gpt-6-sol`, `text-embedding-3`은 **남아 있어야 정상이다.**
- 그 밖: 전체 테스트 새 실패 0, §4 9단계 화면 시험 완료, Code-Engr-bot critical 0.

---

## 6. 적용 기록

키·질문·답은 적지 않는다.

| 날짜 | 항목(§) | 파일 | 바꾼 내용 요약 | 확인 결과 |
|---|---|---|---|---|
| 2026-10-11 | §4-0 | `.env`, `workspaces/`, `taxonomy/taxonomy.json` | 원본에서 복사, `.env`의 `SUPABASE_*` 2줄 삭제. worktree 체크아웃이 CRLF라 `taxonomy.json`을 원본과 같은 LF 바이트로 맞추고 수정 시각을 xlsx 뒤로 | 앵커 bad=0, `OPENAI_API_KEY` 있음 |
| 2026-10-11 | §2-1 | `labelbot/llm.py`, `tests/test_pipeline.py` | `chat_once` + `ChatOnceTest` 4사례 | 통과 |
| 2026-10-11 | LT B1~B7 | `labelbot/localstore.py`(새), `workspace.py`, `vectorpush.py`, `slidepush.py`, `llm.py`, `selfcheck.py`, `export.py`, `slideimg.py`, `runchain.py`, `rulesboard.py`, `dashboard.py`, `cli.py`, 화면 3개, `init_workspace.py`, `summary.py`, 테스트 11개 | Supabase → 로컬 저장소. 계획과 다른 점: `export.py` SCHEMA 문구는 스냅샷 보호를 위해 유지, 저장소 쓰기 오류 사유 코드 `LOCAL_STORE_ERROR` 추가 | 지정 테스트 새 실패 0 |
| 2026-10-11 | LT C1·C2 | `labelbot/raglib.py`, `labelbot/ragsearch.py`(새), 테스트 2개(새) | lib.ts 1:1 이식(node로 원본과 대조, 차이 0), SQL 검색 이식. k=0은 1(원래 SQL과 같게) | 38 통과, 사례 수 18=18 |
| 2026-10-11 | LT C3~C6 | `labelbot/ragsrv.py`, `tests/test_ragsrv.py`(새), `rag/beol_rag.html`, `tests/test_rag_ui.py`, `.claude/launch.json` | 로컬 서버(§2-2 OpenAI 호출), 같은 출처 API. CSP 테스트 이름 `..._self_connect_src`로 변경 | 87 통과 |
| 2026-10-11 | LT D, A7 일부 | `rag/functions/`, `docs/supabase_schema.md` 삭제, `.env.example`, `requirements*.txt` | Supabase 부분만 삭제 | — |
| 2026-10-11 | LT E | 스냅샷 3개 | `cli_labelbot`(설명 2줄), `constants`(`supabase`→`vector_store`), golden(push 문구 2줄) | §3-3 표와 일치, 재실행 통과 |
| 2026-10-11 | LT F | SKILL.md 9개, workflow 템플릿, skill_map.json, README, PRD, plan, PRODUCT | Supabase·Edge Function 문구만 변경 | skill 명령·이름 테스트 통과 |
| 2026-10-11 | §3-5, §3-6 | 작업 폴더 9개 `pipeline.json` | `vector_store`로 이전(원본 `pipeline.prev.json`), push-vectors 228행·push-slides 228건 실패 0 | 저장소 184 chunk·54 파일, 완전한 행 184, facets 95 |
| 2026-10-11 | §4-9 | — | 원본 폴더의 옛 정적 서버가 8795를 쓰고 있어 8796으로 시험. 첫 질문(근거 5/7·그림 표시), 후속 질문(고쳐 쓰기 확인), 👍 피드백 저장 | 모두 정상 |
| 2026-10-11 | §4-10~12 | — | 전체 테스트 `35 failed, 1174 passed`(실패 이름 10개가 LT §12와 같음), §5 grep은 `PRODUCT.md` 결정 기록 1줄만(계획서가 정한 문구), Code-Engr-bot `CR-20261011T150526-7c18` APPROVE critical 0 · minor 1 | 새 실패 0 |
