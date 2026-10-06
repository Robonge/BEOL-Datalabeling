# change-dashboard: 세션 변경 대시보드

이 저장소에서 일한 Claude 세션들(BEOL-Labeling & Feedback, Domain-Engr-bot, 리팩토링 세션 등)이 일정 기간 동안 무엇을 바꿨는지 한 화면에 모아 보여 준다. 기본 주기는 3시간이다.

- **초보자용 설명**: 세션마다 무엇을 했고 왜 했는지 쉬운 말로 적는다.
- **S4·S5 관점**: 바뀐 파일을 `docs/project_intro.html`의 S4 팀 지도(역할)와 S5 workflow 단계 위에 표시한다.
  - S4 그림은 소개서의 SVG·CSS를 렌더할 때마다 원문 그대로 가져와 변경 배지와 세션 점만 덧씌운다. bot·skill·작업대·엔지니어 노드를 누르면 그 대상의 변경 설명·파일·요청이 상세 칸에 나온다.
  - 마지막 섹션 "전체 작업공간 workflow"는 S5의 단계 데이터(`ST`)와 CSS를 그대로 써서 단계 줄과 입력·처리·출력을 보여 주고, 단계마다 이번 기간 변경을 붙인다.
- **디자인**: 루트 `design.md.md`(BEOL AX 토큰, `#EDF1F7` 바탕과 48px 그리드, 인디고 그라디언트, 음수 자간, 400/700 굵기)를 따른다.

## 파일

| 경로 | 내용 |
|---|---|
| `collect.py` | 세션 transcript(`~/.claude/projects/<repo>/`)를 읽어 기간 안의 파일 편집·사용자 요청을 모으고, 파일마다 S4 역할과 S5 단계를 붙인다. → `data/<stamp>_facts.json` |
| `data/<stamp>_summary.json` | 초보자용 설명. Claude(또는 사람)가 facts를 보고 쓴다. 없으면 사실만으로 그린다 |
| `render.py` | facts와 summary를 합쳐 `reports/<stamp>.html`과 최신본 `index.html`을 만든다 |
| `index.html` | 가장 최근 대시보드. 지난 회차로 가는 링크가 있다 |

## 실행

```bash
PYTHONIOENCODING=utf-8 python change-dashboard/collect.py --hours 3
PYTHONIOENCODING=utf-8 python change-dashboard/render.py
```

`collect.py`가 찍는 stamp와 같은 이름으로 `data/<stamp>_summary.json`을 쓴 뒤 `render.py`를 돌린다.

summary 형식:

```json
{"headline": "...",
 "sessions": {"<세션 제목>": {"plain": "...", "changes": [{"title": "...", "role": "<S4 역할>", "stage": "<S5 단계 또는 null>", "why": "..."}]}},
 "glossary": [{"term": "...", "meaning": "..."}]}
```

## 커밋하지 않는 것

`data/`, `reports/`, `index.html`은 생성물이고 세션 요청 원문이 들어 있어 `.gitignore`로 뺀다. 스크립트와 이 문서만 커밋한다.

## 규칙

- 표준 라이브러리만 쓴다. 쓰기 형식은 `.json`, `.html`, `.md`뿐이다(루트 CLAUDE.md).
- 사내 파일은 열지 않는다. transcript와 git 출력만 읽는다.
- 화면에는 파일 경로, 시각, 요청 요지만 싣는다. 사내 문서 본문은 싣지 않는다.
- 파일 → 역할·단계 대응표는 `collect.py`의 `LABELBOT_STAGE`, `SKILL_ROLE`, `classify_path`에 있다.
