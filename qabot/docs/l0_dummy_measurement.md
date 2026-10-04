# L0 더미 pptx 실측(QM3)

- 측정일: 2026-10-04
- 대상: 저장소 `dummy pptx files/` 전체. 파일 147개(pptx 146, csv 1), pptx 슬라이드(unit) 730장
- 방법: 코드 폴더 밖 임시 작업 폴더에 labelbot 수집·파싱(`pipeline.run_ingest`, LLM 없음)을 돌리고, `labelbot_ws.load_units_only`로 번들을 만들어 `checks/l0_parse.py`를 파일마다 돌렸다. 정책은 `qabot/defaults/policy.json`의 `l0` 기본값 그대로다.
- 원본은 labelbot `ingest.read_input`으로만 읽혔다. 추출 텍스트는 디스크에 쓰지 않았다. 이 문서에는 파일 ID 앞 12자, 슬라이드 파트, 코드, 숫자만 적는다.

## 코드별 건수

| code | severity | 건수 |
|---|---|---|
| `L0_FORMAT_UNSUPPORTED` | info | 1 (csv 1개, labelbot 수집 상태 `failed`/`UNSUPPORTED_FORMAT`) |
| 그 밖의 L0 코드 | 전부 | 0 |

major 이상: 0건. minor: 0건.

## major 이상 전수 분류

| 파일 ID(12자) | 슬라이드 파트 | code | 분류 | 사유 |
|---|---|---|---|---|
| (없음) | | | | |

검수 오탐 0건이다. 임계값을 바꿀 근거가 없으므로 `l0` 기본값을 그대로 둔다(정책 변경 제안 없음).

## 여유(margin) 측정

| 항목 | 값 | 기준 |
|---|---|---|
| 슬라이드 수 비교 | 146개 파일 모두 원본 슬라이드 수 = unit 수 | `L0_PAGE_COUNT_MISMATCH` |
| 텍스트 커버리지 최솟값 | 0.9907 (5% 분위수 1.0, 730장 모두 계산, 원본 20자 미만으로 건너뛴 슬라이드 0) | minor 0.85, major 0.6 |
| 반복 줄 제외를 끈 경우 | 커버리지 0.85 미만 8장, 0.6 미만 2장 | 반복 바닥글 제외가 오탐을 막는다(13.1절 R5) |
| 깨진 문자 비율 최댓값 | 0.0 | minor 0.005 |
| 빈 unit(본문 10자 미만) | 0장 | `L0_EMPTY_UNIT`, `L0_EMPTY_RATIO_HIGH` |
| 표 셀 비율(파서/원본) 최솟값 | 1.0 (원본 `a:tbl`이 있는 슬라이드 317장) | minor 0.8 |
| 원본 표(`a:tbl`) 444개 / 파서 표 942개 | 파서 쪽이 많다(좌표 표 복원). 많은 쪽은 이슈가 아니다 | `L0_TABLE_LOST` |
| 원본 그림 2,055개 | 2,048 bytes 미만 1,500개, 여러 슬라이드에 반복 98개, 그 밖 457개 | 457개가 있는 슬라이드는 모두 파서 이미지가 1개 이상이다 |
| 파서 경고 | 0건 | `L0_PARSER_WARNING` |
| 숨김 슬라이드 | 0장 | |
| 슬라이드 번호·날짜 placeholder 글자가 있는 슬라이드 | 306장(분모에서 뺐다) | |

## 더미 데이터 주입 탐지(참고)

더미 번들의 파일마다 대상 unit 하나에 L0 뮤테이터 5종을 하나씩 주입해 기대 코드가 붙는지 봤다.

| 뮤테이터 | 탐지 / 주입 | 비고 |
|---|---|---|
| `drop_slide` | 146 / 146 | |
| `empty_text` | 146 / 146 | |
| `garble` | 146 / 146 | |
| `break_image_ref` | 101 / 101 | |
| `drop_table` | 원본 `a:tbl`이 있는 unit 317 / 317 | 파서가 좌표로 복원한 표만 있는 unit 284개는 원본에 `a:tbl`이 없어 탐지 대상이 아니다(설계대로, 5.1절 엣지 케이스) |

합성 fixture에서는 L0 뮤테이터 5종의 탐지율 1.00, 오탐률 0.00을 `qabot/tests/test_l0.py`가 확인한다.

## 재현

1. 코드 폴더 밖 임시 폴더에 `labelbot.workspace.Workspace(<임시 폴더>)`를 만들고 `labelbot.pipeline.run_ingest(ws, "<저장소>/dummy pptx files")`를 돌린다.
2. `qabot.adapters.labelbot_ws.load_units_only(<임시 폴더>)`로 번들을 만든다.
3. `qabot.checks.l0_parse.ParseFidelityCheck().run(engine.FileTarget(bundle, file_id), engine.Ctx(bundle, policy, schema))`를 파일마다 돌려 코드별로 센다.
