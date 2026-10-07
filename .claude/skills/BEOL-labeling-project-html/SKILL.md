---
name: BEOL-labeling-project-html
description: 프로젝트 소개 발표 HTML(docs/project_intro.html, 슬라이드 00~10)을 가장 최근 작업 폴더의 실행 수치로 갱신해 내보낸다. 08 PILOT RESULT(id s7)(숫자 칸 · 의심 chunk 와플 · 분포 알림 반원 게이지 · labeling 교정 · 불량 chunk 5→0 그림)를 최신 실행 값으로 다시 그리고, 맨 마지막 Appendix(id sA)에 프로젝트 스킬 지도(그룹 · 상하위 계층)를 assets/skill_map.json과 .claude/skills/ 폴더로 다시 그린 뒤, 슬라이드 수 · 번호 · 외부 리소스를 검사한 뒤 날짜 붙은 사본(docs/snapshots/)을 남긴다. 같은 실행에서 사용자 흐름도 docs/user_flow.html도 검사 · 사본까지 함께 만든다. 최종 답변은 두 HTML 링크만 간결하게 낸다. 사용자가 "프로젝트 소개 HTML 뽑아줘", "project_intro 출력", "발표 HTML 최신화", "소개 슬라이드 수치 갱신", "파일럿 슬라이드 최신 결과로", "project html 내보내기", "user_flow 뽑아줘"라고 하거나 /BEOL-labeling-project-html을 부르면 이 스킬을 쓴다. 슬라이드 문구 · 레이아웃 수정은 docs/project_intro.html을 직접 고치고(이 스킬은 파일럿 슬라이드만 다시 그린다), 워크플로 HTML(docs/workflow.html)은 BEOL-labeling-workflow, 라벨링 실행은 BEOL-labeling이 맡는다.
---

# BEOL-labeling-project-html: 프로젝트 소개 HTML 최신화 · 출력

`docs/project_intro.html`이 원본이다. 이 스킬은 그 파일에서 **08 PILOT RESULT(id s7) 섹션**을 최신 실행 수치로 다시 그리고, **맨 마지막 Appendix(id sA) 스킬 지도**를 다시 만든다. 나머지 슬라이드(00~07, 09~10)의 문구 · 그림은 손대지 않는다. `scripts/build_project_html.py`가 수치 수집 · 07 렌더링 · 검사 · 저장을 한 번에 하고, LLM 호출은 0회다.

```
슬라이드 구성(2026-10-07 기준, 12장 · 번호 00~10, 괄호는 HTML id)
00 Hook(s0) → 00+ Why not(s0b, 범용 LLM의 두 벽) → 01 Data labeling(s2, 맥락 없는 글, 출처 없는 TEM)
→ 02 Why(s1, 찾고, 답한다) → 03 Goal(s3, AI-readable DB) → 04 Workflow(s5, 8 step) → 05 Team(s4, multi-agent)
→ 06 Learning loop(s8, Domain-Engr-bot · Code-Engr-bot) → 07 Trust(s6) → 08 Pilot(s7, ← 이 스킬이 다시 그림)
→ 09 Knowledge Vault(s9, 모으기 · 잇기 · 쌓기) → 10 AI transformation(s10, TODAY → TOMORROW)
→ A Appendix(sA, 스킬 지도 ← 이 스킬이 다시 그림. 번호 "A / 10", 본편 장 수에 넣지 않음)
```
화면 번호와 HTML id가 다르다. 순서를 바꿀 때 id는 그대로 두고(change-dashboard · workflow 스킬이 `id="s4"` 등으로 그림을 찾는다) 섹션 위치 · 위쪽 라벨 · 아래 번호 · 내비게이션만 바꾼다. 스크립트는 `id="s7"` 섹션을 찾고, 그 섹션의 기존 위쪽 라벨 · 제목 · 번호를 그대로 둔 채 본문만 다시 그린다.

## 최종 출력 규칙 (사용자 결정, 2026-10-07)

성공하면 답변에는 **아래 두 줄의 링크만** 쓴다. 표 · 수치 · 검사 결과 · 설명 · 인사말을 붙이지 않는다.

```
[project_intro.html](docs/project_intro.html)
[user_flow.html](docs/user_flow.html)
```

- 두 파일은 `SendUserFile`(`display: attach`, 캡션 없음)으로도 보낸다.
- 실패하거나 검사가 어긋나면(`error`, `nav_matches:false`, `map_matches:false`, `skills_unmapped` 비어 있지 않음 등) 링크 대신 **한 줄**로 사유 코드와 조치만 쓴다. 어긋난 채로 링크를 내지 않는다.
- 사용자가 숫자나 변경 내역을 따로 물으면 그때만 답한다. 중간 확인 질문(이미 최신인데 갱신할까요 등)도 하지 않고 그냥 갱신한다.

## 사용자 흐름도(docs/user_flow.html)

`docs/user_flow.html`은 손으로 쓴 안내 페이지다(화면 그림은 base64로 내장). 이 스킬은 **내용을 고치지 않고** `scripts/build_project_html.py`가 검사한 뒤 `docs/snapshots/user_flow_<YYYYMMDD-HHMMSS>.html` 사본을 남긴다. 출력 JSON의 `flow`에 결과가 나온다. 끄려면 `--no-flow`, 다른 경로는 `--flow`.

- 검사: `map_matches`(한눈에 보기의 단계 링크 = 단계 카드 id), `external_resources:false`, `images`(내장 화면 그림 수). 어긋나면 위 규칙대로 한 줄로 알린다.
- 문구 · 그림을 바꾸려면 `docs/user_flow.html`을 직접 고친다(다른 세션이 고치는 중일 수 있으니 실행 직전에 저장이 끝났는지는 사용자에게 묻지 말고, 사본 시각만 남긴다).
- 쓰기 규칙은 project_intro와 같다. 건수 · 실행 ID만 넣고 파일명 · 본문은 넣지 않는다.

## 고정 값

- 코드 폴더: `C:\Users\dltkd\Desktop\261004 BEOL AX day2`. 명령은 여기서 실행한다.
- 원본 · 출력: `docs/project_intro.html`(제자리 갱신). 다른 경로는 `--out`.
- 사본: `docs/snapshots/project_intro_<YYYYMMDD-HHMMSS>.html`. 끄려면 `--no-snapshot`.
- 작업 폴더: 인자로 받는다. 없으면 `workspaces/261004_BEOL_*` 중 `work.sqlite`가 가장 최근에 바뀐 폴더. 실행은 `--run`, 없으면 그 폴더 `runs` 표의 가장 최근 `run` 실행.
- 파일럿 슬라이드 수치의 출처(모두 건수 · 비율만):

| 파일럿 슬라이드 자리 | 출처 |
|---|---|
| pptx 파일 · 실패 | `work.sqlite` `files.status` |
| 건너뛴 파일 수(문장) | `pipeline.json`의 `skip_file_names` 개수(0이면 문장 생략, 칸 이름도 "새 pptx 파일" → "pptx 파일") |
| chunk · LLM의 답 O/X/N/A | `out/labeling.sqlite` `chunks` · `answers`. 답은 사람 교정(`corrections` answer)을 되돌린 **봇의 원래 답** |
| 불량 chunk · 의심 사유 | `flagged_chunks.reason_codes`. 한 chunk에 사유가 여럿이면 심각한 순(분류 실패 → … → 확신도 낮음)으로 대표 사유 하나 |
| 분포 알림 게이지 | 비율은 `reports/baseline_<run>.md`, 알림 여부 · 기준은 `alerts` 표(없으면 기준 30% · 40%) |
| labeling 교정 · LLM O/X 퀴즈 오답 교정 | `corrections` target_kind axis · answer (`review_run_id`=실행) |
| 새로운 label 후보 · 동의어 후보 | `reports/candidates.md`의 "## 새 값 …: N건" · "## 동의어 …: N건" |
| 불량 chunk 5→0 | 검수 완료 신호 `signals/review_done_<run>.json`이 있으면 "검수 후 0"(사람 검수로 해결), 없으면 "검수 대기" |
| DB 적재 · embedding | `vector_push_log` OK chunk 수 · `chunk_embeddings` 수 |

- 의심 사유 색: 많은 순 3개에 남색 `#4A5FA8` · 주황 `#E08A2E` · 청록 `#2BA39A`(dataviz 검증기 통과 조합), 4번째부터는 회색 "기타"로 묶는다. 게이지는 알림이면 `#C99A3B`, 아니면 남색.
- chunk가 25개 넘으면 와플은 10열, 60개 넘으면 한 칸이 여러 chunk를 뜻한다(aria-label에 적힘).

## Appendix · 스킬 지도(id sA)

- 데이터: `assets/skill_map.json`. 그룹(제목 · 한 줄 설명 · 색) → 부모 스킬 → `children`(부르는 하위 스킬) → `role`(한 줄 기능). 지금 그룹은 ① 라벨링 파이프라인(run-labeling 아래 labeling · feedback) ② 품질 점검 · 재라벨링(Domain-Engr-bot 아래 taxonomy-dashboard, Code-Engr-bot 아래 rules-update · axis-update) ③ 문서 · 발표 · PM 관리(workflow · project-html · change-dashboard)다.
- 스크립트는 `.claude/skills/*/SKILL.md` 폴더 목록과 지도를 맞춰 본다. 지도에 없는 스킬은 회색 "미분류" 그룹으로 붙이고 `checks.skills_unmapped`에, 지도에만 있고 폴더가 없는 스킬은 `checks.skills_missing`에 적는다. 둘 중 하나라도 비어 있지 않으면 사용자에게 알리고 `skill_map.json`을 고친 뒤 다시 돌린다.
- 섹션은 항상 마지막 `</section>` 뒤에 새로 만들어 넣고(있던 sA는 지움), 내비게이션에 `A` 링크가 없으면 추가한다. CSS는 섹션 안 `<style>`에 있어 원본 CSS와 상관없다. 좁은 화면(900px 이하)에서는 이 슬라이드만 16:9 고정을 풀고 세로로 늘어나며, 세 그룹이 한 줄씩 쌓인다(휴대폰에서 읽기용).

## 지켜야 할 것과 이유

- HTML과 출력 JSON에는 건수 · 비율 · 실행 ID · 사유 코드 이름만 넣는다. 파일명, chunk 본문, 교정 근거 인용, 후보 문장은 넣지 않는다. 사내 반입 뒤에도 발표 자료를 그대로 공유할 수 있어야 하기 때문이다(`CLAUDE.md` 쓰기 규칙).
- `work.sqlite` · `labeling.sqlite`는 읽기 전용(`mode=ro`)으로만 연다. 원본 pptx와 `.b64`는 열지 않는다.
- 파일럿 슬라이드의 구조(타일 6칸, 세 칸 그래프)를 바꾸려면 `scripts/build_project_html.py`의 `render_s7`을 고친다. `docs/project_intro.html`의 07을 손으로만 고치면 다음 실행 때 덮어써진다. 07의 CSS(`.pv-*`, `#s7 .grid3`)는 원본 HTML에 있고 스크립트는 건드리지 않는다. CSS가 없으면 `S7_CSS_MISSING`으로 멈춘다.
- 파일럿 슬라이드 위쪽 배지 "더미 데이터 기준"과 안내 문장은 스크립트 맨 위 상수 `BADGE` · `LEAD`다. 사내 실제 자료로 돌리면 사용자에게 물어 바꾼다.
- 다른 세션이 같은 HTML을 고치고 있을 수 있다. 스크립트는 실행 순간의 파일을 읽어 파일럿 슬라이드(id s7)만 바꿔 쓰므로, 실행 직전에 그 세션이 저장을 끝냈는지 사용자에게 확인한다.

## 절차

### 1. 실행 (미리 보기 생략)

```bash
python ".claude/skills/BEOL-labeling-project-html/scripts/build_project_html.py" [--workspace "<WS>"] [--run <RUN>] [--out <HTML>] [--flow <HTML>] [--no-snapshot] [--no-flow]
```
`--dry-run`은 쓰지 않고 검사만 보고 싶을 때만 쓴다. 출력 JSON의 `error`가 있으면 멈추고 한 줄로 보고한다.

| error | 뜻 |
|---|---|
| `WORKSPACE_NOT_FOUND` · `WORKSPACE_NO_DB` | 작업 폴더가 없거나 `work.sqlite`가 없다 |
| `RUN_NOT_FOUND` | 그 폴더에 `run` 실행 기록이 없다 |
| `S7_NOT_FOUND` · `S7_PARTS_NOT_FOUND` · `S7_CSS_MISSING` | 원본 HTML의 id s7 섹션 · 제목 · 번호 · CSS를 못 찾았다(다른 세션이 구조를 바꿨을 수 있음) |
| `SA_ANCHOR_NOT_FOUND` · `SA_NAV_NOT_FOUND` | Appendix를 붙일 자리(마지막 섹션 · 내비게이션)를 못 찾았다 |
| `USER_FLOW_NOT_FOUND` | `docs/user_flow.html`이 없다 |

### 2. 검사 확인

`checks`에서 `nav_matches` · `pg_consistent` · `external_resources:false` · `skills_unmapped:[]` · `skills_missing:[]`, `flow.checks`에서 `map_matches` · `external_resources:false`를 본다. 하나라도 어긋나면 사유 한 줄만 쓰고 끝낸다(스크립트는 07과 Appendix 외에는 고치지 않는다).

### 3. 화면 확인 (조용히)

브라우저(`mcp__Claude_Browser__preview_start`의 `url`)로 `docs/project_intro.html`의 파일럿 슬라이드(id s7)와 Appendix(id sA)를 한 번 확인한다. 스크롤 · 스냅 때문에 안 보이면 javascript로 `document.documentElement.style.scrollSnapType='none'` 후 `scrollIntoView()`. 볼 것: 숫자 칸 6개, 와플 칸 수 = chunk 수, 게이지 두 개, 잘린 칸 없음(`scrollHeight > clientHeight`), 콘솔 오류 없음. 고칠 것이 보이면 `render_s7`을 고치고 1단계를 다시 돌린다. 이 과정은 답변에 쓰지 않는다.

### 4. 전달

위 "최종 출력 규칙"대로 `SendUserFile`로 두 파일을 보내고, 답변에는 두 링크만 쓴다.
