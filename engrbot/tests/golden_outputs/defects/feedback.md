# 검수봇 피드백 묶음

- 검수 실행 ID: <QA_RUN_ID>
- 라벨러 실행 ID: 20261004T000000-fx01
- 결정 지문: <DECISIONS_SHA256>
- 검수봇은 taxonomy 시트, labelbot 프롬프트, 작업 DB를 고치지 않는다. 아래 순서대로 사람이 반영한다.

## 1. 시트별 붙여넣기 행

- 없음

## 2. 점검할 축·질문·프롬프트 규칙

- 없음

## 3. 레코드 교정과 재작업

- 레코드 교정: 3건 (REVIEW 1, REJECT 0, AUTO_FIX 2)
- 재작업: 1건
- labelbot의 apply는 4차 불량 목록에 있는 chunk의 교정만 받는다. 그 밖의 교정은 이 묶음과 골든셋에 남는다.

| 레코드 ID | 필드 | 코드 |
|---|---|---|
| 100a80ecffe22ca1:ppt/slides/slide6.xml | axis:Material | L3_SPAN_NOT_FOUND |

## 4. 검수 정책 조정 제안

| 코드 | 검수 오탐 표시 레코드 수 | 고칠 곳 |
|---|---|---|
| L3_SPAN_NOT_FOUND | 1 | 검수 정책(policy)의 임계값이나 severity |
