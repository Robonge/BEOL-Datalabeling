# inhouse-pc-setup.md — 사내 로컬 PC 설치·실행 절차 (저장만 로컬 시험판)

> 대상: GitHub에서 브랜치 `local-pc-dbsave-local-only`를 ZIP으로 받아 사내 Windows PC에 압축을 푼 사람.
> 이 버전은 **Supabase 없이 모든 데이터를 로컬 폴더(`workspaces/_rag_store`)에 저장**하고, **LLM·임베딩은 OpenAI를 그대로 쓴다.**
> 명령은 모두 사내 PC의 PowerShell에서 실행한다. 바뀐 내용과 시험 기록은 `local-dbsave-only.md`에 있다.

---

## 0. 시작 전에 꼭 알아둘 것

1. **이 버전은 OpenAI(사외 서버)를 부른다.** 라벨링·임베딩·RAG 답변을 만들 때 파싱한 슬라이드 본문이 api.openai.com으로 나간다. 실제 사내 문서로 돌리기 전에 사외 전송이 허용되는지 보안 담당에게 확인한다. 허용되지 않으면 **경로 A**(사외 PC에서 만든 데이터를 반입해 화면만 확인)만 한다. 질문할 때도 질문 문장과 근거 본문이 OpenAI로 간다.
2. **ZIP에는 데이터가 없다.** `.env`(키)와 `workspaces/`(작업 폴더·로컬 저장소)는 git에 올라가지 않아 ZIP에 빠져 있다. 5단계에서 따로 준비한다.
3. **전체 테스트는 사내 PC에서 돌리지 않아도 된다.** 테스트가 저장소 밖 `dummy pptx files` 폴더를 요구해서 사내 PC에서는 실패한다. 사내 PC에서는 3~4단계의 점검 명령으로 확인한다.

---

## 1. 압축 풀 위치 정하기

1. ZIP 파일 이름은 `BEOL-Datalabeling-local-pc-dbsave-local-only.zip`이고, 풀면 같은 이름의 폴더가 하나 생긴다.
2. 짧은 경로에 두는 것을 권장한다. 예: `C:\BEOL\BEOL-Datalabeling-local-pc-dbsave-local-only`
   - OneDrive와 동기화되는 폴더(바탕화면·문서가 동기화되는 경우)는 피한다. 작업 중 sqlite 파일이 잠길 수 있다.
   - 경로에 공백이 있어도 동작은 한다. 다만 명령마다 따옴표가 필요해 번거롭다.
3. 그 폴더에 `labelbot`, `rag`, `taxonomy`, `.env.example`, `local-dbsave-only.md`가 보이면 정상이다.

## 2. PowerShell 열고 Python 확인

1. 탐색기에서 그 폴더를 열고, 주소창에 `powershell`을 입력한 뒤 Enter를 누른다. 그 폴더에서 PowerShell이 열린다. **이후 명령은 모두 이 폴더(저장소 루트)에서 실행한다.**
2. Python 버전을 확인한다.
   ```powershell
   python --version
   ```
   - `Python 3.14.x`가 나오면 아래 명령을 그대로 쓴다.
   - `python`이 없거나 버전이 다르면 다음을 실행한다.
     ```powershell
     py -3.14 --version
     ```
     이게 되면 **이후 모든 `python`을 `py -3.14`로 바꿔** 실행한다.
   - 둘 다 안 되면 Python 3.14를 먼저 설치해야 한다.
3. 설치할 패키지는 없다(표준 라이브러리만 쓴다). `pip install`은 하지 않는다.

## 3. `.env` 만들기 (OpenAI 키)

1. 템플릿을 복사한다.
   ```powershell
   Copy-Item .env.example .env
   ```
2. 메모장으로 연다.
   ```powershell
   notepad .env
   ```
3. `OPENAI_API_KEY=` 뒤에 키를 붙여 넣고 저장한다(따옴표 없이, 한 줄로). 이 파일은 다른 사람에게 보내거나 화면에 띄우지 않는다.
4. **회사망이 프록시를 쓰면** `.env`에 아래 줄을 더 넣는다. 프록시 주소는 IT에 확인한다.
   ```text
   HTTPS_PROXY=http://<프록시주소>:<포트>
   ```
5. **회사망이 HTTPS를 검사해서 인증서 오류가 나면** 사내 루트 인증서(.pem) 경로가 필요하다. 이 값은 5단계에서 설정 파일에 넣는다(`ca_file`).

## 4. OpenAI 연결 확인 (데이터 없이)

임베딩 한 번을 보내 본다. 키 값은 화면에 나오지 않는다.

```powershell
python -c "from labelbot.workspace import DEFAULT_CONFIG as D, load_env_file; load_env_file(); from labelbot.llm import HttpEmbedTransport as T; v=T(D['embedding']).embed(['probe']); print(len(v), len(v[0]))"
```

- `1 1536`이 나오면 성공이다. 5단계로 간다.
- `CallFailed: KEY_MISSING`: `.env`가 저장소 루트에 없거나 키 줄 이름이 다르다.
- `CallFailed: NETWORK_ERROR`: 프록시(3-4)나 인증서(3-5) 문제다. 사외 접속 자체가 막혀 있을 수도 있다.
- `CallFailed: HTTP_401`: 키가 잘못됐다.

---

## 5. 데이터 준비 — 둘 중 하나를 고른다

### 경로 A. 사외 PC에서 만든 저장소를 그대로 가져가기 (가장 빠름, 화면 확인용)

사외 PC에서 이미 만든 로컬 저장소(chunk 184개, 슬라이드 그림 포함, 약 26MB)를 옮기는 방법이다. 라벨링을 다시 하지 않는다.

1. 사외 PC에서 `C:\Users\dltkd\Desktop\local-pc-dbsave-local-only\workspaces\_rag_store` 폴더를 통째로 복사한다. 안에는 `rag_store.sqlite`, `rag_config.json`, `slides\`가 있다.
   - `rag_store.sqlite-wal`·`rag_store.sqlite-shm` 파일이 있으면 같이 복사한다. 사외 PC의 RAG 서버를 끈 상태에서 복사한다.
   - 반입 절차(보안 반입 신청 등)는 회사 규정을 따른다. 이 안에는 더미 자료의 본문과 슬라이드 그림이 들어 있다.
2. 사내 PC에서 저장소 루트 아래에 `workspaces` 폴더를 만들고, 그 안에 붙여 넣는다. 최종 경로는 `<저장소 루트>\workspaces\_rag_store\rag_store.sqlite`이어야 한다.
3. 3-5에서 인증서가 필요했다면 `workspaces\_rag_store\rag_config.json`을 메모장으로 연다. `"llm"`과 `"embedding"` 블록의 `"ca_file": null`을 각각 `"ca_file": "C:/경로/사내루트.pem"`으로 바꾼다(슬래시 `/` 사용).
4. 6단계로 간다.

### 경로 B. 사내 PC에서 사내 파일로 새로 라벨링하기 (0-1의 보안 확인이 끝난 경우만)

1. **입력 폴더를 준비한다.** 라벨링할 pptx 파일들을 한 폴더에 모은다. 예: `C:\BEOL_input\set1`
   - DRM 파일이어도 그대로 두면 된다. 프로그램이 `open(path,"rb")` → base64 방식으로 읽는다.
   - 이 폴더는 저장소 폴더 **밖에** 둔다.
2. **작업 폴더를 만든다.**
   ```powershell
   python .claude\skills\BEOL-labeling\scripts\init_workspace.py --input "C:\BEOL_input\set1"
   ```
   - 출력 JSON의 `"workspace"` 값이 작업 폴더 경로다. 예: `.../workspaces/261004_BEOL_set1_20261012-101500`
   - 이후 `<WS>`는 그 경로다. 따옴표로 감싸 쓴다.
   - `pipeline.json`에는 모델 `gpt-6-sol`, `vector_store` 켜짐이 이미 들어가 있다.
3. **(인증서가 필요하면)** `<WS>\pipeline.json`을 열고 `"llm"`과 `"embedding"` 블록에 `"ca_file": "C:/경로/사내루트.pem"`을 넣는다.
4. **환경을 점검한다.**
   ```powershell
   python -m labelbot selfcheck --workspace "<WS>" --probe-llm
   ```
   `llm_probe`, `llm_key_env`, `vector_store`가 PASS이면 다음으로 간다.
5. **입력 구조를 미리 본다** (본문은 출력하지 않는다).
   ```powershell
   python -m labelbot probe --workspace "<WS>"
   ```
6. **라벨링을 실행한다.** 파일 수에 따라 수 분에서 수십 분 걸리고, OpenAI 호출이 일어난다.
   ```powershell
   python -m labelbot run --workspace "<WS>"
   ```
   - 끝에 실행 ID와 건수가 나온다.
   - 중간에 끊겨도 같은 명령을 다시 실행하면 된다. 이미 끝난 호출은 캐시에서 가져오고 실패한 것만 다시 부른다.
7. **사람 검수를 한다.**
   ```powershell
   python -m labelbot review --workspace "<WS>"
   ```
   ```powershell
   python -m labelbot serve --workspace "<WS>" --port 8770
   ```
   - 브라우저에서 `http://127.0.0.1:8770/`을 열고 검수 화면에서 교정한다.
   - 교정이 끝나면 **검수 완료**를 누른다. 교정 내용은 작업 폴더 `inbox\`에 json으로 저장된다.
   - PowerShell 창에서 `Ctrl+C`를 눌러 화면 서버를 끈다.
8. **교정을 반영한다.**
   ```powershell
   python -m labelbot apply --workspace "<WS>"
   ```
9. **임베딩을 만든다** (OpenAI 호출).
   ```powershell
   python -m labelbot embed --workspace "<WS>"
   ```
   `[embed] ... 실패 0`이면 정상이다.
10. **로컬 저장소에 벡터를 적재한다.**
    ```powershell
    python -m labelbot push-vectors --workspace "<WS>"
    ```
    - `[push-vectors] 호출 1회, 전송 n행, 건너뜀 0, 실패 0`이면 정상이다. 한글이 깨져 보여도 숫자만 맞으면 된다.
    - 처음 실행하면 `workspaces\_rag_store\`가 만들어진다.
11. **슬라이드 그림을 만든다.** Edge 또는 Chrome을 화면 없이(headless) 띄워 캡처한다.
    ```powershell
    python -m labelbot slide-images --workspace "<WS>"
    ```
    - `RENDERER_MISSING`이나 `RENDERER_EXITED`가 나오면 `pipeline.json`의 `render.browser_path`에 Edge 경로를 넣는다. 예: `C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe`
    - 열려 있는 Edge 창을 모두 닫고 다시 해 보는 것도 방법이다.
12. **슬라이드 그림을 로컬 저장소에 넣는다.**
    ```powershell
    python -m labelbot push-slides --workspace "<WS>"
    ```
    `업로드 n, 행 갱신 n, ... 실패 0`이면 정상이다. `ROW_MISSING`이 나오면 10번을 먼저 했는지 확인한다.
13. 입력 폴더가 여러 개면 2~12를 폴더마다 반복한다. 같은 저장소에 쌓이고, 같은 chunk는 나중 것이 이긴다.

---

## 6. RAG 화면 띄우기

1. 저장소 루트에서 실행한다.
   ```powershell
   python -m labelbot.ragsrv --port 8795 --bind 127.0.0.1 --directory rag
   ```
   - `[ragsrv] 127.0.0.1:8795 제공(모델 gpt-6-sol)`이 나오면 서버가 뜬 것이다. **이 창은 닫지 말고 둔다.**
   - `rag_config.json 없음`: 5단계(경로 A의 복사 또는 경로 B의 10번)를 하지 않았다.
   - `OPENAI_API_KEY 없음`: 3단계의 `.env`를 확인한다.
   - 8795를 다른 프로그램이 쓰고 있으면 `--port 8796`처럼 바꾼다. Windows는 같은 포트를 두 프로그램이 동시에 열 수 있어서, 예전 서버가 떠 있으면 엉뚱한 화면이 나올 수 있다.
2. 브라우저 주소창에 **`http://127.0.0.1:8795/beol_rag.html`**을 입력한다. `localhost`도 된다. PC 이름이나 IP로 들어가면 403이 난다.
3. 첫 화면 영상에서 **건너뛰기**를 누른다.
4. 아래 순서로 확인한다.
   - [ ] 오른쪽 위 `SLIDES` 숫자가 나온다. 경로 A면 184다.
   - [ ] 위쪽 필터 메뉴(공정 모듈, 구조/레이어, …)를 열면 값 목록이 보인다.
   - [ ] 질문 하나(예: `M2 RSBM TaN ALD cycle window 평가 결과 어때?`)를 보내면 20~40초 뒤 답변·인용 번호·근거 카드가 나온다.
   - [ ] 근거 카드에 슬라이드 그림이 보인다.
   - [ ] 후속 질문(예: `그중 100cy 조건의 문제 원인은 뭐야?`)을 보내면 답변 위에 "검색한 질문: …"이 보인다. 앞 대화를 반영해 질문을 고쳐 쓴 것이다.
   - [ ] **도움이 됐어요**를 누르면 "고마워요, 기록했어요"가 나온다(로컬 저장소에 저장됨).
5. 서버 창에는 요청마다 `[ragsrv] /api/ask OK 20348 k=5 n=13` 같은 한 줄만 찍힌다. 질문·답 내용은 로그에 남지 않는다.
6. 다 쓰면 서버 창에서 `Ctrl+C`를 누른다. 다시 쓸 때는 6-1부터 하면 된다(적재는 다시 하지 않아도 된다).

---

## 7. 막혔을 때

| 증상 | 원인·조치 |
|---|---|
| `python`이 없다고 나옴 | `py -3.14`로 바꿔 실행 (2단계) |
| `KEY_MISSING` | `.env`가 저장소 루트에 있는지, 줄이 `OPENAI_API_KEY=...` 형식인지 확인 |
| `NETWORK_ERROR`, `TIMEOUT` | 프록시(`HTTPS_PROXY`), 인증서(`ca_file`) 확인. 사외 접속이 막혔을 수 있음 |
| `HTTP_401` / `HTTP_429` | 키 오류 / 호출 한도 초과(`pipeline.json`의 `llm.workers`를 2~3으로 줄임) |
| 화면이 403 | 주소가 `127.0.0.1` 또는 `localhost`인지 확인 |
| SLIDES 숫자가 안 나오거나 0 | `push-vectors`를 했는지 확인. 경로 A면 `_rag_store` 위치(5-A-2) 확인 |
| 그림이 "그림 없음" | `slide-images` → `push-slides`를 했는지 확인 |
| 답변 대신 `LLM_FAILED` / `EMBED_FAILED` | OpenAI 연결 문제. 4단계 명령으로 다시 확인 |
| `push-vectors`가 `차단 RULES_CHANGE_RATIO_HIGH` | 규칙 변경 비율이 큼. 현황판을 확인한 뒤에만 `--force`를 붙임 |
| 한글 출력이 깨짐 | 표시 문제일 뿐 동작은 정상. 신경 쓰이면 PowerShell에서 `$env:PYTHONIOENCODING="utf-8"`을 먼저 실행 |

---

경로 A와 B는 섞어도 된다. A로 화면을 먼저 확인하고 나중에 B로 사내 자료를 추가하면 같은 저장소에 쌓인다.
