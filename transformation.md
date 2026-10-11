# transformation.md — 사내 로컬 PC 전환 가이드 (에이전트용)

> **이 문서를 읽는 에이전트(Claude Code 또는 Roo Code)에게**
> 사용자가 §1·§2에 사내 LLM 호출 예시와 S3 업로드 예시를 붙여 넣었다. 그 예시에서 값과 방식을 뽑아(§3) §4의 지도대로 고쳐서, 이 저장소가 **사내 로컬 PC(Windows 업무 PC, 사내망)**에서 OpenAI·Supabase 없이 돌아가게 만든다.
> 순서는 §5를 따른다. 고친 내용은 맨 아래 §8 "적용 기록"에 한 줄씩 남긴다.

- 기준 커밋: `in-house-local` 브랜치 `6b61585`(R1). 아래 줄 번호는 이 커밋 기준이다.
- **줄 번호가 어긋나면 `앵커:` 문자열로 찾는다.** 앵커는 그 파일에 한 번만 나오는 문자열이다. `tests/test_transformation_anchors.py`가 앵커가 실제 파일에 남아 있는지 검사한다.
- §1·§2가 비어 있으면 아무것도 고치지 말고 사용자에게 예시를 붙여 달라고 한다.

---

## 0. 반드시 지킬 규칙

1. **루트 `CLAUDE.md`가 우선한다.** DRM 규칙(사내 파일은 `open(path,"rb")` → base64 → `.b64`, 원본 경로를 여는 곳은 ingest 하나)과 쓰기 규칙(`.b64 .sqlite .json .jsonl .html .md .log`만 쓴다)은 바꾸지 않는다.
2. **본체는 표준 라이브러리만 쓴다.** 사용자 예시가 `openai`·`boto3`·`requests` SDK를 쓰더라도 그 패키지를 설치하거나 import하지 않는다. 예시에서 **주소·헤더·본문·응답 모양**만 읽어 표준 라이브러리 방식으로 옮긴다(§3).
3. **네트워크 호출은 `labelbot/llm.py`를 통해서만 한다.** Code-Engr-bot C2 규칙이다. 새 S3 코드도 `labelbot.llm.request()`를 부른다. `urllib`·`http.client`를 직접 쓰지 않는다.
4. **키·실제 호스트를 코드와 추적 파일에 쓰지 않는다.** 키는 환경변수(이름만 설정에 적는다)로, 실제 주소는 git이 무시하는 `workspaces/_site/`나 각 작업 폴더의 `pipeline.json`에 둔다. 로그·출력에는 파일 ID와 사유 코드만 남긴다.
5. **이 저장소의 GitHub 원격은 공개 저장소다.** 사내 PC에서 고친 결과는 **절대 push하지 않는다.** 사내 값이 들어간 커밋은 사내에만 둔다(필요하면 사내 Git 서버로).
6. TLS 검증을 끄지 않는다. 예시에 `verify=False`가 있어도 따라 하지 않고, 사내 루트 인증서 경로를 `ca_file`에 넣는다(§4-B5).
7. 실패 출력 형식은 기존 마일스톤 체계를 쓴다. 새 사유 코드는 `labelbot/reason_codes.py`에 원인·조치와 함께 넣는다(§4-C7).
8. 검수는 끝에 한 번만 한다: `python -m code_engrbot review --root . --paths <바꾼 파일>`, critical만 고친다(루트 `CLAUDE.md` 임시 지침).

---

## 1. [사용자 입력] 사내 LLM 호출 예시 (OpenAI 형식)

채팅(대화)과 임베딩 호출 예시를 모두 붙인다. 키는 `***`로 가린다. 알면 아래 표도 채운다.

<!-- USER_INPUT:LLM BEGIN -->
```text
(여기에 사내 LLM 채팅 호출 예시 코드를 붙여 넣는다)
```

```text
(여기에 사내 임베딩 호출 예시 코드를 붙여 넣는다. 없으면 "임베딩 없음"이라고 적는다)
```

| 항목 | 값(모르면 비워 둔다) |
|---|---|
| 채팅 모델 이름 | |
| 임베딩 모델 이름 | |
| 임베딩 차원(숫자) | |
| 임베딩 최대 입력 토큰 | |
| 키를 넣을 환경변수 이름 | |
| 사내 루트 인증서(.pem) 경로 | |
| 프록시 필요 여부 | |
<!-- USER_INPUT:LLM END -->

## 2. [사용자 입력] S3 업로드 예시

<!-- USER_INPUT:S3 BEGIN -->
```text
(여기에 사내 S3 업로드 예시 코드를 붙여 넣는다. 키·시크릿은 *** 로 가린다)
```

| 항목 | 값(모르면 비워 둔다) |
|---|---|
| 버킷 이름 | |
| 원본 문서 보관 경로 접두어(예: originals/) | |
| 슬라이드 이미지 경로 접두어(예: slides/) | |
| 암호화(SSE/KMS) 필요 여부 | |
| 액세스 키·시크릿을 넣을 환경변수 이름 | |
<!-- USER_INPUT:S3 END -->

---

## 3. 예시에서 뽑을 값 (추출표)

에이전트는 예시를 읽고 아래 표를 먼저 채워 사용자에게 보여 준 뒤 §4로 간다. 값은 **설정 키 이름**으로 옮긴다.

### 3-1. LLM·임베딩

| 뽑을 것 | 예시에서 찾는 곳 | 옮길 곳(설정 키) |
|---|---|---|
| 기본 주소 | `OpenAI(base_url=...)`, `requests.post("https://.../v1/chat/completions")`의 `/chat/completions` 앞부분 | `llm.base_url`, `embedding.base_url` |
| 채팅 경로 | URL의 나머지(보통 `/chat/completions`) | `llm.chat_path` |
| 임베딩 경로 | 보통 `/embeddings` | `embedding.path` |
| 인증 헤더 | `Authorization: Bearer <키>` / `api-key: <키>` / `x-api-key: <키>` 등 | `llm.auth_header`, `embedding.auth_header` (Authorization이면 `Bearer `가 자동으로 붙는다. 다른 이름이면 키 값만 들어간다) |
| 고정 헤더 | 테넌트·프로젝트 ID 같은 추가 헤더 | `llm.extra_headers`, `embedding.extra_headers` (값이 비밀이면 §4-B1) |
| 키 환경변수 | `os.environ["..."]` | `llm.api_key_env`, `embedding.api_key_env` |
| 모델 이름 | `model="..."` | `llm.model`, `embedding.model` |
| 최대 토큰 매개변수 이름 | `max_tokens` 또는 `max_completion_tokens` | `llm.max_tokens_param` |
| temperature 지원 | 예시에 있으면 지원 | `llm.temperature`(지원 안 하면 `null`) |
| JSON 응답 모드 | `response_format={"type":"json_object"}` | `llm.response_format_json` (지원 안 하면 `false`) |
| 채팅 응답 모양 | `resp.choices[0].message.content` | 같으면 코드 수정 없음. 다르면 §4-B2 |
| 임베딩 응답 모양 | `resp.data[i].embedding`(+`index`) | 같으면 코드 수정 없음. 다르면 §4-B3 |
| 인증서 | `verify="/path/ca.pem"`, `httpx.Client(verify=...)` | `llm.ca_file`, `embedding.ca_file` |
| 시간 제한 | `timeout=` | `llm.timeout`, `embedding.timeout` |

**판정:** 주소·헤더·본문·응답이 OpenAI와 같으면 **§4-A(설정만 수정)**로 끝난다. 하나라도 다르면 §4-B의 해당 항목도 한다.

### 3-2. S3

| 뽑을 것 | 예시에서 찾는 곳 | 옮길 곳(새 설정 블록 `s3`, §4-C1) |
|---|---|---|
| 엔드포인트 | `boto3.client("s3", endpoint_url=...)` | `s3.endpoint` |
| 리전 | `region_name=` | `s3.region` |
| 주소 방식 | `addressing_style: path` / 가상 호스트 | `s3.path_style`(true/false) |
| 인증 방식 | 액세스 키+시크릿(SigV4) / 세션 토큰 / 사내 게이트웨이 토큰 / presigned URL | `s3.auth`(`sigv4` / `bearer` / `presigned`) |
| 키 환경변수 | `aws_access_key_id=os.environ[...]` | `s3.access_key_env`, `s3.secret_key_env`, (`s3.session_token_env`) |
| 버킷·접두어 | `Bucket=`, `Key=` | `s3.bucket`, `s3.prefix_originals`, `s3.prefix_slides` |
| 암호화 | `ServerSideEncryption=`, `SSEKMSKeyId=` | `s3.sse`, `s3.kms_key_id` |
| 인증서 | `verify=` | `s3.ca_file` |

boto3 예시라면 인증 방식은 거의 항상 SigV4다. 표준 라이브러리로 SigV4 서명을 직접 만든다(§4-C1).

---

## 4. 적용 지도 (어느 파일, 몇 번째 줄, 무엇으로)

### A. 설정만으로 되는 부분 (OpenAI 호환이면 여기서 끝)

**A1. 기본 설정값** — `labelbot/workspace.py:14-42`
- 앵커: `labelbot/workspace.py` :: `"chat_path": "/chat/completions",`
- 지금: `llm.base_url`·`embedding.base_url`이 `"https://api.openai.com/v1"`(16, 34줄), 키 환경변수 `"OPENAI_API_KEY"`(19, 37줄), 임베딩 모델 `"text-embedding-3-small"`(36줄).
- 할 일: 주소는 **기본값을 바꾸지 말고** 비워 두는 쪽을 권한다(사내 주소가 추적 파일에 남지 않게). 대신 키 환경변수 이름만 사내 이름으로 바꾸고, 실제 주소는 A2·A3에서 넣는다.
- 바꿀 곳: 19, 37줄의 `"OPENAI_API_KEY"` → §1의 키 환경변수 이름.

**A2. 새 작업 폴더에 쓰는 값** — `.claude/skills/BEOL-labeling/scripts/init_workspace.py:37-54`
- 앵커: `.claude/skills/BEOL-labeling/scripts/init_workspace.py` :: `"model": "gpt-6-sol",`
- 지금: `"model": "gpt-6-sol"`(42줄), `"max_tokens_param": "max_completion_tokens"`(45줄), `"response_format_json": True`(46줄), 임베딩 모델은 기본값(50줄), `"supabase": {"enabled": True, ...}`(52-53줄).
- 할 일:
  - 42줄 모델 → 사내 채팅 모델 이름.
  - 45·46줄 → §3-1의 매개변수 이름·JSON 모드 지원 여부.
  - 50줄 → `{"model": "<사내 임베딩 모델>"}`.
  - 52-53줄 → `"supabase": {"enabled": False, "storage_enabled": False}`. 사내에는 Supabase가 없다. 슬라이드 이미지는 §4-C의 S3로 올린다.
  - 주소(`base_url`)는 여기에 쓰지 않는다. 사이트 값으로 넣는다(A3).

**A3. 실제 주소·인증서 넣기 (git 무시 경로)**
- 기존 작업 폴더: `workspaces/<작업 폴더>/pipeline.json`의 `llm`·`embedding` 블록에 `base_url`, `ca_file`을 넣는다(작업 폴더는 git이 무시한다).
- 새 작업 폴더: `init_workspace.py`가 만든 `pipeline.json`에 같은 값을 넣는다. 매번 넣기 번거로우면 A2의 `PIPELINE`이 `workspaces/_site/profile.json`을 읽어 덮어쓰도록 고친다(파일이 없으면 무시).

**A4. 환경변수** — `.env.example`(추적), 실제 값은 셸 또는 `.env`(무시)
- 앵커: `.env.example` :: `OPENAI_API_KEY=`
- 할 일: `OPENAI_API_KEY=` 아래에 사내 키 환경변수 이름(값은 비움)과 S3 키 환경변수 이름을 추가한다. `SUPABASE_*` 줄은 "사외 PoC 전용"이라는 설명을 남기고 그대로 둔다.
- 외부 전송 가드: 사내 LLM·임베딩·S3 호스트 접미사를 `BEOL_ALLOWED_HOST_SUFFIXES`에 넣는다(쉼표 구분). 설정하면 목록 밖 호스트로는 연결하지 않는다(`labelbot/llm.py:107-127`).
- 앵커: `labelbot/llm.py` :: `def _host_allowed(host, spec=None):`

### B. 예시가 OpenAI와 다를 때만 코드 수정

**B1. 인증 헤더** — `labelbot/llm.py:164-170`
- 앵커: `labelbot/llm.py` :: `def auth_headers(cfg, key):`
- 지금: `auth_header`가 `Authorization`이면 `Bearer <키>`, 다른 이름이면 키 값 그대로, 그다음 `extra_headers`를 덧붙인다.
- 그대로 되는 경우: `api-key: <키>`, `x-api-key: <키>`, 고정 테넌트 헤더.
- 고쳐야 하는 경우:
  - 접두어가 `Bearer`가 아닌 경우(예: `Token <키>`): 설정 `auth_scheme`(기본 `"Bearer"`)을 추가하고 168줄에서 그 값을 쓴다.
  - 헤더 값이 비밀인 추가 헤더: 설정에는 환경변수 이름만 적는 `extra_header_envs: {"헤더이름": "환경변수이름"}`을 추가하고 여기서 읽는다.
  - 토큰을 먼저 발급받는 방식(OAuth 등): 새 함수 `token_from_endpoint(cfg)`를 이 파일에 추가하고(네트워크는 이 파일 안이라 C2 규칙 충족), 만료 시간 동안 캐시한다. 토큰 값은 출력하지 않는다.

**B2. 채팅 응답 모양** — `labelbot/llm.py:222`, `domain_engrbot/llm_http.py:69-70`
- 앵커: `labelbot/llm.py` :: `return resp["choices"][0]["message"]["content"]`
- 앵커: `domain_engrbot/llm_http.py` :: `msg = resp["choices"][0]["message"]`
- 응답이 `choices[0].message.content`가 아니면 두 곳을 같은 방식으로 고친다. 실패 시 사유 코드 `RESPONSE_SHAPE`는 그대로 쓴다.
- domain_engrbot는 tool 모드에서 `tool_calls[0].function.arguments`를 읽는다(70줄). 사내 API가 tool calling을 지원하지 않으면 judge 설정 `mode`를 tool이 아닌 값으로 둔다.

**B3. 임베딩 요청·응답** — `labelbot/llm.py:319-333`(`embed` 함수, 응답 처리는 330-331줄)
- 앵커: `labelbot/llm.py` :: `data = sorted(resp["data"], key=lambda d: d["index"])`
- 지금: 본문 `{"model": ..., "input": [문장 목록]}`, 응답 `data[i].embedding`을 `index` 순서로 정렬한다.
- 다르면 이 함수만 고친다. 예:
  - 입력 키가 `texts`인 경우.
  - 한 번에 한 문장만 받는 경우: 반복 호출로 바꾸고, `embedding.batch_size`를 1로 둔다.
  - `index`가 없는 경우: 받은 순서를 그대로 쓴다.
- 임베딩 최대 입력이 짧으면(예: 512토큰) 긴 chunk가 400 오류를 낸다. 자를 길이를 설정 `embedding.max_input_chars`로 두고 `labelbot/embed.py`에서 자른다(잘랐다는 사실만 로그에 사유 코드로 남긴다).

**B4. 요청 본문 매개변수** — `labelbot/llm.py:249-258`, `domain_engrbot/llm_http.py:35-48`
- 앵커: `labelbot/llm.py` :: `body = {"model": cfg["model"], "messages": messages}`
- 앵커: `domain_engrbot/llm_http.py` :: `body = {"model": cfg.get("model"), "messages": messages}`
- `max_tokens`·`temperature`·`response_format`은 설정으로 켜고 끈다. 사내 API가 추가 필드를 꼭 요구하면(예: `"stream": false`) 설정 `llm.extra_body`(dict)를 추가해 두 곳에서 `body.update(...)`로 넣는다.
- 참고: `labelbot/questions.py:164` 주석은 "gpt-6-sol은 temperature를 받지 않는다"는 전제다. 사내 모델이 temperature를 받으면 그대로 두어도 동작한다.

**B5. 인증서** — `labelbot/llm.py:44-46`
- 앵커: `labelbot/llm.py` :: `def build_opener(ca_file=None):`
- 코드 수정 없음. `ca_file` 설정에 사내 루트 인증서 경로를 넣는다. `verify=False`는 따르지 않는다.

**B6. 모델을 바꾼 뒤**
- 임베딩 모델이 바뀌면 기존 임베딩은 다시 만든다: `python -m labelbot embed --workspace <작업 폴더>`. 로컬 `work.sqlite`의 `chunk_embeddings`는 모델별로 저장된다.
- 라벨링 캐시는 요청 전체(주소·경로·본문)의 해시라 모델·주소를 바꾸면 자연히 새로 호출된다.

### C. S3 업로드 (Supabase Storage 대체)

지금 업로드는 **슬라이드 미리보기 JPG를 Supabase Storage로 올리는 것**(`push-slides`) 하나다. 사내에서는 이것을 S3로 바꾸고, 원본 `.b64` 보관 업로드를 새로 만든다.

**C1. 새 S3 클라이언트** — 새 파일 `labelbot/s3.py`
- 설정 블록 `s3`를 `labelbot/workspace.py`의 `DEFAULT_CONFIG`에 추가한다. `"supabase": {` 블록이 끝나는 곳 다음, `"render"` 줄(58줄) 앞이다.
  - 앵커: `labelbot/workspace.py` :: `"render": {"browser_path": None, "jpeg_quality": 85, "width_px": 1280, "timeout": 30},`
  - 키: `enabled`(false), `endpoint`, `region`, `path_style`(true), `auth`(`"sigv4"`), `access_key_env`, `secret_key_env`, `session_token_env`, `bucket`, `prefix_originals`(`"originals/"`), `prefix_slides`(`"slides/"`), `sse`, `kms_key_id`, `ca_file`, `timeout`(60).
- `labelbot/s3.py` 내용:
  - `put_object(cfg, key, data, content_type)`: `labelbot.llm.request("PUT", url, headers, data, timeout, ca_file)`로 보낸다.
  - `auth="sigv4"`이면 표준 라이브러리 `hmac`·`hashlib`로 AWS SigV4 서명을 만든다.
    - `Host` 헤더는 포트까지 포함해 실제 보내는 값 그대로 서명한다.
    - 경로는 한 번만 URL 인코딩한다.
    - `x-amz-content-sha256`에 본문 sha256을 넣는다.
    - 시계가 15분 넘게 어긋나면 S3가 거절하므로, 403 응답 본문에 `RequestTimeTooSkewed`가 있으면 사유 코드 `CLOCK_SKEW`를 낸다.
  - `auth="bearer"`(사내 게이트웨이)나 `"presigned"`면 예시 방식대로 헤더·URL을 만든다.
  - 단일 PUT만 쓴다(5GiB 이하). 멀티파트는 만들지 않는다.
  - 키·서명·실제 호스트는 출력하지 않는다.
- 테스트 `tests/test_s3.py`:
  - AWS 문서의 SigV4 예제 값으로 서명 결과가 같은지 확인한다. 테스트 키는 `AKIDEXAMPLE`처럼 문서용 값을 실행 중에 조립한다. `AKIA`로 시작하는 문자열 리터럴은 쓰지 않는다(Code-Engr-bot critical).
  - 127.0.0.1 가짜 서버로 PUT 왕복, 403·SignatureDoesNotMatch·RequestTimeTooSkewed 응답이 각각의 사유 코드로 바뀌는지 확인한다.

**C2. 슬라이드 업로드를 S3로** — `labelbot/slidepush.py`
- 앵커: `labelbot/slidepush.py` :: `class StorageSink(SupabaseSinkBase):`
- 지금:
  - `StorageSink.upload`(19-26줄)가 `/storage/v1/object/<버킷>/<경로>`로 POST한다.
  - `push()`(42-50줄)는 `supabase.storage_enabled`가 거짓이면 아무것도 하지 않는다.
  - `_send()`(83-107줄)는 업로드 후 Supabase 벡터 행에 `slide_image_*` 열을 PATCH한다(`patch_row`).
- 할 일:
  - `S3SlideSink` 클래스를 추가한다. `upload(bucket, path, data)`는 `s3.put_object(cfg, prefix_slides + path, data, "image/jpeg")`를 부르고, `patch_row`는 하지 않는다(사내에는 벡터 DB 행이 아직 없다).
  - `push()`에서 `s3.enabled`가 참이면 이 싱크를 쓰고, 버킷은 `s3.bucket`, 대상 해시는 `host_hash(s3.endpoint)`로 한다(`slide_image_push_log`의 멱등 기록이 그대로 동작한다).
  - `_send()`의 PATCH 단계(98-107줄)는 싱크에 `patch_row`가 없으면 건너뛰고 업로드 성공을 `OK`로 기록한다.
- 앵커: `labelbot/slidepush.py` :: `n = sink.patch_row(r["chunk_id"], row_fields(bucket, r))`
  - JPEG는 `slide_images/<sha256>.b64`에서 읽어 bytes로만 보낸다(`.jpg`로 디스크에 쓰지 않는다).

**C3. 원본 .b64 보관 업로드** — 새 파일 `tools/s3_sync_originals.py`
- 마일스톤은 이미 있다: `M27 ORIGINALS_SYNC`(`labelbot/milestones.py:39`).
- 대상: 각 작업 폴더 `b64/<file_id>.b64`(`labelbot/ingest.py:63-64`) → S3 키 `<prefix_originals><file_id>.b64`. `file_id`는 원본 bytes의 sha256이다.
- 앵커: `labelbot/ingest.py` :: `def b64_path(ws, file_id):`
- 동작:
  - 기록 파일 `workspaces/<작업 폴더>/logs/s3_originals.jsonl`(파일 ID·결과 코드만)로 이미 올린 것을 건너뛴다.
  - `--dry-run`을 기본으로 하고 `--apply`일 때만 올린다.
  - 사내 S3에 DRM이 풀린 사본을 두는 것이므로 **사용자가 보관 승인을 했는지 먼저 묻는다**(SSE 필요 여부 포함).
- 실행 래핑: `tools/rag_eval.py`처럼 `labelbot.trace.run_main("M27", ...)`으로 감싼다.

**C4. 점검** — `labelbot/selfcheck.py:154-184`
- 앵커: `labelbot/selfcheck.py` :: `def _check_supabase(ws, item, out):`
- `_check_s3(ws, item)`을 추가해 `s3.enabled`일 때만 키 환경변수 존재와 버킷 접근(작은 HEAD 요청)을 확인한다. `run()`에서 supabase 점검 옆에 부른다.

**C5. 산출물의 버킷 이름** — `labelbot/export.py:106`
- 앵커: `labelbot/export.py` :: `bucket = ws.config["supabase"].get("storage_bucket")`
- `s3.enabled`면 `s3.bucket`을 쓰도록 바꾼다.

**C6. 명령 설명** — `labelbot/cli.py:31-33`
- 앵커: `labelbot/cli.py` :: `("push-slides", "슬라이드 JPG를 Supabase Storage에 올리고 행에 slide_image_* 기록")`
- 설명을 "슬라이드 JPG를 저장소(S3 또는 Supabase Storage)에 올린다"로 바꾼다. 바꾸면 `tests/contracts`의 CLI 스냅샷이 달라지므로 `CONTRACT_UPDATE=1`로 그 키만 갱신하고, 다른 스냅샷이 바뀌지 않았는지 확인한다.

**C7. 사유 코드** — `labelbot/reason_codes.py`
- 앵커: `labelbot/reason_codes.py` :: `"RESPONSE_SHAPE": _e(`
- 새 코드를 원인·조치·마일스톤(`M10`, `M27`)과 함께 넣는다: `S3_CONFIG_MISSING`, `S3_AUTH_FAILED`(403 SignatureDoesNotMatch/InvalidAccessKeyId), `S3_BUCKET_MISSING`(404 NoSuchBucket), `S3_ACCESS_DENIED`(403 AccessDenied). `CLOCK_SKEW`는 이미 있으면 재사용한다.
- `tests/test_reason_codes.py`의 완결성 검사가 새 코드를 요구하므로 그 테스트로 확인한다.

**C8. 환경 진단** — `config/doctor_targets.example.json`, `workspaces/_site/doctor_targets.json`
- S3 별칭(`s3`)의 host·port를 실제 값으로 넣으면(무시 경로) `python tools/beol_doctor.py --step E02,E03,E04`가 DNS·연결·인증서를 점검한다.

### D. 이번 전환에서 하지 않는 것

- **벡터 DB 적재(`push-vectors`)**: 사내 벡터 DB가 정해지지 않았다(게이트 G-VDB). `supabase.enabled=false`로 두고 임베딩은 로컬 `work.sqlite`에만 저장한다.
- **RAG 답변 화면(`rag/`)과 Edge Function**: 사외 Supabase 전용이다. 사내 답변 서버(ragsrv)는 벡터 DB가 정해진 뒤 별도로 만든다.
- **평가 도구 `tools/rag_eval.py`**: 사외 기준선 캡처용이라 그대로 둔다.
- `docs/`는 고치지 않는다.

---

## 5. 적용 순서와 확인 명령

각 단계가 끝날 때마다 확인 명령을 돌리고, 실패하면 다음 단계로 가지 않는다. 실패 블록(`[Mxx …] 실패 사유=…`)이 나오면 `python -m labelbot status --workspace <작업 폴더>` 출력을 사용자에게 보여 준다.

| 순서 | 할 일 | 확인 |
|---|---|---|
| 1 | §3 추출표를 채워 사용자에게 보여 준다 | 사용자 확인 |
| 2 | A1~A4 설정 | `python -m labelbot selfcheck --workspace <작업 폴더> --probe-llm` → `llm_probe` PASS |
| 3 | B1~B5 중 필요한 것 | `python -m pytest -q tests/test_pipeline.py tests/test_llm_guard.py domain_engrbot/tests/test_judge.py` |
| 4 | 임베딩 확인(B3·B6) | `python -m labelbot embed --workspace <작업 폴더>` → `[M07 EMBED] 완료`, 실패 0 |
| 5 | C1 S3 클라이언트 + 테스트 | `python -m pytest -q tests/test_s3.py` |
| 6 | C2·C4·C5·C6·C7 | `python -m labelbot push-slides --workspace <작업 폴더>` → `[M10 PUSH_SLIDES] 완료`, `python -m pytest -q tests/contracts tests/test_reason_codes.py` |
| 7 | C3 원본 동기화(사용자 승인 후) | `python tools/s3_sync_originals.py --workspace <작업 폴더>`(미리보기) → `--apply` |
| 8 | 전체 테스트 | `python -m pytest -p no:cacheprovider -q` → 실패가 §7 기준선 목록과 같을 것(새 실패 0) |
| 9 | 검수 1회 | `python -m code_engrbot review --root . --paths <바꾼 파일>` → critical 0 |
| 10 | 기록 | §8 표에 한 줄씩 남긴다. **push하지 않는다** |

환경 문제(방화벽·프록시·인증서·pip)가 의심되면 먼저 `python tools/beol_doctor.py`를 돌린다. 실패 블록의 "담당자에게:" 문장을 그대로 보안·인프라 담당에게 전달하면 된다.

---

## 6. 막혔을 때

| 증상 | 사유 코드 | 할 일 |
|---|---|---|
| 연결 전에 차단됨 | `EXTERNAL_BLOCKED` | `BEOL_ALLOWED_HOST_SUFFIXES`에 사내 호스트 접미사를 넣는다 |
| 키 없음 | `KEY_MISSING` | 설정의 `api_key_env`가 가리키는 환경변수를 셸에 넣는다 |
| 401·403 | `HTTP_401`, `HTTP_403` | 키·헤더 이름(B1) 확인 |
| 응답 모양이 다름 | `RESPONSE_SHAPE` | B2·B3 |
| 인증서 오류 | `TLS_CA_UNKNOWN` 등 | `ca_file`(B5), `python tools/beol_doctor.py --step E04` |
| S3 서명 오류 | `S3_AUTH_FAILED`, `CLOCK_SKEW` | 키 환경변수, 시계 동기화, `path_style`·리전 확인 |

`python -m labelbot codes --milestone M07`처럼 마일스톤별 사유 코드 목록과 조치를 볼 수 있다.

---

## 7. 테스트 기준선 (전환 전부터 실패하던 것)

아래 10건은 전환 전부터 실패한다(사외 PC에서도 동일). 이 밖의 실패가 새로 생기면 전환 작업이 깨뜨린 것이다.

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

그 밖에 `domain_engrbot/tests/test_golden_outputs.py`와 `test_judge.py`의 하위 테스트(subtest) 실패 25건도 원래 있던 것이다.

---

## 8. 적용 기록

에이전트는 고친 내용을 한 줄씩 남긴다. 키·실제 호스트는 적지 않는다.

| 날짜 | 항목(§4) | 파일:줄 | 바꾼 내용 요약 | 확인 결과 |
|---|---|---|---|---|
| | | | | |
