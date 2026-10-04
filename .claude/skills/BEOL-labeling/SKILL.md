---
name: BEOL-labeling
description: BEOL 공정 문서(pptx·docx) 폴더를 labelbot 워크플로로 파싱부터 분류·라벨링까지 돌리고, 파싱 대조·검수·결과 대시보드 화면을 띄운 뒤 사람 검수 대기에서 멈춘다. 사용자가 폴더 경로를 주며 "라벨링 돌려줘", "파싱부터 라벨링까지", "이 폴더 처리해줘", "BEOL 라벨링", "파일럿 돌려줘", "workflow대로 돌려줘"라고 하거나 /BEOL-labeling을 부르면 이 스킬을 쓴다. 기본 입력 폴더는 저장소의 'parshing test files'다. 검수 JSON을 반영하는 일은 BEOL-labeling-feedback이 맡는다.
---

# BEOL-labeling: 파싱 → 분류·라벨링 → 검수 대기

labelbot 파이프라인(`plan.md` 워크플로)을 한 폴더에 돌린다. 사람 개입 지점 중 **불량 chunk 검수(H6)에서 멈추고**, 사람이 검수를 마치면 `/BEOL-labeling-feedback`이 이어서 반영·적재한다.

```
[이 스킬] 준비 → 사전 점검 → 수집·파싱 → 1~3차 분류·라벨링 → 불량 목록 → 화면 3개 → 멈춤(검수 대기)
[BEOL-labeling-feedback] 대조·검수 JSON 반영 → 화면·리포트 재생성 → 임베딩 → Supabase 적재
```

## 사람 개입 지점을 이렇게 다룬다 (사용자 결정, 2026-10-04)

| 지점 | 처리 | 이유 |
|---|---|---|
| H2 파싱 대조 | 멈추지 않는다. `compare.html`을 띄워 두고 진행 | 대조는 라벨링과 병행해도 된다(plan.md "계속") |
| H5 분포 알림 | 요약에 보여 주고 진행 | 알림은 원인 점검용이며 라벨링을 막지 않는다 |
| H3·H8 새 값·동의어 후보 | 건수와 리포트 위치만 알리고 **이번에 재실행하지 않는다** | 후보는 다음 실행으로 넘긴다. taxonomy 재검토 요청 리포트(`reports/taxonomy_revisit.md`)도 같은 방식으로 다음 실행에 넘긴다. 봇은 taxonomy.xlsx를 고치지 않는다 |
| H6 불량 chunk 검수(재검토 요청 포함) | **여기서 멈춘다** | 사람 값이 최종 라벨이 되고, Supabase 적재는 검수 후에만 한다. 재검토 요청은 라벨을 바꾸지 않는다 |

Supabase 적재는 이 스킬에서 하지 않는다. 검수 전 라벨이 사본에 올라가지 않게 하려는 결정이다.

## 고정 값

- 코드 폴더: `C:\Users\dltkd\Desktop\261004 BEOL AX day2`. 모든 명령은 여기서 `PYTHONIOENCODING=utf-8`을 붙여 실행한다.
- 입력 폴더: 인자로 받는다. 없으면 `parshing test files`(코드 폴더 기준 상대 경로, 폴더명 철자 그대로).
- 작업 폴더: `C:\Users\dltkd\Desktop\261004_BEOL_<입력 폴더 slug>`(코드 폴더 밖). 사용자가 지정하면 그 경로.
- taxonomy: 저장소의 `defaults/taxonomy.xlsx`를 직접 가리킨다.
- 모델: `gpt-6-sol`(temperature 미전송, `max_completion_tokens`). 키는 코드 폴더 `.env`에서 읽는다.

## 지켜야 할 것과 이유

- 원본 파일을 Read 도구나 `cat`·`cp`로 열지 않는다. 사내 파일은 DRM이 걸려 있어 `labelbot.ingest.read_input` 한 곳에서만 연다는 것이 `CLAUDE.md`의 최우선 규칙이고, 사외에서도 같은 습관을 유지해야 사내 반입 때 깨지지 않는다.
- 보고에는 건수, 실행 ID, 사유 코드만 쓴다. 본문과 파일명은 화면(HTML) 안에서만 본다.
- 사외 호스트(OpenAI, Supabase)에는 더미 해시 목록(`tests/gold/dummy_hashes.jsonl`)에 있는 파일만 보낸다. 목록 밖 파일은 labelbot이 그 호출을 막고 `EXTERNAL_NON_DUMMY`를 남긴다. 이것은 정상 동작이므로 우회하지 말고 보고한다.
- `taxonomy.xlsx`와 `pipeline.json`의 모델·안전 설정을 마음대로 바꾸지 않는다.
- 재검토 요청의 메모에는 사내 본문이 들어 있을 수 있다. `reports/taxonomy_revisit.md`·`.jsonl`을 Read·Grep·`cat`으로 열지 않고, `revisit_requests`의 `memo`·`proposed_*` 열을 SELECT하지 않으며, 검수 탭을 `get_page_text`·`read_page`·스크린샷으로 읽지 않는다. 건수와 위치만 보고한다.

## 진행 현황 표시

사용자가 어디까지 왔는지 알 수 있도록, 시작할 때(0%)와 아래 milestone이 끝날 때마다 진행 현황 블록을 응답 텍스트로 보여 준다. 실행이 길어지는 3단계는 출력의 단계 줄을 감시해 중간에도 갱신한다.

| # | milestone | 끝나는 신호 | 누적 |
|---|---|---|---|
| 1 | 준비 | `init_workspace.py`가 `workspace`를 출력 | 5% |
| 2 | 사전 점검 | `결과: 전 항목 PASS` | 10% |
| 3 | 수집·파싱 | `[ingest] 파일 …` 줄 | 20% |
| 4 | 1차 분류 | `[classify] …` 줄 | 40% |
| 5 | 2차 검증 질문 | `[question] …` 줄 | 55% |
| 6 | 3차 라벨링 | `[label] …` 줄과 `[run] 완료` | 80% |
| 7 | 화면 만들기 | `dashboard` 명령 끝 | 85% |
| 8 | 요약 | `summary.py` 출력 | 90% |
| 9 | 화면 띄우기 | 탭 열기 끝(또는 URL 안내) | 95% |
| 10 | 검수 대기 | 사용자 안내 출력 | 100% |

블록 형식(두 줄, 막대는 10칸이며 채운 칸 = 누적% ÷ 10을 내림한 값):
```
**진행 현황 · BEOL-labeling** `███████░░░ 70%` (run_id: <RUN 또는 ->)
✓ 준비 · ✓ 사전 점검 · ✓ 수집·파싱 · ✓ 1차 분류 · ✓ 2차 검증 질문 · ▶ 3차 라벨링 · ○ 화면 만들기 · ○ 요약 · ○ 화면 띄우기 · ○ 검수 대기
```
- `✓` 완료, `▶` 진행 중, `○` 대기, `✗` 실패. 진행 중 단계가 있으면 % 옆에 그 단계 출력의 건수 한 마디를 붙일 수 있다(예: `classify 48/48`). 파일명·본문은 넣지 않는다.
- 3단계 `labelbot run`은 백그라운드로 돌리고, `Monitor`로 출력 파일에서 `^\[(ingest|classify|question|label|run)\]|^\[오류\]` 줄을 감시한다. 줄이 올 때마다 해당 milestone을 `✓`로 바꾸고 다음을 `▶`로 둔 블록을 다시 보여 준다. 실행 중에는 `▶` 단계의 누적%를 바로 앞 단계 값으로 둔다(완료 전에 그 단계 %를 올리지 않는다).
- 멈추는 경우(점검 FAIL, `[오류]`, `error`)에는 그 milestone을 `✗`로 표시한 블록을 보고 앞에 한 번 보여 주고, 도달한 %를 그대로 둔다.
- 같은 블록을 연속으로 반복하지 않는다. 상태가 바뀔 때만 보여 준다.

## 절차

`<S>` = `.claude/skills/BEOL-labeling/scripts`, `<WS>` = 작업 폴더, `<IN>` = 입력 폴더. 각 단계가 끝나면 위 "진행 현황 표시"의 블록을 갱신해 보여 준다.

### 1. 작업 폴더 준비

```bash
python "<S>/init_workspace.py" --input "<IN>"
```
출력 JSON의 `workspace`, `launch_name`, `port`, `file_counts`를 기억한다. `pipeline_written=false`면 기존 설정을 그대로 쓴다(같은 폴더를 다시 돌리면 LLM 캐시 덕분에 바뀐 부분만 호출된다). `file_counts`에 pptx·docx가 아닌 형식이 있으면 그 파일은 `UNSUPPORTED_FORMAT`으로 실패 목록에 들어간다고 미리 알린다. `error`가 나오면 멈추고 보고한다.

### 2. 사전 점검

```bash
python -m labelbot selfcheck --workspace "<WS>" --probe-llm
```
`결과: 전 항목 PASS`가 아니면 FAIL 항목과 사유 코드를 보고하고 멈춘다(키 누락, 모델명, 네트워크 등은 사람이 고쳐야 한다).

### 3. 파싱부터 라벨링까지

```bash
python -m labelbot run --workspace "<WS>"
```
LLM 호출은 chunk당 3회(1차 분류·2차 검증 질문 생성·3차 라벨링)이고 6개씩 병렬이라, 파일 10개(chunk 50개 안팎)면 약 4~7분 걸린다. 백그라운드로 실행하고, `Monitor`로 단계 줄을 감시해 milestone 3~6의 진행 현황을 갱신하면서 끝날 때까지 기다린다. `[run] 완료 run_id=...`가 나와야 끝난 것이고, 출력의 `run_id`를 `<RUN>`으로 쓴다.

실패 신호는 0이 아닌 종료 코드와 `[오류]`로 시작하는 줄이다. 이때 그 줄을 그대로 보고하고 멈춘다. 개별 chunk 실패는 실행을 멈추지 않고 `failures` 표에 사유 코드로 남으며 5단계 요약에 나온다. `<WS>/logs/labelbot.log`에는 파일 수집·파싱과 LLM 호출(분류·라벨링) 실패만 파일 ID·chunk ID와 사유 코드로 기록되고, 처음 실패가 날 때 생긴다. 파일이 없으면 그런 실패가 없었다는 뜻이다(날짜·담당자 추출 경고는 DB에만 남는다).

### 4. 화면 만들기 (LLM 호출 0회)

```bash
python -m labelbot compare --workspace "<WS>" --run <RUN>
python -m labelbot review --workspace "<WS>" --run <RUN>
python -m labelbot dashboard --workspace "<WS>" --run <RUN>
```

### 5. 요약

```bash
python "<S>/summary.py" --workspace "<WS>" --run <RUN>
```
이 JSON으로 아래 형식의 요약을 쓴다.

```
## 라벨링 결과 (run_id: <RUN>)
- 파일 N개(실패 M: 사유별), chunk N개, 분류·라벨 실패 N
- 불량 chunk N개: 사유별 건수
- Q-COM-001 답: O n / X n / N/A n
- 분포 알림(H5): 알림마다 한 줄씩 "조건: 값(기준)" — 원인 점검 대상(라벨링은 끝까지 돌았다). 없으면 "없음"
- 추출 경고: `extract:*` 사유 코드별 건수(날짜·담당자 값을 저장하지 않은 건수. 라벨에는 영향 없음). 없으면 생략
- 후보: 새 값 n, 동의어 n → 다음 실행으로 넘김(reports/candidates.md)
- taxonomy 재검토 요청: 누적 n(reports/taxonomy_revisit.md, 출처 summary의 revisits). 리포트는 열어 보고하지 않는다
- Supabase: 아직 적재하지 않음(검수 후 BEOL-labeling-feedback에서 적재)
```
`failures`에 `EXTERNAL_NON_DUMMY`가 있으면 "더미 해시 목록 밖 파일이라 사외 LLM 호출이 막혔다"고 따로 적는다.

### 6. 화면 띄우기

브라우저 패널에서 `launch_name`으로 화면 서버를 시작하고(`preview_start` name=`<launch_name>`), 탭 세 개를 연다.
- `http://localhost:<port>/results.html` — 결과 대시보드(먼저 보여 줄 탭)
- `http://localhost:<port>/review.html` — 검수 화면(불량 chunk 전부)
- `http://localhost:<port>/compare.html` — 파싱 대조 화면

화면 서버는 `labelbot serve`다(`init_workspace.py`가 launch.json에 등록). 이 서버로 연 검수·대조 화면은 체크할 때마다 교정 JSON을 **`<WS>\inbox\`에 바로 저장**한다(화면 상단 상태 줄에 "inbox 저장됨 시각"). 그래서 사람은 내려받기·이동을 하지 않아도 된다. `preview_start`가 "Port in use by another chat"으로 실패하면, 그 포트의 서버가 예전 `http.server`일 수 있다. 이 경우 화면은 보이지만 inbox 자동 저장은 되지 않으므로, 그 대화에서 서버를 끄거나 이 대화에서 다시 띄워 달라고 사용자에게 알린다.

새 탭을 열 수 없으면(탭 수 한도 등) 이전 실행의 화면 탭(주소가 `localhost:<포트>/results.html`·`review.html`·`compare.html`인 탭)을 이 화면으로 navigate해서 다시 쓴다. 사용자의 다른 탭은 닫지 않는다. 그래도 세 개를 다 열 수 없으면 대시보드를 우선 열고 나머지는 URL로 알려 준다. 브라우저 패널을 쓸 수 없으면 `<WS>\screens\` 아래 세 파일 경로를 알려 준다(로컬 파일로 바로 열린다).

### 7. 검수 대기로 넘기기

마지막에 사용자가 할 일을 이 순서로 안내하고 끝낸다.

1. 검수 화면에서 불량 chunk를 확인·교정한다. taxonomy가 맞지 않는 축·질문은 재검토 요청으로 남긴다(메모 500자까지, 라벨은 바뀌지 않으며 맞는 값이 없으면 unknown으로 교정한다). 교정할 것이 없으면 이 단계를 건너뛴다.
2. (선택) 파싱 대조 화면에서 슬라이드마다 이상 여부를 표시한다.
3. `/BEOL-labeling-feedback`을 부른다. 체크만 해 두면 된다: 화면 서버가 체크할 때마다 `<WS>\inbox\`에 `review_<RUN>.json`·`compare_<RUN>.json`을 저장한다. 화면을 로컬 파일(file://)이나 예전 서버로 열어 Downloads에 내려받았다면, 그 파일도 스킬이 inbox로 옮긴다.
4. 교정할 것이 없었다면 "검수 완료, 교정 없음"이라고 말하면 바로 적재까지 진행한다.

검수가 끝나기 전에는 Supabase에 올리지 않는다는 점을 한 줄로 덧붙인다.
