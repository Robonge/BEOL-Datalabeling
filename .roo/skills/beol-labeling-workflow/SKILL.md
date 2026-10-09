---
name: beol-labeling-workflow
description: 'BEOL 라벨링 워크플로(입력 → 준비·수집·파싱 → 1~3차 분류·검증 질문·라벨링 → 불량 목록 → 사람 검수 → 피드백 반영 → Domain-Engr-bot 장부·규칙 후보 → 임베딩·벡터 저장소 적재 → Domain-Engr-bot 도메인 질문 생성 → 엔지니어 답변·초안 확정 → 규칙·taxonomy 제안 반영 → taxonomy 보드·편집기(taxonomy.json)·도메인 규칙 수정 → 다음 실행)를 단계별 산출물·예시 화면이 있는 HTML 한 장(docs/workflow.html)으로 다시 만든다. 위쪽에 docs/project_intro.html의 S4 팀 지도를 넣어 단계마다 맡은 agent를 강조한다. 최신 실행의 건수·알림·답 분포와 Domain-Engr-bot의 장부·승인 규칙·도메인 질문 건수를 채워 넣는다. 사용자가 "워크플로 HTML 다시 만들어줘", "workflow 시각화", "workflow.html 갱신", "단계별 화면 정리", "BEOL 워크플로 보여줘", "Domain-Engr-bot까지 포함한 workflow"라고 하면 이 스킬을 쓴다.'
---

# BEOL-labeling-workflow: 워크플로 HTML 다시 만들기

> 이 문서는 `.claude/skills/BEOL-labeling-workflow/SKILL.md`에서 생성됐다. 직접 고치지 말고 원본을 고친 뒤 `python tools/gen_roo_skills.py`를 다시 실행한다.

> 폐쇄망: LLM 호출(M02·M03)·임베딩(M07)·벡터 저장소 적재(M08)·슬라이드 JPG 저장(M10)은 사내 API·벡터 저장소·S3 단계라 게이트 G-API·G-VDB·G-S3 이후 릴리스에서 활성화된다. 그 전에는 이 단계가 설정 누락 사유 코드로 멈추거나 "호출하지 않습니다"로 끝나므로 사유 코드만 보고하고 나머지 단계를 계속한다.

> 그룹: ③ 화면 · 발표 · 운영 리포트 · 상위: 없음 · 하위: 없음 · 전체 지도: README.md "스킬 지도"

`docs/workflow.html`을 만든다. 화면 구조(S4 팀 지도, 16단계, 스킬 범위 구역 4개, 예시 화면, 인터랙션)는 템플릿 `.claude/skills/BEOL-labeling-workflow/assets/workflow_template.html`에 있다. `.claude/skills/BEOL-labeling-workflow/scripts/build_workflow.py`가 최신 실행의 수치와 Domain-Engr-bot 건수를 채우고, `docs/project_intro.html`에서 S4 그림을 가져와 넣는다. LLM 호출은 0회다.

```
[S4 팀 지도]             docs/project_intro.html의 S4 SVG·agent 설명(AG)을 빌드 때마다 가져온다.
                         단계를 고르면 맡은 agent와 선이 켜지고, 캐릭터를 누르면 그 agent의 첫 단계로 간다.
[A BEOL-labeling]        1 준비·중복 확인·피드백·taxonomy 변경 보고·수집·파싱 → 2 1차 분류 → 3 2차 질문 매핑·검증 질문 생성
                         → 4 3차 라벨링 → 5 분포 알림·불량 목록·후보·처리 완료 목록 → 6 화면 생성·대시보드·검수 완료 대기
                         → 7 H6 불량 chunk 검수(사람) → 8 H2 파싱 대조(사람, 선택) → 검수 완료 신호 → feedback 호출
[B BEOL-labeling-feedback] 9 교정 모으기·반영
                         → 10 Domain-Engr-bot 장부·라벨링 규칙 후보(domain_engrbot intake · labeling-rules candidates)
                         → 11 화면·리포트 재생성 → 12 임베딩·슬라이드 JPG·벡터 저장소 적재(push-vectors · push-slides)
[C BEOL-labeling-Domain-Engr-bot]    13 도메인 질문 생성(domain_engrbot workspaces · questions generate) → 14 엔지니어 답변·초안 확정(사람, engr_questions.html)
                         → 15 규칙·taxonomy 제안 반영(questions apply → taxonomy/labeling_rules.json · 보드 S7)
[H 도메인 담당자(사람)]   16 taxonomy.json(보드 S7·편집기) · domain_rules.json 수정 → 다음 beol-labeling 스킬(단계 1)
```
사람 작업(7·8·14·16)은 `who:"human"`으로 표시한다. 14는 `k:"ans"`, 15·16은 `k:"tax"`로 S4의 답변 엔지니어·TAXONOMY를 켠다. 7·8은 BEOL-labeling이 검수 완료 신호를 기다리는 동안 사람이 하는 일이라 A 구역에, 14는 Domain-Engr-bot 스킬이 질문 화면 서버를 띄우고 기다리므로 C 구역에 둔다. 16은 어느 봇도 하지 않는 일이라 따로 H 구역에 둔다. 10은 feedback 스킬이 부르지만 Domain-Engr-bot의 일이라 `k:"engr"`로 표시한다.

## 고정 값

- 코드 폴더: 저장소 루트(`git rev-parse --show-toplevel`, 이 SKILL.md 기준 ../../..). 명령은 여기서 `PYTHONIOENCODING=utf-8`을 붙여 실행한다.
- 출력: `docs/workflow.html`(덮어쓴다). 사용자가 다른 경로를 말하면 `--out`.
- 작업 폴더: 인자로 받는다. 없으면 이 대화에서 `beol-labeling` 스킬이 쓴 작업 폴더, 그것도 없으면 스크립트가 `workspaces/261004_BEOL_*`(실행마다 `_YYYYMMDD-HHMMSS`가 붙은 새 폴더) 중 `work.sqlite`가 가장 최근에 바뀐 폴더를 고른다.
- 중복 확인 기준: 코드 폴더의 `injested-file-list/*.json`(BEOL-labeling이 실행 후 기록). HTML에는 목록 파일 수와 건너뛴 건수(`skip_file_names` 개수)만 넣고 파일명은 넣지 않는다.
- S4 그림: `docs/project_intro.html`의 `<symbol id="clawd">`, `<svg class="orch …">`, `var AG={…};`를 그대로 가져온다. 그림을 바꾸려면 project_intro.html을 고치고 이 스킬을 다시 돌린다. 못 찾으면 그 자리에 안내 한 줄만 나오고 생성은 계속된다(출력 JSON `s4:false`).
- Domain-Engr-bot 건수(`LIVE.engr`, 모두 본문 없음):
  - `rules`: `python -m domain_engrbot labeling-rules status`의 JSON(대기 후보·상충·사례 후보, 승인·켜진 규칙과 사례)
  - `ledger`: `python -m domain_engrbot ledger status`의 첫 `[ledger] 누적 …` 줄 숫자만
  - `questions`: 질문 폴더 `workspaces/_domain_engrbot/questions/`의 건수만. `questions.json`의 set_id·열린 질문 수(목표별·이월), `asked.json`의 답함·묻지 않음 수, `taxonomy_proposals.jsonl` 행 수. 파일이 없으면 0, 깨졌으면 "—"다. 질문 문장·답·제안 문장은 넣지 않는다.
  - `domain_rules`: `domain_engrbot/defaults/domain_rules.json`의 draft·approved 개수
  - `revisit_files`: `taxonomy/taxonomy_revisit_requests/*.md` 개수
- 디자인: 저장소의 `design.md.md`(BEOL AX 디자인 시스템)를 따른다. `#EDF1F7` 바탕과 48px 그리드, 인디고 그라디언트(148°), 음수 자간, 굵기 400/700, 외부 CDN 없음.

## 지켜야 할 것과 이유

- HTML에는 건수·실행 ID·사유 코드·답 분포만 넣는다. chunk 본문, 파일명, 경로, 재검토 메모, 규칙·사례 문장은 넣지 않는다. 예시 화면의 문구는 합성 예시로 두고 화면에 그렇게 표시한다. 사내 반입 뒤에도 그대로 공유할 수 있어야 하기 때문이다.
- `work.sqlite`는 읽기 전용으로만 연다. 원본 파일과 `.b64`는 열지 않는다(`CLAUDE.md`).
- Domain-Engr-bot 장부의 `golden.jsonl`·`judge_examples.jsonl`·`evidence.jsonl`과 `labeling_review.html`, 질문 폴더의 `questions.json`·`engr_questions.html`·`answers.jsonl`·`taxonomy_proposals.jsonl`, 재검토 요청 파일은 본문이 있어 Roo가 열어 보지 않는다. 건수는 domain_engrbot 명령 출력과 `build_workflow.py`가 세는 질문 폴더 건수에서만 얻는다.
- 템플릿을 고칠 때는 자리 표시자 `/*__LIVE__*/null`, `<!--__S4_SVG__-->`, `/*__S4_AG__*/null`을 하나씩만 남기고(하나라도 개수가 다르면 `TEMPLATE_PLACEHOLDER` 오류), 외부 리소스(`<script src>`, `<link>`, CDN)를 넣지 않는다.

## 절차

### 1. 생성

```bash
python ".claude/skills/BEOL-labeling-workflow/scripts/build_workflow.py" [--workspace "<WS>"] [--run <RUN>]
```
출력 JSON의 `out`, `workspace`, `run_id`, `fields`, `s4`, `questions`를 본다. `run_id`가 null이면 실행 기록이 없는 것이라 수치 칸이 "—"로 나온다고 알린다. `s4`가 false면 S4 그림을 못 가져온 것이다. `questions.set_id`가 null이면 도메인 질문 기록이 없어 13~15단계의 질문 수치가 0이다. `error`가 나오면 멈추고 보고한다.

### 2. 워크플로가 바뀌었을 때만: 템플릿 고치기

> 폐쇄망에서는 템플릿·스크립트를 고치지 않는다. 워크플로가 바뀌었으면 반출로 로컬에 넘긴다. 아래는 로컬 개발용 설명이다.

단계가 추가·변경됐으면(새 스킬 단계, 새 산출물, 새 사람 개입 지점) `.claude/skills/BEOL-labeling-workflow/assets/workflow_template.html`의 `STEPS` 배열과 해당 mock 함수를 고친 뒤 1단계를 다시 돌린다. 각 단계는 `{z, k?, t, cmd, llm, who, lead, pts, out, mock, bind?}`다.
- `z`: 구역. A=BEOL-labeling, B=BEOL-labeling-feedback, C=BEOL-labeling-Domain-Engr-bot, H=도메인 담당자(사람). 구역 이름은 `ZONES`에 있다.
- `k`: S4 팀 지도의 agent 키(`lab`·`hum`·`fb`·`engr`·`ans`·`tax`·`req`·`code`·`orch`·`ws`. `ans`=답변 엔지니어, `tax`=TAXONOMY). 없으면 `agentKey()`가 구역과 `who`로 정한다(A→lab, B→fb, C→engr, H→req, B의 사람 단계→hum). 다른 스킬이 부르는 Domain-Engr-bot 일처럼 기본값과 다를 때만 쓴다.
- `who:"human"`: 사람이 하는 단계.

새 수치가 필요하면 `build_workflow.py`의 `live_data`(Domain-Engr-bot은 `engr_data`)에 건수 쿼리를 더하고 템플릿에서 `LIVE.<키>`(Domain-Engr-bot은 `ENGR.<키>`)로 읽는다(값이 없으면 `V()`가 "—"로 표시). S4 agent가 늘면 project_intro.html의 SVG와 `AG`에 먼저 넣는다.

taxonomy가 바뀌면(축 추가 등) workflow.html도 다시 만든다. 1차 분류 단계의 축 개수는 최신 실행에서 채운다(템플릿에 숫자를 박지 않는다).

### 3. 확인

생성된 `docs/workflow.html` 경로를 출력하고 사용자가 VS Code(또는 브라우저)에서 연다. 사용자에게 확인할 것을 안내한다.
- 단계 16개, 구역 4개가 보이는지, 단계를 누르면 예시 화면과 맡은 agent가 강조되는지, 캐릭터를 누르면 그 agent의 첫 단계로 가는지.
- 좁은 창(휴대폰 폭)에서도 페이지 가로 스크롤이 없는지(단계 레일은 원래 가로로 스크롤된다).
- 이상이 있으면 폐쇄망에서는 템플릿·스크립트를 고치지 않고 반출로 넘긴다.

### 4. 보고

생성 경로(링크), 기준 실행 ID와 작업 폴더, 채운 주요 수치(파일·chunk·검증 질문·불량·알림), Domain-Engr-bot 수치(장부 사례·근거 있음, 대기 후보, 켜진/승인 규칙·사례, 질문 set_id·열린 질문·답함·taxonomy 제안 수), 확인 결과를 짧게 쓴다. 승인분이 있는데 켜진 것이 0이거나, 장부 사례가 있는데 근거 있는 교정이 0이면 한 줄로 짚는다(화면에도 경고 배지가 뜬다).

## 관계

- 파싱·라벨링 실행은 BEOL-labeling, 사람 검수 진행과 반영·적재는 BEOL-labeling-feedback, 검수 결과로 엔지니어에게 질문해 도메인 지식을 규칙·taxonomy 제안으로 돌려주는 일은 BEOL-labeling-Domain-Engr-bot이 맡는다.

## 마일스톤

이 스킬의 명령은 터미널에 `[Mxx 이름] 시작·완료·실패` 줄을 낸다. 실패하면 아래 ID로 어느 단계인지 보고, `python -m labelbot codes --milestone <Mxx>`로 사유 코드와 조치를 본다.

| 명령 | 마일스톤 |
|---|---|
| `.claude/skills/BEOL-labeling-workflow/scripts/build_workflow.py` | M22 WORKFLOW_HTML |
| `domain_engrbot labeling-rules` | M11 DOMAIN_QA |
| `domain_engrbot ledger` | M11 DOMAIN_QA |

담당 마일스톤: M11·M22

## 실패하면

터미널의 `[Mxx …] 실패` 블록을 먼저 읽는다 → `python -m labelbot status --workspace <작업 폴더>`(Python 3.14가 없으면 `python3 tools/beol_status.py status --workspace <작업 폴더>`) 출력을 복사해 알려 달라. 환경 문제면 `python3 tools/beol_doctor.py`. `BEOL_TRACE=1`은 Roo 명령으로 실행하지 말고 일반 터미널에서만.
