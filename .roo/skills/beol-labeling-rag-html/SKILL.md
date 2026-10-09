---
name: beol-labeling-rag-html
description: 'BEOL 슬라이드 RAG 대화 화면(rag/beol_rag.html)을 로컬 정적 서버로 띄운다. 폐쇄망에서는 B6 릴리스 전까지 "답변 서버(ragsrv) 준비 전: 화면 디자인 수정만 가능"이고, 답변 함수 배포 단계는 없다(B6 릴리스에서 ragsrv 실행 단계로 다시 생성된다).사용자가 "RAG 화면 띄워줘", "beol_rag 실행", "RAG html 켜줘", "RAG 배포", "edge function 배포", "beol-rag-ask 배포", "시스템 프롬프트 바꿨어 반영해줘"라고 하면 이 스킬을 쓴다(배포 요청에는 아직 배포 단계가 없다고 안내한다).'
---

# BEOL-labeling-RAG-html

> 이 문서는 `.claude/skills/BEOL-labeling-RAG-html/SKILL.md`에서 생성됐다. 직접 고치지 말고 원본을 고친 뒤 `python tools/gen_roo_skills.py`를 다시 실행한다.

> 그룹: ③ 화면 · 발표 · 운영 리포트 · 상위: 없음 · 하위: 없음 · 전체 지도: README.md "스킬 지도"

> **답변 서버(ragsrv) 준비 전: 화면 디자인 수정만 가능.** 폐쇄망에는 B6 릴리스 전까지 답변 서버가 없다. 원본 스킬의 답변 함수 배포 단계는 이 버전에 없고, B6 릴리스에서 ragsrv 실행 단계로 다시 생성된다.

| 구성 | 위치 | 역할 |
|---|---|---|
| 화면 | `rag/beol_rag.html` | 질문 입력·답 표시. 로컬 정적 서버로 연다 |
| 답변 서버 | B6 릴리스의 `ragsrv` | 질문 → 검색 → 답변. 지금은 없음 |

## 규칙

- 키는 출력하지 않는다. `rag/beol_rag.html` 안의 키 값을 답변·로그에 적지 않는다.
- B6 전에는 화면에서 질문을 보내도 답이 오지 않는 것이 정상이다. 외부 주소로 보내는 호출을 새로 넣지 않는다.
- 화면 디자인(HTML·CSS)만 `rag/beol_rag.html`에서 고친다. 이 파일은 업그레이드(CU) 때 상태 파일로 이어받는다. 그 밖의 코드는 폐쇄망에서 고치지 않는다.
- 본문·답변 내용은 로그에 남기지 않는다. 건수·사유 코드만 전한다.

## 절차

### 1. 무엇을 하려는지 가른다

- 화면 모양(HTML·CSS)을 고쳤거나 보려는 것이면 2번만 한다.
- 답변 프롬프트·검색 로직·배포 요청이면 "답변 서버(ragsrv) 준비 전: 화면 디자인 수정만 가능"이라고 한 줄로 알리고 끝낸다.

### 2. 화면 실행

정적 서버는 끝날 때까지 막히므로(Roo 명령 도구는 명령이 끝날 때까지 막힌다) 사용자에게 별도 VS Code 터미널에서 실행해 달라고 안내한다.

```bash
python -m http.server 8795 --bind 127.0.0.1 --directory rag
```

- 주소 `http://127.0.0.1:8795/beol_rag.html`(프록시 뒤면 포트 패널·프록시 URL)을 출력하고 사용자가 브라우저에서 연다.
- 8795가 이미 다른 서버(예: taxonomy 보드 서버)로 쓰이고 있으면 다른 포트로 띄운다.
- 이 정적 서버는 마일스톤 줄을 내지 않는다(아래 "마일스톤").

### 3. 마무리 보고

한 줄씩만 전한다.

- 화면: 주소와 서버 상태
- 배포: "답변 서버(ragsrv) 준비 전: 배포 없음"

## 하지 않는 일

- 답변 함수·서버 배포, 답변 시스템 프롬프트 수정(B6 전)
- 슬라이드 적재·임베딩: `beol-labeling-feedback` 스킬

## 관계

- 라벨링 실행은 `beol-labeling` 스킬, 라벨링 결과 적재는 `beol-labeling-feedback` 스킬이 맡는다.

## 마일스톤

이 스킬의 명령은 터미널에 `[Mxx 이름] 시작·완료·실패` 줄을 낸다. 실패하면 아래 ID로 어느 단계인지 보고, `python -m labelbot codes --milestone <Mxx>`로 사유 코드와 조치를 본다.

| 명령 | 마일스톤 |
|---|---|
| `ragsrv serve` | M15 RAG_SERVE |
| `ragsrv /api/ask` | M16 RAG_ASK |

담당 마일스톤: M15·M16

B6 릴리스부터. 지금 정적 화면 서버(`python -m http.server`)는 마일스톤 줄을 내지 않는다.

## 실패하면

터미널의 `[Mxx …] 실패` 블록을 먼저 읽는다 → `python -m labelbot status --workspace <작업 폴더>`(Python 3.14가 없으면 `python3 tools/beol_status.py status --workspace <작업 폴더>`) 출력을 복사해 알려 달라. 환경 문제면 `python3 tools/beol_doctor.py`. `BEOL_TRACE=1`은 Roo 명령으로 실행하지 말고 일반 터미널에서만.
