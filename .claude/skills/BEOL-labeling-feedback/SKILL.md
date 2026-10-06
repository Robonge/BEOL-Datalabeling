---
name: BEOL-labeling-feedback
description: BEOL-labeling이 검수 대기에서 멈춘 뒤 사람 검수부터 적재까지 이어서 한다. 결과 대시보드의 "검수 시작" 버튼을 누르면 BEOL-labeling 대화가 깨어나 이 스킬을 부른다(채팅으로 불러도 된다). 채팅으로 시작했으면 파싱 대조(H2)도 할지 묻고, 검수 화면(review.html, 원하면 compare.html)을 띄워 사람의 불량 chunk 검수(H6)를 기다리며, 화면의 "검수 완료" 버튼이 눌리면 교정을 labelbot에 반영하고 화면·리포트를 다시 만들고 임베딩 후 Supabase에 적재한다. 사용자가 "검수 시작", "검수하자", "검수 화면 열어줘", "검수 끝났어", "체크 다 했어", "검수 반영해줘", "피드백 반영", "inbox에 넣었어", "교정 없음, 적재해줘", "대조 결과 반영", "Supabase 올려줘"라고 하거나 /BEOL-labeling-feedback을 부르면 이 스킬을 쓴다. 파싱·라벨링을 새로 돌리는 일은 BEOL-labeling이 맡는다.
---

# BEOL-labeling-feedback: 사람 검수 → 반영 → 적재

`/BEOL-labeling`이 검수 대기에서 멈춘 뒤 이어서 쓴다. 이 스킬이 검수 화면을 띄우고, 사람이 검수를 마치고 **검수 완료**를 누를 때까지 기다린 뒤, 교정과 대조 기록을 반영하고 확정된 라벨로 Supabase에 올린다. LLM 분류·라벨링은 다시 부르지 않는다(임베딩만 호출).

```
[대시보드 검수 시작 버튼 또는 채팅] → 상태 확인 → (채팅 시작이면 H2 대조 여부 질문·검수 화면 띄우기) → [사람: H6 검수(+H2 대조) → 검수 완료] → 교정 모으기 → 반영 → Domain-Engr-bot 장부·라벨링 규칙 후보 → 화면·리포트 → 임베딩 → 적재 → 보고
```

## 사람 개입 지점을 이렇게 다룬다 (사용자 결정, 2026-10-04)

| 지점 | 처리 |
|---|---|
| H2 파싱 대조 | 대시보드에서 시작했으면 누른 버튼(**검수 시작** / **검수 + 파싱 대조**)으로 정해져 묻지 않는다(2026-10-06). 채팅으로 시작했으면 `AskUserQuestion`으로 이번에 할지 묻는다. 하겠다고 하면 검수 탭과 함께 대조 탭을 열고, 대기는 한 번만 한다. 대조는 선택이며 라벨에 영향을 주지 않는다 |
| H6 불량 chunk 검수 | 검수 탭을 열고 **검수 완료 버튼 신호**를 기다린다. 기다리는 동안 `AskUserQuestion`으로 끝났는지 묻지 않는다. 버튼이 눌리면 바로 반영·적재로 넘어간다 |

## 고정 값

- 코드 폴더: `C:\Users\dltkd\Desktop\261004 BEOL AX day2`. 모든 명령은 여기서 `PYTHONIOENCODING=utf-8`을 붙여 실행한다.
- 작업 폴더 `<WS>`: 인자로 받는다. 없으면 이 대화에서 `/BEOL-labeling`이 쓴 작업 폴더를 쓴다. 그것도 모르면 `C:\Users\dltkd\Desktop\261004 BEOL AX day2\workspaces\261004_BEOL_*` 중 `work.sqlite`가 있고 가장 최근에 바뀐 폴더를 고르고, 어느 폴더를 골랐는지 보고에 적는다.
- 화면 서버: `.claude/launch.json`에서 `runtimeArgs`의 `--workspace`가 `<WS>`인 항목. 이름은 `screens-<입력 폴더 slug>`, 포트는 그 항목의 `port`다(`init_workspace.py`가 등록한다).
- 교정 파일 위치: `<WS>\inbox\review_<실행ID>.json`, `<WS>\inbox\compare_<실행ID>.json`.
- 시작 신호: `<WS>\signals\review_start_<실행ID>.json`. 결과 대시보드의 **검수 시작**·**검수 + 파싱 대조** 버튼을 누르면 화면 서버가 쓴다(실행 ID, 시각, 파싱 대조 여부만). `/BEOL-labeling`이 끝날 때 이 신호를 기다리도록 걸어 두고, 신호가 오면 이 스킬을 부른다.
- 완료 신호: `<WS>\signals\review_done_<실행ID>.json`. 검수 화면의 **검수 완료** 버튼을 누르면 화면 서버가 마지막 교정을 inbox에 저장하고 이 파일을 쓴다. 내용은 실행 ID, 시각, 건수(`edits`·`status`·`syns`·`revisits`)뿐이다.
- 스크립트: 요약 `.claude/skills/BEOL-labeling/scripts/summary.py`, 교정 파일 모으기 `.claude/skills/BEOL-labeling-feedback/scripts/collect_inbox.py`, 완료 대기 `.claude/skills/BEOL-labeling-feedback/scripts/wait_review_done.py`.

## 지켜야 할 것과 이유

- 판단은 사람이 한다. 사람 값이 최종 라벨이기 때문이다. 검수하는 동안 봇은 검수·대조 탭을 클릭하거나 읽지 않고(`get_page_text`·`read_page`·`find`·스크린샷 금지), 완료 신호만 기다린다.
- 교정 JSON은 `python -m labelbot apply`가 `read_input`으로 읽는다. Read 도구, `cat`, `cp`로 열거나 복사하지 않는다. 사람 입력은 한 곳에서만 연다는 `CLAUDE.md` 규칙 때문이다. 완료 신호 파일은 건수만 담은 서버 산출물이므로 `wait_review_done.py`가 읽어도 된다.
- Downloads → inbox 이동은 `collect_inbox.py`로만 한다. 이 스크립트는 같은 드라이브 안에서 이름만 바꾸고(`os.replace`) 내용은 열지 않는다. `CROSS_DEVICE`가 나오면 복사로 우회하지 말고 사용자에게 옮겨 달라고 안내한다.
- 검수 화면의 체크는 그 브라우저의 `localStorage`에 있고, 밖으로 나가는 길은 화면 서버의 inbox 자동 저장, **검수 완료** 버튼, **JSON 저장** 버튼(예전 화면은 **JSON 내려받기**)뿐이다. 3-2에서 브라우저 패널의 상태를 볼 때는 건수만 센다. 버튼을 대신 누르는 것은 파일 내려받기이므로 매번 사용자 확인을 받는다.
- 봇은 `taxonomy.xlsx`를 고치지 않는다. 검수 중 등록한 동의어는 `reports/candidates.md`의 "검수 등록" 행으로만 나오며, 시트에 붙여넣는 것은 사람 몫이고 다음 실행에 반영된다. 검수 중 남긴 taxonomy 재검토 요청은 `reports/taxonomy_revisit.md`(누적)와, `apply`가 반영한 검수 실행마다 쓰는 `taxonomy/taxonomy_revisit_requests/taxonomy_revisit_<연월일_시분초>.md`·`.html`·`.json`(그 실행분만, taxonomy.xlsx가 있는 폴더 기준, git 추적 대상)으로만 나오며 처리됨 판정은 없다. 라벨과 `label_hash`를 바꾸지 않으므로 Supabase 재적재도 없다.
- 재검토 메모에는 사내 본문이 들어 있을 수 있다. `reports/taxonomy_revisit.md`·`.jsonl`과 `taxonomy/taxonomy_revisit_requests/`의 파일을 Read·Grep·`cat`으로 열어 보고하지 않는다(파일 수와 위치는 `apply` 출력 줄로만 안다). `revisit_requests`는 `COUNT`와 `reason`별 `GROUP BY`만 조회한다(`SELECT *`, `.dump`, 다른 열 조회 금지). inbox JSON과 `inputs/<sha256>.b64`는 `apply` 밖에서 열거나 디코딩하지 않는다. 검수 탭과 JSON 저장 대체 텍스트 창에는 `get_page_text`·`read_page`·`find`·스크린샷을 쓰지 않는다(3-2의 건수 스니펫과 저장 버튼을 찾는 `find`만 허용하며 `javascript_tool`은 `revisits.length`만 읽는다). 위치와 건수(요약의 `revisits`)만 보고한다.
- 보고에는 건수, 실행 ID, 사유 코드만 쓴다.
- Domain-Engr-bot 교정 장부(4-1, `workspaces/_domain_engrbot/ledger/`)의 `golden.jsonl`·`judge_examples.jsonl`에는 본문 인용이 있다. 열거나 조회하지 않고 `domain_engrbot intake` 출력의 건수만 쓴다.
- 라벨링 규칙·사례 후보(4-2)는 교정을 다음 라벨링의 규칙·사례 후보로 셀 뿐이고 승인하지 않는다. 확정은 `/BEOL-labeling-Domain-Engr-bot`(검수 결과로 엔지니어에게 질문해 도메인 지식을 규칙·taxonomy 제안으로 돌려주는 봇)의 질문 화면에서 사람이 한다. 후보 리포트 `labeling_candidates.md`와 승인 파일 `taxonomy/labeling_rules.json`에는 본문이 없어 위치를 링크해도 된다.

## 진행 현황 표시

시작할 때(0%)와 아래 milestone이 끝날 때마다 진행 현황 블록을 응답 텍스트로 보여 준다. 사람 검수 대기와 임베딩은 백그라운드로 돌리고 끝나면 갱신한다.

| # | milestone | 끝나는 신호 | 누적 |
|---|---|---|---|
| 1 | 상태 확인 | 1단계 `summary.py`·`wait_review_done.py --check` 출력 | 10% |
| 2 | 사람 검수 대기 | `wait_review_done.py` 출력 `done: true`(또는 채팅의 "검수 끝났어") | 30% |
| 3 | 교정 반영 | `[apply] …` 줄 | 50% |
| 4 | 화면·리포트 재생성 | `report` 명령 끝 | 60% |
| 5 | 임베딩·슬라이드 JPG | `embed` 명령 끝과 `[slide-images] …` 줄 | 85% |
| 6 | Supabase 적재 | `[push-vectors] …`·`[push-slides] …` 줄 | 100% |

절차의 "검수 화면 띄우기"(2-1~2-3), "교정 파일 모으기"(3단계), "보고"(7단계)는 실행하되 진행 현황에는 milestone으로 넣지 않는다(사용자 결정, 2026-10-05). 검수 화면 띄우기와 교정 파일 모으기는 각각 앞뒤의 "사람 검수 대기"·"교정 반영"에 딸린 과정으로 보고, 끝나도 블록을 따로 갱신하지 않는다. 그 과정에서 멈추면(탭을 열 수 없음, 3-2의 사용자 조치 대기, `CROSS_DEVICE` 등) 각각 milestone 2·3을 `❌`나 "사용자 조치 대기"로 표시한다. 보고는 milestone 6이 끝난 뒤 마지막 블록 아래에 쓴다.

블록 형식(제목 줄 + 막대 줄 + 지금 줄 + 세로 목록. 막대는 10칸이며 `🟩` 칸 수 = 누적% ÷ 10을 내림한 값, 나머지는 `⬜`):
```
**진행 현황 · BEOL-labeling-feedback** · run_id: <RUN>

🟩⬜⬜⬜⬜⬜⬜⬜⬜⬜ **10%** · 1/6 완료

> ▶️ **지금 2단계 · 사람 검수 대기** — 검수 완료 버튼 대기

- ✅ 1. 상태 확인
- ▶️ **2. 사람 검수 대기** — 검수 완료 버튼 대기
- ⬜ 3. 교정 반영
- ⬜ 4. 화면·리포트 재생성
- ⬜ 5. 임베딩·슬라이드 JPG
- ⬜ 6. Supabase 적재
```
- 목록에는 milestone 6개를 번호 순서대로 한 줄에 하나씩 항상 모두 쓴다. 단계를 `·`로 가로로 이어 붙이지 않는다. 제목 줄·막대 줄·지금 줄·목록 사이는 빈 줄로 띄운다.
- `✅` 완료, `▶️` 진행 중, `⬜` 대기, `❌` 실패, `⏭️` 건너뜀(예: 이미 검수 완료라 2 생략, 교정 파일이 없어 반영 생략, `supabase.enabled=false`라 적재 생략). `▶️` 줄은 단계 번호·이름을 굵게 쓰고 `— 진행 중`을 붙인다. 건너뛴 단계도 누적%에는 넣고, 막대 줄의 `N/6 완료`는 `✅`와 `⏭️` 줄을 합한 수다.
- 지금 줄(인용 한 줄)에는 `▶️` 단계의 번호와 이름을 굵게 쓴다. 멈췄으면 `> ❌ **N단계 · <이름>에서 멈춤** — <사유 코드>`로, 6단계가 모두 끝났으면 `> ✅ **6단계 모두 완료**`로 쓴다.
- 단계 줄 끝에는 `—` 뒤에 건수나 사유 코드를 붙일 수 있다(예: `— 교정 3건`, `⏭️` 줄의 `— 교정 파일 없음`, `— 임베딩 21 · JPG 실패 0`).
- 사람 검수 대기 중에는 2번을 `▶️`로 두고 `— 진행 중` 대신 "검수 완료 버튼 대기"라고 적는다(지금 줄에도 같이 적는다). 3-2에서 사용자 확인이나 조치를 기다리면 3번을 `▶️`로 두고 "사용자 조치 대기"라고 적는다. 오류로 멈추면 그 milestone을 `❌`로 둔 블록을 보여 주고 도달한 %를 그대로 둔다.
- milestone 6은 `[push-slides]`가 `storage_enabled=false: 호출하지 않습니다`를 내면 `✅`가 아니라 `❌ — STORAGE_DISABLED`로 표시한다(절차 6단계 참고).
- 블록에는 건수·실행 ID·사유 코드만 쓴다. 파일명·본문·재검토 메모는 넣지 않는다. 상태가 바뀔 때만 다시 보여 준다.

## 절차

milestone이 끝날 때마다 위 "진행 현황 표시"의 블록을 갱신해 보여 준다(milestone이 아닌 절차는 갱신하지 않는다).

### 1. 상태 확인

```bash
python ".claude/skills/BEOL-labeling/scripts/summary.py" --workspace "<WS>"
python ".claude/skills/BEOL-labeling-feedback/scripts/wait_review_done.py" --workspace "<WS>" --run <RUN> --check
python ".claude/skills/BEOL-labeling-feedback/scripts/wait_review_done.py" --workspace "<WS>" --run <RUN> --signal start --check
```
요약의 `run_id`를 `<RUN>`으로, `flagged.total`을 불량 chunk 수로 쓴다(두·세 번째 명령은 `<RUN>`을 얻은 뒤 돌린다).

어디서 시작할지 이렇게 정한다.
- `/BEOL-labeling`이 대시보드의 **검수 시작** 신호로 이 스킬을 불렀으면(인자 `대시보드 검수 시작 … compare=<true|false>`), 또는 사용자가 채팅으로 불렀는데 `wait_review_done.py --signal start --check`가 `pending: true`이면(대시보드에서 이미 검수 화면을 열었음) → 2단계를 "대시보드에서 시작" 경로로 진행한다(2-1 질문과 2-3 탭 열기를 건너뛴다). 단, `--check`가 `done: true`이면 아래 줄을 따른다.
- 사용자가 부르면서 "검수 끝났어", "교정 없음, 적재해줘", "반영해줘"처럼 검수가 끝났다고 했거나, `--check`가 `done: true`이면 → 절차 2단계를 건너뛰고(진행 현황의 "2. 사람 검수 대기"는 `⏭️`) 절차 3단계로 간다. 단, 사용자가 "다시 검수"라고 했으면 2단계로 간다.
- 그 밖에는 2단계로 간다. 불량 chunk가 0개여도 2단계로 간다. 검수 화면에 검수 완료 버튼이 있으므로 사람이 바로 눌러 넘어가면 된다.

### 2. 검수 화면 띄우고 기다리기 (H6, 선택 H2)

**대시보드에서 시작한 경우** (1단계 첫 줄): 사람이 대시보드의 **검수 시작**(또는 **검수 + 파싱 대조**) 버튼으로 이미 검수 화면(과 대조 화면)을 열었다.
- 2-1은 묻지 않는다. 파싱 대조 여부는 인자의 `compare`(채팅으로 불렸으면 `--signal start --check` 출력의 `compare`)를 쓴다.
- 2-2는 `--after-start`를 붙여 시작한다. 시작 신호 뒤에 눌린 완료는 이 대기보다 먼저 눌렸어도 받는다.
  ```bash
  python ".claude/skills/BEOL-labeling-feedback/scripts/wait_review_done.py" --workspace "<WS>" --run <RUN> --after-start
  ```
- 2-3은 건너뛴다(탭을 새로 열지 않는다). 화면 서버는 대시보드를 띄운 서버가 그대로 쓴다.
- 2-4 안내에서 "검수 화면은 대시보드에서 이미 열렸다"고 적고 1~4번을 그대로 안내한다. 2-5는 같다.

**2-1. 파싱 대조 여부 묻기.** `AskUserQuestion`으로 한 번 묻는다. 질문은 "이번에 파싱 대조(H2)도 할까요?"이고, 선택지는 "검수만"과 "검수 + 파싱 대조" 두 개다. 설명에 "대조는 선택이며, 이상 슬라이드는 파서 보강 대상이 될 뿐 라벨은 바뀌지 않는다"를 적는다.

**2-2. 완료 대기 시작.** 탭을 열기 **전에** 백그라운드로 시작한다. 그래야 예전에 눌린 신호와 섞이지 않고 탭을 열자마자 누른 경우도 놓치지 않는다.
```bash
python ".claude/skills/BEOL-labeling-feedback/scripts/wait_review_done.py" --workspace "<WS>" --run <RUN>
```
Bash `run_in_background: true`, `timeout: 7200000`으로 돌린다. 끝나면 이 대화가 다시 깨어난다. 짧은 주기로 상태를 다시 확인하지 않는다.

**2-3. 화면 서버와 탭.** 브라우저 패널에서 화면 서버를 시작하고(`preview_start` name=`screens-<slug>`), 아래 탭을 연다.
- `http://localhost:<port>/review.html` — 검수 화면(앞에 둔다)
- `http://localhost:<port>/compare.html` — 2-1에서 "검수 + 파싱 대조"를 골랐을 때만

같은 주소의 탭이 이미 있으면 새로 열지 않고 그 탭을 navigate해서 새로 고친다. 사용자의 다른 탭은 닫지 않는다.
- `preview_start`가 "Port in use by another chat"으로 실패하면 그 포트의 서버가 다른 대화에서 떠 있는 것이다. `labelbot serve`라면 화면과 완료 버튼은 그대로 동작하므로 URL만 안내한다. 예전 `http.server`라면 inbox 자동 저장이 안 되고 완료 버튼이 흐리게 보이며 눌리지 않으므로(검수 완료 버튼은 오른쪽 위 JSON 저장 옆에 늘 보이고, 완료 신호를 받는 `labelbot serve`로 열었을 때만 켜진다), 그 대화에서 서버를 끄거나 이 대화에서 다시 띄워 달라고 안내한다.
- 브라우저 패널을 쓸 수 없으면 위 URL을 사용자의 브라우저로 열어 달라고 안내한다. 같은 PC의 화면 서버이므로 완료 버튼은 어느 브라우저에서나 동작한다.

**2-4. 안내하고 기다리기.** 아래 내용을 안내하고 턴을 끝낸다. 끝났는지 `AskUserQuestion`으로 묻지 않는다.
0. 검수 중인 실행이 지금 taxonomy와 다르면(`python -m labelbot taxonomy-diff --workspace "<WS>"`의 `added`가 있으면) "새 축 n개는 이 실행에 없어 고칠 수 없다. 다시 라벨링한 뒤 검수한다"를 안내한다. 화면에서는 "다음 실행부터 라벨링되는 새 축"으로 보이고, 교정 JSON에 그 축이 들어와도 반영 때 `AXIS_NOT_IN_RUN`으로 건너뛴다. 4단계 보고에 그 건수를 함께 적는다.
1. 검수 화면에서 불량 chunk n개를 확인·교정한다. taxonomy가 맞지 않는 축·질문은 재검토 요청으로 남긴다(메모 500자까지, 라벨은 바뀌지 않으며 맞는 값이 없으면 unknown으로 교정한다). 체크할 때마다 inbox에 자동 저장된다.
   - 값을 고쳤으면 가능하면 **근거**를 남긴다(선택, 사용자 결정 2026-10-05). 고친 축의 근거 버튼을 누르고, 판단의 근거가 된 문장을 이 슬라이드 본문이나 "같은 파일 슬라이드 텍스트"(다른 슬라이드·파일명·문서 제목)에서 드래그한다. 한 교정에 3개까지 남길 수 있고, 이유는 적어도 되고 안 적어도 된다. 같은 근거를 다른 고친 축에도 붙일 수 있다.
   - 근거가 있는 교정만 다음 라벨링의 사례(few-shot)로 쓰이고, 규칙 후보도 근거 있는 교정이 1건 이상인 패턴만 올라온다. 확정은 `/BEOL-labeling-Domain-Engr-bot`의 질문 화면에서 엔지니어가 근거를 보며 한다.
2. (대조를 골랐다면) 파싱 대조 화면에서 슬라이드마다 이상 여부를 표시한다. 대조 표시도 자동 저장되며 대조 화면에는 완료 버튼이 따로 없다.
3. 다 끝나면 검수 화면 상단의 **검수 완료**를 누른다. 교정할 것이 없어도 누르면 된다. 누르면 반영·적재까지 자동으로 이어진다.
4. 검수가 끝나기 전에는 Supabase에 올리지 않는다.

**2-5. 신호가 오면.** 백그라운드 명령의 출력 JSON을 본다.
- `done: true` → `counts`의 건수(교정 n, 상태 표시 n, 동의어 n, 재검토 n)만 한 줄로 알리고 3단계로 간다.
- `code: WAIT_TIMEOUT` → 2-2를 다시 시작하고, 아직 기다리고 있다고 한 줄 알린다.
- 버튼을 누르기 전에 사용자가 채팅으로 "검수 끝났어"라고 하면(완료 버튼이 없는 예전 화면이거나 로컬 파일로 연 경우) 대기 명령을 `TaskStop`으로 끄고 3단계로 간다.

### 3. 교정 파일 모으기

**3-1. Downloads에서 inbox로 옮기기.** 항상 돌린다. 옮길 것이 없으면 아무것도 하지 않는다.
```bash
python ".claude/skills/BEOL-labeling-feedback/scripts/collect_inbox.py" --workspace "<WS>" --run <RUN>
```
출력의 `moved`(이번에 옮긴 수), `inbox`(inbox에 있는 수), `skipped`(사유 코드별)를 본다. 이번 실행 ID가 아닌 파일(이전 실행의 `review_*.json` 등)은 건드리지 않는다. 검수 완료 버튼으로 넘어왔다면 보통 `inbox.review`가 1 이상이다.

**3-2. 화면에만 남은 체크 확인.** 완료 신호 없이 넘어왔고, `inbox.review`가 0이고, 사용자가 "교정 없음"이라고 하지 않았을 때만 한다. 대조는 선택이므로 `inbox.compare`가 0이어도 이 단계를 하지 않는다. 단, 대조 탭에 표시가 있으면 함께 내려받는다.
1. 브라우저 패널(`tabs_context`)에서 주소가 `localhost:<포트>/review.html`인 탭을 찾는다. 없으면 4로 간다.
2. 그 탭에서 `javascript_tool`로 건수만 센다(읽기 전용).
   ```js
   (() => { const o = JSON.parse(localStorage.getItem("labelbot_review_<RUN>") || "{}");
     return {edits: Object.keys(o.edits || {}).length, status: Object.keys(o.status || {}).length,
             syns: (o.syns || []).length, revisits: (o.revisits || []).length}; })()
   ```
   `compare.html` 탭이 있으면 `labelbot_compare_<RUN>`의 `marks` 수도 같은 방식으로 센다.
3. 합계가 1 이상이면 `AskUserQuestion`으로 "검수 탭의 체크 n건을 JSON으로 내려받아 inbox로 옮길까요?"(대조 표시가 있으면 함께)라고 묻는다. 승인하면 그 탭의 **JSON 저장** 버튼(예전 화면은 **JSON 내려받기**)을 `find`로 찾아 누르고, 3-1을 다시 돌린다.
   - 다시 돌려도 `moved`가 0이면 브라우저 패널의 내려받기가 Downloads로 가지 않은 것이다. 사용자에게 그 탭에서 버튼을 직접 눌러 달라고 안내하고 멈춘다.
   - 합계가 0이면 화면에 체크가 없는 것이다. 4로 간다.
4. 그래도 `inbox.review`가 0이면: 사용자가 쓰는 브라우저(예: 사용자의 Chrome)에서 체크했다면 그 브라우저에서 **JSON 저장**(예전 화면은 **JSON 내려받기**)을 눌러 달라고 안내하고 멈춘다. 그 브라우저의 체크는 이 스킬이 볼 수 없다.

- 사용자가 "교정 없음/검수 완료"라고 했고 inbox가 비었다면 4단계를 건너뛰고 5단계로 간다.
- `skipped`에 `CROSS_DEVICE`·`MOVE_FAILED`가 있으면 건수를 보고하고 그 파일을 `<WS>\inbox\`로 옮겨 달라고 안내한다.

### 4. 반영

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
| `RUN_ID_INVALID` | 문서의 실행 ID 형식이 맞지 않음 | 그 파일만 반영하지 않는다. 화면에서 다시 저장해 달라고 안내 |
| `FORMAT_INVALID`, `JSON_INVALID` | 형식 오류 | 화면에서 다시 내려받아 달라고 안내. 같은 `apply`의 다른 파일 반영은 되돌려지지 않는다(파일별 `SAVEPOINT`) |
| `REVISIT_CHUNK_NOT_FLAGGED` | 그 실행의 불량 목록에 없는 chunk의 재검토 요청 | 그 항목만 버림, 파일은 `OK`. 건수만 보고 |
| `REVISIT_REASON_INVALID` | 알 수 없는 대상·사유이거나 허용 조합 밖 | 그 항목만 버림, 파일은 `OK` |
| `REVISIT_FIELD_INVALID` | 형식·필수 칸 오류(키 규칙, 제안 값, 관련 값, 예약어, 필수 메모 없음) | 그 항목만 버림, 파일은 `OK` |
| `REVISIT_DUPLICATE` | 한 문서 안의 같은 `(chunk, 대상, 키)` | 앞 항목만 버림(뒤 항목 저장), 파일은 `OK` |
| `REVISIT_MEMO_TRUNCATED` | 메모가 500자 초과 | 500자로 잘라서 저장 |

`OK`인 review 줄의 실행 ID를 `<RUN>`으로 쓴다. 없으면 1단계 요약의 `run_id`를 쓴다.

재검토 요청이 1건 이상인 검수 실행을 반영하면 `[apply] taxonomy 재검토 요청 파일 N개 → taxonomy/taxonomy_revisit_requests/` 줄이 나온다(실행마다 `taxonomy_revisit_<연월일_시분초>.md`·`.html`·`.json` 3개, 같은 초면 `_2` 접미). 파일 내용은 열지 않고 이 줄의 개수와 위치만 보고한다. 엑셀 반영은 사람 몫이다: md의 탭 구분 코드 블록이나 html 표(머리글 아래 A~K 칸)를 복사해 taxonomy 시트 A열에 붙인다("확인 필요" 블록은 고친 뒤 붙인다).

### 4-1. Domain-Engr-bot 교정 장부로 넘기기 (LLM 호출 0회)

반영(`apply`)이 `OK`인 review가 하나라도 있으면 항상 돌린다. 사람 검수 결과를 Domain-Engr-bot의 입력(도메인 질문의 재료, 라벨링 규칙·사례 후보, 누적 골든셋 등)으로 넘기는 단계다(사용자 결정, 2026-10-05). 진행 현황에서는 milestone 3 "교정 반영"에 딸린 과정으로 보고 블록을 따로 갱신하지 않는다.
```bash
python -m domain_engrbot intake --workspace "<WS>"
```
작업 폴더 DB를 읽기 전용으로 읽어 `workspaces/_domain_engrbot/ledger/`의 이 작업 폴더 몫을 바꾼다(다시 돌려도 결과가 같다). `[intake] …`·`[ledger] …` 줄의 건수와 건너뜀 사유 코드만 보고에 쓴다. 장부의 `golden.jsonl`·`judge_examples.jsonl`에는 본문 인용이 있으므로 열지 않는다. 실패(`[오류] <코드>`)해도 반영·적재는 계속하고 사유 코드만 보고한다.

### 4-2. 라벨링 규칙·사례 후보 만들기 (LLM 호출 0회)

4-1이 성공했을 때만 돌린다. 진행 현황에서는 milestone 3에 딸린 과정으로 본다.
```bash
python -m domain_engrbot labeling-rules candidates --workspace "<WS>"
```
Domain-Engr-bot이 장부의 교정 패턴으로 다음 라벨링(1차 분류·3차 라벨링)에 넣을 규칙 후보와 few-shot 사례 후보를 세어 `workspaces/_domain_engrbot/ledger/labeling_candidates.md`(본문 없음)를 다시 쓴다. `[labeling-rules] …` 줄의 건수만 보고에 쓴다. 승인은 하지 않는다(확정은 `/BEOL-labeling-Domain-Engr-bot` 질문 화면에서 한다). 실패해도 반영·적재는 계속하고 사유 코드만 보고한다.

### 5. 화면·리포트 다시 만들기 (LLM 호출 0회)

```bash
python -m labelbot review --workspace "<WS>" --run <RUN>
python -m labelbot dashboard --workspace "<WS>" --run <RUN>
python -m labelbot report --workspace "<WS>" --run <RUN>
```
대시보드는 사람 교정이 반영된 확정 라벨로 다시 그려진다.

### 6. 임베딩, 슬라이드 JPG, Supabase 적재

```bash
python -m labelbot embed --workspace "<WS>" --run <RUN>
python -m labelbot slide-images --workspace "<WS>" --run <RUN>
python -m labelbot push-vectors --workspace "<WS>" --run <RUN>
python -m labelbot push-slides --workspace "<WS>" --run <RUN>
```
- `embed`는 이미 만든 벡터면 호출 0회다.
- `push-vectors`는 확정 라벨(사람 교정 우선)로 올린다. 이미 같은 라벨로 올라간 chunk는 다시 보내지 않으므로, 두 번째 실행부터는 라벨이 바뀐 chunk만 전송된다.
- 전송 실패는 사유 코드로 남고 반영 결과에는 영향이 없다. 실패하면 사유 코드를 보고한다.
- `supabase.enabled=false`(요약의 `supabase_enabled: false`)면 `push-vectors`가 "호출하지 않습니다"만 출력하고 끝난다. 이 경우에도 `embed`는 돌린다. 로컬 `chunk_embeddings`가 원본이고 Supabase는 사본이므로, 로컬 벡터를 먼저 만들어 두면 나중에 적재를 켰을 때 바로 올릴 수 있다. 보고에는 "Supabase 적재 꺼짐(supabase.enabled=false)"이라고 쓴다.
- `slide-images`는 검수 화면과 같은 슬라이드 근사 미리보기를 headless Edge/Chrome으로 JPG 캡처해 `slide_images/<sha256>.b64`에 두고 `out/labeling.sqlite`의 `chunks.slide_image`를 채운다. LLM 호출 0회이고, 이미 만든 슬라이드는 건너뛴다(BEOL-labeling 4단계에서 검수 썸네일용으로 이미 그렸으면 교정으로 본문이 바뀐 chunk만 다시 그린다). 실패는 사유 코드(`NO_LAYOUT`, `RENDERER_MISSING`, `RENDERER_EXITED`, `RENDERER_PORT_TIMEOUT`, `RENDER_TIMEOUT`, `JPEG_SIGNATURE` 등)로만 보고한다. JPG는 `.b64`로만 둔다. 디코딩해서 `.jpg`로 저장하거나 Read로 열지 않는다.
- `push-slides`는 `push-vectors` 다음에 돌린다. `supabase.storage_enabled=true`일 때만 Storage `BEOL-labeling` 버킷에 올리고 벡터 행의 `slide_image_*` 열을 채운다. `init_workspace.py`가 새 작업 폴더의 `pipeline.json`에 `storage_enabled: true`를 쓰므로 보통은 켜져 있다. 그래도 "storage_enabled=false: 호출하지 않습니다"가 나오면(예전에 만든 작업 폴더) 적재가 빠진 것이므로 `STORAGE_DISABLED`로 보고하고, `AskUserQuestion`으로 "이 작업 폴더의 `pipeline.json`에 `storage_enabled: true`를 넣고 `push-slides`를 다시 돌릴까요?"를 묻는다. 승인하면 그 키 하나만 바꾸고 `push-slides`만 다시 돌린다(멱등이라 벡터는 다시 보내지 않는다). 버킷이나 `slide_image_*` 열이 없으면 `selfcheck`의 `supabase_storage_bucket`·`supabase_slide_columns`가 FAIL을 내므로 `docs/supabase_schema.md`의 SQL을 실행해 달라고 안내한다. `ROW_MISSING`은 벡터 행이 없다는 뜻이고 다음 실행에서 다시 한다.

### 7. 보고

```bash
python -m labelbot dashboard --workspace "<WS>" --run <RUN>
python ".claude/skills/BEOL-labeling/scripts/summary.py" --workspace "<WS>" --run <RUN>
```
대시보드를 적재 뒤에 한 번 더 만든다. 검수 반영 뒤 대시보드는 "검수 반영 결과" 화면(검수 전 불량 → 남은 불량, 사유별 전·후, 처리 결과, 많이 바로잡은 축·질문, 임베딩·Supabase 적재 건수)이고, 적재 건수는 만든 시점 기준이라 5단계의 대시보드에는 아직 0으로 나온다.

먼저 브라우저 패널에 화면 서버가 떠 있으면 `results.html` 탭을 새로고침한다(없으면 연다). 그다음 진행 현황 블록 아래에 아래 형식으로 **짧게** 보고한다. 제목 1줄과 항목 4줄 안팎으로 쓰고, 길어도 6줄을 넘기지 않는다.

```
## 검수 반영 (run_id: <RUN>)
- 검수 <HH:MM> 완료 · review <코드> n건 · 교정 축 n, 질문 n
- 적재: Supabase n행(누적 n) · 임베딩 n · 슬라이드 JPG 실패 n · Storage 꺼짐
- 재검토 요청 n건(누적 m, <사유 코드>) → [taxonomy_revisit.md](<WS 상대>/reports/taxonomy_revisit.md) · 실행별 k개 → [taxonomy_revisit_requests/](taxonomy/taxonomy_revisit_requests/)
- [대시보드](http://localhost:<port>/results.html) · [작업 폴더](<WS 상대>)
```

압축 규칙:
- **링크는 빼지 않는다.** 대시보드 URL, 작업 폴더, 재검토 요청이 1건 이상이면 누적 리포트(`reports/taxonomy_revisit.md`)와 실행별 폴더, 검수 등록 동의어가 1건 이상이면 `reports/candidates.md`를 마크다운 링크로 남긴다. 경로는 코드 폴더 기준 상대 경로로 쓴다.
- **0건이거나 기본값인 항목은 쓰지 않는다.** 확인·판단 불가·재검수 필요가 0이면 교정에서 빼고, 차단·건너뜀·실패가 0이면 빼고, 동의어 0건이면 candidates 줄을 빼고, 대조를 안 했으면 대조 줄을 뺀다. Downloads에서 옮긴 파일이 0이면 "모은 파일"도 쓰지 않는다.
- **피드백 줄은 4-2를 돌렸으면 한 줄 쓴다.** `라벨링 피드백: 규칙 후보 k개(상충 c)·사례 후보 p개 → [labeling_candidates.md](workspaces/_domain_engrbot/ledger/labeling_candidates.md) · /BEOL-labeling-Domain-Engr-bot으로 도메인 질문에 답하면 다음 라벨링에 반영된다`. 출처는 4-2의 `[labeling-rules]` 줄이고, 실패했으면 `라벨링 피드백: <사유 코드>`로 쓴다.
- **Domain-Engr-bot 장부 줄은 4-1을 돌렸으면 한 줄 쓴다.** `Domain-Engr-bot 장부: 사례 n(교정 n, 확인 n) → 누적 골든 n · judge 예시 n · L4 후보 n(draft)`. 출처는 4-1의 `[intake]`·`[ledger]` 줄이고, 실패했으면 `Domain-Engr-bot 장부: <사유 코드>`로 쓴다.
- **조건부 줄은 해당될 때만 한 줄씩 붙인다.** 파싱 대조(`대조: 이상 없음 n, 이상 있음 n`), 동의어(`동의어 n → [candidates.md](…) "검수 등록" 행을 synonyms 시트에`), `REVISIT_*`·`HOST_UNCERTAIN`·전송 실패 같은 사유 코드, Supabase 적재 꺼짐(`supabase.enabled=false`), 3-2에서 대신 내려받은 경우.
- 엑셀 붙여넣기 방법(md 탭 블록 또는 html 표 → taxonomy 시트 A열)은 재검토 요청이 있을 때 재검토 줄 끝에 괄호로 짧게만 적는다.
- 보고 뒤에 설명 문단을 덧붙이지 않는다. 이번 대화에서 설정을 바꾼 것(포트 변경 등)처럼 사용자가 꼭 알아야 할 일만 `※` 한 줄로 쓴다.

각 칸의 출처: 검수 시각은 2-5 `wait_review_done.py` 출력의 `done_at`, 교정은 요약의 `corrections`(`axis`, `answer`, `confirmed`, `undecidable_image`, `recheck`), 파싱 대조는 `compare_marks`(`ok`, `issue`), 검수 등록 동의어는 `review_synonyms`, 재검토는 `revisits`(이번 실행 `run`, 누적 `total`, 사유별 `by_reason`), 누적 적재는 `pushed_ok`, 전송·건너뜀·차단은 6단계 `push-vectors` 출력, 슬라이드 JPG는 6단계 `slide-images`·`push-slides` 출력, 실행별 파일 수는 4단계 `apply` 출력이다. 요약에 없는 값을 추정해서 채우지 않는다.
