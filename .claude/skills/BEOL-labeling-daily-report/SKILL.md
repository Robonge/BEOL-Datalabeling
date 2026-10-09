---
name: BEOL-labeling-daily-report
description: 밤사이 Code-Engr-bot·Domain-Engr-bot 자동 실행(nightly_run.py)이 남긴 아침 대응 목록을 사람이 보는 daily report HTML(workspaces/_nightly/daily_report.html)로 만들어 띄운다. 할 일 카드(심각도 순, 명령 복사, 완료 체크), 핵심 건수 타일(어제 대비), 최근 7일 추이 차트, 밤 실행 단계 상태 한 줄을 project_intro.html 디자인으로 그린다. 오늘 nightly 결과가 없으면 두 봇을 먼저 한 번 돌린다. 사용자가 "daily report", "데일리 리포트", "아침 리포트", "오늘 할 일 보여줘", "밤사이 결과", "nightly 결과 정리", "아침 대응 목록"이라고 하거나 /BEOL-labeling-daily-report를 부르면 이 스킬을 쓴다.
---

# BEOL-labeling-daily-report: 아침 대응 목록 리포트

> 그룹: ③ 화면 · 발표 · 운영 리포트 · 상위: 없음 · 하위: 없음 · 전체 지도: README.md "스킬 지도"

밤 자동 실행 결과를 HTML 한 장으로 보여 준다. 수집과 렌더는 스크립트가 하고, Claude는 실행하고 요약만 전한다.

```
(필요하면) nightly_run.py로 두 봇 실행 → daily_report.py로 HTML 생성 → 화면 열기 → 할 일 요약 보고
```

## 고정 값

- 저장소: 저장소 루트(`git rev-parse --show-toplevel`, 이 SKILL.md 기준 ../../..). 모든 명령은 저장소 루트에서 `PYTHONIOENCODING=utf-8`을 붙여 실행한다.
- 스크립트:
  - `nightly_run.py`: 두 봇을 돌리고 아침 목록을 남긴다. 예약(작업 스케줄러)은 사용자가 따로 건다.
  - `daily_report.py`: 목록을 HTML로 만든다.
  - 둘 다 표준 라이브러리만 쓴다.
- 입력: `workspaces/_nightly/<YYYYMMDD>/morning_queue.jsonl`, `steps.jsonl`. 날짜 폴더가 없는 날은 추이에 `–`로 표시한다.
- 출력:
  - `workspaces/_nightly/<YYYYMMDD>/daily_report.html`: 날짜별 사본
  - `workspaces/_nightly/daily_report.html`: 최신본
  - `workspaces/`는 커밋 대상이 아니다.
- 디자인: `docs/project_intro.html`과 루트 `design.md.md`의 토큰·컴포넌트를 그대로 쓴다.
  - 쓰는 것: 격자 배경, eyebrow, 그라디언트 강조 제목, tile, pn, badge, 탄성 곡선.
  - 외부 CDN·폰트를 쓰지 않는다.
  - 화면을 고칠 때는 `daily_report.py`의 `PAGE` 템플릿을 고치고, 새 색을 만들지 않는다.

## 절차

1. 리포트를 만든다.
   ```
   python daily_report.py
   ```
   - 오늘 결과가 없으면 nightly_run을 먼저 돈다. 두 봇이 돌고 질문 생성에서 LLM을 부르며, 1분 남짓 걸린다.
   - 사용자가 "다시 돌려서", "최신으로"라고 하면 `--run`을 붙인다.
   - 추이 기간을 바꾸려면 `--days N`을 붙인다.
2. 화면을 연다. `--open`을 붙이거나, 브라우저 미리보기로 `workspaces/_nightly/daily_report.html`을 연다.
3. 보고한다. 세 줄 이내로 쓴다.
   - 할 일 건수(바로 처리·조치 필요·참고)와 HTML 링크를 전한다.
   - 바로 처리(critical) 항목이 있으면 한 줄씩 적는다.
   - 할 일을 직접 실행하지 않는다.
   - 사용자가 처리를 요청하면 항목의 명령에 맞는 담당 스킬을 부른다.

## 할 일 종류(kind)

| kind | 화면 이름 | 처리 스킬·명령 |
|---|---|---|
| `step_failed`, `questions_failed` | 단계 실패 · 질문 생성 실패 | 해당 명령을 수동으로 다시 실행 |
| `code_finding` | 코드 검수 지적 | `/BEOL-labeling-Code-Engr-bot` |
| `axis_relabel_needed` | 축 변경 · 재라벨링 | `/BEOL-labeling-axis-update <WS>` |
| `rules_relabel_needed` | 규칙 변경 · 재라벨링 | `/BEOL-labeling-rules-update <WS>` (적재까지 가므로 사람 확인 뒤) |
| `engr_questions_open` | 도메인 질문 답변 | `/BEOL-labeling-Domain-Engr-bot` (질문 화면) |
| `rule_candidate_pending` | 규칙 후보 승인 | `python -m domain_engrbot labeling-rules review --workspace <WS>` |
| `taxonomy_board` | taxonomy 제안 확인 | `/BEOL-taxonomy-dashboard` |

새 kind를 `nightly_run.py`에 추가하면 `daily_report.py`의 `KIND` 표와 이 표에도 넣는다.

## 규칙

- 루트 CLAUDE.md의 쓰기 규칙을 따른다.
  - 출력은 `.html`·`.jsonl`·`.json`·`.md`만 쓴다.
  - 화면과 기록에는 작업 폴더 ID·건수·명령만 넣고, 파일명·본문·base64는 넣지 않는다.
- 완료 체크는 브라우저 `localStorage`에만 저장한다. 다른 사람·다른 PC와 공유되지 않는다. 진짜 처리 여부는 다음 밤 실행에서 항목이 사라지는지로 본다.
- 이 스킬은 읽고 보여 주기만 한다. 재라벨링·적재·승인·`taxonomy.json` 쓰기는 하지 않는다.
- 다른 일은 다른 스킬이 맡는다: 코드 검수는 BEOL-labeling-Code-Engr-bot, 변경 대시보드는 BEOL-labeling-change-dashboard, 소개 HTML은 BEOL-labeling-project-html.

## 관계

- 목록에 오른 일(재라벨링·질문 답변·규칙 승인·taxonomy 보드)을 실제로 처리하는 일은 각 담당 스킬(BEOL-labeling-rules-update, BEOL-labeling-axis-update, BEOL-labeling-Domain-Engr-bot, BEOL-taxonomy-dashboard)이 맡는다.
