# labeling.sqlite 스키마

BEOL 비정형 자료 라벨링 결과다. 읽기 전용 SELECT로 조회한다. 라벨은 chunk와 축 값의 관계(facet_labels)로 저장된다.

## files

파일 단위 정보. 파일 1개 = 행 1개

| 열 | 형식 | 설명 |
|---|---|---|
| file_id | TEXT PRIMARY KEY | 원본 bytes의 sha256 |
| file_name | TEXT NOT NULL | 파일명(처음 본 위치 기준) |
| rel_path | TEXT NOT NULL | 대표 상대 경로(입력 루트 기준, 구분자 /) |
| title | TEXT | 문서 속성의 제목 |
| authored_at | TEXT | 작성일(YYYY-MM-DD) |
| author | TEXT | 작성자 |
| memo | TEXT | taxonomy.xlsx files 시트의 맥락 메모 |
| chunk_count | INTEGER | chunk 수 |

## file_locations

같은 파일(해시)이 놓인 모든 위치. files와 1:N

| 열 | 형식 | 설명 |
|---|---|---|
| file_id | TEXT NOT NULL | files.file_id |
| rel_path | TEXT NOT NULL | 상대 경로 |
| file_name | TEXT NOT NULL | 그 위치의 파일명 |
| first_seen_run | TEXT | 처음 본 실행 ID |
| last_seen_run | TEXT | 마지막으로 본 실행 ID |

## chunks

검색 단위. pptx는 슬라이드 1장 = chunk 1개

| 열 | 형식 | 설명 |
|---|---|---|
| chunk_id | TEXT PRIMARY KEY | <파일 ID 앞 16자>:<part 이름> |
| file_id | TEXT NOT NULL | files.file_id |
| seq | INTEGER | 파일 안 순서(슬라이드 번호) |
| chunk_type | TEXT | 내용/표지/목차/참고문헌 |
| title | TEXT | 슬라이드 제목 |
| text | TEXT | chunk 본문([표], [노트], [차트] 구간 포함) |
| text_hash | TEXT | 본문 해시 |
| dup_group | TEXT | 같은 본문 chunk 묶음 ID(없으면 NULL) |
| image_paths | TEXT | 이미지 파일 경로 JSON 목록(images/<id>.b64) |
| parse_warnings | TEXT | 파싱 경고 코드 JSON 목록 |
| slide_image | TEXT | 슬라이드 근사 미리보기 JPG JSON(rel_file=slide_images/<sha256>.b64, sha256, width, height, bucket, object_path). 없으면 NULL |

## facet_values

분류 체계(축과 표준 값)

| 열 | 형식 | 설명 |
|---|---|---|
| axis | TEXT | 축 이름 |
| value | TEXT | 표준 값 |
| parent | TEXT | 상위값(계층 축) |
| kind | TEXT | 분류/상태 |
| definition | TEXT | 정의·판정 규칙 |

## aliases

동의어 → 표준어

| 열 | 형식 | 설명 |
|---|---|---|
| alias | TEXT | 본문 표현 |
| canonical | TEXT | 표준어 |

## questions

O/X 질문

| 열 | 형식 | 설명 |
|---|---|---|
| question_id | TEXT PRIMARY KEY | 질문 ID |
| text | TEXT | 질문 문장 |
| target | TEXT | 적용 대상(공통 또는 축=값) |

## facet_labels

chunk와 축 값의 관계. 값마다 1행

| 열 | 형식 | 설명 |
|---|---|---|
| chunk_id | TEXT | chunks.chunk_id |
| axis | TEXT | 축 이름 |
| value | TEXT | 표준 값. state가 value가 아니면 '해당 없음' 또는 'unknown' |
| state | TEXT | value / 해당 없음 / unknown |
| evidence | TEXT | 근거 인용 |
| confidence | REAL | 확신도 0~1 |
| review_status | TEXT | 검수하지 않음 / 사람이 확인 / 사람이 교정 |

## answers

chunk별 질문 답

| 열 | 형식 | 설명 |
|---|---|---|
| chunk_id | TEXT | chunks.chunk_id |
| question_id | TEXT | questions.question_id |
| answer | TEXT | O / X / N/A |
| quote | TEXT | 근거 인용 |
| confidence | REAL | 확신도 0~1 |
| review_status | TEXT | 검수하지 않음 / 사람이 확인 / 사람이 교정 |

## extracted_values

날짜·담당자 값

| 열 | 형식 | 설명 |
|---|---|---|
| target_type | TEXT | file 또는 chunk |
| target_id | TEXT | file_id 또는 chunk_id |
| item | TEXT | date 또는 person |
| value | TEXT | 값(날짜는 YYYY-MM-DD) |
| evidence | TEXT | 근거 인용 |
| source | TEXT | docprops / filename / body |

## meta

산출 정보

| 열 | 형식 | 설명 |
|---|---|---|
| key | TEXT PRIMARY KEY | 키 |
| value | TEXT | 값 |

## 관계

- files 1 : N file_locations (file_id). 같은 파일이 여러 폴더에 있으면 file_locations에 모두 있다.
- files 1 : N chunks (file_id)
- chunks 1 : N facet_labels, answers (chunk_id)
- facet_labels.(axis, value) → facet_values.(axis, value) (state='value'일 때)
- answers.question_id → questions.question_id

## 분류 체계

- **구조/레이어** (분류, 다중값 Y): M0, M1, M2, M3, Mx, V0, V1, V2, V3, Vx, JHV
- **공정 모듈** (분류, 다중값 Y): Litho, Etch, Metal, CMP, Clean, CVD
- **제품·세대** (분류, 다중값 Y): SF1.4, SF1.0, SF0.7, SF2, SF2X
- **REMSPC** (분류, 다중값 Y): Reticle, Equipment, Materials, Scheme, Process, Controllability
- **Patterning** (분류, 다중값 Y): EUV-SAUP, EUV-SET, ArF-SET, ArF-LELE
- **Material** (분류, 다중값 Y): IMD, BM/Liner, Metallization
- **불량 모드** (분류, 다중값 Y): Open, Short, Reliability, EM(<Reliability), TDDB(<Reliability), Parametric, Rs 산포(<Parametric), MHC, Via Rc high(<MHC), Line R high(<MHC)
- **물리 현상** (분류, 다중값 Y): Void, metal bridge, not open, unCMP, hardmask loss, dishing, CD imbalance, CD small, CD 산포불량
- **결과** (상태, 다중값 Y): improved, degraded, neutral, inconclusive
- **의사결정 상태** (상태, 다중값 N): adopted, rejected, pending

## 질문

- Q-COM-001: 이 chunk가 BEOL interconnect 공정에 관련한 내용이 맞는가?

## 예시 SQL

경로로 파일과 chunk 찾기:

```sql
SELECT f.file_id, l.rel_path, c.chunk_id, c.title
FROM file_locations l JOIN files f ON f.file_id = l.file_id JOIN chunks c ON c.file_id = f.file_id
WHERE l.rel_path LIKE '%M2%' ORDER BY l.rel_path, c.seq;
```

특정 축 값이 붙은 chunk:

```sql
SELECT c.chunk_id, c.title FROM facet_labels fl JOIN chunks c ON c.chunk_id = fl.chunk_id
WHERE fl.axis = '불량 모드' AND fl.value = 'Short';
```

미해결 위험이 있다고 답한 chunk:

```sql
SELECT a.chunk_id, a.quote FROM answers a WHERE a.question_id = 'Q-COM-001' AND a.answer = 'O';
```
