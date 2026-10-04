---
name: labeling-codebot
description: 저장소 코드와 workflow가 프로젝트 규칙(루트 CLAUDE.md), 기술 stack, 단계 사이 계약을 지키는지 code review 형태로 검수한다. 읽기 전용이며 코드를 고치지 않는다. codebot review를 돌려 review ID·판정·건수를 전하고, review.md의 critical·major 이슈를 path:line, 규칙 ID, 수정 제안으로 요약한다. 사용자가 "코드 검수", "codebot 돌려줘", "workflow 검수", "코드 리뷰 봇"이라고 하거나 /labeling-codebot을 부르면 이 스킬을 쓴다. 라벨의 도메인 검수는 labeling-Engr-bot, 라벨링 실행은 BEOL-labeling, 사람 검수 반영과 적재는 BEOL-labeling-feedback이 맡는다.
---

# labeling-codebot: 코드 검수

저장소 코드와 workflow를 정적 분석으로 검수한다. 소스를 import하거나 실행하지 않고 텍스트와 AST로만 읽는다. 결과는 `codebot/out/<review ID>/`에 쓴다. 라벨 내용의 도메인 검수는 하지 않는다(labeling-Engr-bot).

```
review 실행 → review ID·판정·건수 전달 → review.md 읽고 critical·major 요약 → (사용자가 요청하면) 수정
```

## 고정 값

- 코드 폴더: `C:\Users\dltkd\Desktop\261004 BEOL AX day2`. 모든 명령은 여기서 `PYTHONIOENCODING=utf-8`을 붙여 실행한다.
- 출력: `codebot/out/<review ID>/findings.jsonl`, `review.md`, `manifest.json`.
- 기본 검사 대상: `labelbot`, `engrbot`, `codebot`, `tests`, `.claude/skills`.

## 규칙 층

| 층 | 보는 것 |
|---|---|
| C1 프로젝트 규칙 | 루트 `CLAUDE.md`의 DRM 규칙과 쓰기 규칙(경로 기반 파서, 표준 라이브러리 밖 import, 금지 확장자 쓰기, ingest 밖의 원본 열기) |
| C2 stack | Python 3.14 문법, 사외 전송 안전장치(transport 모듈 밖 직접 호출), 비밀값 리터럴, `requirements.txt` |
| C3 workflow 계약 | skill·README에 적힌 명령이 CLI에 있는지, engrbot의 labelbot import 경계, 단계 사이 표·열 계약 |
| C4 완료 위생 | 테스트 skip, TODO·FIXME와 빈 함수 |

규칙 ID와 severity 전체는 카탈로그 명령으로 본다.

```bash
python -m codebot rules
```

## 판정과 종료 코드

| 조건 | 판정 | 종료 코드 |
|---|---|---|
| critical이 1건 이상 | `REQUEST_CHANGES` | 1 |
| major가 1건 이상 | `COMMENT` | 0 |
| 그 밖 | `APPROVE` | 0 |

억제된(`suppressed`) finding은 판정에서 제외하고 리포트에 건수만 낸다. 종료 코드 1은 오류가 아니라 critical이 있다는 신호다.

## 지켜야 할 것

- 읽기 전용이다. 사용자가 고치라고 하기 전에는 소스를 고치지 않는다.
- 이 봇은 소스를 import·실행하지 않는다. 그 방식은 바꾸지 않는다.
- 사내 파일을 Read 도구로 열지 않는다(루트 `CLAUDE.md`). 코드 검수에는 필요 없다.
- 오탐은 코드를 억지로 바꾸지 않고 해당 줄에 주석으로 누른다. 사유를 반드시 적는다.
  ```python
  data = open(path, "rb").read()  # codebot: allow C1_OPEN_OUTSIDE_INGEST <사유>
  ```
  저장소 단위 허용은 `codebot/defaults/policy.json`의 `allow`(`rule`, `path`, `reason`)에 둔다. 억제는 사람이 정한다. 사용자 요청 없이 주석을 달지 않는다.
- LLM 코드 리뷰, 실행 흔적 연결(C5, C6)은 아직 없다. 있는 것처럼 쓰지 않는다.

## 절차

### 1. 실행

```bash
python -m codebot review --root .
```

- 일부만 볼 때: `--paths <경로> [<경로> …]`
- 층을 고를 때: `--layers C1,C2,C3,C4`
- 출력 위치나 정책을 바꿀 때: `--out <폴더>`, `--policy <파일>`

### 2. 콘솔 결과 전달

콘솔에 나오는 review ID, 판정, severity별 건수(critical, major, minor, info)를 그대로 전한다.

### 3. review.md 요약

`codebot/out/<review ID>/review.md`를 읽고 critical, major 순으로 요약한다. 항목마다 아래를 적는다.

- `path:line`
- 규칙 ID
- 수정 제안

minor와 info는 건수만 전한다. 억제된 건수는 있으면 한 줄로 전한다. 위반처럼 보이지만 오탐으로 의심되는 항목은 "오탐 의심"이라고 표시하고 사유를 한 줄로 적는다.

### 4. 수정

사용자가 고치라고 할 때만 수정에 들어간다. 고친 뒤 같은 명령으로 다시 돌려 해당 finding이 사라졌는지 확인한다.

## 이 스킬이 하지 않는 일

- 라벨 도메인 검수: labeling-Engr-bot
- 라벨링 실행: BEOL-labeling
- 사람 검수 반영과 Supabase 적재: BEOL-labeling-feedback
- LLM 코드 리뷰, 실행 흔적 연결, `eval`
