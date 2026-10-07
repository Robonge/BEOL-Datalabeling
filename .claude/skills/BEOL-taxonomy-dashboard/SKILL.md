---
name: BEOL-taxonomy-dashboard
description: 흩어진 taxonomy 수정 제안(feedback·proposals·taxonomy_candidates·labelbot candidates·taxonomy_revisit·ledger 동의어·엔지니어 답변)을 중복 없이 한 화면에 모은 taxonomy 교정 대시보드(taxonomy_board.html)를 만들어 보드 서버로 띄운다. 사람이 카드에서 편집 칸을 고치고 반영함·기각을 표시한 뒤 "최종 완료"를 누르면 변경 미리보기를 확인받고 봇이 taxonomy.json에 쓴다(원자적 저장, 이력 taxonomy_history.jsonl). 사용자가 "taxonomy 대시보드", "taxonomy 교정 화면", "taxonomy 수정 보드", "taxonomy 보드 띄워줘", "taxonomy 반영 화면", "taxonomy 제안 모아줘", "taxonomy 보드 초기화"라고 하거나 /BEOL-taxonomy-dashboard를 부르면 이 스킬을 쓴다. 도메인 질문·승인 규칙은 BEOL-labeling-Domain-Engr-bot이 맡는다.
---

# BEOL-taxonomy-dashboard

> 그룹: ② 품질 점검 · 재라벨링 · 상위: /BEOL-labeling-Domain-Engr-bot · 하위: 없음 · 전체 지도: README.md "스킬 지도"

taxonomy 수정 제안을 한 화면에 모아 보여 주고, 사람이 고른 것만 `taxonomy/taxonomy.json`에 반영하는 `taxonomy_board.html`을 만들고 띄운다. 코드는 `domain_engrbot/taxonomy_board.py`, 화면 틀은 `domain_engrbot/screens/taxonomy_board.html`, 서버는 `domain_engrbot/serve.py`의 보드 서버 절이다.

품질 점검 · 재라벨링 루프에서 `/BEOL-labeling-Domain-Engr-bot`의 하위 스킬이다(2026-10-07). 라벨링 파이프라인(`/BEOL-labeling-run-labeling`)은 이 보드를 자동으로 띄우지 않는다. 저장 뒤 재라벨링은 하지 않고 안내도 하지 않는다. 축·규칙 점검(`/BEOL-labeling-Code-Engr-bot`)은 사람이 부른다.

## 규칙 (루트 CLAUDE.md DRM 규칙)

- taxonomy 원본은 `taxonomy/taxonomy.json` 하나다. Excel(xlsx)은 쓰지도 열지도 않는다. 예전 xlsx는 `taxonomy-migrate`로 한 번 변환한다(보드에 .xlsx를 주면 `TAXONOMY_XLSX_NEEDS_MIGRATION`).
- 읽기는 `domain_engrbot/adapters/labelbot_ws.py`(labelbot ingest bytes 경로)로만, 쓰기는 `labelbot.taxonomy.save_doc`(버전 확인 → 검증 → 이력 → 원자적 교체)으로만 한다.
- 산출물은 `.html`·`.json`·`.jsonl`만 쓴다. 로그·응답에는 ID·건수·사유 코드만 적고 본문·파일명은 적지 않는다.
- 보드를 Claude가 직접 열어 보지 않는다. 화면 확인이 필요하면 건수·경로만 전한다.

## 절차

1. 보드 서버를 띄운다(백그라운드 실행, 사용자가 Ctrl+C로 닫는다). 작업 폴더를 지정하지 않으면 기본 작업 폴더를 모두 쓴다.

   ```bash
   python -m domain_engrbot taxonomy-board --serve --open
   ```

   옵션: `--workspace <폴더>`(여러 번 가능), `--taxonomy <taxonomy.json 경로>`, `--out-dir <폴더>`, `--open`(브라우저로 연다), `--reset`, `--serve`(보드 서버 127.0.0.1:8795). 보기만 할 때는 `python -m domain_engrbot taxonomy-board`로 html만 만든다(파일로 연 화면에서는 반영되지 않는다).

2. 결과 한 줄(항목 수·미반영·반영됨·기각·먼저 할 일·확인 불가)과 서버 주소·화면 경로 `workspaces/_domain_engrbot/taxonomy_board/taxonomy_board.html`을 전한다.

3. 사람이 하는 일을 안내한다.
   - **화면 이름:** 보드는 taxonomy.json 키 대신 화면 이름을 쓴다(파일 키는 그대로). 축 → **분류 기준**, 값 → **라벨**, 상위값 → **상위 라벨**, 정의·판정 규칙 → **라벨 설명**. 포함 예·제외 예·사용 여부는 그대로다. 축 속성 4열(다중값·계층·중복 알림 제외·종류)은 보드에서 보이지 않고, 고치려면 편집기를 쓴다.
   - **카드에서 고치기:** 노란 편집 칸을 고친다. 줄바꿈도 그대로 저장된다.
     - 새로 붙이는 행은 이름까지 고칠 수 있다: 새 라벨(분류 기준·라벨·상위 라벨·라벨 설명·예), 동의어(동의어·표준어·메모), 용어 후보 행, 새 질문.
     - 이미 있는 행 덮어쓰기는 분류 기준·라벨 이름을 잠근다(붙은 라벨·질문 적용 대상·동의어가 어긋나지 않게). 라벨 행은 상위 라벨·라벨 설명·포함 예·제외 예·사용 여부를, 분류 기준 행은 라벨 설명·예를, 질문 수정은 문장·적용 대상·우선순위를 고친다. 끄기 카드는 라벨 설명에 끄는 이유를 남길 수 있다.
     - 같은 라벨이 여러 행이면 상위 라벨·사용 여부를 바꿀 때 다른 켜진 행에도 같이 쓴다.
     - 새 라벨 이름이 예약어(해당없음·unknown·n/a·na)이거나 같은 분류 기준에 켜진 라벨이면, 새 분류 기준 이름이 이미 있으면 화면과 서버가 막는다(`ITEM_NOT_APPLICABLE`).
   - **대안 고르기:** 값·축 정의 보완은 "새 행으로 추가"(같은 값 행을 하나 더 붙여 labelbot이 정의를 합쳐 씀)와 "덮어쓰기"(예전 정의를 버림. 같은 값·축의 다른 켜진 행 H~J도 비움) 중 하나를, 용어 후보는 "동의어 행"과 "값 행" 중 하나를 라디오로 고른다.
   - **반영함·기각:** 필수 칸이 비었거나 형식이 틀렸거나, 문장 수정 항목(값·축 정의, 겹치는 값 정의, 질문 문장)에 쓸 문장이 없으면(편집 칸이 비었거나 지금 행과 같음) 반영함이 꺼져 있다. 겹치는 값 정의처럼 메모만 있는 제안은 정의를 써야 반영할 수 있다. 기각하면 모든 종류(값·동의어·질문·값 끄기·값 정의·겹침·축 정의·질문 수정·새 축·용어·기타)가 taxonomy.json rejected 목록에 행을 남긴다(원래 문장이 없는 새 질문만 결정만 남김). 대조는 종류와 내용("|"로 나눈 칸마다 NFKC·공백·대소문자 무시)으로 하므로, 새 실행에서 같은 제안이 표기만 조금 바뀌어 다시 올라와도 기각 상태로 접혀 검토를 묻지 않는다. 보드 기각 확정(decisions.json)도 새 출처가 붙어도 유지된다.
   - **최종 완료:** 추가·수정·기각 행(시트·행 번호·바뀌는 칸 이전 → 이후)과 검증 오류를 미리보기로 보여 준다. "taxonomy.json에 쓰기"를 누르면 봇이 저장하고(바꾸기 전 문서를 `taxonomy/taxonomy_history.jsonl`에 한 줄 남김) `decisions.json`에 확정을 기록한 뒤 보드를 새로 만든다. 표시하지 않은 항목은 미반영으로 남는다.
   - **거절되는 경우:** 다른 화면(편집기 등)이 먼저 저장했으면 `TAXONOMY_CHANGED`(409, 새로고침 후 다시), 검증이 깨지면 `TAXONOMY_INVALID`(오류 목록, 파일 그대로), 반영할 수 없는 항목이면 `ITEM_NOT_APPLICABLE`, 두 항목이 같은 칸을 다르게 고치면 `ITEM_CONFLICT`.
   - **확정 취소:** 반영함 카드의 "확정 취소"는 확정 기록만 지운다(쓴 내용은 그대로, 필요하면 편집기에서 고친다). 반영함은 같은 제안이 새 실행에서 다시 올라오면 확정이 풀려 다시 미반영이 된다.
   - **기각 해제:** 기각된 카드(전체 보기에서는 맨 아래 "기각 N건" 접힌 구역)의 "기각 해제"는 rejected 목록의 그 행과 보드 기각 확정을 지워 다시 미반영으로 올린다(이력이 남는다). Domain-Engr-bot에서 기각한 제안은 여기서 풀지 않는다. 기각 뒤 사람·엔지니어 출처(검수 등록·재검토·교정 장부·엔지니어 답변)가 새로 붙으면 기각은 유지하되 카드에 "새 사람 출처" 배지를 달고 콘솔에 건수를 낸다.

4. taxonomy를 직접 보고 고치려면(축·값 트리, 칸 수정, 행 추가·삭제, 사용 여부 끄기) 편집기를 쓴다.

   ```bash
   python -m domain_engrbot taxonomy-editor
   ```

5. 다 반영했거나 의미가 없어진 항목을 화면에서 빼려면 초기화한다.

   ```bash
   python -m domain_engrbot taxonomy-board --reset
   ```

   초기화는 지금 보이는 항목의 출처 지문을 `cleared.json`에 기록해 숨긴다. 새 제안이 올라오면 그것만 다시 나타난다. 되돌리려면 `workspaces/_domain_engrbot/taxonomy_board/cleared.json`을 지운다.

### 새 축 체크리스트

taxonomy 목록에서 값 칸이 빈 행이 축이다. 새 축은 다음을 모두 채워야 라벨링에 들어간다.

1. 축 정의 행 D~G(다중값·계층·중복 알림 제외·종류)는 필수 칸이다. 보드의 "새 분류 기준" 카드는 이 칸을 기본값(다중값 Y, 계층 Y, 중복 알림 제외 N, 종류 분류)으로 채우고 읽기 전용으로 보여 준다. 상태 축이나 다른 값이 필요하면 편집기(`python -m domain_engrbot taxonomy-editor --open`)에서 만든다. 편집기에서 비우면 저장 검증이 `YN_INVALID`·`AXIS_KIND_INVALID`로 거절한다.
2. H열에 정의·판정 규칙(보드 화면 이름: 라벨 설명)을 쓴다. 비면 사전 점검(`taxonomy_axes`)이 WARN을 낸다.
3. 값 행을 1개 이상 둔다. 값 행이 없으면 그 축은 비활성이다.
4. questions에 `새축=값`을 적용 대상으로 하는 질문 행을 둔다. 없으면 사전 점검이 WARN을 낸다(실행은 계속).
5. 저장한 뒤 `/BEOL-labeling`을 다시 돌린다. 옛 실행은 새 축이 비어 있으므로 `/BEOL-labeling-Code-Engr-bot`의 축 점검으로 찾아 다시 라벨링한다. `python -m labelbot taxonomy-diff --workspace "<WS>"`가 추가된 축을 보여 준다.

## 화면이 보여 주는 것

- 제안 출처: feedback 제안, proposals, taxonomy_candidates, labelbot 후보, taxonomy_revisit(요청 파일 포함), ledger 동의어, 엔지니어 답변.
- 같은 수정(값 추가·끄기·정의·겹치는 값·축 정의·동의어·질문·TERM·taxonomy 밖)은 한 건으로 합친다.
- 동의어는 1차 분류 본문을 표준어로 '치환'하므로 엄밀한 동의어(같은 대상의 다른 표기·한영 혼용·오타)만 올린다. 봇(labelbot 후보)만 올린 동의어는 다음이면 뺀다: 같은 말, 3자 이하 영문(JGV 제외), 표준어가 taxonomy의 축·값 이름이 아님, 표현이 표준어를 품음(더 좁은 개념), 같은 표현에 표준어 둘 이상, 전체 빈도 2 미만. 사람·엔지니어 출처가 섞이면 그대로 둔다. 뺀 수는 콘솔 한 줄로 낸다. 상위·하위 관계는 동의어가 아니라 값의 상위값(계층)이나 포함 예로 둔다.
- 행 초안은 taxonomy 열 순서(축·값·상위값·다중값·계층·중복 알림 제외·종류·정의·판정 규칙·포함 예·제외 예·사용 여부)이고 칸은 원문 그대로다. 서버는 반영할 때 행을 다시 만들고 사람이 고친 편집 칸만 얹는다. 값 끄기는 같은 값의 켜진 행을 모두 끈다.
- 왜 올라왔나: 출처별 사유(labelbot 근거 문구, 재검토 사유·봇 값, Domain-Engr-bot 판정 종류·지표)와 근거 슬라이드(파일명·슬라이드 번호·제목, 미리보기 그림은 슬라이드마다 한 번만 넣어 모든 근거 슬라이드에 보이고 누르면 크게 보기. 그림이 없는 슬라이드는 labelbot slide-images로 만든다). 근거 chunk는 작업 폴더 work.sqlite에서 읽기 전용으로 찾는다.
- 상태: 미반영·반영됨(taxonomy에 있음 또는 보드에서 반영함)·기각(rejected 목록·Domain-Engr-bot 기각·보드에서 기각함)·먼저 할 일(없는 축·상위값, 끄면 하위값·질문 대상이 깨지는 값, 대상 행 없음)·확인 불가(taxonomy.json을 읽지 못함).
- 형식 점검(필수 칸, Y/N, 분류/상태, 정수, 적용 대상, 새 질문 ID, 상위값·축 이름)을 화면과 저장 검증에서 함께 한다. 어두운 화면 설정과 휴대폰 폭에서도 쓸 수 있다.

## 관계
- taxonomy 직접 편집: `python -m domain_engrbot taxonomy-editor`
- 도메인 질문·승인 규칙 관리: `BEOL-labeling-Domain-Engr-bot`
- 사용법·구조 상세: 저장소 `README.md`의 "domain_engrbot (도메인 질문)"·"저장소 구조" 절, `.claude/skills/BEOL-labeling-Domain-Engr-bot/SKILL.md`의 "taxonomy 수정 보드" 절
- taxonomy를 직접 고치는 편집기는 python -m domain_engrbot taxonomy-editor, 도메인 질문·승인 규칙 관리는 BEOL-labeling-Domain-Engr-bot, 라벨링 실행은 BEOL-labeling, 검수 반영은 BEOL-labeling-feedback이 맡는다.
