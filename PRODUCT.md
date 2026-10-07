# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

BEOL(Back-End-of-Line) 공정 엔지니어. 불량·이슈를 조사하는 중에 이전 세대나 다른 제품의 비슷한 평가 이력을 찾는다. 지금은 사내 웹드라이브와 Confluence를 keyword로 뒤지고, 파일을 5개 이상 열어 본 뒤에야 맞는 파일을 찾는다(`PRD.md` 1절). 맞는 이력 슬라이드만 찾아 주면 유사도 판단은 엔지니어가 직접 한다.

이 기록은 RAG 화면(`rag/beol_rag.html`) 기준이다. 라벨링 검수 화면(`review.html`·`results.html`)의 사용자는 아직 이 기록에 담지 않았다.

## Product Purpose

질문을 받으면 라벨이 붙은 슬라이드에서 근거를 찾아, 출처 번호를 붙인 답과 근거 슬라이드를 함께 돌려준다. 성공은 엔지니어가 **근거 슬라이드를 빨리 찾고 믿는 것**이다. 답은 안내이고, 판단은 엔지니어가 원문 슬라이드를 보고 한다.

## Positioning

keyword 검색은 다른 제품·다른 case에서도 같은 용어를 써서 엉뚱한 파일이 섞인다. 이 화면은 taxonomy 라벨(공정 모듈·구조/레이어·제품·세대와 축 8개 더)로 범위를 좁히고, 답의 문장마다 근거 슬라이드 번호를 붙여 출처를 바로 열어 보게 한다.

## Operating Context

- 사무실 데스크톱 모니터, 밝은 사무실 조명, Windows PC의 Chrome·Edge에서 오래 읽는다. 휴대폰은 깨지지만 않으면 된다.
- 한국어 UI에 영문 공정 용어가 섞인다(예: M2 RSBM TaN ALD cycle window, Rc, WF, Lot).
- 근거 슬라이드는 흰 바탕 16:9 PowerPoint 슬라이드 캡처(JPG)다. 화면은 이 흰 슬라이드 그림과 어울려야 한다.

## Capabilities and Constraints

- 기능: 질문 입력(Enter 전송, Shift+Enter 줄바꿈, 한글 조합 중 Enter 무시), 라벨 필터(축 11개, 값별 건수, 축당 최대 30개 선택), 출처 번호가 붙은 답, 근거 슬라이드(검색된 상위 슬라이드와 답에 인용된 같은 파일 슬라이드), 슬라이드 팝업(그림·라벨·Lot/WF/작성자/날짜·cosine/RRF 점수·본문), 답 평가(좋아요/아쉬워요와 한 줄 의견, Supabase 기록), 최근 대화 이어 묻기, "자료에 없음"·참고용 표시, 오류 사유 코드와 다시 시도.
- 백엔드: Supabase(REST 표·Storage·Edge Function `beol-rag-ask`). Edge Function이 OpenAI API를 부른다.
- HTML 한 파일, 엄격한 CSP(외부 폰트·스크립트 불가, 그림은 Supabase·data·blob만).
- **사내 오프라인 환경(2026-10-07, `CLAUDE.md` "환경 규칙")**: 외부 인터넷이 막힌 사내 리눅스 클라우드 VS Code에서 돈다. 외부 API·URL·웹훅·CDN·웹 폰트에 접근하는 코드를 새로 쓰지 않고, 코드·폰트·이미지는 저장소 안 로컬 파일(예: `assets/`)이나 파일 안 data URI로만 쓴다. `pip`은 사내 미러로 된다.
- **결정(2026-10-07)**: RAG 화면은 지금처럼 Supabase(REST·Storage·Edge Function)를 부르고, Edge Function은 OpenAI API를 부른다. 사용자가 당분간 OpenAI API를 쓰는 방식으로 통일하기로 했다(`CLAUDE.md` 환경 규칙의 예외). 로컬 대체는 사용자가 다시 요청할 때까지 보류한다.
- 저장소에는 아직 로컬 폰트 파일이 없다. 그 전까지는 시스템 폰트만 쓴다.
- 사내 파일 DRM 규칙(`CLAUDE.md`): 사내 파일 그림은 `.b64`로만 저장한다.
- 데모 단계다(제목의 "(데모)").

## Brand Commitments

- 이름: BEOL Slide RAG / BEOL 슬라이드 RAG (데모).
- 첫 화면 히어로는 고정한다. Casa Lunara 사진(비상업 데모 용도로 사용 허락 받음), 문구 "Back End of Line / Ask the Slides"와 그 서체를 그대로 두고, 나머지 화면은 히어로와 자연스럽게 어울려야 한다.
- 저장소 디자인 시스템 `design.md.md`(BEOL AX)는 이 페이지에 적용하지 않는다(사용자 결정, 2026-10-07).

## Evidence on Hand

- Supabase에 적재된 슬라이드 70장과 축별 라벨 건수(필터 화면에 나오는 실제 값).
- 시안의 예시 대화(질문 2개, 답, 근거 제목)는 설명용이며 실제 답이 아니다.
- 사용량, 만족도, 시간 절감 같은 수치는 없다. 지어내지 않는다.

## Product Principles

1. 근거가 먼저다. 출처 번호와 슬라이드 그림이 답을 증명하고, 판단은 엔지니어가 한다.
2. 범위를 좁히고 묻는다. 라벨 필터는 질문의 범위다.
3. 모르면 모른다고 한다. "자료에 없음"과 참고용 표시를 숨기지 않는다.
4. 화면 자원은 모두 저장소 안에 있다. 글꼴·그림·스크립트를 외부에서 받지 않고, 밖으로 나가는 것은 데이터와 답(Supabase·OpenAI API)뿐이다.

## Accessibility & Inclusion

- 글자 대비 WCAG AA(본문 4.5:1 이상).
- 키보드만으로 필터·전송·근거 팝업(이전/다음, Esc 닫기)을 쓸 수 있어야 한다.
- 동작 줄이기 설정을 따른다.
