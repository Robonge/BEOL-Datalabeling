---
name: beol-drm-probe
description: '폐쇄망에서 사내 문서(OOXML 3~5개)의 DRM이 풀린 채로 읽히는지 python -m labelbot probe로 확인하고(C4), G-DRM 규칙으로 판정한다: 사유 코드 ENCRYPTED·NOT_OOXML이 나오면 미복호화(업무 PC에서 라벨링 후 작업 폴더만 옮기는 CM 경로), 전부 사유 없음이면 폐쇄망에서 바로 ingest. 사용자가 "DRM 확인", "DRM probe", "사내 파일 읽히나", "복호화 확인", "G-DRM 판정"이라고 하면 이 스킬을 쓴다.'
---

# beol-drm-probe: DRM probe (C4)

> 수작성 skill(폐쇄망 운영). 근거: 폐쇄망 계획 C4, 루트 `CLAUDE.md` DRM 규칙(Roo: `.roo/rules/00-beol-governing.md`).

## 지킬 것

- 사내 파일을 파일 읽기 도구나 `cat`으로 열지 않는다. 여는 것은 `labelbot probe`(내부에서 `labelbot.ingest` 한 곳) 뿐이다.
- 출력은 파일 ID 16자·사유 코드·구조 통계뿐이다. 파일명·본문을 대화에 옮기지 않는다.

## 절차

1. 사용자에게 사내 샘플 폴더 경로(OOXML `.pptx`·`.docx`·`.xlsx` 3~5개)를 묻는다.
2. probe를 실행한다(사용자 승인 후).
   ```bash
   mkdir -p workspaces/_drm_probe
   python -m labelbot probe --workspace workspaces/_drm_probe --input "<사내 샘플 폴더>" > workspaces/_drm_probe/probe.log 2>&1
   echo "rc=$?"
   ```
3. `workspaces/_drm_probe/probe.log`는 파일 ID·사유 코드만 담고 있다. 파일마다 `reason` 값을 센다.
4. G-DRM 판정을 한 줄로 보고한다.

| probe 결과(OOXML) | 판정 | 다음 |
|---|---|---|
| 하나라도 `ENCRYPTED`·`NOT_OOXML` | 미복호화 | CM 경로: 업무 PC에서 ingest·라벨링하고 작업 폴더만 옮긴 뒤 `beol-upgrade-carry` 스킬 6단계의 경로 변환 |
| 전부 사유 없음(None) | 복호화됨 | 폐쇄망에서 바로 `beol-labeling` 스킬로 ingest |
| 섞여 있음 | 판정 보류 | 사용자가 결정한다(파일 종류·경로별로 다시 probe) |
| csv·txt만 | 판정 불가 | OOXML 샘플을 다시 고른다 |

## 수락

- `probe.log`에 파일명이 0건(파일 ID·사유 코드·통계만).
- 판정 결과(미복호화·복호화됨·보류)를 사용자가 확인.

## 마일스톤

`labelbot probe`는 명령 진입 줄 `[M00 ENV/CLI]`을 낸다. 판정 대상(DRM 확인)은 수집 단계 M01 INGEST의 일이다.

| 명령 | 마일스톤 |
|---|---|
| `labelbot probe` | M00 ENV/CLI |
| DRM 판정(`labelbot ingest`와 같은 읽기 경로) | M01 INGEST |

담당 마일스톤: M00·M01

## 실패하면

터미널의 `[Mxx …] 실패` 블록을 먼저 읽는다 → `python -m labelbot status --workspace <작업 폴더>`(Python 3.14가 없으면 `python3 tools/beol_status.py status --workspace <작업 폴더>`) 출력을 복사해 알려 달라. 환경 문제면 `python3 tools/beol_doctor.py`. `BEOL_TRACE=1`은 Roo 명령으로 실행하지 말고 일반 터미널에서만.
