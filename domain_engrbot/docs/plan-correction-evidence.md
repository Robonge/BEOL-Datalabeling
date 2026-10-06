> 2026-10-06 이름 변경: Engr-bot → Domain-Engr-bot(`domain_engrbot`), code-bot → Code-Engr-bot(`code_engrbot`). 아래 본문은 이력이라 옛 이름을 그대로 둔다.

> 이력 문서다(2026-10-06 이전 개념). Engr-bot의 현재 개념은 `engrbot/docs/plan-question-loop.md`를 본다.

# 검수 교정에 근거 남기기 → Engr-bot 최종 검수 → 라벨링 피드백

작성 2026-10-05 · 상태: 구현 중 · 관련: `plan-ledger.md`, `plan-labeling-return.md`

## 1. 왜

승인된 규칙(29)·사례(23)에는 "사람이 파일의 어느 부분을 보고 고쳤는지"가 없다. 규칙은 "봇이 놓친 값을 사람이 n건 더했다"뿐이고,
사례는 본문 앞부분과 봇→사람 값만 있다. 이전 실측에서 규칙이 덮은 교정 8/38, 출력 변화 0이었고, 교정의 25/38은 본문이 아니라
문서 맥락(파일명·제목·다른 슬라이드)으로 정하는 축이었다. 근거가 없으면 LLM은 "무엇을 보고 고쳐야 하는지"를 배울 수 없다.

## 2. 사용자 결정 (2026-10-05)

| # | 결정 |
|---|---|
| E1 | 근거 = 종류 + 인용 + 이유. 위치는 **같은 슬라이드 또는 같은 파일의 다른 슬라이드의 특정 부분을 드래그**해 지정한다(파일명·문서 제목 줄도 드래그 대상). 이유는 선택 입력 |
| E2 | 근거는 선택. 근거 없는 교정은 **규칙 건수에만** 쓰고 사례(few-shot)에는 쓰지 않는다 |
| E3 | Engr-bot 최종 검수 화면에 근거 인용(본문 일부)을 보여 준다. 화면은 `workspaces/_engrbot/ledger/`(git 제외)에만 있고 Claude는 내용을 열어 보고하지 않는다 |
| E4 | 기존 승인 규칙 29·사례 23은 기록을 두고 모두 끈다(`enabled=false`). 후보는 근거 있는 교정이 1건 이상인 패턴만 올린다 |
| F1 | 최종 검수는 Engr-bot에만 둔다(`BEOL-labeling`은 건수만 알림). 앞선 결정 |

## 3. 계약 (labelbot ↔ engrbot)

### 3.1 검수 JSON (`inbox/review_<RUN>.json`) — corrections 항목에 두 키 추가

```json
{"chunk_id": "...", "target": "axis", "key": "제품·세대", "value": ["SF1.0"], "status": "corrected",
 "evidence": [{"source": "chunk", "chunk_id": "<같은 파일의 chunk>", "quote": "드래그한 문장"},
              {"source": "doc_title", "quote": "..."}],
 "reason": "파일 제목의 세대 표기로 판단"}
```

- `source`: `chunk`(같은 파일의 아무 슬라이드, `chunk_id` 필수, 교정 chunk 자신이면 같은 슬라이드) · `file_name` · `doc_title`.
- `evidence`·`reason`은 없어도 된다(E2). 한 교정에 근거 최대 3개, 인용 2~300자(공백 정규화 뒤), 이유 300자 이내.
- 같은 근거를 여러 축 교정에 붙일 수 있다(화면에서 "이 근거를 다른 고친 축에도").

### 3.2 `labelbot apply` 검증과 저장

- 근거 항목마다: `chunk`면 그 chunk가 교정 chunk와 **같은 파일**이고 인용이 그 chunk의 제목·본문에 있어야 한다(공백 정규화 일치).
  `file_name`은 파일명·상대 경로, `doc_title`은 문서 제목에 있어야 한다. 안 맞는 항목은 버리고 센다(`EVIDENCE_QUOTE_NOT_FOUND`, `EVIDENCE_OTHER_FILE`, `EVIDENCE_FORMAT`).
- `corrections` 새 열(추가형 마이그레이션): `evidence TEXT`(검증 통과 항목 JSON 목록 `[{source, chunk_id, slide_no, quote}]`, 없으면 NULL),
  `reason TEXT`(300자 이내, 없으면 NULL), `evidence_dropped INTEGER`(버린 항목 수).
- 이 열들에는 본문 인용이 들어간다. `work.sqlite`는 원래 본문을 담는 곳이라 새 위험이 아니다. 로그에는 건수·사유 코드만 쓴다.

### 3.3 Engr-bot 장부

- `cases.jsonl`(본문 없음 유지): `evidence_sources`(예: `["chunk_same", "chunk_other", "file_name", "doc_title"]`)·`has_reason` 추가.
- 새 `evidence.jsonl`(본문 인용 있음, golden·judge_examples와 같은 취급): `{case_id, source_ws, labeler_run_id, record_id, field, evidence, reason}`.
  Claude는 열지 않는다.

### 3.4 라벨링 규칙·사례 (`engrbot/labeling_rules.py`, 승인 파일 v3)

- 규칙 후보: 지지 건수는 근거 유무와 관계없이 센다. 단 근거 있는 지지 레코드가 `min_evidence`(기본 1) 이상인 패턴만 후보.
  규칙에 `evidence_count`, `evidence_mix`(근거 위치 종류별 건수)를 두고, 규칙 문장에 "근거 위치: 문서 제목 n건, 다른 슬라이드 n건…"을 붙인다.
- 사례 후보: 근거 있는 교정 축이 하나 이상인 레코드만. 승인 파일에는 참조만 둔다(본문·인용 없음, git 추적 유지).
- 승인 파일의 규칙 문장에는 인용을 넣지 않는다(본문 없음 원칙).

### 3.5 labelbot 소비 (`labelbot/feedback.py`)

- 사례를 풀 때 원래 작업 폴더 `corrections`에서 그 chunk의 `evidence`·`reason`을 읽기 전용으로 가져온다.
- 사례 블록에 줄을 더한다: `근거(제품·세대): [문서 제목] '…' · [다른 슬라이드 4] '…' / 이유: …`(인용 200자 상한).
- 프롬프트 치환 순서 문제를 막기 위해 피드백 블록(규칙·사례)의 `{{`·`}}`는 치환 전에 무력화한다.

### 3.6 Engr-bot 최종 검수 화면

- 규칙 카드: 지지 레코드별 근거(위치 종류·슬라이드·인용·이유, 최대 5건). 사례 카드: 고친 축마다 근거.
- 보안 지적 반영: 결정 파일은 화면 digest와 같아야 반영(`DECISIONS_STALE`), 화면에 있던 ID만 결정 가능(`DECISIONS_ID_NOT_ON_SCREEN`),
  결정 파일 1MB 상한, `RecursionError` 처리, 규칙 문장의 `{{`·`}}`·제어 문자 거부, 스킬은 결정 파일을 고른 뒤 사용자에게 확인.

## 4. 작업 패키지

| WP | 내용 | 소유 |
|---|---|---|
| L1 | `labelbot/store.py` 열 추가, `labelbot/review.py`(화면 DATA에 같은 파일 슬라이드 텍스트·파일명·문서 제목, apply 검증·저장) | labelbot |
| L2 | `labelbot/screens/review.html` 근거 UI(드래그, 같은 파일 슬라이드 텍스트 패널, 이유 입력, 다른 축에 복사) | labelbot |
| L3 | `labelbot/feedback.py` 사례 근거 줄, `{{` 무력화 | labelbot |
| G1 | `engrbot/ledger.py` cases 근거 요약, `evidence.jsonl` | engrbot |
| G2 | `engrbot/labeling_rules.py` 근거 요건·mix·문장 | engrbot |
| G3 | `engrbot/labeling_review.py`·화면: 근거 표시, 보안 지적 반영 | engrbot |
| D1 | 기존 승인 29·23 끄기(사용자 결정 E4, `labeling-rules apply` 결정 파일로 기록) | 사람 결정 실행 |
| D2 | 스킬(`BEOL-labeling-feedback` 검수 안내, `BEOL-labeling-Engr-bot`), `plan.md`·`PRD.md` | 문서 |

검증: 각 단위 테스트, 합성 작업 폴더로 검수 JSON(근거 포함) → apply → intake → 후보 → 화면 → 결정 → labelbot 사례 블록까지 끝에서 끝,
codebot review, 보안·코드 리뷰.
