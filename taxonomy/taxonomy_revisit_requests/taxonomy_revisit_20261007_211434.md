# taxonomy 재검토 요청: 검수 실행 20261007T105157-2b26

- 생성: 2026-10-07T12:14:34Z
- 요청: 2건 (바로 반영 가능 행 2, 확인 필요 행 0, 목록만 0건)
- 사유별: NO_FIT_VALUE 2
- 반영하는 법: 이 요청은 taxonomy 보드(python -m domain_engrbot taxonomy-board --serve)에 카드로 올라온다. 카드에서 고치고 반영함 → 최종 완료를 누르면 봇이 taxonomy.json에 쓴다. 아래 행(A~K 탭 구분 11칸)은 참고용 초안이다.
- 이 파일은 사람이 적은 메모를 담는다.

## 바로 반영 가능 (taxonomy 행 A~K)

```
Material	ASD									
물리 현상	Depo selectivity loss									
```

| 행 | 축 | 값 | 상위값 | 요청 # |
|---|---|---|---|---|
| 1 | Material | ASD | - | #1 |
| 2 | 물리 현상 | Depo selectivity loss | - | #2 |

## 확인 필요 (고친 뒤 반영)

확인할 행이 없다.

## 요청 목록

- 시트 배치: #1 바로 반영 가능, #2 바로 반영 가능
- AMBIGUOUS_DEF·VALUE_OVERLAP·OTHER·NEED_QUESTION은 행 초안을 내지 않는다(질문은 questions 시트에 직접 쓴다).

| # | chunk ID | 파일 ID | 대상 | 키 | 사유 | 봇 값 | 사람 교정 | 제안·관련 값 |
|---|---|---|---|---|---|---|---|---|
| 1 | e431cf31a553c265:ppt/slides/slide4.xml | e431cf31a553c265 | 축 | Material | NO_FIT_VALUE 맞는 값이 없음 | unknown | - | ASD |
| 2 | e431cf31a553c265:ppt/slides/slide4.xml | e431cf31a553c265 | 축 | 물리 현상 | NO_FIT_VALUE 맞는 값이 없음 | unknown | - | Depo selectivity loss |

메모
- #1
  > FAV등 selective depsotion향으로 Material 추가 필요
- #2
  > sel depo에서 selectivity loss 현상
