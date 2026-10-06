> 2026-10-06 이름 변경: Engr-bot → Domain-Engr-bot(`domain_engrbot`), code-bot → Code-Engr-bot(`code_engrbot`). 아래 본문은 이력이라 옛 이름을 그대로 둔다.

# 질문 루프 전환의 프로젝트 전체 영향 점검 (2026-10-06)

`plan-question-loop.md`가 끝났을 때 다른 skill·bot·문서에서 고칠 곳을 점검했다. 읽기 전용 점검이며, 이 문서를 쓰는 것 말고 파일은 고치지 않았다.

## 0. Engr-bot 세션이 이미 처리한 범위

Engr-bot 세션(제목 "Engr-bot 개념 전환 (autopilot)")은 점검 시각(01:30 KST) 기준 **통합 확인 단계**에 있다. 아래 항목은 그 세션에서 이미 처리했다.

| 작업 | 상태 | 대상 |
|---|---|---|
| A 질문 생성 | 완료 | `questions.py`, `prompts/engr_*.md`, `cli.py questions`, `workspaces.py question_state`, `policy.py` |
| B 답 반영 | 완료 | `answers.py`, `taxonomy_board.py` S7, `labeling_review.py` 축소, 루트 `tests/test_question_rules_contract.py` |
| C 질문 화면·서버 | 완료 | `question_screen.py`, `screens/engr_questions.html`, `serve.py` |
| D 문서 | 완료 | 6개 SKILL.md, README, PRD.md H9, `docs/project_intro.html` S4·S5의 Engr-bot 설명, workflow 템플릿·`build_workflow.py`, `docs/workflow.html` 재생성 |

아래 항목은 D가 맡은 범위 밖에서 남은 것이다. 통합 확인 중인 그 세션이 일부를 처리할 수도 있으니, 손대기 전에 그 세션의 마무리 보고를 먼저 확인한다.

## 1. 필수

| # | 위치 | 문제 | 제안 |
|---|---|---|---|
| M1 | `tests/contracts/snapshots/cli_engrbot.json` | 스냅샷에 `questions`·`workspaces`·`taxonomy-board`·`serve`가 없다. `test_engrbot_cli`와 `test_skill_commands_exist_in_cli`가 실패한다. 새 SKILL.md가 부르는 명령을 스냅샷이 모른다 | CLI 변경이 끝난 뒤 `CONTRACT_UPDATE=1 python -m unittest tests.contracts.test_contract_cli`로 다시 만들고 diff를 검토한다(`tests/contracts/_support.py:21-22`) |
| M2 | `tests/contracts/snapshots/labelbot_symbols_used_by_engrbot.json` | 실패한다. `labelbot_ws.py:13-19`가 import하는 `labelbot.candidates`·`labelbot.xlsx`·`labelbot.taxonomy` 일부 심볼이 스냅샷에 없다. 원인은 질문 루프가 아니라 앞선 taxonomy 보드 작업이다 | M1과 같은 `CONTRACT_UPDATE=1`로 다시 만든다. 질문 루프가 새로 쓰는 labelbot 심볼은 이미 있는 `labelbot.llm.*`뿐이다 |
| M3 | `engrbot/engine.py:6-8,103-113,152-157`, `engrbot/report.py:16,207-,259-261,328,457-463`, `engrbot/adapters/labelbot_ws.py:357`(`labeler_flagged`), `engrbot/defaults/policy.json:19` | 이 세션이 앞서 넣은 "L3B는 지표로만" 미완료 변경이다. judge·golden 테스트를 깨뜨리며, Engr-bot 세션은 이를 "다른 세션의 judge 변경에서 온 기존 실패 15건"으로 보고 있다. D7에 따라 스킬이 L0~L6를 더 이상 부르지 않으므로 이 변경의 목적이 없어졌다 | **되돌린다**(이 4개 파일의 해당 부분만. `labelbot_ws.py`의 `chunk_context` 등 Engr-bot 세션 변경분은 건드리지 않는다). 되돌린 뒤 `python -m unittest discover -s engrbot/tests -t .`로 judge·golden 실패가 0인지 확인한다 |
| M4 | `labelbot/screens/results.html:405` | 라벨링 결과 화면 문구가 "근거를 남긴 교정 → Engr-bot 최종 검수 뒤 다음 실행에 반영"이다. 최종 검수 화면은 이제 없다 | "Engr-bot 질문 화면에서 사람이 확정한 뒤 다음 실행에 반영"으로 고치고 `tests/test_screens.py`를 돌린다 |
| M5 | `taxonomy/labeling_rules.json` | git이 추적하지 않고 `.gitignore`에도 없다. 다음 라벨링 프롬프트에 들어가는 승인 규칙 원본인데, 백업은 `rules_history.jsonl`(역시 ignore 대상) 하나뿐이다. 반대로 `git add .`를 하면 도메인 규칙 문장이 실수로 커밋될 수 있다 | 사용자가 정한다: (a) 커밋해 이력을 남긴다(사내 문장 포함 여부를 먼저 본다), (b) `.gitignore`에 넣고 `rules_history.jsonl`만 백업으로 쓴다 |

## 2. 권장

| # | 위치 | 문제 | 제안 |
|---|---|---|---|
| R1 | `engrbot/cli.py:1,19,23` | docstring과 description이 "검수봇(Label QA Agent)"이다. 옛 QA 명령(`run`·`report`·`review`·`serve`)이 앞에 있고 `questions`는 86~95행 부근에 있다 | description을 질문 루프로 바꾸고, 옛 명령 help에 "(옛 QA 흐름, 스킬은 부르지 않음)"을 붙인다. M1 스냅샷은 이 작업 뒤에 다시 만든다 |
| R2 | `change-dashboard/render.py:40` (`STAGE_DESC["Engr-bot"]="도메인 감시 · feedback"`), `NODE_INFO["engr"]`(:26부터) | 변경 대시보드의 Engr-bot 설명이 옛 개념이다 | "검수 결과로 엔지니어에게 질문 → 규칙·taxonomy 제안"으로 고친다. "감시" 배지(:173)는 project_intro S4가 "감시 agent" 틀을 유지하므로 그대로 둔다 |
| R3 | `change-dashboard/collect.py:65-76` (`classify_path`) | `tests/test_question_rules_contract.py`는 role=workspace로, `taxonomy/labeling_rules.json`은 BEOL-labeling·1차 분류로 분류된다. 실제 생산자는 Engr-bot이다 | 두 경로를 Engr-bot으로 보내는 예외를 둔다 |
| R4 | `docs/project_intro.html:663-` ("감시 agent의 첫 점검과 다음 단계") | Engr-bot 카드가 옛 QA 실행(QA-ID, L0~L5 비율, L3B mock 판정)을 현재 결과처럼 보여 준다. S4·S5 설명은 D가 고쳤다 | 첫 `questions generate` 실행 뒤 그 건수(질문 수, 라벨링/taxonomy, 이월)로 바꾸거나 "옛 QA 점검(이력)"으로 표시한다 |
| R5 | `plan.md:51,67-68,120,577` | `labeling-rules candidates/approve/reject` 표, H9 "최종 검수는 /BEOL-labeling-Engr-bot에서만", "git 추적"이 옛 내용이다 | 해당 줄을 질문 루프 기준으로 고치고 이력 한 줄을 더한다 |
| R6 | `docs/feedback_loop_report.md:3` | 배너가 "최종 검수는 승인 화면에서만"이라고 안내한다 | "후보 승인은 질문 화면(`questions serve`), 승인 화면은 승인분 관리만"으로 고친다 |
| R7 | `engrbot/engrbot_plan.md:1,11,705,1108,1124`, `engrbot/docs/plan-correction-evidence.md`, `plan-labeling-return.md`, `plan-ledger.md`, `plan-bot-split*.md`, `docs/code-review-plan-2026-10-05.md:32,47-48,62,72` | Engr-bot을 도메인 QA로 전제하거나, 후보 승인을 `labeling_review.py`에 있는 것으로 적는다(지금은 `answers.py`에 있다) | 각 문서 맨 위에 "이력 문서. 현재 개념은 plan-question-loop.md"라는 한 줄을 넣는다(본문은 이력으로 둔다) |
| R8 | `engrbot/workspaces.py:1-8` | 모듈 docstring 첫 줄이 "Engr-bot 검수 상태"이다 | 질문 상태(`question_state`)를 앞세워 고친다(칸은 계획 8.8대로 유지) |
| R9 | `labelbot/feedback.py:3`, `labelbot/workspace.py:72` | 주석에 "규칙 생산은 Engr-bot `labeling-rules`"라고 적혀 있다. 동작에는 영향이 없다 | 주석만 "Engr-bot 질문 답변(`answers.apply`)"로 고친다 |
| R10 | 메모리 `qabot-artifacts-in-qabot-folder.md`, `qabot-split-into-qabot-and-codebot.md` | 색인 설명이 Engr-bot을 "도메인 검수봇"으로 적는다 | 설명에 "2026-10-06부터 질문 루프([[engrbot-question-loop]])"를 덧붙인다 |

## 3. 선택

- `.claude/skills/BEOL-labeling-Engr-bot/scripts/collect_qa_decisions.py`: 새 SKILL.md는 이 스크립트를 부르지 않는다. docstring에 "옛 QA 흐름용"이라고 적거나, 사용자가 정하면 지운다.
- `codebot/defaults/policy.json:22` `doc_globs`: 지금은 SKILL.md와 README만 명령 참조 검사를 받는다. `engrbot/docs/*.md`와 `plan.md`를 더하려면 R7의 이력 배너를 먼저 넣는다(옛 명령 참조가 한꺼번에 걸린다).
- `engrbot/docs/issue_codes.md`: `QUESTIONS_INVALID`·`ANSWERS_*`·`NO_CONFIRMED_DRAFT` 등을 카탈로그(`codes.py`)에 넣을지 정한다. 넣으면 `engrbot_issue_codes.json` 스냅샷도 다시 만든다.
- `.claude/launch.json`: 질문 서버는 포트(8900~9099)가 set_id에 따라 정해지고 작업 폴더도 바뀐다. 그래서 고정 항목은 넣지 않는다. 스킬 방식(`run_in_background`)대로 띄운다.
- `codebot/tests/test_c3.py`: `python -m engrbot questions apply` 선언을 확인하는 회귀 케이스를 하나 더할 수 있다.

## 4. 바꿀 필요가 없음을 확인한 것

- **labelbot 승인 파일 소비**(`labelbot/feedback.py`)
  - `load_rules`·`_valid_rule`(:60-89)은 추가 키(question_id·set_id·origin·edited_at)를 무시한다.
  - kind 화이트리스트에 MANUAL이 있다(:80).
  - 단계 분기는 target이 "label"이면 3차 라벨링, 그 밖이면 1차 분류다(:345-346). 계획 8.6과 같다.
  - `enabled`를 지킨다(:331, :455).
  - 상한은 MANUAL을 먼저 남기고 단계별로 자른다(:348-350, `max_rules` 기본 30).
  - EX- 사례는 few-shot으로 쓰이고, text_hash가 바뀌면 건너뛴다(:382, :270).
  - 루트 `tests/test_question_rules_contract.py`가 이 경로를 실제로 읽어 확인하며 통과한다.
- **engrbot이 읽는 labelbot 자료**: corrections·revisit_requests·candidates(review 동의어)·chunks·slide_images의 열, 그리고 `reports/taxonomy_revisit.jsonl`이 `labelbot_ws.py` 읽기 함수(`correction_runs`, `revisit_counts`, `review_synonyms`, `chunk_context`, `read_config`)와 일치한다.
- **codebot**
  - C3 import 경계: 새 모듈은 `engrbot.adapters.labelbot_ws`로만 labelbot에 닿는다.
  - C2: `http.server`는 우회 모듈 목록에 없다.
  - C1·C4: 새 모듈에 `open(...,'rb')`·TODO가 없다.
  - targets가 `engrbot` 전체라 새 .py도 자동으로 검사 대상이다.
- **gitignore**: `workspaces/_engrbot/questions/*`와 `<WS>/qa/inbox/engr_answers_*.json`은 `.gitignore:15`의 `workspaces/` 규칙에 걸린다.
- **change-dashboard 단계 이름**: `STAGES` 10개, `project_intro.html`의 `ST`, change-dashboard SKILL.md의 stage 열거가 서로 일치한다. `engrbot/**` 경로는 모두 Engr-bot으로 분류된다.
- **labelbot 프롬프트**: `prompts/*.md`와 labelbot 검수·대조 화면에는 옛 Engr-bot 흐름 문구가 없다. labelbot의 "검증 질문(Q-GEN)"은 Engr-bot 질문 루프와 별개이니 문서에서 섞어 쓰지 않는다.
- **`labeling-rules candidates`·`status` 호출**: `BEOL-labeling-feedback/SKILL.md:186-192`(4-2), `BEOL-labeling/SKILL.md:113`, `build_workflow.py:139`, `workflow_template.html:484-488,629`(단계 B "장부 · 라벨링 규칙 후보")가 아직 이 명령을 부른다. 후보는 질문 재료로 남는 것이 계획의 의도라(D가 "확정은 질문 화면"으로 문구를 고쳤다) 바꿀 필요가 없다. 다만 `labeling-rules` 명령을 줄이거나 없애면 이 네 곳이 깨지므로 함께 고친다. intake 콘솔 줄의 "골든·judge 예시·L4 후보" 건수는 옛 QA 산출물이라 질문 루프와는 관계가 없다.
- **메모리 색인**: `MEMORY.md`에 `engrbot-question-loop.md`가 들어 있다.

## 4.1 루트 테스트 결과 (`python -m unittest discover -s tests -t .`, 296건 중 실패 18건)

| 실패 | 건수 | 질문 루프 관련 | 처리 |
|---|---|---|---|
| `test_contract_cli.test_engrbot_cli` | 1 | 예 | M1 |
| `test_contract_skill_commands` (Engr-bot SKILL의 `workspaces`·`questions *`·`taxonomy-board`) | 10 | 예. 새 SKILL.md가 부르는 명령이 낡은 CLI 스냅샷에 없다 | M1 스냅샷을 다시 만들면 함께 풀린다 |
| `test_contract_labelbot_api.test_symbols` | 1 | 아니다. 앞선 taxonomy 보드 작업에서 생겼다 | M2 |
| `test_contract_skill_scripts.test_skill_scripts_help` | 1 | 아니다 | 단독으로 다시 돌리면 통과한다. 다른 세션이 동시에 고치던 중이었던 것으로 보인다 |
| `test_defaults_taxonomy` ×2, `test_golden_run` ×3 | 5 | 아니다. taxonomy·labelbot 쪽 다른 변경에서 생겼다 | 이 점검 범위 밖이다. 다른 세션 작업이 끝난 뒤 따로 확인한다 |

engrbot 테스트는 452건 중 15건이 실패하며, 모두 M3에서 생긴다.

## 4.2 사용자 결정 (2026-10-06)

- M3: **그대로 둔다.** engrbot 테스트 15건 실패는 이 변경 때문이며, 다른 세션이 처음부터 있던 실패로 오인하지 않게 한다.
- M5: **git으로 추적한다.** 커밋 전에 사내 문서 인용이 들어 있지 않은지 확인하고, 계획 8.7의 "git이 추적하지 않는다" 문장과 `plan.md:67`도 함께 고친다.
- 나머지 필수·권장 항목은 **Engr-bot 세션이 처리한다.**

## 5. 처리 순서 제안

1. Engr-bot 세션의 통합 확인과 마무리 보고를 기다린다(M1·M2를 거기서 처리했는지 확인한다).
2. (M3은 사용자 결정으로 그대로 둔다.)
3. R1(cli 문구)을 고친 다음 M1·M2 스냅샷을 다시 만든다.
4. M4·R2·R3·R9: 문구와 분류만 고치는 작은 수정이다.
5. M5: `taxonomy/labeling_rules.json`을 git에 추가한다(커밋은 사용자 요청 때).
6. R4·R5·R6·R7·R10: 문서의 이력 표시를 정리한다.
