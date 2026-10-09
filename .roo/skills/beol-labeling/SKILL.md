---
name: beol-labeling
description: 'BEOL 공정 문서(pptx·docx) 폴더를 labelbot 워크플로로 파싱부터 분류·라벨링까지 돌리고, 파싱 대조·검수·결과 대시보드 화면을 만들어 결과 대시보드를 띄운 뒤 사람 검수 완료 대기에서 멈춘다. 검수 화면을 열어 달라는 요청에는 이 스킬이 대시보드 URL로 안내한다. 사용자가 폴더 경로를 주며 "라벨링 돌려줘", "파싱부터 라벨링까지", "이 폴더 처리해줘", "BEOL 라벨링", "파일럿 돌려줘", "workflow대로 돌려줘"라고 하면 이 스킬을 쓴다. 기본 입력 폴더는 저장소의 ''parshing test files''다. 검수 완료 뒤 교정 반영·적재하는 일은 BEOL-labeling-feedback이 맡는다.'
---

# BEOL-labeling: 파싱 → 분류·라벨링 → 검수 대기

> 이 문서는 `.claude/skills/BEOL-labeling/SKILL.md`에서 생성됐다. 직접 고치지 말고 원본을 고친 뒤 `python tools/gen_roo_skills.py`를 다시 실행한다.

> 폐쇄망: LLM 호출(M02·M03)·임베딩(M07)·벡터 저장소 적재(M08)·슬라이드 JPG 저장(M10)은 사내 API·벡터 저장소·S3 단계라 게이트 G-API·G-VDB·G-S3 이후 릴리스에서 활성화된다. 그 전에는 이 단계가 설정 누락 사유 코드로 멈추거나 "호출하지 않습니다"로 끝나므로 사유 코드만 보고하고 나머지 단계를 계속한다.

> 그룹: ① 라벨링 파이프라인 · 상위: beol-labeling-run-labeling 스킬 · 하위: 없음 · 전체 지도: README.md "스킬 지도"

labelbot 파이프라인(`plan.md` 워크플로)을 한 폴더에 돌린다. 사람 개입 지점 중 **불량 chunk 검수(H6) 앞에서 멈추고**, 사람이 검수 화면에서 **검수 완료**를 누르면 이 스킬이 완료 신호를 받아 `beol-labeling-feedback` 스킬을 불러 반영·적재한다.

```
[이 스킬] 준비 → (검수 피드백 반영 상태 확인) → 사전 점검 → 수집·파싱 → 1~3차 분류·라벨링(승인된 피드백 규칙·사례 반영) → 불량 목록 → 화면 3개 만들기 → 대시보드 띄우기 → 멈춤(검수 완료 대기)
[BEOL-labeling-feedback] 교정 모으기 → 반영 → Domain-Engr-bot 장부·라벨링 규칙 후보 → 화면·리포트 재생성 → 임베딩 → 벡터 저장소 적재
```

## 사람 개입 지점을 이렇게 다룬다 (사용자 결정, 2026-10-04)

| 지점 | 처리 | 이유 |
|---|---|---|
| H2 파싱 대조 | 멈추지 않는다. `compare.html`은 만들기만 하고 띄우지 않는다. 사람이 대시보드의 **검수 + 파싱 대조** 버튼으로 연다 | 대조는 선택이며 라벨링을 막지 않는다(plan.md "계속") |
| H5 분포 알림 | 요약에 보여 주고 진행 | 알림은 원인 점검용이며 라벨링을 막지 않는다 |
| H3·H8 새 값·동의어 후보 | 건수와 리포트 위치만 알리고 **이번에 재실행하지 않는다** | 후보는 다음 실행으로 넘긴다. taxonomy 재검토 요청 리포트(`reports/taxonomy_revisit.md`)도 같은 방식으로 다음 실행에 넘긴다. 봇은 taxonomy.json을 마음대로 고치지 않는다(사람이 taxonomy 보드·편집기에서 저장한다) |
| 검수 피드백 승인 | 묻지 않는다. 1-2에서 승인분·대기분 건수만 알리고, 대기분은 `beol-labeling-domain-engr-bot` 스킬로 안내한다 | 사람 교정에서 나온 규칙·사례는 사람이 Domain-Engr-bot 질문 화면에서 확정한 것만 1차 분류·3차 라벨링 프롬프트에 들어간다(사용자 결정, 2026-10-05·2026-10-06). 확정 자리는 Domain-Engr-bot 한 곳이다 |
| H6 불량 chunk 검수(재검토 요청 포함) | **이 앞에서 멈춘다.** 검수 화면은 사람이 대시보드 버튼으로 열고, **검수 완료**를 누르면 이 스킬이 완료 신호를 받아 `beol-labeling-feedback` 스킬로 반영·적재를 이어간다 | 사람 값이 최종 라벨이 되고, 벡터 저장소 적재는 검수 후에만 한다. 재검토 요청은 라벨을 바꾸지 않는다 |

벡터 저장소 적재는 이 스킬에서 하지 않는다. 검수 전 라벨이 사본에 올라가지 않게 하려는 결정이다.

## 고정 값

- 코드 폴더: 저장소 루트(`git rev-parse --show-toplevel`, 이 SKILL.md 기준 ../../..). 모든 명령은 여기서 `PYTHONIOENCODING=utf-8`을 붙여 실행한다.
- 입력 폴더: 인자로 받는다. 없으면 `parshing test files`(코드 폴더 기준 상대 경로, 폴더명 철자 그대로).
- 작업 폴더: 실행할 때마다 저장소 루트의 `workspaces/261004_BEOL_<입력 폴더 slug>_<YYYYMMDD-HHMMSS>`로 새로 만든다(모든 작업은 코드 폴더 안). 사용자가 지정하면 그 경로. 새 폴더라 LLM 캐시가 없으므로 매번 전체를 호출한다(사용자 결정, 2026-10-05).
- 처리 완료 파일 목록: 코드 폴더의 `injested-file-list/<작업 폴더 이름>.json`(`files`에 처리를 마친 파일명). 실행 전 중복 확인에 쓴다.
- taxonomy: 저장소의 `taxonomy/taxonomy.json`을 직접 가리킨다(2026-10-07부터 xlsx 대신 json이 원본이다).
- 모델·키: 폐쇄망에서는 사내 OpenAI 호환 API(게이트 G-API 이후 릴리스)를 쓴다. 값은 `workspaces/_site/profile.json`·`beol.env`에 있고, 키 값은 출력하지 않는다.

## 지켜야 할 것과 이유

- 원본 파일을 Read 도구나 `cat`·`cp`로 열지 않는다. 사내 파일은 DRM이 걸려 있어 `labelbot.ingest.read_input` 한 곳에서만 연다는 것이 `CLAUDE.md`의 최우선 규칙이고, 사외에서도 같은 습관을 유지해야 사내 반입 때 깨지지 않는다.
- 보고에는 건수, 실행 ID, 사유 코드만 쓴다. 본문과 파일명은 화면(HTML) 안에서만 본다.
- PoC에서는 사외·사내를 구분하지 않는다(2026-10-05 사용자 결정). 더미 해시 가드는 없고, 호스트를 판정할 수 없는 URL만 `HOST_UNCERTAIN`으로 막힌다.
- `taxonomy.json`과 `pipeline.json`의 모델·안전 설정을 마음대로 바꾸지 않는다.
- 검수 피드백의 확정(규칙·사례 승인과 문장 수정)은 `beol-labeling-domain-engr-bot` 스킬(검수 결과로 엔지니어에게 질문해 도메인 지식을 규칙·taxonomy 제안으로 돌려주는 봇)의 질문 화면에서 사람이 한다. 이 스킬은 `status`로 건수만 보고, `approve`·`reject`·`apply`를 부르지 않으며, `taxonomy/labeling_rules.json`을 고치지 않는다. 승인 파일과 후보 리포트 `workspaces/_domain_engrbot/ledger/labeling_candidates.md`에는 본문이 없어 위치를 링크해도 된다. 장부의 `golden.jsonl`·`judge_examples.jsonl`은 본문 인용이 있으므로 열지 않는다.
- 재검토 요청의 메모에는 사내 본문이 들어 있을 수 있다. `reports/taxonomy_revisit.md`·`.jsonl`을 Read·Grep·`cat`으로 열지 않고, `revisit_requests`는 `COUNT`와 `reason`별 `GROUP BY`만 조회하며(`SELECT *`, `.dump` 금지), inbox JSON과 `inputs/<sha256>.b64`를 열거나 디코딩하지 않고, 검수 탭을 화면 내용 읽기·캡처로 읽지 않는다. 건수와 위치만 보고한다.

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
| 7 | 대시보드 띄우기 | 탭 열기 끝(또는 URL 안내) | 95% |
| 8 | 검수 완료 대기 | 사용자 안내 출력 | 100% |

절차의 "4. 화면 만들기"와 "5. 요약"은 실행하되 진행 현황에는 milestone으로 넣지 않는다(사용자 결정, 2026-10-05). 둘은 milestone 7 "대시보드 띄우기"를 준비하는 과정으로 보고, 끝나도 블록을 따로 갱신하지 않는다. 화면 만들기가 실패하면(`slide-images` 제외) milestone 7을 `❌`로 표시한다.

블록 형식(제목 줄 + 막대 줄 + 지금 줄 + 세로 목록. 막대는 10칸이며 `🟩` 칸 수 = 누적% ÷ 10을 내림한 값, 나머지는 `⬜`):
```
**진행 현황 · BEOL-labeling** · run_id: <RUN 또는 ->

🟩🟩🟩🟩🟩⬜⬜⬜⬜⬜ **55%** · 5/8 완료

> ▶️ **지금 6단계 · 3차 라벨링**

- ✅ 1. 준비
- ✅ 2. 사전 점검
- ✅ 3. 수집·파싱
- ✅ 4. 1차 분류 — classify 48/48
- ✅ 5. 2차 검증 질문
- ▶️ **6. 3차 라벨링** — 진행 중
- ⬜ 7. 대시보드 띄우기
- ⬜ 8. 검수 완료 대기
```
- 목록에는 milestone 8개를 번호 순서대로 한 줄에 하나씩 항상 모두 쓴다. 단계를 `·`로 가로로 이어 붙이지 않는다. 제목 줄·막대 줄·지금 줄·목록 사이는 빈 줄로 띄운다.
- `✅` 완료, `▶️` 진행 중, `⬜` 대기, `❌` 실패. `▶️` 줄은 단계 번호·이름을 굵게 쓰고 `— 진행 중`을 붙인다. 막대 줄의 `N/8 완료`는 `✅` 줄의 수다.
- 지금 줄(인용 한 줄)에는 `▶️` 단계의 번호와 이름을 굵게 쓴다. 멈췄으면 `> ❌ **N단계 · <이름>에서 멈춤** — <사유 코드>`로, 8단계가 모두 끝났으면 `> ✅ **8단계 모두 완료**`로 쓴다.
- 단계 줄 끝에는 `—` 뒤에 그 단계 출력의 건수 한 마디나 사유 코드를 붙일 수 있다(예: `— classify 48/48`). 파일명·본문은 넣지 않는다.
- 3단계 `labelbot run`은 사용자에게 별도 VS Code 터미널에서 실행해 달라고 안내한다(Roo 명령 도구는 명령이 끝날 때까지 막힌다). 사용자가 `[ingest]`·`[classify]`·`[question]`·`[label]`·`[run]`·`[오류]` 줄을 알려 주면 해당 milestone을 `✅`로 바꾸고 다음을 `▶️`로 둔 블록을 다시 보여 준다. 실행 중에는 `▶️` 단계의 누적%를 바로 앞 단계 값으로 둔다(완료 전에 그 단계 %를 올리지 않는다).
- 멈추는 경우(점검 FAIL, `[오류]`, `error`)에는 그 milestone을 `❌`로 표시한 블록을 보고 앞에 한 번 보여 주고, 도달한 %를 그대로 둔다.
- 같은 블록을 연속으로 반복하지 않는다. 상태가 바뀔 때만 보여 준다.

## 절차

`<S>` = `.claude/skills/BEOL-labeling/scripts`, `<WS>` = 작업 폴더, `<IN>` = 입력 폴더. milestone이 끝날 때마다 위 "진행 현황 표시"의 블록을 갱신해 보여 준다(절차 4·5는 milestone이 아니므로 갱신하지 않는다).

### 1. 작업 폴더 준비

```bash
python "<S>/init_workspace.py" --input "<IN>"
```
출력 JSON의 `workspace`, `launch_name`, `port`, `file_counts`, `duplicates`를 기억한다. 작업 폴더는 매번 타임스탬프가 붙은 새 폴더다. `pipeline_written=false`면(사용자가 기존 폴더를 지정한 경우) 기존 설정을 그대로 쓴다. `file_counts`에 pptx·docx가 아닌 형식이 있으면 그 파일은 `UNSUPPORTED_FORMAT`으로 실패 목록에 들어간다고 미리 알린다. `error`가 나오면 멈추고 보고한다.

#### 1-1. 중복 작업 확인 (작업 시작 전 필수)

`duplicates.count`가 0이면 그대로 2단계로 간다. 1 이상이면 이번 입력 파일 중 `injested-file-list`에 이미 처리 완료로 기록된 파일명이 있다는 뜻이므로, **2단계로 가기 전에 사용자에게 묻는다.** 질문에는 중복 건수와 출처 목록 파일(`duplicates.sources`)만 쓰고 파일명은 쓰지 않는다(파일명은 사용자가 목록 파일에서 직접 본다).

| 선택지 | 처리 |
|---|---|
| 중복 파일 빼고 진행 | `python "<S>/init_workspace.py" --input "<IN>" --workspace "<WS>" --skip-duplicates`를 실행한다. `pipeline.json`의 `skip_file_names`에 중복 파일명이 들어가고, 수집 단계가 그 파일을 열지 않고 건너뛴다. 출력의 `skipped` 건수를 보고하고 2단계로 간다 |
| 중복 포함 전체 진행 | 그대로 2단계로 간다 |
| 중단 | 진행 현황의 준비를 `❌`로 표시하고 멈춘다. 만든 작업 폴더는 지우지 않고 경로만 알린다 |

중복을 빼고 나니 처리할 파일이 0개면(`file_counts` 합계 = `skipped`) 그 사실을 알리고 멈춘다.

#### 1-2. 검수 피드백 반영 상태 확인 (승인하지 않는다)

```bash
python -m domain_engrbot labeling-rules status --workspace "<WS>"
```
출력 JSON의 `rules.enabled`(승인돼 켜진 규칙)·`examples.enabled`(승인돼 켜진 사례)가 이번 실행에 들어갈 피드백이고, `candidates`(승인 대기 규칙 후보, 그중 `candidates_conflict`는 상충)·`examples_pending`(승인 대기 사례 후보)은 아직 사람이 Domain-Engr-bot 질문 화면에서 확정하지 않은 것이다. 묻지 않고 한 줄로 알린 뒤 2단계로 간다.

- 형식: `검수 피드백: 승인 규칙 n·사례 n 반영 예정, 확정 대기 규칙 n(상충 n)·사례 n`.
- 대기분이 있으면 "대기분은 이번 실행에 들어가지 않는다. 확정은 `beol-labeling-domain-engr-bot` 스킬(도메인 질문)의 질문 화면에서 한다"를 덧붙인다.
- 규칙·사례의 확정은 Domain-Engr-bot의 몫이다(사용자 결정, 2026-10-05. 2026-10-06부터 질문 화면에서 한다). 이 스킬은 `domain_engrbot labeling-rules approve`·`reject`·`apply`를 부르지 않고, 승인 여부를 사용자에게 묻지도 않는다.
- 사용자가 "이번엔 피드백 없이"라고 하면 3단계를 `python -m labelbot run --workspace "<WS>" --no-feedback`으로 돌린다.

#### 1-3. taxonomy 변경 한 줄 보고

```bash
python -m labelbot taxonomy-diff --workspace "<WS>"
```
출력의 JSON 한 줄(`added`·`removed`·`changed`·`values_added`)과 사람용 `[taxonomy] ...` 줄을 그대로 한 줄로 전한다. 묻지 않고 2단계로 간다. 첫 실행이면 `NO_PREVIOUS_RUN`이라 비교할 것이 없다고 알린다.

- `added`가 있으면 "이번 실행부터 새 축이 라벨링된다. 이전 실행의 검수 화면에서는 새 축을 고칠 수 없다(다음 실행부터 라벨링되는 새 축으로만 보인다)"를 덧붙이고, 2단계 사전 점검의 `taxonomy_axes` WARN(정의 없음, 질문 없음)을 함께 보여 준다.
- 축 이름과 건수만 전한다. 정의·질문 문장은 옮기지 않는다.

### 2. 사전 점검

```bash
python -m labelbot selfcheck --workspace "<WS>" --probe-llm
```
`결과: 전 항목 PASS`가 아니면 FAIL 항목과 사유 코드를 보고하고 멈춘다(키 누락, 모델명, 네트워크 등은 사람이 고쳐야 한다). `taxonomy_axes`의 WARN(정의·판정 규칙 없는 축, 질문 적용 대상에 없는 새 축, 값 행이 없어 비활성인 축)은 실패가 아니므로 멈추지 않고 축 이름·건수만 보고한 채 3단계로 간다.

### 3. 파싱부터 라벨링까지

```bash
python -m labelbot run --workspace "<WS>"
```
`[feedback] …` 줄이 이번 실행에 넣은 승인 규칙 수·사례 풀·제외 사유(원래 작업 폴더가 없거나 본문이 바뀐 사례)·유사도 방식을 알린다. 사례 본문은 승인 파일에 없고 원래 작업 폴더의 DB에서 읽기 전용으로 가져온다. 승인된 사례가 있고 임베딩을 쓸 수 있으면 분류 전에 이번 chunk를 한 번 임베딩한다(임베딩 호스트로 본문이 나간다. 저장된 벡터는 검수 뒤 임베딩 단계가 다시 쓰므로 호출이 늘지 않는다). LLM 호출은 chunk당 3회(1차 분류·2차 검증·대조 질문 생성·3차 라벨링)이고 6개씩 병렬이라, 파일 10개(chunk 50개 안팎)면 약 4~7분 걸린다. 이 명령은 사용자에게 별도 VS Code 터미널에서 실행해 달라고 안내하고(Roo 명령 도구는 명령이 끝날 때까지 막힌다), 끝나면(또는 `[run] 완료 run_id=…` 줄이 보이면) 마지막 줄들을 붙여 달라고 한다. 중간에 단계 줄을 알려 주면 milestone 3~6의 진행 현황을 갱신한다. `[run] 완료 run_id=...`가 나와야 끝난 것이고, 출력의 `run_id`를 `<RUN>`으로 쓴다.

끝나면 바로 처리 완료 파일 목록을 남긴다.
```bash
python "<S>/record_ingested.py" --workspace "<WS>" --run <RUN>
```
출력의 `list_file`과 `count`만 보고한다. 이 목록이 다음 실행의 1-1 중복 확인 기준이 된다.

실패 신호는 0이 아닌 종료 코드와 `[오류]`로 시작하는 줄이다. 이때 그 줄을 그대로 보고하고 멈춘다. 개별 chunk 실패는 실행을 멈추지 않고 `failures` 표에 사유 코드로 남으며 5단계 요약에 나온다. `<WS>/logs/labelbot.log`에는 파일 수집·파싱과 LLM 호출(분류·라벨링) 실패만 파일 ID·chunk ID와 사유 코드로 기록되고, 처음 실패가 날 때 생긴다. 파일이 없으면 그런 실패가 없었다는 뜻이다(날짜·담당자 추출 경고는 DB에만 남는다).

### 4. 화면 만들기 (LLM 호출 0회)

```bash
python -m labelbot compare --workspace "<WS>" --run <RUN>
python -m labelbot slide-images --workspace "<WS>" --run <RUN>
python -m labelbot review --workspace "<WS>" --run <RUN>
python -m labelbot dashboard --workspace "<WS>" --run <RUN>
```
`slide-images`를 `review` 앞에 두는 것은 검수 화면의 "같은 파일 슬라이드" 썸네일(JPG) 때문이다. 실패해도(브라우저 없음 등) 멈추지 않는다. `[slide-images]` 줄의 사유 코드만 보고하고 이어 간다. 이 경우 검수 화면에는 썸네일 대신 안내 문구가 나온다.

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
- 대조 질문(Q-CTL-) 답: O n / X n / N/A n — summary의 `controls`. O는 1차 분류 누락이나 3차 과잉 판정 신호이며 `CONTROL_O`로 불량 목록에 오른다. 확정 라벨·적재에는 들어가지 않는다. `controls`가 비었으면 생략
- 분포 알림(H5): 알림마다 한 줄씩 "조건: 값(기준)" — 원인 점검 대상(라벨링은 끝까지 돌았다). 없으면 "없음"
- 추출 경고: `extract:*` 사유 코드별 건수(날짜·담당자 값을 저장하지 않은 건수. 라벨에는 영향 없음). 없으면 생략
- 후보: 새 값 n, 동의어 n → 다음 실행으로 넘김(reports/candidates.md)
- taxonomy 재검토 요청: 누적 n(reports/taxonomy_revisit.md, 출처 summary의 revisits). 리포트는 열어 보고하지 않는다
- 검수 피드백: 승인 규칙 분류 n·라벨 n, 사례 풀 n(사례를 받은 chunk n, 유사도 <방식>). summary의 `feedback`이 출처이며, `enabled=false`면 그 `reason`(꺼짐·승인된 것 없음)을 쓴다
- 벡터 저장소: 아직 적재하지 않음(검수 후 BEOL-labeling-feedback에서 적재)
```
`failures`에 `HOST_UNCERTAIN`이 있으면 "호스트를 판정할 수 없는 URL이라 호출이 막혔다"고 따로 적는다.

### 6. 대시보드 띄우기

화면 서버를 띄운다. 서버는 끝날 때까지 막히므로(Roo 명령 도구는 명령이 끝날 때까지 막힌다) 사용자에게 별도 VS Code 터미널에서 실행해 달라고 안내한다. `<port>`는 1단계 출력의 `port`다.

```bash
python -m labelbot serve --workspace "<WS>" --port <port>
```

- 서버가 `[M05 REVIEW_SERVE] 대기 중 URL=…`을 내면 결과 대시보드 주소 `http://localhost:<port>/results.html`(프록시 뒤면 포트 패널·프록시 URL 뒤에 `results.html`)을 출력하고, 사용자가 브라우저에서 연다.
- 같은 포트로 이미 떠 있으면(`PORT_IN_USE`) 그 서버를 그대로 쓴다. 다른 실행의 서버라면 사용자에게 그 터미널에서 Ctrl+C로 끄고 다시 띄워 달라고 한다(검수 화면의 inbox 자동 저장과 검수 완료 버튼은 이 작업 폴더의 `labelbot serve`에서만 동작한다).
- 열린 화면의 내용은 읽지 않는다(화면 내용 읽기·캡처 금지). 건수와 URL만 보고한다.
- 검수(`review.html`)·파싱 대조(`compare.html`)는 사람이 대시보드의 **검수 시작** 또는 **검수 + 파싱 대조** 버튼으로 연다(7단계). 떠 있는 서버는 그대로 둔다.

### 7. 검수 완료 대기로 넘기기

검수는 대시보드의 버튼으로 시작한다(사용자 결정, 2026-10-06). 사람이 검수 화면에서 **검수 완료**를 누르면 화면 서버가 완료 신호 `<WS>/signals/review_done_<RUN>.json`(실행 ID, 시각, 건수만)을 쓴다.

**7-1. 완료 대기(선택).** 대기 명령은 끝날 때까지 막히므로 Roo 명령 도구로 돌리지 않는다. 원하면 사용자가 별도 VS Code 터미널에서 실행한다.
```bash
python ".claude/skills/BEOL-labeling-feedback/scripts/wait_review_done.py" --workspace "<WS>" --run <RUN>
```
`done: true` JSON이 나오면 그 줄을 붙여 달라고 한다. `code: WAIT_TIMEOUT`이면 같은 명령을 다시 실행하면 된다.

**7-2. 안내하고 멈추기.** 아래 내용을 안내하고 여기서 멈춘다(사용자가 알려 줄 때까지 기다린다).
1. 대시보드에서 결과를 훑어본다.
2. 오른쪽 위 **검수 시작**을 누른다. 파싱 대조도 하려면 **검수 + 파싱 대조**를 누른다(대조 화면이 새 탭으로 함께 열린다). 이 버튼은 화면만 연다.
3. 검수 화면에서 불량 chunk n개 중 **강조된 라벨부터** 확인·교정한다. 확신도 높은 라벨은 접혀 있다.
4. 다 끝나면 화면 상단의 **검수 완료**를 누른다. 교정할 것이 없어도 누르면 된다. 누르면 화면이 잠긴다.
5. 그다음 이 대화에 "검수 끝났어"라고 알리거나 7-1 대기 명령의 `done: true` 줄을 붙여 넣는다. 그때 반영·임베딩·적재가 이어진다.

검수가 끝나기 전에는 벡터 저장소에 올리지 않는다는 점을 한 줄로 덧붙인다.

**7-3. 완료를 알려 오면.**
- 붙여 넣은 `done: true` JSON이 있으면 `counts`의 건수(교정 n, 상태 표시 n, 동의어 n, 재검토 n)를 한 줄로 알리고 `beol-labeling-feedback` 스킬 절차를 이어서 따른다. 인자는 `검수 완료 <WS> run=<RUN> edits=n status=n syns=n revisits=n done_at=<시각>`이다.
- 사용자가 "검수 끝났어"라고만 하면 같은 인자(건수·`done_at`은 모르면 생략)로 `beol-labeling-feedback` 스킬 절차를 따른다. 대기 명령이 아직 떠 있으면 그 터미널에서 Ctrl+C로 끄게 한다(`[M05 REVIEW_SERVE] 중단(사용자)`는 실패가 아니다).

## 마일스톤

이 스킬의 명령은 터미널에 `[Mxx 이름] 시작·완료·실패` 줄을 낸다. 실패하면 아래 ID로 어느 단계인지 보고, `python -m labelbot codes --milestone <Mxx>`로 사유 코드와 조치를 본다.

| 명령 | 마일스톤 |
|---|---|
| `labelbot run` | M01 INGEST · M02 CLASSIFY · M03 LABEL · M04 REPORT |
| `.claude/skills/BEOL-labeling/scripts/init_workspace.py` | M24 WORKSPACE_INIT |
| `domain_engrbot labeling-rules` | M11 DOMAIN_QA |
| `labelbot taxonomy-diff` | M23 DIFF_CHECK |
| `labelbot selfcheck` | M00 ENV/CLI |
| `.claude/skills/BEOL-labeling/scripts/record_ingested.py` | M01 INGEST |
| `labelbot compare` | M04 REPORT |
| `labelbot slide-images` | M09 SLIDE_IMAGES |
| `labelbot review` | M04 REPORT |
| `labelbot dashboard` | M04 REPORT |
| `.claude/skills/BEOL-labeling/scripts/summary.py` | M00 ENV/CLI |
| `labelbot serve` | M05 REVIEW_SERVE |
| `.claude/skills/BEOL-labeling-feedback/scripts/wait_review_done.py` | M05 REVIEW_SERVE |

담당 마일스톤: M00·M01·M02·M03·M04·M05·M09·M11·M23·M24

## 실패하면

터미널의 `[Mxx …] 실패` 블록을 먼저 읽는다 → `python -m labelbot status --workspace <작업 폴더>`(Python 3.14가 없으면 `python3 tools/beol_status.py status --workspace <작업 폴더>`) 출력을 복사해 알려 달라. 환경 문제면 `python3 tools/beol_doctor.py`. `BEOL_TRACE=1`은 Roo 명령으로 실행하지 말고 일반 터미널에서만.
