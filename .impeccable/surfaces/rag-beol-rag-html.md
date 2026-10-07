---
version: 1
slug: "rag-beol-rag-html"
primary_target: "rag/beol_rag.html"
related_targets: []
---

# Surface brief: rag/beol_rag.html (대화 화면, 히어로 제외)

## Scope and mode

- 범위: 히어로 아래 대화 화면 전체(위 막대·필터·질문 이력·답·근거 슬라이드·팝업·입력창). 히어로(사진·문구·서체)는 고정이며 건드리지 않는다.
- 모드: Operate. 엔지니어가 범위를 좁혀 묻고, 근거 슬라이드를 확인해 직접 판단한다.

## Audience, job, constraints

- BEOL 공정 엔지니어, 불량 조사 중, 사무실 데스크톱(밝은 조명, Chrome·Edge). 휴대폰은 깨지지 않으면 된다.
- 성공: 근거 슬라이드를 빨리 찾고 믿는다. 답은 안내다.
- 근거 슬라이드는 흰 바탕 16:9 캡처다. 화면은 이 흰 그림과 어울려야 한다.
- 오프라인 규칙: 외부 폰트·CDN·외부 이미지 없음, 시스템 폰트와 파일 안 자원만. 데이터와 답은 당분간 지금처럼 Supabase·OpenAI API를 쓴다(2026-10-07 사용자 결정, PRODUCT.md).
- 기존 기능과 문구, 접근성(키보드·포커스·동작 줄이기·한글 조합 Enter)은 그대로 지킨다.

## Direction contract

THESIS: 답은 로트 진행표처럼 STEP 번호로 쌓이고, 문장마다 찍힌 주홍 도장이 그 근거 슬라이드로 이어진다. 거부하는 기본 배치는 회색 바탕에 말풍선만 이어지는 채팅 화면이다.

OWN-WORLD: 슬레이트(#3A4048, 히어로 벽의 청회색) 셸이 위 막대와 왼쪽 STEP 레일을 L자로 감싸고, 읽는 면은 밝은 회벽색(#EBEBE8), 답은 흰 진행 시트, 근거 슬라이드는 회색 트레이 위의 흰 첨부 장이다. 주홍(#D2452B, 히어로의 노을·붉은 그래피티)은 도장(출처 번호·근거 연결)에만, 모래색 꼬리표(#E6D6B8)는 현재 STEP·선택된 범위·선택 수에만, 호박색(#EBA33A)은 HOLD에만 쓴다. 글자는 한국어 시스템 고딕, STEP·Lot·WF·건수·점수 같은 값은 고정폭, 필드 이름은 고정폭 대문자(STEP, TIME, SCOPE, EVIDENCE, CITED, SLIDES, LOT, WF, SIGN-OFF). 시트마다 맨 위에 칸을 나눈 진행표 줄(STEP | TIME | SCOPE | EVIDENCE)이 있다. 히어로 세리프는 브랜드에만. (2026-10-07 사용자 결정: 처음 고른 카본 남색 셸은 히어로와 어울리지 않아 슬레이트로 바꿈)

STORY: 엔지니어는 히어로에서 내려와 위 막대의 드롭다운으로 범위를 잡고 묻는다. 답이 STEP으로 쌓이면 도장이 찍히고, 도장에 마우스를 올리면 그 슬라이드가 짚인다. 슬라이드를 열어 원문으로 판단하고, 좋아요·아쉬워요로 남긴다. 레일에서 앞 STEP으로 돌아간다.

FIRST VIEWPORT: 1440×900 기준. 위 막대 60px(슬레이트): 왼쪽 브랜드, 그 옆 필터 드롭다운 4개(공정 모듈·구조/레이어·제품·세대·+ 축 8개, 선택 수는 모래색 숫자), 오른쪽 SLIDES 70과 ↑. 왼쪽 레일 248px(슬레이트): STEP 목록, 현재 STEP에 모래색 꼬리표. 가운데 940px 읽기 열(회벽색 위 흰 시트): 진행표 줄(STEP·TIME·SCOPE·EVIDENCE), 질문, 도장이 박힌 답, 흰 근거 첨부 5칸(명판·관련도 막대), 평가 줄. 아래 입력창은 읽기 열 폭에 맞춰 고정되고 슬레이트 전송 버튼이 주된 동작이다. 대표 동작(도장 찍기와 도장↔슬라이드 짚기)은 답 시트와 근거 트레이 사이에 산다.

FORM: 로트 진행표(런카드). 내 근거 목록 7개 중 1순위, 주사위 배정은 4순위(옐로룸)였고 사용자가 IMPECCABLE’S PICK으로 이 방향을 골랐다. seed a5cbf57e. 접은 경쟁안에서 가져온 원칙: 근거마다 고정 명판(캐릭터 굿즈 카탈로그), 관련도는 정확한 길이의 막대(라바노테이션), 근거 칸 위치 고정(역 출발 안내판).

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Memorable moment

답이 도착하면 주홍 도장이 문장마다 찍히고, 도장 하나를 짚으면 아래 흰 첨부 장 중 그 슬라이드만 주홍 테두리와 명판 꼬리표로 응답한다.

## Unresolved

- Supabase·OpenAI 호출의 로컬 대체: 2026-10-07 사용자 결정으로 보류(당분간 OpenAI API로 통일). 사용자가 다시 요청하면 연다.
- 저장소에 로컬 폰트 파일이 생기면 고정폭·본문 글꼴을 다시 검토한다.
