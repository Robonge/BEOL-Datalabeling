# 검수봇 issue code 카탈로그

이 문서는 `engrbot/defaults/issue_codes.json`에서 `python -m engrbot codes`로 생성한다. 손으로 고치지 않는다.

- 카탈로그 버전: 2026-10-05.1
- 카탈로그 해시: a5d970620798
- severity의 판정 영향: critical → REJECT, major → REVIEW, fixable → AUTO_FIX, minor·info → PASS(기록)
- fail-safe 코드는 major 아래로 내릴 수 없다.

## L0

| code | severity | scope | 판정 영향 | 설명 |
|---|---|---|---|---|
| `L0_EMPTY_RATIO_HIGH` | major | file | REVIEW | 빈 슬라이드 비율이 높다 |
| `L0_EMPTY_UNIT` | major | record | REVIEW | 파서 본문은 비었는데 원본 추출 텍스트가 있다 |
| `L0_FORMAT_UNSUPPORTED` | info | file | 리포트에만 | 그 확장자의 독립 추출기가 등록되어 있지 않다 |
| `L0_GARBLED_TEXT` | major/minor | record | REVIEW / PASS | 깨진 문자 비율이 높다 |
| `L0_IMAGE_DROPPED` | minor | record | PASS | 원본에 이미지가 있는데 파서 이미지가 0개다 |
| `L0_IMAGE_LINK_MISMATCH` | major | record | REVIEW | unit 이미지가 그 슬라이드의 원본 미디어에 없다 |
| `L0_IMAGE_ONLY_UNIT` | info | record | 리포트에만 | 본문은 없고 이미지만 있다 |
| `L0_IMAGE_REF_BROKEN` | major | record | REVIEW | 이미지 저장 파일이 없거나 비었거나 해시가 다르다 |
| `L0_PAGE_COUNT_MISMATCH` | major | file | REVIEW | pptx의 독립 슬라이드 수와 unit 수가 다르다 |
| `L0_PARSER_WARNING` | minor/info | record | PASS / 리포트에만 | 파서 경고가 있다 |
| `L0_PARSE_FAILED` | critical | file | REJECT | 파일의 파싱 상태가 실패다 |
| `L0_SIGNATURE_MISMATCH` | critical | file | REJECT | 디코딩 직후 시그니처가 확장자와 다르다(ENCRYPTED, NOT_OOXML, OLE_LEGACY) |
| `L0_SOURCE_UNREADABLE` | critical | file | REJECT | .b64가 없거나 디코딩에 실패한다 |
| `L0_TABLE_CELLS_LOST` | minor | record | PASS | 비지 않은 셀 수 비율이 낮다 |
| `L0_TABLE_LOST` | major | record | REVIEW | 파서 표 수가 원본 표 수보다 적다 |
| `L0_TEXT_COVERAGE_LOW` | major/minor | record | REVIEW / PASS | 원본 대비 파서 텍스트 커버리지가 낮다 |

## L1

| code | severity | scope | 판정 영향 | 설명 |
|---|---|---|---|---|
| `L1_CONFIDENCE_RANGE` | major/minor | record | REVIEW / PASS | 확신도가 0~1 밖이거나 null이다 |
| `L1_DATE_FORMAT` | major | record | REVIEW | 추출 날짜의 연월일 순서를 확정할 수 없다 |
| `L1_DUPLICATE_FIELD` | major | record | REVIEW | 같은 필드의 라벨 행이 두 개 이상이다 |
| `L1_ENUM_INVALID` | critical | record | REJECT | 허용값 밖이다 |
| `L1_EVIDENCE_MISSING` | major | record | REVIEW | 근거가 필요한 필드에 근거가 없다 |
| `L1_FORMAT_NORMALIZED` | fixable | record | AUTO_FIX | 포맷 정규화를 적용했다 |
| `L1_LABELER_FAILED` | critical | record | REJECT | 라벨러 실패 목록에 있고 라벨 행이 없다 |
| `L1_LOT_ID_UNCOMMON` | info | record | 리포트에만 | lot ID의 R 다음 글자가 흔한 글자가 아니다 |
| `L1_PATTERN_MISMATCH` | major | record | REVIEW | 스키마 패턴에 맞지 않는다 |
| `L1_REQUIRED_MISSING` | critical | record | REJECT | 필수 필드가 없다 |
| `L1_TYPE_INVALID` | critical | record | REJECT | 필드 타입이 다르다 |
| `L1_UNKNOWN_FIELD` | minor | record | PASS | 스키마에 없는 필드나 질문 ID가 있다 |

## L2

| code | severity | scope | 판정 영향 | 설명 |
|---|---|---|---|---|
| `L2_ALL_NOT_APPLICABLE` | minor | record | PASS | 내용 chunk인데 모든 분류 축이 해당 없음이다 |
| `L2_AXIS_UNKNOWN` | critical | record | REJECT | 축 이름이 taxonomy의 활성 축에 없다 |
| `L2_HIERARCHY_INCONSISTENT` | major | record | REVIEW | 상위·하위 값 관계가 taxonomy 규칙과 맞지 않는다 |
| `L2_LABEL_NOT_IN_TAXONOMY` | critical | record | REJECT | 값이 그 축의 활성 값도 예약어도 아니다 |
| `L2_MUTEX_VIOLATION` | critical/major | record | REJECT / REVIEW | 함께 붙으면 안 되는 값이 함께 있다 |
| `L2_STATUS_MISMATCH` | major | record | REVIEW | 상태 필드와 값이 맞지 않는다 |
| `L2_TAXONOMY_STALE` | minor | record | PASS | 라벨의 taxonomy 시트 해시가 현재 버전과 다르다 |
| `L2_UNKNOWN_OVERUSE` | major | record | REVIEW | unknown 비율이 높다 |

## L3A

| code | severity | scope | 판정 영향 | 설명 |
|---|---|---|---|---|
| `L3_EXTRACT_NOT_IN_QUOTE` | major | record | REVIEW | 추출값이 인용 안에 없다 |
| `L3_SPAN_NOT_FOUND` | critical | record | REJECT | 근거 인용이 본문과 같은 파일 어디에도 없다 |
| `L3_SPAN_OFFSET_INVALID` | critical | record | REJECT | 근거 offset이 범위 밖이거나 인용과 다르다 |
| `L3_SPAN_TOO_LONG` | minor | record | PASS | 인용이 너무 길어 근거가 특정되지 않는다 |
| `L3_SPAN_TOO_SHORT` | minor | record | PASS | 인용이 너무 짧아 일치 여부를 믿을 수 없다 |
| `L3_SPAN_WRONG_UNIT` | critical | record | REJECT | 근거 인용이 같은 파일의 다른 chunk에 있다 |

## L3B

| code | severity | scope | 판정 영향 | 설명 |
|---|---|---|---|---|
| `L3_JUDGE_FAILED` | major | record | REVIEW | judge 호출 또는 응답 검증이 재시도 뒤에도 실패했다 (fail-safe) |
| `L3_JUDGE_SKIPPED` | major | record | REVIEW | judge를 돌리지 않았다(--no-judge 또는 LLM 설정 없음) (fail-safe) |
| `L3_NOT_SUPPORTED` | major | record | REVIEW | judge가 인용이 라벨을 지지하지 않는다고 판정했다 |
| `L3_PARTIALLY_SUPPORTED` | minor | record | PASS | judge가 부분 지지로 판정했다 |

## L4

| code | severity | scope | 판정 영향 | 설명 |
|---|---|---|---|---|
| `L4_AXIS_COMBO_VIOLATION` | major/minor | record | REVIEW / PASS | 승인된 도메인 규칙의 축 조합(expect·forbid)과 맞지 않는다 |
| `L4_RULE_DRAFT_HIT` | info | record | 리포트에만 | draft 도메인 규칙에 걸렸다(판정에 반영하지 않는다) |
| `L4_SYNONYM_SUGGEST` | info | record | 리포트에만 | taxonomy 밖 값이 동의어와 같아 표준값을 제안한다(자동 교정하지 않는다) |
| `L4_TITLE_LABEL_MISMATCH` | major/minor | record | REVIEW / PASS | chunk 제목에서 뽑은 축 값이 라벨에 없다 |

## L5

| code | severity | scope | 판정 영향 | 설명 |
|---|---|---|---|---|
| `L5_DUP_GROUP_DISAGREE` | major | record | REVIEW | 같은 중복 묶음 레코드끼리 분류 축 값이 다르다 |

## L6

| code | severity | scope | 판정 영향 | 설명 |
|---|---|---|---|---|
| `L6_DRIFT_HIGH` | info | batch | 리포트에만 | 축 분포의 JSD가 경보 기준 이상이다 |
| `L6_PASS_RATE_DROP` | info | batch | 리포트에만 | 통과율이 기준선보다 크게 낮다 |
| `L6_SAMPLE_TOO_SMALL` | info | batch | 리포트에만 | 라벨 수가 적어 드리프트를 계산하지 않았다 |
| `L6_UNKNOWN_RATE_HIGH` | info | batch | 리포트에만 | 축의 unknown 비율이 경보 기준 이상이다 |
| `L6_UNMAPPED_TERMS` | info | batch | 리포트에만 | 매핑되지 않는 빈출 용어 후보가 있다 |
| `L6_UNUSED_LABELS` | info | batch | 리포트에만 | 연속 미사용 값이 있다 |

