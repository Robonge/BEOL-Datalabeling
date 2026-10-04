---
name: BEOL-labeling-workflow
description: BEOL 라벨링 워크플로(입력 → 준비·수집·파싱 → 1~3차 분류·검증 질문·라벨링 → 불량 목록 → 사람 검수 → 피드백 반영 → 임베딩·Supabase 적재)를 단계별 산출물·예시 화면이 있는 HTML 한 장(docs/workflow.html)으로 다시 만든다. 최신 실행의 건수·알림·답 분포를 채워 넣는다. 사용자가 "워크플로 HTML 다시 만들어줘", "workflow 시각화", "workflow.html 갱신", "단계별 화면 정리", "BEOL 워크플로 보여줘"라고 하거나 /BEOL-labeling-workflow를 부르면 이 스킬을 쓴다. 파싱·라벨링 실행은 BEOL-labeling, 사람 검수 진행과 반영·적재는 BEOL-labeling-feedback이 맡는다.
---

# BEOL-labeling-workflow: 워크플로 HTML 다시 만들기

`docs/workflow.html`을 만든다. 화면 구조(11단계, 스킬 범위 구역, 예시 화면, 인터랙션)는 템플릿 `assets/workflow_template.html`에 있고, 실제 수치는 `scripts/build_workflow.py`가 최신 실행에서 채운다. LLM 호출은 0회다.

```
[BEOL-labeling]          1 준비(타임스탬프 작업 폴더)·중복 확인·수집·파싱 → 2 1차 분류 → 3 2차 질문 매핑·검증 질문 생성 → 4 3차 라벨링 → 5 분포 알림·불량 목록·후보·처리 완료 목록 → 6 화면 3개 생성·대시보드 띄우기
[BEOL-labeling-feedback] (H2 대조 여부 질문 · 검수 화면 띄우기)
                         7 H6 불량 chunk 검수(사람, 슬라이드 근사 미리보기·재검토 요청, 검수 완료 버튼) → 8 H2 파싱 대조(사람, 선택)
                         → 9 교정 모으기·반영 → 10 화면·리포트 재생성 → 11 임베딩·Supabase 적재
```
사람 작업(7·8)은 따로 구역을 두지 않고 feedback 구역 안의 사람 단계(`who:"human"`)로 표시한다. feedback 스킬이 화면을 띄우고 검수 완료 신호를 기다리기 때문이다.

## 고정 값

- 코드 폴더: `C:\Users\dltkd\Desktop\261004 BEOL AX day2`. 명령은 여기서 `PYTHONIOENCODING=utf-8`을 붙여 실행한다.
- 출력: `docs/workflow.html`(덮어쓴다). 사용자가 다른 경로를 말하면 `--out`.
- 작업 폴더: 인자로 받는다. 없으면 이 대화에서 `/BEOL-labeling`이 쓴 작업 폴더, 그것도 없으면 스크립트가 `workspaces/261004_BEOL_*`(실행마다 `_YYYYMMDD-HHMMSS`가 붙은 새 폴더) 중 `work.sqlite`가 가장 최근에 바뀐 폴더를 고른다.
- 중복 확인 기준: 코드 폴더의 `injested-file-list/*.json`(BEOL-labeling이 실행 후 기록). HTML에는 목록 파일 수와 건너뛴 건수(`skip_file_names` 개수)만 넣고 파일명은 넣지 않는다.
- 디자인: 저장소의 `design.md.md`(BEOL AX 디자인 시스템)를 따른다. `#EDF1F7` 바탕과 48px 그리드, 인디고 그라디언트(148°), 음수 자간, 굵기 400/700, 외부 CDN 없음.

## 지켜야 할 것과 이유

- HTML에는 건수·실행 ID·사유 코드·답 분포만 넣는다. chunk 본문, 파일명, 경로, 재검토 메모는 넣지 않는다. 예시 화면의 문구는 합성 예시로 두고 화면에 그렇게 표시한다. 사내 반입 뒤에도 그대로 공유할 수 있어야 하기 때문이다.
- `work.sqlite`는 읽기 전용으로만 연다. 원본 파일과 `.b64`는 열지 않는다(`CLAUDE.md`).
- 템플릿을 고칠 때는 `/*__LIVE__*/null` 자리 표시자를 하나만 남기고, 외부 리소스(`<script src>`, `<link>`, CDN)를 넣지 않는다.

## 절차

### 1. 생성

```bash
python ".claude/skills/BEOL-labeling-workflow/scripts/build_workflow.py" [--workspace "<WS>"] [--run <RUN>]
```
출력 JSON의 `out`, `workspace`, `run_id`, `fields`를 본다. `run_id`가 null이면 실행 기록이 없는 것이라 수치 칸이 "—"로 나온다고 알린다. `error`가 나오면 멈추고 보고한다.

### 2. 워크플로가 바뀌었을 때만: 템플릿 고치기

단계가 추가·변경됐으면(새 스킬 단계, 새 산출물, 새 사람 개입 지점) `assets/workflow_template.html`의 `STEPS` 배열과 해당 mock 함수를 고친 뒤 1단계를 다시 돌린다. 각 단계는 `{z, t, cmd, llm, who, lead, pts, out, mock, bind?}`이고 `z`는 구역(A=BEOL-labeling, B=BEOL-labeling-feedback)이고, 사람이 하는 단계는 `who:"human"`으로 표시한다. 새 수치가 필요하면 `build_workflow.py`의 `live_data`에 건수 쿼리를 더하고 템플릿에서 `LIVE.<키>`로 읽는다(값이 없으면 `V()`가 "—"로 표시).

### 3. 확인

브라우저 패널에서 `file:///<코드 폴더>/docs/workflow.html`을 열고 확인한다.
- `javascript_tool`로 단계 수(`.item`, 11), 구역 수(`.zone`, 2), 각 단계 클릭 시 `#mockroot` 렌더링, 콘솔 오류 0을 본다.
- 모바일 폭(375px)에서 가로 스크롤이 없는지 본다(`document.documentElement.scrollWidth <= innerWidth`). 끝나면 뷰포트를 desktop으로 되돌린다.

### 4. 보고

생성 경로(링크), 기준 실행 ID와 작업 폴더, 채운 주요 수치(파일·chunk·검증 질문·불량·알림), 확인 결과를 짧게 쓴다. 팀에 공유할 것 같으면 Artifact로 게시할 수 있다고 한 줄로 제안한다(파일 자체는 사내 반입용으로 그대로 둔다).
