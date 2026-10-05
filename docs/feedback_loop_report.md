# 검수 교정 → 최초 라벨링 피드백 루프: 점검과 구현 보고 (2026-10-05)

## 1. 점검 결과: 루프가 없었다

- 사람 교정은 그 실행 작업 폴더의 `work.sqlite` `corrections`에만 남고, 최종 라벨을 덮어쓸 때만 쓰였다.
- `/BEOL-labeling`은 실행마다 새 작업 폴더를 만들므로, 교정이 다음 실행의 1차 분류(`prompts/classify.md`)·3차 라벨링(`prompts/label.md`)에 들어갈 길이 없었다.
- 있던 것은 사람이 엑셀에 손으로 옮기는 경로뿐이었다(검수 등록 동의어 → synonyms 시트, taxonomy 재검토 요청 → taxonomy 시트). engrbot의 `feedback.py`는 engrbot 자체 결정 묶음이라 labelbot 프롬프트와 연결되지 않는다.

## 2. 만든 것 (결정: 규칙 + 유사 사례 few-shot, 사람 승인 후 적용, 커밋 안 함)

```
검수 완료 → apply → feedback harvest(교정 장부·사례 수집) → 규칙 후보 리포트
   → [사람] 다음 /BEOL-labeling 시작 때 승인(feedback approve) → run: 승인 규칙·유사 사례를 프롬프트에 넣음
```

| 구성 | 위치 | 본문 | git |
|---|---|---|---|
| 교정 장부·사례·수집 이력 | `workspaces/_feedback/feedback.sqlite` | 사례 본문 앞부분 있음 | 제외 |
| 승인 규칙·기각 ID | `taxonomy/labeling_rules.json` (아직 없음, 첫 승인 때 생김) | 없음 | 추적 |
| 승인 대기 후보 리포트 | `workspaces/_feedback/reports/rule_candidates.md` | 없음 | 제외 |

- 규칙 후보는 LLM 없이 교정 패턴을 센다. REPLACE(값 혼동), REMOVE(과잉), ADD(누락), ANSWER, GEN_ANSWER. 지지 chunk 2개 이상만 후보가 되고, 반대 방향 교정도 2건 이상이면 '상충'으로 표시한다. `--all`은 상충 후보를 승인하지 않는다.
- 규칙 문장은 "경향" 형태의 조건부 지침이며, 프롬프트에 "분류 체계 정의가 우선"이라고 적었다. 사람이 `labeling_rules.json`에서 문장(`text`)을 고치거나 `enabled`를 끄거나 MANUAL 규칙을 더할 수 있다.
- 사례(few-shot)는 사람이 교정했거나 유효하게 확인한 chunk다. 1차 분류에 유사도 상위 2개를 넣고, 고친 축과 그대로 둔 축을 나눠 보여 준다. 같은 파일·같은 본문(text_hash·dup_hash)의 사례는 쓰지 않으며, 사외 전송 가드를 통과한 파일의 사례만 고른다. 유사도는 임베딩을 쓰고, 안 되면 문자 3-gram을 쓴다.
- 적용 이력: meta `feedback_applied:<실행ID>`, labels·runs `sheet_hashes.labeling_rules`. `summary.py`의 `feedback` 필드로 요약에 나온다.
- 스킬 연결:
  - `BEOL-labeling-feedback`: 4-1에서 `feedback harvest`를 실행한다. 수집만 하고 승인은 하지 않는다.
  - `BEOL-labeling`: 1-2에서 승인 대기가 있으면 `AskUserQuestion`을 띄운다. 선택지는 "전부 승인", "승인된 것만", "이번엔 피드백 없이(`run --no-feedback`)"다.

## 3. 지금 상태

- 기존 작업 폴더 5개의 교정을 실제 저장소로 백필했다. 교정 124건, 사례 20건이 모였고, 규칙 후보 29개(상충 2개)가 승인 대기 중이다.
- **아무것도 승인하지 않았다.** 승인은 사람 몫으로 남겼다. 다음 `/BEOL-labeling`을 시작하면 1-2에서 승인 여부를 묻는다.

## 4. 검증

- 단위·mock 테스트(`tests/test_feedback.py`) 13개가 통과했다. 수집 멱등성, 재검수 제외, 후보 결정성, 승인·기각과 사람 편집 보존, 다음 실행 요청 본문에 규칙·사례가 들어가는지, `--no-feedback`, 미승인 상태, 같은 파일·가드 제외, 저장소 미생성, 퍼지를 확인했다.
- 전체 테스트는 228개이고 실패는 3건이다. 3건 모두 `tests/test_slides.py`이며 기준선에서도 같은 실패였다(이번 변경과 무관). codebot은 critical 0건이고, major·minor는 모두 이번 변경 밖 파일이다.
- 실제 LLM 1회 실행(평가 작업 폴더 `workspaces/261004_BEOL_feedback-eval_20261005`, LLM 78회, Supabase 적재 없음):
  - 방법: 마지막 검수 실행(041826)을 holdout으로 두고, 나머지 4개 작업 폴더 교정으로 만든 규칙 18개(분류 17, 라벨 1)와 사례 15개를 **평가 전용 사본에서만** 승인해, 041826과 같은 파일 5개를 다시 라벨링했다.
  - 사례 15개는 모두 사외 전송 가드에 막혀 0개가 들어갔다. 원본 파일이 지금 `parshing test files`에 없고 더미 목록에도 없기 때문이며, 가드는 의도대로 동작했다. 따라서 이번 실측은 규칙 효과만 잰 것이다.
  - holdout에서 사람이 고친 축 32개를 보면, 원래 봇은 0개, 피드백 적용 봇은 1개가 사람 값과 일치했다. 사람이 고치지 않은 축 18개 중 1개는 반대로 바뀌었다. 표본이 작고 LLM 응답이 실행마다 달라 효과를 주장할 수 없다.
  - 원인: holdout 교정 키 38개 중 승인 규칙이 덮은 것은 8개였고, 그 8개도 출력이 바뀌지 않았다. 교정의 대부분(25/38)은 사람이 '누락'으로 더한 값이다(예: 제품·세대, 공정 모듈). 이런 값은 슬라이드 본문보다 문서 맥락(파일 제목 등)으로 정한 것으로 보이는데, 지금 분류 규칙은 근거를 본문에서만 인용하게 되어 있어 "본문에 근거가 있으면 빠뜨리지 않는다" 식의 규칙으로는 움직이지 않는다.

## 5. 사람이 정할 것

1. 규칙 후보 승인: `workspaces/_feedback/reports/rule_candidates.md`를 보고 다음 `/BEOL-labeling` 1-2에서 고르거나, `python -m labelbot feedback approve --workspace <작업 폴더> --ids FR-…`로 승인한다.
2. 문서 수준 축(제품·세대, 공정 모듈 등)을 문서 맥락으로 붙여도 되는지 정해야 한다. 허용하면 분류 프롬프트의 근거 규칙과 불량 판정(인용 불일치)을 함께 바꿔야 하는 정책 변경이다. 그 전에는 해당 규칙 문장을 `labeling_rules.json`에서 고쳐 시험해 볼 수 있다.
3. 사례 few-shot을 실제로 쓰려면, 사례의 원본 파일이 사외 전송 허용 목록에 있어야 한다(사외 기준). 사내에서는 내부 호스트라 가드가 막지 않는다.
4. 작업 폴더를 지울 때는 `python -m labelbot feedback purge --workspace <아무 작업 폴더> --source-ws <지울 작업 폴더 이름>`으로 저장소의 사례 본문도 지운다.

## 6. 바뀐 파일 (커밋하지 않음)

- 새 파일: `labelbot/feedback.py`, `tests/test_feedback.py`, 이 보고서.
- 고친 파일: `labelbot/pipeline.py`, `labelbot/classify.py`, `labelbot/label.py`, `labelbot/embed.py`, `labelbot/store.py`, `labelbot/workspace.py`, `labelbot/cli.py`, `prompts/classify.md`, `prompts/label.md`, `.claude/skills/BEOL-labeling/SKILL.md`, `.claude/skills/BEOL-labeling/scripts/summary.py`, `.claude/skills/BEOL-labeling-feedback/SKILL.md`, `plan.md`, `PRD.md`, `README.md`.
- 생성된 데이터(커밋 제외): `workspaces/_feedback/`, `workspaces/261004_BEOL_feedback-eval_20261005/`.
