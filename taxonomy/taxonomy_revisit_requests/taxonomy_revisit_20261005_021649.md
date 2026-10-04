# taxonomy 재검토 요청: 검수 실행 20261004T170250-a1e5

- 생성: 2026-10-04T17:16:49Z
- 요청: 2건 (바로 붙여넣기 행 2, 확인 필요 행 0, 목록만 0건)
- 사유별: NO_FIT_VALUE 2
- 붙이는 법: 코드 블록의 행(머리글 없음, A열부터 탭 구분 11칸)을 복사해 taxonomy 시트 A열의 빈 행에 붙인다. 같은 이름의 .html에서 표를 드래그 복사해도 된다. 사용 여부(K)는 빈칸(바로 켜짐)이다.
- 붙인 뒤에 다음 apply를 한다. 붙이기 전에 다음 apply를 하면 같은 값이 다음 파일에도 나와, 두 번 붙이면 값 중복 오류로 시트 전체를 읽지 못한다.
- 이 파일은 사람이 적은 메모를 담는다.

## 바로 붙여넣기 (taxonomy 시트 A~K)

```
Material	CMP slurry									
불량 모드	MinA void	Open								
```

| 행 | 축 | 값 | 상위값 | 요청 # |
|---|---|---|---|---|
| 1 | Material | CMP slurry | - | #1 |
| 2 | 불량 모드 | MinA void | Open | #2 |

## 확인 필요 (고친 뒤 붙여넣기)

확인할 행이 없다.

## 요청 목록

- 시트 배치: #1 바로 붙여넣기, #2 바로 붙여넣기
- AMBIGUOUS_DEF·VALUE_OVERLAP·OTHER·NEED_QUESTION은 엑셀 행을 내지 않는다(질문은 questions 시트에 직접 쓴다).

| # | chunk ID | 파일 ID | 대상 | 키 | 사유 | 봇 값 | 사람 교정 | 제안·관련 값 |
|---|---|---|---|---|---|---|---|---|
| 1 | 1d310b28feb5d277:ppt/slides/slide4.xml | 1d310b28feb5d277 | 축 | Material | NO_FIT_VALUE 맞는 값이 없음 | 해당 없음 | - | CMP slurry |
| 2 | 1d310b28feb5d277:ppt/slides/slide4.xml | 1d310b28feb5d277 | 축 | 불량 모드 | NO_FIT_VALUE 맞는 값이 없음 | 해당 없음 | - | MinA void (상위 Open) |

메모
- #1
  > 누락된 것 같아
- #2
  > Open을 상위단계로 올리기
