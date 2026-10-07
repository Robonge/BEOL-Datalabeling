---
name: BEOL Slide RAG
description: 범위를 좁혀 묻고, 주홍 도장으로 근거 슬라이드를 짚는 로트 진행표형 대화 화면
colors:
  shell: "#3A4048"
  shell-2: "#454C55"
  shell-3: "#515963"
  shell-line: "#58606A"
  shell-text: "#F2EFEA"
  shell-muted: "#C4C9D0"
  ground: "#EBEBE8"
  tray: "#F3F3F1"
  sheet: "#FFFFFF"
  line: "#D4D5D4"
  line-2: "#E3E3E1"
  ink: "#1E2227"
  ink-2: "#4B5159"
  ink-3: "#626972"
  action: "#2C3238"
  action-hover: "#3A4048"
  stamp: "#D2452B"
  stamp-ink: "#B4361F"
  stamp-soft: "rgba(210,69,43,.09)"
  tag: "#E6D6B8"
  tag-ink: "#2A2318"
  hold: "#EBA33A"
  hold-soft: "#FBE8C4"
  hold-ink: "#2A1A00"
  hero-cream: "#F3EBDD"
  hero-ink: "#1D1A1A"
typography:
  brand:
    fontFamily: "'Sitka Banner', 'Didot', 'Bodoni 72', 'Bodoni MT', Georgia, serif"
    fontSize: "19px"
    fontWeight: 400
    lineHeight: 1
  hero-script:
    fontFamily: "'Edwardian Script ITC', 'Snell Roundhand', 'Apple Chancery', 'Gabriola', Georgia, serif"
    fontSize: "clamp(30px, 3.6vw, 56px)"
    fontWeight: 400
    lineHeight: 1
  headline:
    fontFamily: "'Apple SD Gothic Neo', 'Noto Sans KR', 'Malgun Gothic', sans-serif"
    fontSize: "17px"
    fontWeight: 700
    lineHeight: 1.5
    letterSpacing: "-0.02em"
  title:
    fontFamily: "'Apple SD Gothic Neo', 'Noto Sans KR', 'Malgun Gothic', sans-serif"
    fontSize: "16.5px"
    fontWeight: 700
    lineHeight: 1.45
  answer:
    fontFamily: "'Apple SD Gothic Neo', 'Noto Sans KR', 'Malgun Gothic', sans-serif"
    fontSize: "15.5px"
    fontWeight: 400
    lineHeight: 1.85
  body:
    fontFamily: "'Apple SD Gothic Neo', 'Noto Sans KR', 'Malgun Gothic', sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.6
    letterSpacing: "-0.01em"
    fontFeature: "tnum"
  small:
    fontFamily: "'Apple SD Gothic Neo', 'Noto Sans KR', 'Malgun Gothic', sans-serif"
    fontSize: "12.5px"
    fontWeight: 400
    lineHeight: 1.45
  value:
    fontFamily: "Consolas, 'D2Coding', 'SF Mono', Menlo, monospace"
    fontSize: "12.5px"
    fontWeight: 400
  label:
    fontFamily: "Consolas, 'D2Coding', 'SF Mono', Menlo, monospace"
    fontSize: "11px"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "0.08em"
rounded:
  xs: "4px"
  sm: "6px"
  md: "8px"
  lg: "10px"
  xl: "12px"
  input: "14px"
  modal: "16px"
  work: "18px"
  pill: "999px"
  circle: "50%"
spacing:
  xs: "6px"
  sm: "8px"
  md: "10px"
  lg: "12px"
  xl: "14px"
  2xl: "18px"
  3xl: "22px"
  4xl: "28px"
components:
  button-send:
    backgroundColor: "{colors.action}"
    textColor: "{colors.sheet}"
    rounded: "{rounded.lg}"
    padding: "0 16px"
    height: "40px"
  button-send-hover:
    backgroundColor: "{colors.action-hover}"
  filter-button:
    backgroundColor: "{colors.shell-2}"
    textColor: "{colors.shell-text}"
    rounded: "{rounded.pill}"
    padding: "0 10px 0 13px"
    height: "34px"
  filter-button-hover:
    backgroundColor: "{colors.shell-3}"
  filter-button-open:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
  scope-chip:
    backgroundColor: "{colors.tag}"
    textColor: "{colors.tag-ink}"
    rounded: "{rounded.pill}"
    padding: "0 7px 0 10px"
    height: "26px"
  feedback-button:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.pill}"
    padding: "0 12px"
    height: "30px"
  feedback-button-on:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.sheet}"
  step-sheet:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "16px 22px"
  evidence-tray:
    backgroundColor: "{colors.tray}"
    rounded: "{rounded.xl}"
    padding: "12px 12px 14px"
  stamp:
    backgroundColor: "{colors.stamp-soft}"
    textColor: "{colors.stamp-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.circle}"
    size: "22px"
  stamp-hot:
    backgroundColor: "{colors.stamp}"
    textColor: "{colors.sheet}"
  hold-banner:
    backgroundColor: "{colors.hold-soft}"
    textColor: "{colors.hold-ink}"
    rounded: "{rounded.md}"
    padding: "10px 12px"
  hold-tag:
    backgroundColor: "{colors.hold}"
    textColor: "{colors.hold-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.xs}"
    height: "22px"
  question-input:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.input}"
    padding: "7px 7px 7px 14px"
---

# Design System: BEOL Slide RAG

> **적용 범위.** 이 문서는 `rag/beol_rag.html`의 대화 화면, 곧 히어로 아래 모든 것(위 막대·STEP 레일·범위 칩·진행 시트·근거 트레이·평가 줄·HOLD·입력창·근거 팝업)만 다룬다. 히어로는 고정 요소로 기록만 하고 이 규칙으로 바꾸지 않는다. 저장소의 다른 화면(대시보드, 검수 화면, labelbot 페이지)은 계속 기존 BEOL AX 문서 `design.md.md`를 따른다. 두 문서는 서로를 덮지 않는다.

## Overview

**Creative North Star: "로트 진행표(런카드)"**

답은 채팅 말풍선이 아니라 공정 로트의 진행표처럼 STEP 번호로 쌓인다. 슬레이트 셸이 위 막대와 왼쪽 STEP 레일을 L자로 감싸고, 그 안쪽의 밝은 회벽색 작업면 위에 흰 진행 시트가 한 장씩 놓인다. 시트마다 맨 위에 칸을 나눈 진행표 줄(STEP | TIME | SCOPE | EVIDENCE)이 있고, 답의 문장에 찍힌 주홍 도장이 아래 회색 트레이의 흰 근거 슬라이드로 이어진다. 근거 슬라이드는 흰 바탕 16:9 캡처라서, 작업면은 그 흰 그림이 가장 밝은 물건이 되도록 한 단계 어둡게 깔린다.

밀도는 사무실 데스크톱에서 오래 읽는 작업 화면의 밀도다. 본문은 한국어 시스템 고딕, STEP·Lot·WF·건수·점수 같은 값은 고정폭, 필드 이름은 고정폭 대문자다. 색은 셸의 청회색과 작업면의 무채색이 거의 전부이고, 색이 있는 세 가지(주홍, 모래색, 호박색)는 각각 한 가지 의미만 맡는다. 색이 보이면 그 의미가 있는 것이다.

히어로(Casa Lunara 사진, "Back End of Line / Ask the Slides", 세리프와 스크립트 서체)는 사용 허락을 받은 비상업 데모용 고정 요소다. 셸의 슬레이트(#3A4048)는 히어로 벽의 청회색에서, 주홍은 히어로의 노을빛에서 왔다. 히어로 세리프는 대화 화면에서 브랜드 글자에만 쓴다. 확정된 거부: 카본 남색 셸, 갈색·검정에 노을 주황을 얹은 다크 테마, BEOL AX 인디고, 회색 말풍선 채팅 배치.

**Key Characteristics:**
- 슬레이트 L자 셸(위 막대 60px + STEP 레일 248px)과 왼쪽 위 모서리만 둥근 회벽색 작업면.
- 940px 읽기 열 안에 흰 진행 시트가 STEP 순서로 쌓인다.
- 시트 맨 위 진행표 줄: 고정폭 대문자 필드 이름과 값.
- 주홍 원형 도장이 문장 끝에서 근거 번호를 찍고, 짚으면 그 슬라이드만 주홍 테두리로 응답한다.
- 근거 슬라이드는 회색 트레이 위 5칸 고정 그리드의 흰 첨부 장(명판, 관련도 막대).
- 시스템 폰트만, 외부 자원 없음.

## Colors

청회색 셸과 무채색 작업면 위에, 의미가 하나씩 묶인 세 가지 색만 얹는 팔레트다.

### Primary
- **슬레이트 셸** (shell): 위 막대, STEP 레일, 히어로 둘레의 바탕. 히어로 벽의 청회색에서 가져왔고 2026-10-07 사용자가 확정했다. 한 단계 밝은 셸 2·3(shell-2, shell-3)은 셸 위 버튼의 바탕과 hover, 셸 선(shell-line)은 셸 위 테두리, 셸 글자(shell-text)와 흐린 셸 글자(shell-muted)는 셸 위 글자다.
- **진행 동작 먹색** (action): 전송 버튼, 확인함 체크, 예시 질문 테두리, 링크, 작업면 위 포커스 링. hover는 슬레이트(action-hover)로 한 단계 밝아진다. 작업면 위에서 주된 동작은 이 색 하나다.

### Secondary
- **주홍 도장** (stamp): 출처 번호 도장의 테두리와 눌린 상태, 도장이 짚은 근거 슬라이드의 테두리. 도장 안 숫자는 주홍 먹(stamp-ink), 평상시 도장 안은 아주 옅은 주홍(stamp-soft)이다.

### Tertiary
- **모래색 꼬리표** (tag): 현재 STEP 번호, 선택된 범위 칩, 필터 버튼의 선택 수. 글자는 꼬리표 먹(tag-ink).
- **호박색 HOLD** (hold): 답을 받지 못한 STEP의 HOLD 표. 옅은 호박(hold-soft)은 HOLD 띠의 바탕, 호박 먹(hold-ink)은 HOLD 글자, 다시 시도 버튼, 진행표 줄 EVIDENCE 칸의 HOLD 값이다.

### Neutral
- **회벽색 작업면** (ground): 읽기 열 뒤의 바탕. 흰 시트와 흰 슬라이드가 떠 보이도록 한 단계 어둡다.
- **트레이 회색** (tray): 근거 트레이, 진행표 줄, 팝업의 그림 쪽, 입력란 바탕, 옵션 hover.
- **시트 흰색** (sheet): 진행 시트, 입력창, 팝업, 드롭다운, 슬라이드 썸네일 바탕.
- **선** (line, line-2): line은 입력과 버튼 테두리, 썸네일 외곽, 관련도 막대 트랙. line-2는 시트 테두리, 진행표 줄 칸 구분, 평가 줄 위 구분선처럼 더 조용한 구분.
- **먹** (ink, ink-2, ink-3): 본문과 제목, 보조 글자, 필드 이름과 흐린 메타. ink-3(#626972)이 가장 옅은 글자이며 그보다 옅게 내리지 않는다.
- **히어로 크림·히어로 먹** (hero-cream, hero-ink): 히어로 안에서만 쓴다. 대화 화면에 가져오지 않는다.

### Named Rules
**The One Meaning Rule.** 주홍은 도장(출처 번호와 도장↔슬라이드 연결)에만, 모래색은 꼬리표(현재 STEP, 선택된 범위, 선택 수)에만, 호박색은 HOLD에만 쓴다. 빌드에서 모래색은 셸 위 포커스 링과 글자 선택 바탕에도 쓰이는데, 둘 다 셸 위 가독성을 위한 예외이고 새 용도를 늘리는 근거가 아니다.

**The White Is For Evidence Rule.** 가장 밝은 흰색은 시트와 근거 슬라이드 몫이다. 작업면 바탕은 회벽색으로 두고, 흰색을 넓은 바탕으로 깔지 않는다.

## Typography

**Display Font:** 대화 화면에는 디스플레이 서체가 없다. 히어로 세리프('Sitka Banner', Didot, Bodoni 계열, Georgia)는 브랜드 글자 "BEOL Slide RAG"에만 쓴다. 히어로 스크립트(`hero-script`: 'Edwardian Script ITC' 등 시스템 서체)는 고정 요소인 히어로의 "Back End of Line" 한 줄에만 있고, 대화 화면에서는 쓰지 않는다.
**Body Font:** 'Apple SD Gothic Neo', 'Noto Sans KR', 'Malgun Gothic', sans-serif (시스템 고딕)
**Label/Mono Font:** Consolas, 'D2Coding', 'SF Mono', Menlo, monospace (시스템 고정폭)

**Character:** 한국어 고딕이 문장을 맡고, 고정폭이 값과 필드 이름을 맡는다. 진행표처럼 읽히는 것은 고정폭 대문자 필드 이름과 그 옆 값의 짝 때문이다.

### Hierarchy
- **Brand** (400, 19px, 1): 위 막대의 브랜드 글자만. 히어로 세리프.
- **Headline** (700, 17px, 1.5, -0.02em): 시트의 질문, 첫 화면 안내 제목.
- **Title** (700, 16.5px, 1.45): 근거 팝업의 슬라이드 제목.
- **Answer** (400, 15.5px, 1.85, 최대 46em): 답 본문. 가장 오래 읽는 글자라 줄간격이 가장 넓다.
- **Body** (400, 14px, 1.6, -0.01em, 숫자 tabular-nums): 기본 글자, 안내 문단(최대 44em).
- **Small** (400, 12.5–13px): 필터·칩·평가 버튼, 트레이 머리, 명판 제목(700), 다시 묻는 질문 줄.
- **Value** (고정폭 400–700, 11–13px): STEP 번호, Lot/WF, 날짜, 점수, 건수.
- **Label** (고정폭 700, 11px, 0.08em, 대문자): 필드 이름. STEP, TIME, SCOPE, EVIDENCE, CITED, SAME FILE, SLIDES, LOT, WF, AUTHOR, DATE, SCORE, FILE, SIGN-OFF.

### Named Rules
**The Field Pair Rule.** 고정폭 대문자 라벨은 진행표의 필드 이름이다. 반드시 바로 옆이나 같은 줄의 값(또는 그 필드가 담는 목록)과 짝을 이룬다. 제목 위에 홀로 얹는 장식 꼬리말로 쓰지 않는다.

**The Keep-All Rule.** 한국어 질문·답·안내는 `word-break: keep-all`과 `overflow-wrap: anywhere`로 어절 단위로 끊는다.

## Layout

화면은 히어로(100svh, 스크롤 스냅)와 대화 화면(100dvh) 두 장이다. 대화 화면은 위 막대(최소 60px) 아래에 248px STEP 레일과 작업면이 나란히 서는 L자 셸이다. 작업면은 왼쪽 위 모서리만 18px로 둥글어 셸 안쪽으로 파인 면처럼 보인다.

작업면 안에는 범위 칩 줄, 스크롤되는 질문 이력, 아래 고정 입력창이 세로로 선다. 질문 이력과 입력창은 모두 940px 읽기 열에 맞춰 가운데 정렬된다. 시트 사이 간격은 22px, 작업면 안쪽 여백은 22–28px다. 간격 단계는 6, 8, 10, 12, 14, 18, 22, 28px이다.

근거 트레이는 5칸 고정 그리드(칸 간격 14px)다. 근거 칸 위치는 고정이라 같은 번호는 언제나 같은 자리에 있다. 근거 팝업은 그림 1.6 : 정보 1(최소 260px) 두 칸, 최대 1000px.

900px 이하: 레일을 숨기고, 필터는 위 막대 아래 한 줄 가로 스크롤로 내려가며, 드롭다운은 화면 아래에 붙는 시트와 어두운 막(scrim)으로 바뀐다. 진행표 줄은 TIME 칸을 빼고, 근거 트레이는 150px 칸 5개를 가로 스크롤한다. 팝업은 한 칸으로 쌓인다.

## Elevation & Depth

깊이는 주로 색조 층으로 만든다. 슬레이트 셸, 회벽색 작업면, 회색 트레이, 흰 시트 순서로 밝아지며 앞으로 나온다. 그림자는 아주 낮고 넓게 퍼지는 차가운 그림자(rgba(20,22,26,…))이며, 떠 있는 것(드롭다운, 팝업)만 진한 그림자를 받는다. 딱딱한 오프셋 그림자는 없다.

### Shadow Vocabulary
- **시트 놓임** (`box-shadow: 0 1px 2px rgba(20,22,26,.05), 0 8px 24px rgba(20,22,26,.06)`): 진행 시트.
- **입력창 떠 있음** (`box-shadow: 0 6px 18px rgba(20,22,26,.08)`): 아래 고정 입력창.
- **입력창 포커스** (`box-shadow: 0 0 0 3px rgba(44,50,56,.16), 0 6px 18px rgba(20,22,26,.08)`): 입력창 안에 포커스가 있을 때, 테두리는 진행 동작 먹색.
- **슬라이드 외곽** (`box-shadow: 0 0 0 1px var(--line), 0 2px 6px rgba(20,22,26,.08)`): 근거 썸네일. 짚으면 `0 0 0 2px var(--stamp), 0 6px 16px rgba(20,22,26,.14)`.
- **도장 꼬리표** (`box-shadow: 0 2px 6px rgba(20,22,26,.15)`): 썸네일 모서리의 번호 도장.
- **드롭다운** (`box-shadow: 0 18px 44px rgba(0,0,0,.28), 0 2px 6px rgba(0,0,0,.12)`): 셸 위로 펼쳐지는 필터 목록.
- **팝업** (`box-shadow: 0 30px 80px rgba(0,0,0,.4)`): 근거 팝업, 뒤는 rgba(20,22,26,.55) 막.

### Named Rules
**The Tonal First Rule.** 층을 나눌 때 먼저 바탕색 단계(셸 → 회벽 → 트레이 → 흰 시트)로 나눈다. 그림자는 그 위에 얹는 보조이고, 진한 그림자는 화면 위에 뜬 것에만 준다.

## Shapes

모서리는 부드럽고 크기에 비례한다. 작은 체크 상자와 HOLD 표 4px, 진행표 줄과 썸네일 6px, 옵션·입력란·HOLD 띠 8px, 시트·STEP 버튼·전송 버튼 10px, 트레이와 드롭다운 12px, 입력창 14px, 팝업 16px, 작업면 모서리 18px. 필터 버튼, 범위 칩, 평가 버튼, 선택 수는 알약형(999px)이다. 도장과 위로 가기 버튼, 브랜드 표식은 정원이다.

도장은 번호마다 고정된 작은 각도(-5°에서 +5°, 번호로 계산)로 기울어 손으로 찍은 느낌을 준다. 진행표 줄은 1px 선으로 칸을 나눈다. 예시 질문 버튼만 점선 테두리를 쓴다.

## Components

### Buttons
작업면 위 버튼은 조용하고, 주된 동작은 먹색 하나다.
- **Shape:** 부드러운 모서리(10px), 높이 40px.
- **Primary (전송):** 진행 동작 먹색 바탕, 흰 글자 700, 좌우 16px, 오른쪽 화살표 아이콘. hover에서 슬레이트로 밝아진다.
- **Hover / Focus:** 작업면 위 포커스는 2px 진행 동작 먹색 외곽선, 2px 띄움. 셸 위 포커스는 모래색 외곽선.
- **Secondary:** 평가 버튼(알약형 30px, 흰 바탕, line 테두리, 선택되면 먹색 바탕 흰 글자), 다시 시도(6px, 흰 바탕, 호박 먹 테두리와 글자), 팝업 이전·다음(8px, 흰 바탕, line 테두리), 예시 질문(10px 점선 진행 동작 먹색 테두리, 트레이 바탕).
- **Disabled:** 불투명도 .55, not-allowed 커서.

### Chips
- **필터 버튼(셸 위):** 알약형 34px, 셸 2 바탕, 셸 선 테두리, 셸 글자, 아래 꺾쇠. hover는 셸 3, 펼쳐지면 흰 바탕 먹 글자. 선택 수는 모래색 알약 안 고정폭 숫자.
- **범위 칩(작업면 위):** 알약형 26px, 모래색 바탕, 꼬리표 먹 글자 12px, 축 이름은 흐리게, 끝에 x 아이콘. 누르면 그 범위가 빠진다.
- **팝업 라벨 태그:** 알약형, 트레이 바탕, line 테두리. "해당 없음" 값은 점선 테두리와 불투명도 .6. 모래색을 쓰지 않는다.

### Cards / Containers
- **Corner Style:** 진행 시트 10px, 근거 트레이 12px.
- **Background:** 시트는 흰색, 트레이는 트레이 회색, 진행표 줄은 트레이 회색.
- **Shadow Strategy:** 시트 놓임 그림자(Elevation 참고). 트레이는 그림자 없음.
- **Border:** 시트는 line-2 1px.
- **Internal Padding:** 시트 16px 22px(모바일 14px), 트레이 12px 12px 14px.

### Inputs / Fields
- **Style:** 입력창은 흰 바탕, line 1px 테두리, 14px 모서리, 떠 있음 그림자. 왼쪽에 고정폭 "STEP 02" 다음 번호, 가운데 늘어나는 textarea(40–140px), 오른쪽 전송 버튼.
- **Focus:** 테두리가 진행 동작 먹색으로 바뀌고 3px 옅은 먹색 링이 둘러진다. textarea 자체 외곽선은 없앤다.
- **평가 의견란:** 30px, 트레이 바탕, line 테두리, 8px.

### Navigation
- **위 막대:** 슬레이트 바탕, 브랜드(세리프) → 필터 버튼 4개 → 오른쪽 SLIDES 건수와 위로 가기 원형 버튼.
- **STEP 레일:** 각 STEP은 30px 번호 칸 + 질문 두 줄 + 상태 한 줄. 번호 칸은 셸 2 바탕 흐린 글자, 현재 STEP은 모래색 바탕 꼬리표 먹. hover는 셸 2 바탕.
- **모바일:** 레일을 숨기고 필터를 한 줄 가로 스크롤로 내린다.

### 진행 시트와 진행표 줄 (Signature)
시트 맨 위는 칸을 나눈 진행표 줄이다: STEP | TIME | SCOPE | EVIDENCE. 필드 이름은 고정폭 대문자 라벨, 값은 고정폭(SCOPE만 한국어 고딕). 답을 받지 못하면 EVIDENCE 값이 호박 먹 굵은 글자로 바뀐다. 그 아래 질문(Headline), 답(Answer), 근거 트레이, 평가 줄(SIGN-OFF, 위쪽 line-2 구분선)이 이어진다.

### 주홍 도장 (Signature)
22px 정원, 2px 주홍 테두리, 옅은 주홍 안, 주홍 먹 고정폭 숫자, 번호별 고정 기울기. hover나 짚힘 상태에서 주홍으로 채워지고 흰 숫자가 된다. 새 답이 오면 도장이 1.7배에서 눌려 내려앉는 0.46s 애니메이션(cubic-bezier(.16,1,.3,1), 90ms 간격)이 재생되고, 동작 줄이기 설정에서는 재생하지 않는다.

### 근거 첨부 장 (Signature)
트레이 위 5칸 그리드. 각 칸은 16:9 흰 썸네일(6px, 외곽 링), 오른쪽 위 26px 번호 도장, 명판(고정폭 번호 + 굵은 제목, 고정폭 Lot·WF, 두 줄 요약), 관련도 막대(3px 트랙, ink-2 채움, 고정폭 점수)로 이루어진다. 도장이나 칸을 짚으면 그 칸만 2px 주홍 테두리와 채워진 번호 도장으로 응답한다. 트레이 머리는 EVIDENCE·CITED·SAME FILE 같은 필드 이름과 고정폭 값.

### HOLD 띠
옅은 호박 바탕 8px 띠, 호박색 HOLD 표(고정폭 대문자, 4px), 사유 코드가 담긴 문장, 다시 시도 버튼. 다시 시도가 의미 없는 사유 코드에서는 버튼을 붙이지 않는다.

### 근거 팝업
그림 쪽(트레이 바탕, 16:9 흰 그림, 이전·다음 근거)과 정보 쪽(도장 + 제목 + 닫기, LOT/WF/AUTHOR/DATE/SCORE/FILE 표, 라벨 태그, 펼치는 본문)의 두 칸.

## Do's and Don'ts

### Do:
- **Do** 대화 화면의 바탕을 슬레이트 셸(#3A4048)과 회벽색 작업면(#EBEBE8)으로 두고, 흰색은 시트와 근거 슬라이드에 남긴다.
- **Do** 주홍(#D2452B)은 도장에만, 모래색(#E6D6B8)은 꼬리표(현재 STEP·선택된 범위·선택 수)에만, 호박색(#EBA33A)은 HOLD에만 쓴다.
- **Do** 새 답 화면에도 시트 맨 위 진행표 줄(STEP | TIME | SCOPE | EVIDENCE)을 둔다.
- **Do** 값(STEP·Lot·WF·건수·점수·날짜)은 고정폭, 필드 이름은 고정폭 대문자 11px 700 0.08em으로 쓰고 값과 짝을 짓는다.
- **Do** 시스템 폰트 스택만 쓴다. 로컬 폰트 파일은 저장소 `assets/`에 생긴 뒤 경로로 직접 연결한다.
- **Do** 아이콘은 16px 인라인 SVG(stroke 1.7, currentColor, 둥근 끝)로 넣는다.
- **Do** 근거 칸 위치를 고정하고, 관련도는 정확한 길이의 막대와 고정폭 점수로 보여 준다.
- **Do** 움직임은 `prefers-reduced-motion: no-preference`일 때만 재생한다.

### Don't:
- **Don't** 카본 남색 셸(#1F2B57)을 쓰지 않는다. 히어로와 어울리지 않아 사용자가 거절했다.
- **Don't** 갈색·검정 바탕에 노을 주황을 얹은 다크 테마를 쓰지 않는다.
- **Don't** BEOL AX 인디고를 이 화면에 가져오지 않는다. BEOL AX `design.md.md`는 다른 화면의 규칙이다.
- **Don't** 회색 바탕에 말풍선만 이어지는 채팅 배치를 쓰지 않는다.
- **Don't** CDN, 외부 웹 폰트, 외부 이미지·URL을 어떤 코드 조각에도 넣지 않는다.
- **Don't** 주홍·모래색·호박색을 장식이나 강조색으로 돌려쓰지 않는다.
- **Don't** 히어로 세리프와 스크립트 서체를 브랜드 글자 밖의 대화 화면 제목이나 본문에 쓰지 않는다.
- **Don't** 고정폭 대문자 라벨을 값 없이 제목 위에 홀로 얹는 꼬리말로 쓰지 않는다.
