# 검수봇 mutation 하네스 결과

- 레코드 수: 107
- judge: mock
- reviewer 버전: 0.1.0+a5d97062+9af26808+mock
- 오탐률(정답 레코드 중 PASS가 아닌 비율): 0.0000
- AUTO_FIX 정확도: 1.0000
- judge 호출 수(정답 번들): 97

## 층별 탐지율

| 층 | 주입 | 탐지 | 탐지율 | 층별 오탐률 |
|---|---|---|---|---|
| L0 | 10 | 10 | 1.0 | 0.0 |
| L1 | 10 | 10 | 1.0 | 0.0 |
| L1_AUTOFIX | 6 | 6 | 1.0 | 0.0 |
| L2 | 10 | 10 | 1.0 | 0.0 |
| L3A | 6 | 6 | 1.0 | 0.0 |
| L3B | 4 | 4 | 1.0 | 0.0 |
| L3B_FAILSAFE | 6 | 0 | 0.0 | 0.0 |

## 뮤테이터별

| 뮤테이터 | 층 | 기대 코드 | 주입 | 탐지 | 탐지율 | 비고 |
|---|---|---|---|---|---|---|
| drop_slide | L0 | L0_PAGE_COUNT_MISMATCH | 2 | 2 | 1.0 |  |
| empty_text | L0 | L0_EMPTY_UNIT | 2 | 2 | 1.0 |  |
| drop_table | L0 | L0_TABLE_LOST | 2 | 2 | 1.0 |  |
| garble | L0 | L0_GARBLED_TEXT | 2 | 2 | 1.0 |  |
| break_image_ref | L0 | L0_IMAGE_REF_BROKEN | 2 | 2 | 1.0 |  |
| drop_field | L1 | L1_REQUIRED_MISSING | 2 | 2 | 1.0 |  |
| bad_type | L1 | L1_TYPE_INVALID | 2 | 2 | 1.0 |  |
| bad_enum | L1 | L1_ENUM_INVALID | 2 | 2 | 1.0 |  |
| bad_confidence | L1 | L1_CONFIDENCE_RANGE | 2 | 2 | 1.0 |  |
| ambiguous_date | L1 | L1_DATE_FORMAT | 2 | 2 | 1.0 |  |
| case_ws_noise | L1_AUTOFIX | L1_FORMAT_NORMALIZED | 2 | 2 | 1.0 |  |
| fullwidth | L1_AUTOFIX | L1_FORMAT_NORMALIZED | 2 | 2 | 1.0 |  |
| date_dots | L1_AUTOFIX | L1_FORMAT_NORMALIZED | 2 | 2 | 1.0 |  |
| out_of_taxonomy | L2 | L2_LABEL_NOT_IN_TAXONOMY | 2 | 2 | 1.0 |  |
| parent_and_child | L2 | L2_HIERARCHY_INCONSISTENT | 2 | 2 | 1.0 |  |
| reserved_plus_value | L2 | L2_MUTEX_VIOLATION | 2 | 2 | 1.0 |  |
| single_axis_multi | L2 | L2_MUTEX_VIOLATION | 2 | 2 | 1.0 |  |
| unknown_flood | L2 | L2_UNKNOWN_OVERUSE | 2 | 2 | 1.0 |  |
| span_other_slide | L3A | L3_SPAN_WRONG_UNIT | 2 | 2 | 1.0 |  |
| span_fabricated | L3A | L3_SPAN_NOT_FOUND | 2 | 2 | 1.0 |  |
| offset_shift | L3A | L3_SPAN_OFFSET_INVALID | 2 | 2 | 1.0 |  |
| label_swap | L3B | L3_NOT_SUPPORTED | 2 | 2 | 1.0 |  |
| answer_flip | L3B | L3_NOT_SUPPORTED | 2 | 2 | 1.0 |  |
| judge_timeout | L3B_FAILSAFE | L3_JUDGE_FAILED | 2 | 0 | 0.0 | PASS로 남은 fail-safe 2건 |
| judge_bad_json | L3B_FAILSAFE | L3_JUDGE_FAILED | 2 | 0 | 0.0 | PASS로 남은 fail-safe 2건 |
| judge_missing_item | L3B_FAILSAFE | L3_JUDGE_FAILED | 2 | 0 | 0.0 | PASS로 남은 fail-safe 2건 |

## 혼동표(주입 종류 × 새로 붙은 코드)

- drop_slide: L0_PAGE_COUNT_MISMATCH 2
- empty_text: L0_EMPTY_UNIT 2, L3_SPAN_NOT_FOUND 2, L3_SPAN_WRONG_UNIT 2
- drop_table: L0_TABLE_CELLS_LOST 2, L0_TABLE_LOST 2
- garble: L0_GARBLED_TEXT 2, L3_SPAN_NOT_FOUND 2, L3_SPAN_WRONG_UNIT 1
- break_image_ref: L0_IMAGE_REF_BROKEN 2
- drop_field: L1_REQUIRED_MISSING 2
- bad_type: L1_TYPE_INVALID 2
- bad_enum: L1_ENUM_INVALID 2
- bad_confidence: L1_CONFIDENCE_RANGE 2
- ambiguous_date: L1_DATE_FORMAT 2
- case_ws_noise: L1_FORMAT_NORMALIZED 2
- fullwidth: L1_FORMAT_NORMALIZED 2
- date_dots: L1_FORMAT_NORMALIZED 2
- out_of_taxonomy: L2_LABEL_NOT_IN_TAXONOMY 2, L2_STATUS_MISMATCH 2
- parent_and_child: L2_HIERARCHY_INCONSISTENT 2, L3_NOT_SUPPORTED 2
- reserved_plus_value: L2_MUTEX_VIOLATION 2, L2_STATUS_MISMATCH 2
- single_axis_multi: L1_EVIDENCE_MISSING 2, L2_MUTEX_VIOLATION 2
- unknown_flood: L2_UNKNOWN_OVERUSE 2
- span_other_slide: L3_SPAN_WRONG_UNIT 2
- span_fabricated: L3_SPAN_NOT_FOUND 2
- offset_shift: L3_SPAN_OFFSET_INVALID 2
- label_swap: L3_NOT_SUPPORTED 2
- answer_flip: L3_NOT_SUPPORTED 2
- judge_timeout: L3_JUDGE_FAILED 2
- judge_bad_json: L3_JUDGE_FAILED 2
- judge_missing_item: L3_JUDGE_FAILED 2
