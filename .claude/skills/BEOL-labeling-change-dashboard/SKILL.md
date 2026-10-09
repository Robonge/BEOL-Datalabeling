---
name: BEOL-labeling-change-dashboard
description: 이 저장소에서 일한 Claude 세션들(BEOL-labeling, Domain-Engr-bot, Code-Engr-bot, 리팩토링 fork 등)이 정해진 기간(기본 3시간) 동안 무엇을 바꿨는지 초보자도 이해할 수 있게 정리하고, docs/project_intro.html의 S4 팀 지도·S5 workflow 위에 표시하는 변경 대시보드(change-dashboard/index.html)를 만든다. S4 노드를 누르면 그 bot·skill의 변경이 나온다. 사용자가 "변경 대시보드", "change dashboard 갱신", "세션별 변경 정리", "3시간 동안 뭐 바뀌었어", "대시보드 다시 만들어줘"라고 하거나 /BEOL-labeling-change-dashboard를 부르면, 또는 3시간 주기 예약 작업이 돌면 이 스킬을 쓴다.
---

# BEOL-labeling-change-dashboard: 세션 변경 대시보드

> 그룹: ③ 화면 · 발표 · 운영 리포트 · 상위: 없음 · 하위: 없음 · 전체 지도: README.md "스킬 지도"

세션별로 일정 기간 동안 바뀐 것을 한 화면에 모은다. 사실 수집과 화면 생성은 스크립트가 하고, 초보자용 설명은 Claude가 쓴다.

```
collect.py로 사실 수집 → facts 읽고 summary.json 작성 → render.py로 HTML 생성 → 화면 확인 → 사용자에게 한두 줄 보고
```

## 고정 값

- 저장소: 저장소 루트(`git rev-parse --show-toplevel`, 이 SKILL.md 기준 ../../..). 모든 명령은 저장소 루트에서 `PYTHONIOENCODING=utf-8`을 붙여 실행한다.
- 스크립트: `change-dashboard/collect.py`, `change-dashboard/render.py`. 둘 다 표준 라이브러리만 쓴다. 세부 설명은 `change-dashboard/README.md`에 있다.
- 출력:
  - `change-dashboard/data/<stamp>_facts.json`: 수집 사실
  - `change-dashboard/data/<stamp>_summary.json`: 초보자용 설명
  - `change-dashboard/reports/<stamp>.html`: 회차별 사본
  - `change-dashboard/index.html`: 최신본
  - 출력은 모두 `.gitignore` 대상이라 커밋하지 않는다.
- 디자인: 루트 `design.md.md`. S4 그림과 S5 단계 데이터는 렌더할 때마다 `docs/project_intro.html`에서 원문 그대로 가져온다. 그래서 소개서가 바뀌면 대시보드도 따라 바뀐다.

## 절차

### 1. 사실 수집

```bash
PYTHONIOENCODING=utf-8 python change-dashboard/collect.py --hours 3
```

- 기간을 바꿀 때는 `--hours N`, 또는 `--since <ISO> --until <ISO>`를 쓴다.
- 콘솔에 찍힌 `<stamp>`(예: `20261005-1537`)를 기억한다.
- 수집 대상은 두 가지다.
  - **세션 기록**: `~/.claude/projects/<repo>/`의 transcript와 subagent 기록에서 파일 편집, 사용자 요청, 셸 명령 수를 모은다. fork 세션은 원본에서 복사된 구간을 빼고 새로 한 일만 남긴다.
  - **커밋**: 기간 안 커밋이 바꾼 파일을 `git 커밋`으로 따로 모은다. 셸 스크립트로 고쳐 편집 기록에 안 잡힌 변경을 보완하려는 것이다. 입력 데이터 폴더는 뺀다.

### 2. 설명 쓰기

`data/<stamp>_facts.json`을 읽는다. 세션별 요청(`prompts`), 바뀐 파일(`files`), `git.commits`를 본다. 커밋 본문이 필요하면 `git log --since=<since> --pretty=format:"%h %s%n%b"`로 읽는다. 그다음 `data/<stamp>_summary.json`을 Write 도구로 쓴다.

```json
{"headline": "이번 기간 핵심 2~3문장",
 "sessions": {"<facts의 세션 제목 그대로>": {
    "plain": "이 세션이 한 일을 초보자에게 2~3문장으로",
    "changes": [{"title": "짧은 제목", "role": "<S4 역할>", "stage": "<S5 단계 또는 null>", "why": "무엇을 왜 바꿨는지 1~2문장"}]}},
 "glossary": [{"term": "용어", "meaning": "쉬운 풀이"}]}
```

- `role`은 다음 중 하나다: `Orchestrator`, `BEOL-labeling`, `검수 엔지니어`, `BEOL-labeling-feedback`, `workspace`, `Domain-Engr-bot`, `Code-Engr-bot`. 지난 회차 기록의 옛 이름(`Engr-bot`, `code-bot`)은 `render.py`가 읽을 때 새 이름으로 바꾼다.
- `stage`는 다음 중 하나이거나 `null`이다: `수집 · 파싱`, `1차 분류`, `2차 검증 질문`, `3차 라벨링`, `불량 목록`, `1차 검수`, `교정 반영`, `임베딩 · 적재`, `Domain-Engr-bot`, `Code-Engr-bot`. 가운뎃점 앞뒤 공백까지 그대로 쓴다.
- 세션 제목은 facts의 `title`과 글자 그대로 같아야 화면에 붙는다.
- 문체는 쉬운 말과 `-다` 평서문이다. 전문 용어는 처음 나올 때 풀어 쓰고 `glossary`에 넣는다.
- 이번 기간에 새 활동이 없는 세션은 "지난 회차에 소개한 작업이다"라고 짧게 적는다.
- 쓰지 않는 것: 사내 문서 본문, 인용문, 사내 파일명, 비밀값. 경로·커밋 ID·건수·요지만 쓴다.
- 한글이 들어간 JSON이나 코드는 셸 heredoc으로 쓰지 않고 Write·Edit 도구로 쓴다. Windows 콘솔 인코딩 때문에 깨질 수 있다.

### 3. HTML 생성

```bash
PYTHONIOENCODING=utf-8 python change-dashboard/render.py
```

- 지난 회차를 다시 그릴 때는 `--stamp <stamp>`를 쓴다.
- summary가 없어도 사실만으로 그린다. 이때 설명 칸에는 "아직 작성되지 않았습니다"가 나온다.

### 4. 화면 확인

`change-dashboard/index.html`을 Browser pane으로 연다(`preview_start`에 `file:///` URL). 아래를 확인한다.

- 콘솔 오류가 없다.
- 가로 넘침이 없다. `scrollWidth`와 `clientWidth`가 같아야 한다.
- S4 노드에 변경 배지가 붙고, 노드를 클릭하면 `#detail`에 그 노드의 변경이 나온다.
- 마지막 "전체 작업공간 workflow" 섹션의 단계를 누르면 입력·처리·출력과 이번 기간 변경이 나온다.

### 5. 보고

사용자에게 한두 줄로 알린다. 이번 회차의 핵심 변화와 파일 위치(`change-dashboard/index.html`, `reports/<stamp>.html`)를 적는다. 스크립트를 고쳤으면 `change-dashboard/` 아래 스크립트만 커밋한다.

## 3시간 주기 예약

사용자가 주기 갱신을 원하면 세션 cron으로 이 스킬을 부른다. 예: `17 */3 * * *`, 프롬프트 `/BEOL-labeling-change-dashboard`. 세션 cron은 세션이 열려 있는 동안만 돌고 7일 뒤 만료된다. 사용자에게 이 점을 알린다.

## 지켜야 할 것

- 루트 `CLAUDE.md`를 따른다. 사내 파일(pptx 등)은 열지 않는다. 이 스킬은 transcript와 git 출력만 읽고 `.json`, `.html`, `.md`만 쓴다.
- 대시보드를 만드는 동안 labelbot·domain_engrbot·code_engrbot 코드와 skill 절차는 고치지 않는다.
- S4 그림을 손으로 다시 그리지 않는다. 표시를 바꿀 때는 `render.py`의 덧씌우기(배지, 클릭 상세)만 고친다.

## 이 스킬이 하지 않는 일

- 코드 검수: BEOL-labeling-Code-Engr-bot
- 도메인 질문(검수 결과 → 엔지니어 답 → 규칙·taxonomy 제안): BEOL-labeling-Domain-Engr-bot
- 워크플로 소개 HTML(`docs/workflow.html`) 생성: BEOL-labeling-workflow
- 라벨링 실행, 검수 반영과 적재: BEOL-labeling, BEOL-labeling-feedback

## 관계

- 코드 검수는 BEOL-labeling-Code-Engr-bot, 워크플로 소개 HTML은 BEOL-labeling-workflow가 맡는다.
