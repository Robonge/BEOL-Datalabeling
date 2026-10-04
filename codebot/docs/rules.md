# codebot 규칙 카탈로그

`python -m codebot rules`로 만든다. 직접 고치지 않는다.

| 규칙 | 층 | severity | 설명 |
|---|---|---|---|
| `C1_NONSTDLIB_IMPORT` | C1 | critical | 표준 라이브러리도 로컬 패키지도 아닌 모듈을 import한다. |
| `C1_OPEN_OUTSIDE_INGEST` | C1 | major | ingest 모듈 밖에서 open(..., 'rb')로 원본을 연다(휴리스틱). |
| `C1_PATH_PARSER` | C1 | critical | 경로를 받는 파서(Presentation, load_workbook, pd.read_*, csv.reader(open), ZipFile)를 쓴다. |
| `C1_WRITE_EXT_FORBIDDEN` | C1 | critical | office·텍스트 확장자 경로로 쓰기 모드 open을 한다. |
| `C2_PY314_SYNTAX` | C2 | critical | Python 3.14 구문으로 파싱되지 않는다. |
| `C2_REQUIREMENTS_NOT_EMPTY` | C2 | major | requirements.txt에 패키지 줄이 있다. |
| `C2_SECRET_LITERAL` | C2 | critical | 키·토큰 꼴 문자열 리터럴이 있다. |
| `C2_TRANSPORT_BYPASS` | C2 | major | 전송 공용 모듈 밖에서 네트워크 호출을 직접 쓴다. |
| `C3_CLI_REF_MISSING` | C3 | major | 문서의 `python -m <패키지> <명령>`이 그 패키지 cli에 선언돼 있지 않다 |
| `C3_IMPORT_BOUNDARY` | C3 | major | engrbot이 허용 모듈 밖에서 labelbot을 import한다 |
| `C3_TABLE_CONTRACT_DRIFT` | C3 | critical | REQUIRED의 표·열이 store.TABLES에 없다 |
| `C4_PLACEHOLDER` | C4 | minor | 미완 표식 주석이나 빈 구현이 있다. |
| `C4_TEST_SKIP` | C4 | major | 테스트를 건너뛰거나 실패를 기대 처리한다. |
