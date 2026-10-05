# 검수 교정 → Engr-bot → 최초 라벨링 규칙 환류: 이전 계획

작성 2026-10-05 · 코드 변경 없음(계획만) · 상태: 사용자 결정 대기

## 1. Engr-bot 세션 직접 확인 결과

확인 근거: Engr-bot 세션 대화 기록(마지막 25개 메시지)과 그 세션이 이 세션으로 보낸 메시지, `engrbot/docs/plan-ledger.md`(미추적 파일). 코드 변경은 아직 작업 트리에 없다(`git status`에서 engrbot 아래는 `plan-ledger.md`뿐).

| 구분 | 무엇을 하나 | 최초 라벨링 프롬프트로 환류하나 | 상태 |
|---|---|---|---|
| A. Engr-bot 현재 작업(`plan-ledger.md`) | 검수 교정을 `workspaces/_engrbot/ledger/`에 누적(intake) → 골든셋, L3b judge 예시, L4 규칙 후보(draft) | **아니오.** 용도를 ①골든셋 ②L4 규칙 후보 ③judge 예시로 정했고, labelbot 루프는 "그대로 두고 병행"이라고 적었다 | 설계 문서만 있음, 구현 전 |
| B. Engr-bot의 이전 시도(worktree `lessons-loop`) | LLM이 규칙 초안 → 승인 화면 → classify/label 프롬프트 주입 → taxonomy 반영 제안 | 예. 단 labelbot 안(`labelbot/lessons.py`)에 구현하는 설계 | 사양·결정 문서까지, 사용량 한도로 중단, 코드 0줄 |
| C. 이 세션의 `labelbot/feedback.py` | 결정적 규칙 후보 + 사례, CLI 승인, classify/label 프롬프트 주입 | 예 | 구현·테스트(13개) 완료, 미커밋, labelbot 소유 |

결론: **사용자가 말한 작업("Engr-bot이 검수 기록을 받아 규칙을 labeling에 피드백")과 같은 작업이 아니다.** Engr-bot 쪽 A는 "받는 쪽"(수집·장부)만 하고, "라벨링에 되돌려주는 쪽"은 비어 있다. 되돌리는 구현은 B·C로 labelbot 안에 있다. A와 C는 같은 입력(`corrections`)을 따로 읽는 중복이다.

Engr-bot 세션이 직접 답장으로 확인했다: "labelbot 프롬프트로 되먹이는 경로는 이번 범위에 없다"(사용자가 기존 labelbot 루프 병행 유지로 결정). 그 세션은 `BEOL-labeling-feedback/SKILL.md`에 4-2(`engrbot intake`)와 보고 줄을 이미 덧붙였다.

Engr-bot 세션은 이 세션의 `BEOL-labeling-feedback/SKILL.md` 4단계 뒤에 `python -m engrbot intake` 한 줄만 덧붙이겠다고 알려 왔고, 이 세션은 편집하지 않는 상태라고 회신했다.

## 2. 목표 구조 (권장): 만드는 곳은 Engr-bot, 쓰는 곳은 labelbot

```
검수 → labelbot apply → work.sqlite(corrections)
   └ engrbot intake ─→ ledger(누적)  ─┬ golden / judge 예시 / L4 후보   (A, 기존 계획)
                                      └ labeling 규칙 후보 (새로 추가)
                                           └ 사람 승인(engrbot labeling-rules approve)
                                                └ taxonomy/labeling_rules.json  ← 계약 파일(본문 없음, git 추적)
labelbot run: 승인 규칙만 읽어 classify·label 프롬프트에 넣음 (소비만, 수집·승인 코드 없음)
```

- 라벨링 규칙 후보는 L4 도메인 규칙 후보와 **소비자가 다르다**(프롬프트 vs QA 검사). 같은 ledger에서 만들되 파일을 분리한다: `labeling_candidates.json` ≠ `rule_candidates.json`.
- labelbot은 engrbot을 import하지 않고, 둘 사이는 파일 계약(`taxonomy/labeling_rules.json`)으로만 잇는다. engrbot이 labelbot을 import하는 곳은 기존대로 adapter 한 곳이다.
- 최소 이동: C에서 `Feedback.load/prepare/rules_text`, 프롬프트 변경, provenance 기록은 labelbot에 남기고, `harvest`·패턴·후보·`decide`·`status`·`purge`·CLI `feedback`을 engrbot ledger로 옮긴다. 이미 있는 13개 테스트를 같이 옮긴다.

## 3. 결정이 필요한 것 (사용자)

| # | 질문 | 권장 | 이유 |
|---|---|---|---|
| D1 | 환류의 소유 위치 | 위 2절(Engr-bot이 생산·승인, labelbot은 소비) | 사용자가 정한 방향이고, 승인 이력이 Engr-bot 결정 기록(`decisions.jsonl`)과 한곳에 모인다 |
| D2 | 문서 맥락(파일 제목 등)으로 정하는 축(제품·세대, 공정 모듈)을 본문 근거 없이 붙여도 되는가 | 정책을 먼저 정한다 | 실측에서 교정의 25/38이 이 유형이고, 규칙만으로는 32개 교정 축 중 1개만 맞았다. 허용 안 하면 환류 효과가 거의 없다. 허용하면 classify 프롬프트의 근거 규칙과 불량 판정이 같이 바뀐다 |
| D3 | few-shot 사례를 쓸 것인가 | 1차는 **규칙만**, 사례는 보류 | 사례는 사외 전송 가드(더미 목록)에 막혀 실측에서 0개 주입됐다. 가드를 넓히는 것은 보안 결정이다 |
| D4 | B(`lessons-loop`)와 C의 처리 | B는 보류하고 보안 지적 4건만 가져온다. C는 소비부만 남긴다 | 같은 일을 세 곳에서 만들면 유지가 안 된다. B의 규칙 출처 고정, 승인 뒤 변경 감지(`approved_rev`)는 C에 필요한 지적이다 |

## 4. 작업 패키지

| WP | 내용 | 소유 | 선행 |
|---|---|---|---|
| WP0 합의 | Engr-bot 세션에 ledger에 "라벨링 규칙 후보" 산출물(2절)과 계약 파일 경로·형식을 요청. 두 세션이 같은 SKILL.md를 건드리는 순서 정함 | 이 세션 → Engr-bot 세션 | D1 |
| WP1 생산 이동 | `engrbot/labeling_rules.py`(새): 패턴·후보(REPLACE/REMOVE/ADD/ANSWER/GEN_ANSWER, 지지 chunk ≥2, 상충 표시)와 승인/기각. CLI는 기존 `engrbot feedback`(자체 결정 묶음)과 이름이 겹치므로 `engrbot labeling-rules candidates|approve|reject|status`. 입력은 ledger의 `cases.jsonl`/`records.jsonl` | Engr-bot | WP0, plan-ledger 구현(intake) |
| WP2 계약 | `taxonomy/labeling_rules.json` v1 스키마를 문서화하고 검증기를 양쪽에 둠. 본문 없음, 문장 300자 이내, 축·값은 taxonomy에 있는 것만, 규칙마다 `source_file_ids`와 `approved_rev`(승인 뒤 문장이 바뀌면 주입 제외) | 양쪽 | WP0 |
| WP3 소비부 정리 | `labelbot/feedback.py`에서 수집·후보·승인·purge·`feedback` CLI 제거. `load/prepare/rules_text`, `prompts/classify.md`·`label.md` 주입, `feedback_applied` 메타, `sheet_hashes.labeling_rules` 유지. `store.migrate(tables)`·`embed(quiet)`는 사례를 보류하면 되돌릴 수 있는지 검토 | labelbot | WP2 |
| WP4 스킬·문서 | `BEOL-labeling-feedback` 4-1 `feedback harvest` → `engrbot intake`로 교체. `BEOL-labeling` 1-2의 승인 확인을 `engrbot labeling-rules status/approve` 호출로 교체. `PRD.md`·`plan.md`·`README.md`·`labeling-Engr-bot/SKILL.md` 갱신 | 이 세션 + Engr-bot 세션 | WP1, WP3 |
| WP5 검증 | 단위 테스트(이동한 13개 + 계약 검증), 전체 테스트(기준선 실패 3건은 `test_slides` 기존), codebot review(새 critical·major 0), 4곳 작업 폴더 intake → 후보 → (평가 사본에서만) 승인 → 이전 holdout 재라벨링 비교. 건수만 보고 | 양쪽 | WP1~4 |

## 5. 이 세션 구현에서 이어받는 미해결 지적

- `decide()`가 `n>0`일 때만 저장함 / `enabled`·`count` 타입 검증 없음 / 사례가 "확인한 라벨"로 잘못 표기됨 / `example_id`에 검수 실행 ID 필요 (사례를 보류하면 마지막 둘은 사라짐).
- 교정 값을 taxonomy로 검증하고 규칙 문장을 300자로 제한(WP2에 포함).
- `store_path`를 `workspaces/` 안으로 제한, `?mode=ro` URI는 `pathlib.Path.as_uri()`로 만들기, `source_ws` 충돌은 경로 해시로 구분, CLI는 `sqlite3.Error`·`ValueError`를 잡기.
- PRD 115·247행의 "임베딩은 run 안에서 호출하지 않는다"와 사례용 임베딩 문서 정합(사례 보류 시 불필요).
- Engr-bot 쪽 critic이 지적한 보안 4건: 규칙 출처 고정(`source_file_ids`는 합집합으로만 증가), 승인 뒤 변경 감지, 사외 전송 가드는 규칙·사례의 출처 file_id 전부에 적용, 메인 트리로 쓰기가 새지 않게 경로 가드.

## 6. 위험과 순서 제약

- **같은 파일 동시 편집**: `BEOL-labeling-feedback/SKILL.md`, `BEOL-labeling/SKILL.md`는 두 세션이 모두 고친다. Engr-bot 세션이 intake 한 줄을 먼저 넣고, 이 세션은 WP4에서 그 위에 교체한다.
- **plan-ledger 구현이 먼저**: WP1은 ledger(`cases.jsonl` 등)가 있어야 시작할 수 있다. 그때까지 `labelbot/feedback.py`는 그대로 두어 현재 동작(미승인 상태에서는 프롬프트 불변)을 유지한다.
- **효과 한계**: D2가 정해지기 전에는 환류가 구조적으로 거의 움직이지 않는다는 실측이 있다(규칙 덮은 교정 키 8/38, 출력 변화 0). 승인 UI나 이동 작업보다 D2가 먼저다.
- 커밋하지 않는다(사용자 결정 유지). 승인은 어떤 단계에서도 봇이 하지 않는다.
