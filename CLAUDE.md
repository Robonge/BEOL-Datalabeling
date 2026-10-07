# CLAUDE.md — BEOL AX governing rule

모든 작업(코드, 파일 분석, 서브 에이전트, 스킬)에 우선 적용한다. `PRD.md`·`plan.md`와 충돌하면 이 파일을 따르고 사용자에게 알린다.

## DRM 규칙: 사내 파일은 경로로 파싱하지 않고 base64를 거친다

사내 파일(pptx, docx, xlsx, csv, txt, ppt/doc/xls, pdf, hwp, 이미지)은 모두 DRM이 걸려 있어, 경로를 받는 파서로는 열 수 없다. 업무 PC에서 Python `open(path, "rb")`로 읽으면 DRM이 풀린 bytes가 나온다. 이 bytes를 base64로 보관하고, 이후 작업은 모두 메모리에서 한다.

```
open(path,"rb") → b64encode → <sha256>.b64 저장 → b64decode → io.BytesIO/StringIO → 파싱·chunk·임베딩
```

- **원본 경로를 여는 코드는 ingest 한 곳뿐**이다. 나머지 단계는 `.b64`만 읽는다. dummy 파일은 평문이지만 같은 경로로 처리한다.
- **경로 기반 파서는 쓰지 않는다**: `Presentation(path)`, `load_workbook(path)`, `pd.read_*(path)`, `csv.reader(open(path))`, `zipfile.ZipFile(path)`, `pptx`·`xlsx`·`docx`·`pdf` 스킬, 사내 파일을 Read 도구로 직접 열기.
- **구현은 표준 라이브러리만 쓰고 Python 3.14.2 기준으로 작성한다**(사외 구동 기준. 사외 PoC SDK는 `requirements-poc.txt`에만 두고 본체는 import하지 않는다): OOXML은 `zipfile.ZipFile(io.BytesIO(b))`와 `xml.etree`로 읽는다. CSV는 `utf-8-sig`로 먼저 읽고, 실패하면 `cp949`로 읽는다. 파서가 없는 형식(OLE, PDF, HWP)은 실패 목록에 넣는다.
- **임베딩·LLM에는 파싱한 텍스트를 넣는다**: base64 문자열을 그대로 넣지 않는다. 이미지를 비전 모델에 보내는 data URL만 예외다.
- **DRM 해제 여부는 디코딩 직후 시그니처로 확인한다**: 확장자와 맞지 않으면 사유 코드와 함께 실패 처리하고 다음 파일로 넘어간다. OOXML은 `PK\x03\x04`이고, OOXML인데 `D0 CF 11 E0`이면 암호가 걸린 파일이다.

## 쓰기 규칙

- 디코딩한 bytes와 추출 결과는 office·텍스트 확장자(`.pptx .xlsx .docx .csv .txt .pdf .hwp` 등)로 쓰지 않는다. 쓰면 DRM이 다시 걸린다.
- 허용 형식은 `.b64`(원본과 이미지), `.sqlite`, `.json`, `.jsonl`, `.html`, `.md`, `.log`다. 표·이력 데이터는 `.jsonl`로 쓴다(예: `synonyms_log.jsonl`).
- 로그에는 파일 ID와 사유 코드만 남긴다. base64, 본문, 파일명은 넣지 않는다.


## 임시 지침: 코드 검수 간소화 (2026-10-08~, 사용자가 해제할 때까지)

taxonomy, Domain-Engr-bot(`domain_engrbot/`), labeling(`labelbot/`·`taxonomy/`·`.claude/skills/BEOL-*`) 관련 수정을 하는 모든 세션은 Code-Engr-bot 검수를 **최대한 간략히** 한다.

- 검수는 작업을 끝낼 때 **한 번만** 돌린다: `python -m code_engrbot review --root . --paths <이번에 바꾼 파일>`. 수정 중간마다, 사소한 고침마다 다시 돌리지 않는다.
- critical만 고친다. major·minor는 한 줄로 보고하고 고치지 않는다(사용자가 시킬 때만 고친다). 고친 뒤 재검수는 critical이 있었을 때 한 번만 한다.
- architect·code-reviewer·security-reviewer 같은 별도 검토 에이전트를 이 목적으로 따로 띄우지 않는다. 검수 결과 보고도 판정 · 건수 · critical 한 줄씩만 쓴다.
- 이 지침은 속도를 위한 임시 완화다. 루트 CLAUDE.md의 DRM · 쓰기 규칙과 사내 반입 관련 검사는 줄이지 않는다.
