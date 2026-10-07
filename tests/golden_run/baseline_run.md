# 기준선 리포트

- 실행 ID: <RUN>
- 생성: <TS>

## 요약

- 대상 chunk 28개, 내용 chunk 25개, 불량 chunk 19개(67.9%)
- 사유 코드별 불량: UNKNOWN_HIGH 6(21.4%), LOW_CONFIDENCE 3(10.7%), QUOTE_NOT_FOUND 3(10.7%), PARSE_WARNING 0(0.0%), CLASSIFY_FAILED 3(10.7%), LABEL_FAILED 5(17.9%), CONTROL_O 0(0.0%), UNKNOWN_O 0(0.0%)
- 실패 chunk: 분류 3, 라벨 5 / 실패 파일 0
- dup_group 중복 비율: 0.0%
- 교정 건수: 검수 없음
- N/A 비율: 100.0% (답 45개), 중복 라벨링 비율: 42.4% (라벨 59개)
- H5 알림: DUP_LABEL_HIGH=0.4237(기준 0.4)

## 축별 unknown 비율 (unknown / (전체 − 해당 없음))

| 축 | 종류 | unknown | 분모 | 비율 |
|---|---|---|---|---|
| 구조/레이어 | 분류 | 6 | 18 | 33.3% |
| Main step | 분류 | 6 | 20 | 30.0% |
| 공정 모듈 | 분류 | 6 | 15 | 40.0% |
| 제품·세대 | 분류 | 6 | 6 | 100.0% |
| REMSPC | 분류 | 6 | 7 | 85.7% |
| Patterning/scheme | 분류 | 6 | 9 | 66.7% |
| Material | 분류 | 6 | 10 | 60.0% |
| 불량 모드 | 분류 | 6 | 18 | 33.3% |
| 물리 현상 | 분류 | 6 | 10 | 60.0% |
| 결과 | 상태 | 6 | 6 | 100.0% |
| 의사결정 상태 | 상태 | 6 | 6 | 100.0% |

## 값별 사용 빈도 (1% 미만: 합칠 후보, 50% 초과: 쪼갤 후보)

| 축 | 값 | 건수 | 비율 | 표시 |
|---|---|---|---|---|
| 구조/레이어 | M0 | 0 | 0.0% | 합칠 후보 |
| 구조/레이어 | M1 | 0 | 0.0% | 합칠 후보 |
| 구조/레이어 | I1 | 0 | 0.0% | 합칠 후보 |
| 구조/레이어 | X1 | 0 | 0.0% | 합칠 후보 |
| 구조/레이어 | L1 | 0 | 0.0% | 합칠 후보 |
| 구조/레이어 | M2 | 5 | 20.0% |  |
| 구조/레이어 | M3 | 1 | 4.0% |  |
| 구조/레이어 | X3 | 0 | 0.0% | 합칠 후보 |
| 구조/레이어 | M4 | 4 | 16.0% |  |
| 구조/레이어 | Fx | 0 | 0.0% | 합칠 후보 |
| 구조/레이어 | Dx | 1 | 4.0% |  |
| 구조/레이어 | VA | 8 | 32.0% |  |
| 구조/레이어 | V1 | 4 | 16.0% |  |
| 구조/레이어 | V2 | 0 | 0.0% | 합칠 후보 |
| 구조/레이어 | V3 | 1 | 4.0% |  |
| 구조/레이어 | Sx | 0 | 0.0% | 합칠 후보 |
| 구조/레이어 | JHV | 0 | 0.0% | 합칠 후보 |
| 구조/레이어 | I2 | 0 | 0.0% | 합칠 후보 |
| Main step | AASI | 11 | 44.0% |  |
| Main step | ASEI | 7 | 28.0% |  |
| Main step | AMI | 10 | 40.0% |  |
| Main step | ACI | 8 | 32.0% |  |
| Main step | API | 0 | 0.0% | 합칠 후보 |
| Main step | AHI | 0 | 0.0% | 합칠 후보 |
| Main step | AEI | 0 | 0.0% | 합칠 후보 |
| Main step | ASI | 11 | 44.0% |  |
| 공정 모듈 | Litho | 0 | 0.0% | 합칠 후보 |
| 공정 모듈 | Etch | 4 | 16.0% |  |
| 공정 모듈 | Metal | 3 | 12.0% |  |
| 공정 모듈 | CMP | 4 | 16.0% |  |
| 공정 모듈 | Clean | 0 | 0.0% | 합칠 후보 |
| 공정 모듈 | CVD | 0 | 0.0% | 합칠 후보 |
| 제품·세대 | SF1.4 | 0 | 0.0% | 합칠 후보 |
| 제품·세대 | SF1.0 | 0 | 0.0% | 합칠 후보 |
| 제품·세대 | SF0.7 | 0 | 0.0% | 합칠 후보 |
| 제품·세대 | SF2 | 0 | 0.0% | 합칠 후보 |
| 제품·세대 | SF2X | 0 | 0.0% | 합칠 후보 |
| REMSPC | Reticle | 0 | 0.0% | 합칠 후보 |
| REMSPC | Equipment | 0 | 0.0% | 합칠 후보 |
| REMSPC | Materials | 0 | 0.0% | 합칠 후보 |
| REMSPC | Scheme | 0 | 0.0% | 합칠 후보 |
| REMSPC | Process | 1 | 4.0% |  |
| REMSPC | Controllability | 0 | 0.0% | 합칠 후보 |
| Patterning/scheme | EUV-SAUP | 0 | 0.0% | 합칠 후보 |
| Patterning/scheme | EUV-SET | 0 | 0.0% | 합칠 후보 |
| Patterning/scheme | ArF-SET | 0 | 0.0% | 합칠 후보 |
| Patterning/scheme | ArF-LELE | 0 | 0.0% | 합칠 후보 |
| Patterning/scheme | Cu dual damascene | 0 | 0.0% | 합칠 후보 |
| Patterning/scheme | Cu single damascene | 0 | 0.0% | 합칠 후보 |
| Patterning/scheme | Ru subtractive | 3 | 12.0% |  |
| Patterning/scheme | Ru semi-damascene | 0 | 0.0% | 합칠 후보 |
| Patterning/scheme | SAV | 0 | 0.0% | 합칠 후보 |
| Patterning/scheme | Trench-first | 0 | 0.0% | 합칠 후보 |
| Material | CMP slurry | 0 | 0.0% | 합칠 후보 |
| Material | Clean chemical | 0 | 0.0% | 합칠 후보 |
| Material | IMD | 4 | 16.0% |  |
| Material | BM/Liner | 0 | 0.0% | 합칠 후보 |
| Material | Metallization | 0 | 0.0% | 합칠 후보 |
| 불량 모드 | Open | 1 | 4.0% |  |
| 불량 모드 | Short | 0 | 0.0% | 합칠 후보 |
| 불량 모드 | Reliability | 0 | 0.0% | 합칠 후보 |
| 불량 모드 | EM | 11 | 44.0% |  |
| 불량 모드 | TDDB | 1 | 4.0% |  |
| 불량 모드 | Parametric | 0 | 0.0% | 합칠 후보 |
| 불량 모드 | Rs 산포 | 0 | 0.0% | 합칠 후보 |
| 불량 모드 | MHC | 0 | 0.0% | 합칠 후보 |
| 불량 모드 | Via Rc high | 0 | 0.0% | 합칠 후보 |
| 불량 모드 | Line R high | 0 | 0.0% | 합칠 후보 |
| 불량 모드 | MinA void | 0 | 0.0% | 합칠 후보 |
| 물리 현상 | Void | 2 | 8.0% |  |
| 물리 현상 | metal bridge | 0 | 0.0% | 합칠 후보 |
| 물리 현상 | not open | 0 | 0.0% | 합칠 후보 |
| 물리 현상 | unCMP | 0 | 0.0% | 합칠 후보 |
| 물리 현상 | overCMP | 0 | 0.0% | 합칠 후보 |
| 물리 현상 | hardmask loss | 0 | 0.0% | 합칠 후보 |
| 물리 현상 | dishing | 3 | 12.0% |  |
| 물리 현상 | Particle | 0 | 0.0% | 합칠 후보 |
| 물리 현상 | CD imbalance | 0 | 0.0% | 합칠 후보 |
| 물리 현상 | CD small | 0 | 0.0% | 합칠 후보 |
| 물리 현상 | CD 산포불량 | 0 | 0.0% | 합칠 후보 |
| 물리 현상 | low-k plasma damage | 0 | 0.0% | 합칠 후보 |
| 물리 현상 | 계면 산화 | 0 | 0.0% | 합칠 후보 |
| 결과 | improved | 0 | 0.0% | 합칠 후보 |
| 결과 | degraded | 0 | 0.0% | 합칠 후보 |
| 결과 | neutral | 0 | 0.0% | 합칠 후보 |
| 결과 | inconclusive | 0 | 0.0% | 합칠 후보 |
| 의사결정 상태 | adopted | 0 | 0.0% | 합칠 후보 |
| 의사결정 상태 | rejected | 0 | 0.0% | 합칠 후보 |
| 의사결정 상태 | pending | 0 | 0.0% | 합칠 후보 |

## 질문별 O/X/N/A 분포

| 질문 | O | X | N/A | n | 표시 |
|---|---|---|---|---|---|
| Q-COM-001 | 0 | 0 | 20 | 20 | N/A 편중 |

## 후보와 동의어 시트

- synonyms 시트 항목 수: 4, 항목이 일치한 chunk 비율: 25.0%
- 후보 수: 0

## 파싱 대조

- 대조 기록: 없음

## 실패 목록 (단계, 사유 코드, 건수)

- classify AXIS_MISSING 3
- label QUESTION_MISSING 5

실패 파일: 없음

## 조회 검증

- PoC 단계에서는 실행하지 않았다(querycheck 미구현).
