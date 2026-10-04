---
name: BEOL-labeling-feedback
description: BEOL-labeling이 띄운 검수 화면(review.html)·파싱 대조 화면(compare.html)의 교정을 labelbot에 반영하고, 화면·리포트를 다시 만들고, 임베딩 후 Supabase에 적재한다. 화면에서 체크만 했어도 Downloads의 JSON을 inbox/로 옮기고, 내려받지 않았으면 브라우저 패널의 검수 탭에서 내려받기까지 확인을 받아 처리한다. 사용자가 "검수 끝났어", "체크 다 했어", "검수 반영해줘", "피드백 반영", "inbox에 넣었어", "교정 없음, 적재해줘", "대조 결과 반영", "Supabase 올려줘"라고 하거나 /BEOL-labeling-feedback을 부르면 이 스킬을 쓴다. 파싱·라벨링을 새로 돌리는 일은 BEOL-labeling이 맡는다.
---

# BEOL-labeling-feedback: 사람 검수 반영 → 적재

`/BEOL-labeling`이 검수 대기에서 멈춘 뒤 이어서 쓴다. 사람이 남긴 교정과 대조 기록을 반영하고, 확정된 라벨로 Supabase에 올린다. LLM 분류·라벨링은 다시 부르지 않는다(임베딩만 호출).

## 고정 값

- 코드 폴더: `C:\Users\dltkd\Desktop\261004 BEOL AX day2`. 모든 명령은 여기서 `PYTHONIOENCODING=utf-8`을 붙여 실행한다.
- 작업 폴더 `<WS>`: 인자로 받는다. 없으면 이 대화에서 `/BEOL-labeling`이 쓴 작업 폴더를 쓴다. 그것도 모르면 `C:\Users\dltkd\Desktop\261004_BEOL_*` 중 `work.sqlite`가 있고 가장 최근에 바뀐 폴더를 고르고, 어느 폴더를 골랐는지 보고에 적는다.
- 교정 파일 위치: `<WS>\inbox\review_<실행ID>.json`, `<WS>\inbox\compare_<실행ID>.json`.
- 요약 스크립트: `.claude/skills/BEOL-labeling/scripts/summary.py`.
- 교정 파일 모으기 스크립트: `.claude/skills/BEOL-labeling-feedback/scripts/collect_inbox.py`.

## 지켜야 할 것과 이유

- JSON은 `python -m labelbot apply`가 `read_input`으로 읽는다. Read 도구, `cat`, `cp`로 열거나 복사하지 않는다. 사람 입력은 한 곳에서만 연다는 `CLAUDE.md` 규칙 때문이다.
- Downloads → inbox 이동은 `collect_inbox.py`로만 한다. 이 스크립트는 같은 드라이브 안에서 이름만 바꾸고(`os.replace`) 내용은 열지 않는다. `CROSS_DEVICE`가 나오면 복사로 우회하지 말고 사용자에게 옮겨 달라고 안내한다.
- 검수 화면의 체크는 그 브라우저의 `localStorage`에만 있고, 밖으로 나가는 길은 화면 서버의 inbox 자동 저장과 **JSON 저장** 버튼(예전 화면은 **JSON 내려받기**)뿐이다. 브라우저 패널에서 그 상태를 볼 때는 건수만 센다(본문·값은 보고하지 않는다). 버튼을 대신 누르는 것은 파일 내려받기이므로 매번 사용자 확인을 받는다.
- 봇은 `taxonomy.xlsx`를 고치지 않는다. 검수 중 등록한 동의어는 `reports/candidates.md`의 "검수 등록" 행으로만 나오며, 시트에 붙여넣는 것은 사람 몫이고 다음 실행에 반영된다. 검수 중 남긴 taxonomy 재검토 요청은 `reports/taxonomy_revisit.md`로만 나오며 처리됨 판정은 없다. 라벨과 `label_hash`를 바꾸지 않으므로 Supabase 재적재도 없다.
- 재검토 메모에는 사내 본문이 들어 있을 수 있다. `reports/taxonomy_revisit.md`·`.jsonl`을 Read·Grep·`cat`으로 열어 보고하지 않고, `revisit_requests`의 `memo`·`proposed_*` 열을 SELECT하지 않는다. 검수 탭에는 `get_page_text`·`read_page`·스크린샷을 쓰지 않는다(1-3의 건수 스니펫만 허용하며 `javascript_tool`은 `revisits.length`만 읽는다). 위치와 건수(요약의 `revisits`)만 보고한다.
- 보고에는 건수, 실행 ID, 사유 코드만 쓴다.

## 진행 현황 표시

시작할 때(0%)와 아래 milestone이 끝날 때마다 진행 현황 블록을 응답 텍스트로 보여 준다. 임베딩은 호출 수에 따라 길어질 수 있으므로 백그라운드로 돌리고 끝나면 갱신한다.

| # | milestone | 끝나는 신호 | 누적 |
|---|---|---|---|
| 1 | 교정 파일 모으기 | 1-2 `collect_inbox.py` 출력(1-3을 했으면 그 뒤) | 15% |
| 2 | 교정 반영 | `[apply] …` 줄(교정 없음이면 건너뜀 표시) | 30% |
| 3 | 화면·리포트 재생성 | `report` 명령 끝 | 45% |
| 4 | 임베딩 | `embed` 명령 끝 | 75% |
| 5 | Supabase 적재 | `[push-vectors] …` 줄 | 90% |
| 6 | 보고 | `summary.py` 출력과 보고 | 100% |

블록 형식(두 줄, 막대는 10칸이며 채운 칸 = 누적% ÷ 10을 내림한 값):
```
**진행 현황 · BEOL-labeling-feedback** `████░░░░░░ 45%` (run_id: <RUN>)
✓ 교정 파일 모으기 · ✓ 교정 반영 · ✓ 화면·리포트 재생성 · ▶ 임베딩 · ○ Supabase 적재 · ○ 보고
```
- `✓` 완료, `▶` 진행 중, `○` 대기, `✗` 실패, `–` 건너뜀(예: "교정 없음"이라 반영 생략, `supabase.enabled=false`라 적재 생략). 건너뛴 단계도 누적%에는 넣는다.
- 1-3·1-4에서 사용자 확인이나 조치를 기다리며 멈추면, 그 milestone을 `▶`로 둔 블록과 함께 "사용자 조치 대기"라고 적는다. 오류로 멈추면 그 milestone을 `✗`로 둔 블록을 보여 주고 도달한 %를 그대로 둔다.
- 블록에는 건수·실행 ID·사유 코드만 쓴다. 파일명·본문·재검토 메모는 넣지 않는다. 상태가 바뀔 때만 다시 보여 준다.

## 절차

각 단계가 끝나면 위 "진행 현황 표시"의 블록을 갱신해 보여 준다.

### 1. 상태 확인과 교정 파일 모으기

사용자는 화면에서 체크만 하고 이 스킬을 부를 수 있다. 내려받기·이동은 아래 순서로 스킬이 맡는다.

**1-1. 실행 ID 확인**
```bash
python ".claude/skills/BEOL-labeling/scripts/summary.py" --workspace "<WS>"
```
`run_id`를 `<RUN>`으로 쓴다.

화면 서버(`labelbot serve`)로 연 화면은 체크할 때마다 inbox에 바로 저장하므로 보통은 1-1 뒤 inbox에 이미 파일이 있다. 1-2·1-3은 화면을 로컬 파일이나 예전 `http.server`로 열어 inbox에 저장되지 않았을 때를 위한 대비다. 그래도 1-2는 항상 돌린다(옮길 것이 없으면 아무것도 하지 않는다).

**1-2. Downloads에서 inbox로 옮기기**
```bash
python ".claude/skills/BEOL-labeling-feedback/scripts/collect_inbox.py" --workspace "<WS>" --run <RUN>
```
출력의 `moved`(이번에 옮긴 수), `inbox`(inbox에 있는 수), `skipped`(사유 코드별)를 본다. 이번 실행 ID가 아닌 파일(이전 실행의 `review_*.json` 등)은 건드리지 않는다.

**1-3. 화면에만 남은 체크 확인** — `inbox.review`가 0이고 사용자가 "교정 없음"이라고 하지 않았을 때만 한다(대조는 선택이므로 `inbox.compare`가 0이어도 이 단계를 하지 않는다. 단, 대조 탭에 표시가 있으면 함께 내려받는다).

1. 브라우저 패널(`tabs_context`)에서 주소가 `localhost:<포트>/review.html`인 탭을 찾는다. 없으면 4로 간다.
2. 그 탭에서 `javascript_tool`로 건수만 센다(읽기 전용).
   ```js
   (() => { const o = JSON.parse(localStorage.getItem("labelbot_review_<RUN>") || "{}");
     return {edits: Object.keys(o.edits || {}).length, status: Object.keys(o.status || {}).length,
             syns: (o.syns || []).length, revisits: (o.revisits || []).length}; })()
   ```
   `compare.html` 탭이 있으면 `labelbot_compare_<RUN>`의 `marks` 수도 같은 방식으로 센다.
3. 합계가 1 이상이면 `AskUserQuestion`으로 "검수 탭의 체크 n건을 JSON으로 내려받아 inbox로 옮길까요?"(대조 표시가 있으면 함께)라고 묻는다. 승인하면 그 탭의 **JSON 저장** 버튼(예전 화면은 **JSON 내려받기**)을 `find`로 찾아 누르고, 1-2를 다시 돌린다.
   - 다시 돌려도 `moved`가 0이면 브라우저 패널의 내려받기가 Downloads로 가지 않은 것이다. 사용자에게 그 탭에서 버튼을 직접 눌러 달라고 안내하고 멈춘다.
   - 합계가 0이면 화면에 체크가 없는 것이다. 4로 간다.
4. 그래도 `inbox.review`가 0이면: 사용자가 쓰는 브라우저(예: 사용자의 Chrome)에서 체크했다면 그 브라우저에서 **JSON 저장**(예전 화면은 **JSON 내려받기**)을 눌러 달라고 안내하고 멈춘다. 그 브라우저의 체크는 이 스킬이 볼 수 없다.

- 사용자가 "교정 없음/검수 완료"라고 했고 inbox가 비었다면: 2단계를 건너뛰고 3단계로 간다.
- `skipped`에 `CROSS_DEVICE`·`MOVE_FAILED`가 있으면 건수를 보고하고 그 파일을 `<WS>\inbox\`로 옮겨 달라고 안내한다.

### 2. 반영

파일이 있는 종류만 실행한다.
```bash
python -m labelbot apply --workspace "<WS>" --kind compare
python -m labelbot apply --workspace "<WS>" --kind review
```
출력 한 줄마다 `<종류> 파일 <sha> run_id=<실행ID>: <코드> (<건수>건)`이다.

| 코드 | 뜻 | 할 일 |
|---|---|---|
| `OK` | 반영됨 | 계속 |
| `SUPERSEDED` | 같은 실행의 더 최근 검수 파일이 있어 건너뜀 | 정상. 최신 파일이 그 실행의 교정 전체를 대신한다 |
| `NO_FLAGGED_FOR_RUN` | 그 실행 ID로 만든 검수 목록이 없음 | 다른 작업 폴더의 파일이거나 오래된 화면에서 받은 파일이다. 사용자에게 확인하고 그 파일은 반영하지 않는다 |
| `FORMAT_INVALID`, `JSON_INVALID` | 형식 오류 | 화면에서 다시 내려받아 달라고 안내. 같은 `apply`의 다른 파일 반영은 되돌려지지 않는다(파일별 `SAVEPOINT`) |
| `REVISIT_CHUNK_NOT_FLAGGED` | 그 실행의 불량 목록에 없는 chunk의 재검토 요청 | 그 항목만 버림, 파일은 `OK`. 건수만 보고 |
| `REVISIT_REASON_INVALID` | 알 수 없는 대상·사유이거나 허용 조합 밖 | 그 항목만 버림, 파일은 `OK` |
| `REVISIT_FIELD_INVALID` | 형식·필수 칸 오류(키 규칙, 제안 값, 관련 값, 예약어, 필수 메모 없음) | 그 항목만 버림, 파일은 `OK` |
| `REVISIT_DUPLICATE` | 한 문서 안의 같은 `(chunk, 대상, 키)` | 앞 항목만 버림(뒤 항목 저장), 파일은 `OK` |
| `REVISIT_MEMO_TRUNCATED` | 메모가 500자 초과 | 500자로 잘라서 저장 |

`OK`인 review 줄의 실행 ID를 `<RUN>`으로 쓴다. 없으면 1단계 요약의 `run_id`를 쓴다.

### 3. 화면·리포트 다시 만들기 (LLM 호출 0회)

```bash
python -m labelbot review --workspace "<WS>" --run <RUN>
python -m labelbot dashboard --workspace "<WS>" --run <RUN>
python -m labelbot report --workspace "<WS>" --run <RUN>
```
대시보드는 사람 교정이 반영된 확정 라벨로 다시 그려진다.

### 4. 임베딩과 Supabase 적재

```bash
python -m labelbot embed --workspace "<WS>" --run <RUN>
python -m labelbot push-vectors --workspace "<WS>" --run <RUN>
```
- `embed`는 이미 만든 벡터면 호출 0회다.
- `push-vectors`는 확정 라벨(사람 교정 우선)로 올린다. 이미 같은 라벨로 올라간 chunk는 다시 보내지 않으므로, 두 번째 실행부터는 라벨이 바뀐 chunk만 전송된다.
- 전송 실패는 사유 코드로 남고 반영 결과에는 영향이 없다. 실패하면 사유 코드를 보고한다.
- `supabase.enabled=false`(요약의 `supabase_enabled: false`)면 `push-vectors`가 "호출하지 않습니다"만 출력하고 끝난다. 이 경우에도 `embed`는 돌린다. 로컬 `chunk_embeddings`가 원본이고 Supabase는 사본이므로, 로컬 벡터를 먼저 만들어 두면 나중에 적재를 켰을 때 바로 올릴 수 있다. 보고에는 "Supabase 적재 꺼짐(supabase.enabled=false)"이라고 쓴다.

### 5. 보고

```bash
python ".claude/skills/BEOL-labeling/scripts/summary.py" --workspace "<WS>" --run <RUN>
```
아래 형식으로 보고한다.

```
## 검수 반영 결과 (run_id: <RUN>, 작업 폴더: <WS>)
- 모은 파일: Downloads에서 옮긴 review n, compare n (1-3에서 대신 내려받았으면 그렇다고 적는다)
- 반영한 파일: 종류별 코드와 건수
- 교정: 축 n, 질문 n / 확인(이상 없음) n / 판단 불가(이미지) n / 재검수 필요 n
- 파싱 대조: 이상 없음 n, 이상 있음 n (이상 슬라이드는 파서 보강 대상)
- 검수 등록 동의어 n → reports/candidates.md "검수 등록" 행을 synonyms 시트에 붙여넣으면 다음 실행에 반영
- taxonomy 재검토 요청: 이번 실행 n, 누적 m → reports/taxonomy_revisit.md (버린 항목이 있으면 `REVISIT_*` 코드별 건수)
- Supabase: 전송 n행, 건너뜀 n, 차단 n (누적 적재 chunk n) 또는 "적재 꺼짐(supabase.enabled=false)"
```

각 칸의 출처: 교정은 요약의 `corrections`(`axis`, `answer`, `confirmed`, `undecidable_image`, `recheck`), 파싱 대조는 `compare_marks`(`ok`, `issue`), 검수 등록 동의어는 `review_synonyms`, 재검토는 `revisits`(이번 실행 `run`, 누적 `total`, 검수 실행 수 `runs`, 사유별 `by_reason`), 누적 적재는 `pushed_ok`, 전송·건너뜀·차단은 4단계 `push-vectors` 출력이다. 요약에 없는 값을 추정해서 채우지 않는다.

브라우저 패널에 화면 서버가 떠 있으면 `results.html` 탭을 새로고침해 바뀐 대시보드를 보여 준다.
