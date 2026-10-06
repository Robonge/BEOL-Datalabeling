---
name: BEOL-taxonomy-dashboard
description: 흩어진 taxonomy 수정 제안(feedback·proposals·taxonomy_candidates·labelbot candidates·taxonomy_revisit·ledger 동의어·엔지니어 답변)을 중복 없이 한 화면에 모은 taxonomy 교정 대시보드(taxonomy_board.html)를 만들어 띄운다. 왼쪽은 이 HTML, 오른쪽은 사람이 연 taxonomy.xlsx(Excel)이며, 항목마다 taxonomy 시트 열 순서의 붙여넣기 행(초안)을 복사해 Excel에 붙여 넣는다. 봇은 xlsx를 쓰지 않는다. 사용자가 "taxonomy 대시보드", "taxonomy 교정 화면", "taxonomy 수정 보드", "taxonomy 보드 띄워줘", "taxonomy 반영 화면", "taxonomy 제안 모아줘", "taxonomy 보드 초기화"라고 하거나 /BEOL-taxonomy-dashboard를 부르면 이 스킬을 쓴다. 도메인 질문·승인 규칙 관리는 BEOL-labeling-Domain-Engr-bot, 라벨링 실행은 BEOL-labeling, 검수 반영은 BEOL-labeling-feedback이 맡는다.
---

# BEOL-taxonomy-dashboard

taxonomy 수정 제안을 한 화면에 모아 보여 주는 `taxonomy_board.html`을 만들고 띄운다. 코드는 `domain_engrbot/taxonomy_board.py`, 화면 틀은 `domain_engrbot/screens/taxonomy_board.html`이다.

## 규칙 (루트 CLAUDE.md DRM 규칙)

- 봇은 `taxonomy.xlsx`를 **쓰지 않는다**. 읽기는 `labelbot` ingest와 같은 bytes 경로(`domain_engrbot/adapters/labelbot_ws.py`)로만 한다. 수정은 사람이 Excel에서 한다.
- 산출물은 `.html`·`.json`만 쓴다. 로그·응답에는 ID·건수만 적고 본문·파일명은 적지 않는다.
- 보드를 Claude가 직접 열어 보지 않는다. 화면 확인이 필요하면 건수·경로만 전한다.

## 절차

1. 보드를 만든다. 작업 폴더를 지정하지 않으면 기본 작업 폴더를 쓴다.

   ```bash
   python -m domain_engrbot taxonomy-board
   ```

   옵션: `--workspace <폴더>`(여러 번 가능), `--taxonomy <경로>`, `--out-dir <폴더>`, `--open`(왼쪽 HTML·오른쪽 Excel 나란히 띄움), `--reset`, `--serve`(보드 서버 127.0.0.1:8795).

   사람이 검토하며 반영·기각을 확정하려면 서버로 연다(백그라운드 실행, 사용자가 Ctrl+C로 닫는다):

   ```bash
   python -m domain_engrbot taxonomy-board --serve --open
   ```

   화면 우측 상단 "최종 완료"가 반영함·기각함 표시를 `decisions.json`에 확정하고 taxonomy.xlsx를 다시 읽어 현황(미반영·반영됨·기각)을 갱신한다. 표시하지 않은 항목은 미반영으로 남는다. 확정한 항목은 카드의 "확정 취소"로 되돌리고, 같은 제안이 새 실행에서 다시 올라오면 확정이 풀려 다시 미반영이 된다. 반영함인데 시트에서 자동 확인되지 않으면 "시트 미확인" 배지가 붙는다.

2. 결과 한 줄(항목 수·미반영·반영됨·기각·먼저 할 일·확인 불가)과 화면 경로 `workspaces/_domain_engrbot/taxonomy_board/taxonomy_board.html`을 전한다. 사용자가 원하면 `--open`으로 다시 만들어 창을 띄운다.

3. 사람이 하는 일을 안내한다: 항목의 "행 복사"를 누르고 Excel의 해당 위치에 붙여 넣는다. 값 정의 보완은 "빈 행에 추가"(같은 값 행을 하나 더 붙임)가 기본이다. labelbot은 같은 축·값 행이 여럿이면 정의·포함 예·제외 예를 모두 합쳐 라벨러에 준다(상위값이 다르면 오류). 예전 정의를 버려야 하면 "덮어쓰기" 행을 쓴다. 붙여넣은 뒤 xlsx를 저장하고, 카드의 "Excel에 반영함"을 누른다. 거절할 항목은 "기각"을 누르면 rejected 시트 행이 복사되고 기각함으로 표시된다(그 행을 rejected 시트에 붙인다). 두 표시는 카드를 접고 이 브라우저에만 저장되며, 보드를 다시 만들어 시트에서 반영됨·기각됨이 확인되면 사라진다.

4. 다 반영했거나 의미가 없어진 항목을 화면에서 빼려면 초기화한다.

   ```bash
   python -m domain_engrbot taxonomy-board --reset
   ```

   초기화는 지금 보이는 항목의 출처 지문을 `cleared.json`에 기록해 숨긴다. 새 제안이 올라오면 그것만 다시 나타난다. 되돌리려면 `workspaces/_domain_engrbot/taxonomy_board/cleared.json`을 지운다.

### 새 축 체크리스트

taxonomy 시트에서 값 칸이 빈 행이 축이다. 새 축은 다음을 모두 채워야 라벨링에 들어간다.

1. 축 정의 행 D~G(다중값·계층·중복 알림 제외·종류)는 필수 칸이다. 비면 `YN_INVALID`·`AXIS_KIND_INVALID`로 멈춘다.
2. H열에 정의·판정 규칙을 쓴다. 비면 사전 점검(`taxonomy_axes`)이 WARN을 낸다.
3. 값 행을 1개 이상 둔다. 값 행이 없으면 그 축은 비활성이다.
4. questions 시트에 `새축=값`을 적용 대상으로 하는 질문 행을 둔다. 없으면 사전 점검이 WARN을 낸다(실행은 계속).
5. 저장한 뒤 `/BEOL-labeling`을 다시 돌린다. 옛 실행은 새 축이 비어 있으므로 `/BEOL-labeling-Code-Engr-bot`의 축 점검으로 찾아 다시 라벨링한다. `python -m labelbot taxonomy-diff --workspace "<WS>"`가 추가된 축을 보여 준다.

## 화면이 보여 주는 것

- 제안 출처: feedback 제안, proposals, taxonomy_candidates, labelbot 후보, taxonomy_revisit(요청 파일 포함), ledger 동의어, 엔지니어 답변.
- 같은 수정(값 추가·끄기·정의·중복 알림·축 정의·동의어·질문·TERM·out)은 한 건으로 합친다.
- 붙여넣기 행은 taxonomy 시트 열 순서(축·값·상위값·다중값·계층·중복 알림 제외·종류·정의·판정 규칙·포함 예·제외 예·사용 여부)이다. 비TERM 제안(정의 문장, 사용 여부 N)도 초안 행을 준다.
- 왜 올라왔나: 출처별 사유(labelbot 근거 문구, 재검토 사유·봇 값, Domain-Engr-bot 판정 종류·지표)와 근거 슬라이드(파일명·슬라이드 번호·제목, 미리보기 그림은 슬라이드마다 한 번만 넣어 모든 근거 슬라이드에 보이고 누르면 크게 보기. 그림이 없는 슬라이드는 labelbot slide-images로 만든다). 근거 chunk는 작업 폴더 work.sqlite에서 읽기 전용으로 찾는다.
- 상태: 미반영·반영됨·기각·먼저 할 일(부모값·질문 대상값을 끄면 워크북이 깨지는 경우)·확인 불가.
- 형식 점검(상위값·축 이름 유효성)과 Excel 붙여넣기용 TSV 따옴표 처리, 수식 주입 방지(`'` 접두)를 한다.

## 관련

- 도메인 질문·승인 규칙 관리: `BEOL-labeling-Domain-Engr-bot`
- 사용법·구조 상세: `domain_engrbot/README.md`, `.claude/skills/BEOL-labeling-Domain-Engr-bot/SKILL.md`의 "taxonomy 수정 보드" 절
