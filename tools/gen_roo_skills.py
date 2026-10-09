#!/usr/bin/env python3
"""Roo Code skill·rules 생성기(L4, 마일스톤 M25 RELEASE_TOOLS, 로컬 전용).

`.claude/skills/<원래 이름>/SKILL.md` 12개 → `.roo/skills/<소문자 이름>/SKILL.md`, 루트 `CLAUDE.md` →
`.roo/rules/00-beol-governing.md`, 생성 목록 `.roo/skills/.generated.json`.

- 변환은 아래 선언형 표(RULES: 정규식 → 바꿀 문장, 스킬별 줄은 원문에 있어야 한다)와 스킬별 절 교체
  (SECTIONS·BODY_OVERRIDES·DESC_OVERRIDES)로만 한다. 원문이 바뀌어 스킬별 줄이 안 맞으면 생성이 멈춘다.
- 스크립트는 복사하지 않고 `.claude/skills/<원래 이름>/scripts/…`·`assets/…`로 가리키며 존재를 검사한다.
- 생성물마다 머리 줄, "## 마일스톤"(labelbot.milestones.ENTRYPOINTS로 명령 → Mxx), "## 실패하면"을 붙인다.
- 수작성 skill(beol-import-verify 등 7개)은 이 도구가 쓰지 않는다(.generated.json에도 없다).

사용: python tools/gen_roo_skills.py           # 생성(바뀐 파일만 쓴다)
      python tools/gen_roo_skills.py --check   # 메모리에서 다시 만들어 저장소 파일과 비교, 차이가 있으면 종료 1
"""
import argparse
import hashlib
import json
import os
import re
import sys

CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if CODE_ROOT not in sys.path:
    sys.path.insert(0, CODE_ROOT)

from labelbot import milestones  # noqa: E402

MILESTONE = "M25"
GENERATOR_VERSION = "1"

CLAUDE_SKILLS = ".claude/skills"
ROO_SKILLS = ".roo/skills"
ROO_RULES = ".roo/rules/00-beol-governing.md"
MANIFEST = ".roo/skills/.generated.json"
GOVERNING_SOURCE = "CLAUDE.md"

# 생성 대상 12개(.claude/skills 13개 중 change-dashboard 제외)
INCLUDED = (
    "BEOL-labeling", "BEOL-labeling-run-labeling", "BEOL-labeling-feedback", "BEOL-labeling-axis-update",
    "BEOL-labeling-rules-update", "BEOL-labeling-Code-Engr-bot", "BEOL-labeling-Domain-Engr-bot",
    "BEOL-taxonomy-dashboard", "BEOL-labeling-daily-report", "BEOL-labeling-project-html",
    "BEOL-labeling-workflow", "BEOL-labeling-RAG-html",
)
EXCLUDED = {"BEOL-labeling-change-dashboard": "~/.claude/projects 세션 기록에 의존(폐쇄망 Roo에 없음)"}
# 수작성 skill(폐쇄망 운영 절차). 참조 검사에만 쓴다.
HANDWRITTEN = (
    "beol-import-verify", "beol-upgrade-carry", "beol-env-setup", "beol-drm-probe",
    "beol-proxy-measure", "beol-release-accept", "beol-backup-ops",
)

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# 생성물에 남으면 안 되는 Claude 전용 구문. "/BEOL-"는 슬래시 명령꼴만 센다(경로 .claude/skills/BEOL-…는 아님).
FORBIDDEN = (
    ("AskUserQuestion", re.compile(r"AskUserQuestion")),
    ("preview_start", re.compile(r"preview_start")),
    ("/BEOL-", re.compile(r"(?<![\w.-])/BEOL-")),
    ("run_in_background", re.compile(r"run_in_background")),
    ("7200000", re.compile(r"7200000")),
    ("Monitor", re.compile(r"Monitor")),
    ("get_page_text", re.compile(r"get_page_text")),
    ("read_page", re.compile(r"read_page")),
    ("mcp__", re.compile(r"mcp__")),
    ("Skill(", re.compile(r"Skill\(")),
)

HEADER = ("> 이 문서는 `{src}`에서 생성됐다. 직접 고치지 말고 원본을 고친 뒤 "
          "`python tools/gen_roo_skills.py`를 다시 실행한다.")

NOTE_GATED = (
    "> 폐쇄망: LLM 호출(M02·M03)·임베딩(M07)·벡터 저장소 적재(M08)·슬라이드 JPG 저장(M10)은 사내 API·벡터 저장소·S3 "
    "단계라 게이트 G-API·G-VDB·G-S3 이후 릴리스에서 활성화된다. 그 전에는 이 단계가 설정 누락 사유 코드로 멈추거나 "
    "\"호출하지 않습니다\"로 끝나므로 사유 코드만 보고하고 나머지 단계를 계속한다.")
GATED_HINTS = ("push-vectors", "labelbot embed", "--probe-llm", "questions generate")

FAILURE_SECTION = (
    "## 실패하면\n\n"
    "터미널의 `[Mxx …] 실패` 블록을 먼저 읽는다 → `python -m labelbot status --workspace <작업 폴더>`"
    "(Python 3.14가 없으면 `python3 tools/beol_status.py status --workspace <작업 폴더>`) 출력을 복사해 알려 달라. "
    "환경 문제면 `python3 tools/beol_doctor.py`. `BEOL_TRACE=1`은 Roo 명령으로 실행하지 말고 일반 터미널에서만.\n")

SEP_TERMINAL = "Roo 명령 도구는 명령이 끝날 때까지 막힌다"


class GenError(Exception):
    pass


def roo_name(orig):
    return orig.lower()


def _lit(text):
    return re.escape(text)


# ---- 변환 표 ---------------------------------------------------------------------
# (규칙 ID, 적용 스킬(None=전부), 정규식, 바꿀 문장 또는 함수, 플래그)
# 스킬을 지정한 줄은 그 스킬 원문(설명+본문)에 반드시 한 번 이상 맞아야 한다(원문 변경 감지).

# "스킬"은 ㄹ받침이라 을·이·은·로·과·이나를 붙인다
_PARTICLE = {"를": "을", "가": "이", "는": "은", "으로": "로", "와": "과", "나": "이나"}
_SKILL_REF = (r"(?P<name>BEOL-[A-Za-z]+(?:-[A-Za-z]+)*)")
_PART = r"(?P<sk> ?(?:스킬|skill))?(?P<p>으로|로|을|를|이나|나|이|가|은|는|과|와)?"


def _skill_ref(m, tick=True):
    """`/BEOL-x 인자`꼴 → `beol-x` 스킬(인자) + 받침에 맞춘 조사. 백틱 밖 꼴은 코드 범위 안일 수 있어 백틱을 넣지 않는다."""
    gd = m.groupdict()
    out = ("`%s` 스킬" if tick else "%s 스킬") % roo_name(gd["name"])
    arg = (gd.get("arg") or "").strip()
    if arg:
        out += "(%s)" % arg
    p = gd.get("p") or ""
    if gd.get("sk"):
        return out + p  # 원문이 이미 "스킬"에 맞춘 조사다
    return out + _PARTICLE.get(p, p)


def _skill_call(m):
    out = "`%s` 스킬 절차를 따른다" % roo_name(m.group(1))
    if m.group(2):
        out += "(인자: %s)" % m.group(2).strip()
    return out


def _win_path(m):
    return "`" + m.group(1).replace("%USERPROFILE%", "~").replace("\\", "/") + "`"


RULES = [
    # ---- BEOL-labeling ----
    ("S-LAB-MODEL", ("BEOL-labeling",),
     _lit("- 모델: `gpt-6-sol`(temperature 미전송, `max_completion_tokens`). 키는 코드 폴더 `.env`에서 읽는다."),
     "- 모델·키: 폐쇄망에서는 사내 OpenAI 호환 API(게이트 G-API 이후 릴리스)를 쓴다. 값은 "
     "`workspaces/_site/profile.json`·`beol.env`에 있고, 키 값은 출력하지 않는다.", 0),
    ("S-LAB-PROGRESS", ("BEOL-labeling",),
     r"- 3단계 `labelbot run`은 백그라운드로 돌리고, `Monitor`로.*?다시 보여 준다\.",
     "- 3단계 `labelbot run`은 사용자에게 별도 VS Code 터미널에서 실행해 달라고 안내한다(" + SEP_TERMINAL + "). "
     "사용자가 `[ingest]`·`[classify]`·`[question]`·`[label]`·`[run]`·`[오류]` 줄을 알려 주면 해당 milestone을 "
     "`✅`로 바꾸고 다음을 `▶️`로 둔 블록을 다시 보여 준다.", 0),
    ("S-LAB-RUN", ("BEOL-labeling",),
     _lit("백그라운드로 실행하고, `Monitor`로 단계 줄을 감시해 milestone 3~6의 진행 현황을 갱신하면서 끝날 때까지 기다린다."),
     "이 명령은 사용자에게 별도 VS Code 터미널에서 실행해 달라고 안내하고(" + SEP_TERMINAL + "), 끝나면(또는 "
     "`[run] 완료 run_id=…` 줄이 보이면) 마지막 줄들을 붙여 달라고 한다. 중간에 단계 줄을 알려 주면 milestone 3~6의 "
     "진행 현황을 갱신한다.", 0),
    # ---- BEOL-labeling-run-labeling ----
    ("S-RUN-STEP1", ("BEOL-labeling-run-labeling",),
     r"`Skill\(BEOL-labeling, <입력 폴더>\)`\. 7-1의 완료 대기까지 걸고 턴을 끝낸다\.",
     "`beol-labeling` 스킬 절차를 따른다(인자: <입력 폴더>). 7단계 안내까지 하고 멈춘다(검수 완료는 사용자가 알려 준다).", 0),
    ("S-RUN-STEP2", ("BEOL-labeling-run-labeling",),
     _lit("BEOL-labeling 7-3이 `BEOL-labeling-feedback`을 자동으로 부른다. 별도로 부르지 않는다. "
          "사용자가 채팅으로 \"검수 끝났어\"라고 해도 같다."),
     "사용자가 \"검수 끝났어\"라고 하거나 완료 대기 출력(`done: true`)을 붙여 넣으면 `beol-labeling` 스킬 7-3대로 "
     "`beol-labeling-feedback` 스킬 절차를 이어서 따른다.", 0),
    ("S-RUN-EACH", ("BEOL-labeling-run-labeling",),
     _lit("각 단계는 Skill 도구로 해당 스킬을 부른 뒤 그 스킬의 절차를 끝까지 따른다."),
     "각 단계는 해당 스킬의 절차를 순서대로 끝까지 따른다.", 0),
    # ---- BEOL-labeling-feedback ----
    ("S-FB-PANEL", ("BEOL-labeling-feedback",),
     _lit("1-2에서 브라우저 패널의 상태를 볼 때는 건수만 센다. 버튼을 대신 누르는 것은 파일 내려받기이므로 매번 사용자 확인을 받는다."),
     "Roo는 브라우저 화면을 읽거나 버튼을 누르지 않는다. 화면에만 남은 체크는 사용자가 **JSON 저장**을 눌러야 밖으로 나온다.", 0),
    ("S-FB-NOREAD", ("BEOL-labeling-feedback",),
     _lit("검수 탭과 JSON 저장 대체 텍스트 창에는 `get_page_text`·`read_page`·`find`·스크린샷을 쓰지 않는다"
          "(1-2의 건수 스니펫과 저장 버튼을 찾는 `find`만 허용하며 `javascript_tool`은 `revisits.length`만 읽는다)."),
     "검수 탭과 JSON 저장 대체 텍스트 창의 내용은 읽지 않는다.", 0),
    ("S-FB-12", ("BEOL-labeling-feedback",),
     r"\*\*1-2\. 화면에만 남은 체크 확인\.\*\*.*?(?=\n- 사용자가 \"교정 없음/검수 완료\")",
     "**1-2. 화면에만 남은 체크 확인.** 완료 버튼 인자 없이 채팅으로 왔고, `inbox.review`가 0이고, 사용자가 "
     "\"교정 없음\"이라고 하지 않았을 때만 한다. 검수 화면의 체크는 그 브라우저의 `localStorage`에만 있어 Roo가 볼 수 없다.\n"
     "1. 사용자에게 검수 탭(`…/review.html`)에서 **JSON 저장**(예전 화면은 **JSON 내려받기**)을 눌러 달라고 안내한다. "
     "대조 탭에 표시가 있으면 대조 화면에서도 저장한다. 그다음 멈추고 사용자가 알려 줄 때까지 기다린다.\n"
     "2. 알려 오면 1-1을 다시 돌린다. 그래도 `moved`가 0이면 내려받기가 `~/Downloads`로 가지 않은 것이다. "
     "저장된 파일을 `<WS>/inbox/`로 옮겨 달라고 안내하고 멈춘다.\n", re.S),
    ("S-FB-SCHEMA", ("BEOL-labeling-feedback",),
     _lit("FAIL을 내므로 `docs/supabase_schema.md`의 SQL을 실행해 달라고 안내한다."),
     "FAIL을 낸다. 폐쇄망에서는 저장소 스키마를 바꾸지 않고 사유 코드만 보고한다(S3·벡터 저장소 스키마는 게이트 "
     "G-S3·G-VDB 이후 릴리스 절차).", 0),
    ("S-FB-REFRESH", ("BEOL-labeling-feedback",),
     _lit("먼저 브라우저 패널에 화면 서버가 떠 있으면 `results.html` 탭을 새로고침한다(없으면 연다)."),
     "먼저 화면 서버가 떠 있으면 사용자에게 `results.html` 탭을 새로고침해 달라고 안내한다(서버가 없으면 대시보드 "
     "URL만 보고에 남긴다).", 0),
    ("S-FB-EMBEDBG", ("BEOL-labeling-feedback",),
     _lit("임베딩은 백그라운드로 돌리고 끝나면 갱신한다."),
     "임베딩이 오래 걸리면 사용자에게 별도 VS Code 터미널에서 실행해 달라고 안내하고, 끝나면 갱신한다.", 0),
    # ---- BEOL-labeling-axis-update ----
    ("S-AX-WAIT", ("BEOL-labeling-axis-update",),
     _lit("안내하기 전에 완료 대기를 백그라운드로 건다."),
     "완료 대기 명령(선택)은 끝날 때까지 막히므로 Roo 명령 도구로 돌리지 않는다.", 0),
    ("S-AX-TIMEOUT", ("BEOL-labeling-axis-update",),
     _lit("`code: WAIT_TIMEOUT`이면 같은 대기를 다시 건다."),
     "`code: WAIT_TIMEOUT`이면 같은 대기 명령을 다시 실행해 달라고 한다. 대기 명령 없이 사용자가 \"검수 끝났어\"라고 "
     "알려 와도 6단계로 간다.", 0),
    ("S-AX-DONE", ("BEOL-labeling-axis-update",),
     _lit("완료 신호(`done: true`)가 오면"),
     "사용자가 완료 신호(`done: true` 줄)를 붙여 주거나 \"검수 끝났어\"라고 하면", 0),
    # ---- BEOL-labeling-Code-Engr-bot ----
    ("S-CODE-FIX", ("BEOL-labeling-Code-Engr-bot",),
     r"- \*\*코드 수정\*\*:[^\n]*",
     "- **코드 수정**: 폐쇄망에서는 코드를 고치지 않는다. 고칠 항목(review ID·`path:line`·규칙 ID)은 "
     "`CLOSED_NETWORK_RUNBOOK.md`의 반출 절차로 로컬에 넘기고 다음 릴리스에서 고친다. 오탐 억제 주석·`policy.json` "
     "수정도 같다.", 0),
    # ---- BEOL-labeling-Domain-Engr-bot ----
    ("S-DOM-SERVE", ("BEOL-labeling-Domain-Engr-bot",),
     _lit("아래 명령을 Bash `run_in_background`로 띄우고(timeout은 최대 7200000), 출력에 나오는 `127.0.0.1` 주소를 "
          "브라우저 창에서 연다."),
     "아래 명령은 화면 서버라 끝날 때까지 막히므로 사용자에게 별도 VS Code 터미널에서 실행해 달라고 안내한다(Roo 명령 "
     "도구로 실행하지 않는다). 서버가 내는 주소(`[M11 DOMAIN_QA] 대기 중 URL=…`)를 사용자가 브라우저에서 연다"
     "(프록시 뒤면 포트 패널·프록시 URL).", 0),
    ("S-DOM-WAKE", ("BEOL-labeling-Domain-Engr-bot",),
     _lit("반영을 마치면 서버가 스스로 닫히고, 백그라운드 작업이 끝났다는 알림으로 Claude가 깨어나 절차 5-A로 마무리한다"
          "(사용자 결정, 2026-10-06)."),
     "반영을 마치면 서버가 스스로 닫힌다. 사용자가 그 터미널의 마지막 줄들(`[questions] 반영: …`, `[serve] …`)을 "
     "붙여 주거나 \"질문 답변 끝났어\"라고 하면 절차 5-A로 마무리한다(사용자 결정, 2026-10-06).", 0),
    ("S-DOM-GUIDE", ("BEOL-labeling-Domain-Engr-bot",),
     _lit("반영까지 끝나고, Claude가 마무리 보고를 한다"),
     "반영까지 끝난다. 끝나면 그 터미널의 마지막 줄들을 붙여 주거나 \"질문 답변 끝났어\"라고 알려 주면 마무리 보고를 한다", 0),
    ("S-DOM-5A", ("BEOL-labeling-Domain-Engr-bot",),
     _lit("절차 3의 백그라운드 작업이 끝났다는 알림이 오면(또는 사용자가 \"질문 답변 끝났어\"라고 했는데 서버 출력에 반영 "
          "줄이 이미 있으면) 그 작업의 출력 파일을 읽는다."),
     "사용자가 질문 화면 서버 터미널의 마지막 줄들을 붙여 주면(\"질문 답변 끝났어\"라고만 했으면 그 줄들을 붙여 달라고 "
     "한다) 그 줄을 본다.", 0),
    ("S-DOM-NOASK", ("BEOL-labeling-Domain-Engr-bot",),
     _lit("`AskUserQuestion`·`questions apply`·TaskStop은 하지 않는다"),
     "사용자에게 다시 묻거나 `questions apply`를 돌리거나 서버를 끄지 않는다", 0),
    ("S-DOM-TIMEOUT", ("BEOL-labeling-Domain-Engr-bot",),
     _lit("(사람이 저장하지 않았거나 2시간 timeout)"),
     "(사람이 저장하지 않고 서버를 껐으면)", 0),
    ("S-DOM-FAILLINE", ("BEOL-labeling-Domain-Engr-bot",),
     _lit("서버가 아직 떠 있으면 출력 파일에서 `[serve] 반영 실패: <코드>` 줄을 본다."),
     "서버가 아직 떠 있으면 그 터미널에 `[serve] 반영 실패: <코드>` 줄이 있는지 사용자에게 묻는다.", 0),
    ("S-DOM-STOP", ("BEOL-labeling-Domain-Engr-bot",),
     _lit("4. 절차 3에서 띄운 질문 화면 서버가 아직 떠 있으면 멈춘다(TaskStop)."),
     "4. 절차 3에서 띄운 질문 화면 서버가 아직 떠 있으면 사용자에게 그 터미널에서 Ctrl+C로 꺼 달라고 한다"
     "(`[M11 DOMAIN_QA] 중단(사용자)`는 실패가 아니다).", 0),
    ("S-DOM-FILEOPEN", ("BEOL-labeling-Domain-Engr-bot",),
     _lit("브라우저 창에서 그 파일을 연다(`file:///` 경로)"),
     "그 파일 경로를 출력하고 사용자가 브라우저에서 연다(`file:///` 경로)", 0),
    ("S-DOM-OTHER", ("BEOL-labeling-Domain-Engr-bot",),
     _lit("(사용자는 \"Other\"로 고른다)"), "(사용자는 이름을 직접 적어 고른다)", 0),
    ("S-DOM-RECOMMEND", ("BEOL-labeling-Domain-Engr-bot",),
     _lit("\"(Recommended)\"를 붙인다"), "\"(권장)\"을 붙인다", 0),
    # ---- BEOL-taxonomy-dashboard ----
    ("S-TAX-SERVE", ("BEOL-taxonomy-dashboard",),
     _lit("1. 보드 서버를 띄운다(백그라운드 실행, 사용자가 Ctrl+C로 닫는다)."),
     "1. 보드 서버를 띄운다. 서버는 끝날 때까지 막히므로 사용자에게 별도 VS Code 터미널에서 실행해 달라고 안내한다"
     "(사용자가 Ctrl+C로 닫는다). 서버가 낸 주소를 사용자가 브라우저에서 연다(`BEOL_NO_BROWSER=1`이면 `--open`은 "
     "주소만 낸다).", 0),
    # ---- BEOL-labeling-daily-report ----
    ("S-DR-OPEN", ("BEOL-labeling-daily-report",),
     _lit("2. 화면을 연다. `--open`을 붙이거나, 브라우저 미리보기로 `workspaces/_nightly/daily_report.html`을 연다."),
     "2. 화면을 연다. 생성된 `workspaces/_nightly/daily_report.html` 경로를 출력하고 사용자가 VS Code나 브라우저에서 "
     "연다(`BEOL_NO_BROWSER=1`이면 `--open`은 주소만 낸다).", 0),
    ("S-DR-SCHED", ("BEOL-labeling-daily-report",),
     _lit("예약(작업 스케줄러)은 사용자가 따로 건다."),
     "예약은 사용자가 crontab으로 건다(`CLOUD_SETUP.md` 9절).", 0),
    ("S-DR-CHANGE", ("BEOL-labeling-daily-report",),
     _lit("변경 대시보드는 BEOL-labeling-change-dashboard"),
     "변경 대시보드(BEOL-labeling-change-dashboard)는 폐쇄망 Roo 버전에 없음", 0),
    # ---- BEOL-labeling-project-html ----
    ("S-PH-SEND", ("BEOL-labeling-project-html",),
     _lit("- 두 파일은 `SendUserFile`(`display: attach`, 캡션 없음)으로도 보낸다."),
     "- 두 파일은 사용자가 VS Code(또는 브라우저)에서 연다. 링크는 저장소 기준 상대 경로다.", 0),
    # ---- BEOL-labeling-workflow ----
    ("S-WF-ARTIFACT", ("BEOL-labeling-workflow",),
     _lit(" 팀에 공유할 것 같으면 Artifact로 게시할 수 있다고 한 줄로 제안한다(파일 자체는 사내 반입용으로 그대로 둔다)."),
     "", 0),
    ("S-WF-TEMPLATE", ("BEOL-labeling-workflow",),
     r"(### 2\. 워크플로가 바뀌었을 때만: 템플릿 고치기\n)",
     "\\1\n> 폐쇄망에서는 템플릿·스크립트를 고치지 않는다. 워크플로가 바뀌었으면 반출로 로컬에 넘긴다. 아래는 로컬 개발용 "
     "설명이다.\n", 0),

    # ---- 공통 ----
    # frontmatter 트리거: 슬래시 호출 문구만 빼고 자연어 트리거는 그대로 둔다
    ("G-DESC-SLASH", None, r"(이라고|라고) 하거나 /BEOL-[A-Za-z-]+(?:을|를) 부르면", r"\1 하면", 0),
    ("G-SKILL-CALL", None, r"`?Skill\((" + r"BEOL-[A-Za-z-]+" + r")(?:,\s*([^)]*))?\)`?", _skill_call, 0),
    ("G-SKILL-TOOL1", None, r"Skill 도구로 `?(BEOL-[A-Za-z-]+)`?(?:을|를) 부른다",
     lambda m: "`%s` 스킬 절차를 이어서 따른다" % roo_name(m.group(1)), 0),
    ("G-SKILL-TOOL2", None, r"Skill 도구로 해당 (스킬|skill)을 부르고", r"해당 \1의 절차를 따르고", 0),
    ("G-SKILL-TOOL3", None, r"Skill 도구로 해당 (스킬|skill)을 부른 뒤", r"해당 \1의 절차를 따른 뒤", 0),
    ("G-SLASH-TICK", None, r"`/" + _SKILL_REF + r"(?P<arg> [^`\n]*)?`" + _PART, _skill_ref, 0),
    ("G-SLASH", None, r"(?<![\w.-])/" + _SKILL_REF + _PART, lambda m: _skill_ref(m, tick=False), 0),
    ("G-ASK-DUP", None, r"사용자에게 `AskUserQuestion`(?:으로|로) ", "사용자에게 ", 0),
    ("G-ASK-MULTI", None, r"`AskUserQuestion`\(`multiSelect: true`\)(?:으로|로) 묻는다",
     "사용자에게 묻는다(여러 개 고를 수 있게)", 0),
    ("G-ASK", None, r"`AskUserQuestion`(?:으로|로) ", "사용자에게 ", 0),
    ("G-ASK-REST", None, r"`?AskUserQuestion`?", "사용자 질문", 0),
    ("G-NOREAD", None, r"`get_page_text`·`read_page`(?:·`find`)?·스크린샷(으로|로)?",
     lambda m: "화면 내용 읽기·캡처" + ("로" if m.group(1) else ""), 0),
    ("G-NOREAD-REST1", None, r"`?get_page_text`?", "화면 텍스트 읽기", 0),
    ("G-NOREAD-REST2", None, r"`?read_page`?", "화면 구조 읽기", 0),
    ("G-MON-LINE", None, r"백그라운드로 (?:돌리고|실행하고),? `Monitor`로 (`[^`]+`) 줄을 본다\.",
     "이 명령은 사용자에게 별도 VS Code 터미널에서 실행해 달라고 안내하고(" + SEP_TERMINAL + "), 끝나면(또는 \\1 줄이 "
     "보이면) 마지막 줄들을 붙여 달라고 한다.", 0),
    ("G-MON-NOUSE", None, r"감시\(`Monitor`\)", "출력 감시", 0),
    ("G-MON-REST", None, r"`?Monitor`?", "출력 감시", 0),
    ("G-BG-WAIT", None, r"Bash `run_in_background: true`, `timeout: 7200000`(?:으로 돌린다)?\.",
     "이 명령은 Roo 명령 도구로 실행하지 않는다(끝날 때까지 막힌다). 사용자에게 별도 VS Code 터미널에서 실행하고, "
     "끝나면(또는 `done: true` 줄이 보이면) 알려 달라고 한다.", 0),
    ("G-BG-REST", None, r"(?:Bash )?`?run_in_background(?:: true)?`?", "별도 VS Code 터미널 실행", 0),
    ("G-TIMEOUT-REST", None, r",? ?`?timeout(?:은 최대|:)? ?7200000`?", "", 0),
    ("G-BG-PHRASE", None, r"백그라운드로 돌리고", "별도 VS Code 터미널에서 실행하게 하고", 0),
    ("G-PREVIEW-OPEN", None,
     r"화면 서버를 띄우고\(`preview_start` name=`<launch_name>`\) 사용자의 Chrome에서 (`[^`]+`)을 연다\. "
     r"여는 방법과 탭 재사용 규칙은 BEOL-labeling 6단계와 같다\. 열린 탭 내용은 읽지 않는다\.",
     "화면 서버(`python -m labelbot serve --workspace \"<WS>\" --port <port>`)를 사용자에게 별도 VS Code 터미널에서 "
     "띄워 달라고 안내한다(이미 떠 있으면 그대로 쓴다. 방법은 `beol-labeling` 스킬 6단계와 같다). 서버가 "
     "`[M05 REVIEW_SERVE] 대기 중 URL=…`을 내면 \\1을 출력하고 사용자가 브라우저에서 연다. 화면 내용은 읽지 않는다.", 0),
    ("G-PREVIEW-REST", None, r"`?(?:mcp__Claude_Browser__)?preview_start`?(?:\s*\{[^}]*\})?", "화면 서버 실행", 0),
    ("G-MCP-REST", None, r"`?mcp__[\w-]+`?", "브라우저 도구", 0),
    ("G-SENDFILE", None, r"`?SendUserFile`?(?:\([^)]*\))?", "파일 경로 출력", 0),
    ("G-ARTIFACT", None, r"(?<![A-Za-z])Artifact(?![A-Za-z])", "공유 페이지", 0),
    ("G-TASKSTOP", None, r"`?TaskStop`?(?:으로|로)", "터미널에서 Ctrl+C로", 0),
    ("G-TASKSTOP-REST", None, r"`?TaskStop`?", "터미널에서 Ctrl+C로 종료", 0),
    ("G-TURN-END", None, r"턴을 끝낸다", "여기서 멈추고 사용자가 알려 줄 때까지 기다린다", 0),
    ("G-TURN-END2", None, r"턴을 끝낼 때", "멈출 때", 0),
    ("G-TURN-END3", None, r"턴을 끝내", "멈추", 0),
    ("G-WAKE", None, r"이 대화가 (?:다시 )?깨어(?:난다|나)", "사용자가 알려 온다", 0),
    ("G-REFRESH", None, r"(\S+) 탭을 새로고침한다", r"사용자에게 \1 탭을 새로고침해 달라고 안내한다", 0),
    ("G-AGENT", None, r"서브 ?에이전트|subagent|(?<![A-Za-z])Agent(?![A-Za-z])", "순차 단계", 0),
    ("G-CHROME", None, r"Claude in Chrome", "브라우저 자동화", 0),
    ("G-CLAUDE-CODE", None, r"Claude Code", "Roo Code", 0),
    ("G-CLAUDE", None, r"(?<![A-Za-z])Claude(?![A-Za-z])", "Roo", 0),
    ("G-SUPABASE-STORAGE", None, r"Storage `BEOL-labeling` 버킷", "S3 저장소(`BEOL-labeling` 버킷 자리)", 0),
    ("G-SUPABASE", None, r"Supabase(?! 올려줘)", "벡터 저장소", 0),
    ("G-OPENAI", None, r"(?<!사내 )(?<![A-Za-z])OpenAI(?![A-Za-z])(?! 호환)", "사내 OpenAI 호환 API", 0),
    ("G-WINPATH", None, r"`((?:<WS>|workspaces|%USERPROFILE%)\\[^`\n]*)`", _win_path, 0),
]

# 절 교체(제목 줄 그대로 → 새 본문). 원래 절 구조는 남기고 Claude 도구 의존 단계만 바꾼다.
SECTIONS = {
    "BEOL-labeling": {
        "### 6. 대시보드 띄우기": (
            "화면 서버를 띄운다. 서버는 끝날 때까지 막히므로(" + SEP_TERMINAL + ") 사용자에게 별도 VS Code 터미널에서 "
            "실행해 달라고 안내한다. `<port>`는 1단계 출력의 `port`다.\n\n"
            "```bash\npython -m labelbot serve --workspace \"<WS>\" --port <port>\n```\n\n"
            "- 서버가 `[M05 REVIEW_SERVE] 대기 중 URL=…`을 내면 결과 대시보드 주소 `http://localhost:<port>/results.html`"
            "(프록시 뒤면 포트 패널·프록시 URL 뒤에 `results.html`)을 출력하고, 사용자가 브라우저에서 연다.\n"
            "- 같은 포트로 이미 떠 있으면(`PORT_IN_USE`) 그 서버를 그대로 쓴다. 다른 실행의 서버라면 사용자에게 그 "
            "터미널에서 Ctrl+C로 끄고 다시 띄워 달라고 한다(검수 화면의 inbox 자동 저장과 검수 완료 버튼은 이 작업 "
            "폴더의 `labelbot serve`에서만 동작한다).\n"
            "- 열린 화면의 내용은 읽지 않는다(화면 내용 읽기·캡처 금지). 건수와 URL만 보고한다.\n"
            "- 검수(`review.html`)·파싱 대조(`compare.html`)는 사람이 대시보드의 **검수 시작** 또는 **검수 + 파싱 대조** "
            "버튼으로 연다(7단계). 떠 있는 서버는 그대로 둔다."),
        "### 7. 검수 완료 대기로 넘기기": (
            "검수는 대시보드의 버튼으로 시작한다(사용자 결정, 2026-10-06). 사람이 검수 화면에서 **검수 완료**를 누르면 "
            "화면 서버가 완료 신호 `<WS>/signals/review_done_<RUN>.json`(실행 ID, 시각, 건수만)을 쓴다.\n\n"
            "**7-1. 완료 대기(선택).** 대기 명령은 끝날 때까지 막히므로 Roo 명령 도구로 돌리지 않는다. 원하면 사용자가 "
            "별도 VS Code 터미널에서 실행한다.\n"
            "```bash\npython \".claude/skills/BEOL-labeling-feedback/scripts/wait_review_done.py\" --workspace \"<WS>\" "
            "--run <RUN>\n```\n"
            "`done: true` JSON이 나오면 그 줄을 붙여 달라고 한다. `code: WAIT_TIMEOUT`이면 같은 명령을 다시 실행하면 된다.\n\n"
            "**7-2. 안내하고 멈추기.** 아래 내용을 안내하고 여기서 멈춘다(사용자가 알려 줄 때까지 기다린다).\n"
            "1. 대시보드에서 결과를 훑어본다.\n"
            "2. 오른쪽 위 **검수 시작**을 누른다. 파싱 대조도 하려면 **검수 + 파싱 대조**를 누른다(대조 화면이 새 탭으로 "
            "함께 열린다). 이 버튼은 화면만 연다.\n"
            "3. 검수 화면에서 불량 chunk n개 중 **강조된 라벨부터** 확인·교정한다. 확신도 높은 라벨은 접혀 있다.\n"
            "4. 다 끝나면 화면 상단의 **검수 완료**를 누른다. 교정할 것이 없어도 누르면 된다. 누르면 화면이 잠긴다.\n"
            "5. 그다음 이 대화에 \"검수 끝났어\"라고 알리거나 7-1 대기 명령의 `done: true` 줄을 붙여 넣는다. 그때 "
            "반영·임베딩·적재가 이어진다.\n\n"
            "검수가 끝나기 전에는 벡터 저장소에 올리지 않는다는 점을 한 줄로 덧붙인다.\n\n"
            "**7-3. 완료를 알려 오면.**\n"
            "- 붙여 넣은 `done: true` JSON이 있으면 `counts`의 건수(교정 n, 상태 표시 n, 동의어 n, 재검토 n)를 한 줄로 "
            "알리고 `beol-labeling-feedback` 스킬 절차를 이어서 따른다. 인자는 `검수 완료 <WS> run=<RUN> edits=n "
            "status=n syns=n revisits=n done_at=<시각>`이다.\n"
            "- 사용자가 \"검수 끝났어\"라고만 하면 같은 인자(건수·`done_at`은 모르면 생략)로 `beol-labeling-feedback` 스킬 "
            "절차를 따른다. 대기 명령이 아직 떠 있으면 그 터미널에서 Ctrl+C로 끄게 한다(`[M05 REVIEW_SERVE] 중단(사용자)`는 "
            "실패가 아니다)."),
    },
    "BEOL-labeling-project-html": {
        "### 3. 화면 확인 (조용히)": (
            "생성된 `docs/project_intro.html` 경로를 출력하고, 사용자가 VS Code(또는 브라우저)에서 열어 파일럿 "
            "슬라이드(id s7)와 Appendix(id sA)를 확인한다. 볼 것: 숫자 칸 6개, 와플 칸 수 = chunk 수, 게이지 두 개, "
            "잘린 칸 없음. 사용자가 이상을 알려 오면 폐쇄망에서는 코드(`render_s7`)를 고치지 않고 반출로 넘긴다. "
            "이 과정은 답변에 쓰지 않는다."),
        "### 4. 전달": "위 \"최종 출력 규칙\"대로 답변에는 두 링크만 쓴다. 사용자가 VS Code(또는 브라우저)에서 연다.",
    },
    "BEOL-labeling-workflow": {
        "### 3. 확인": (
            "생성된 `docs/workflow.html` 경로를 출력하고 사용자가 VS Code(또는 브라우저)에서 연다. 사용자에게 확인할 "
            "것을 안내한다.\n"
            "- 단계 16개, 구역 4개가 보이는지, 단계를 누르면 예시 화면과 맡은 agent가 강조되는지, 캐릭터를 누르면 그 "
            "agent의 첫 단계로 가는지.\n"
            "- 좁은 창(휴대폰 폭)에서도 페이지 가로 스크롤이 없는지(단계 레일은 원래 가로로 스크롤된다).\n"
            "- 이상이 있으면 폐쇄망에서는 템플릿·스크립트를 고치지 않고 반출로 넘긴다."),
    },
}

DESC_OVERRIDES = {
    "BEOL-labeling-RAG-html": (
        "BEOL 슬라이드 RAG 대화 화면(rag/beol_rag.html)을 로컬 정적 서버로 띄운다. 폐쇄망에서는 B6 릴리스 전까지 "
        "\"답변 서버(ragsrv) 준비 전: 화면 디자인 수정만 가능\"이고, 답변 함수 배포 단계는 없다"
        "(B6 릴리스에서 ragsrv 실행 단계로 다시 생성된다).사용자가 \"RAG 화면 띄워줘\", \"beol_rag 실행\", "
        "\"RAG html 켜줘\", \"RAG 배포\", \"edge function 배포\", \"beol-rag-ask 배포\", \"시스템 프롬프트 바꿨어 "
        "반영해줘\"라고 하면 이 스킬을 쓴다(배포 요청에는 아직 배포 단계가 없다고 안내한다)."),
}

BODY_OVERRIDES = {
    "BEOL-labeling-RAG-html": (
        "# BEOL-labeling-RAG-html\n\n"
        "> 그룹: ③ 화면 · 발표 · 운영 리포트 · 상위: 없음 · 하위: 없음 · 전체 지도: README.md \"스킬 지도\"\n\n"
        "> **답변 서버(ragsrv) 준비 전: 화면 디자인 수정만 가능.** 폐쇄망에는 B6 릴리스 전까지 답변 서버가 없다. "
        "원본 스킬의 답변 함수 배포 단계는 이 버전에 없고, B6 릴리스에서 ragsrv 실행 단계로 다시 생성된다.\n\n"
        "| 구성 | 위치 | 역할 |\n|---|---|---|\n"
        "| 화면 | `rag/beol_rag.html` | 질문 입력·답 표시. 로컬 정적 서버로 연다 |\n"
        "| 답변 서버 | B6 릴리스의 `ragsrv` | 질문 → 검색 → 답변. 지금은 없음 |\n\n"
        "## 규칙\n\n"
        "- 키는 출력하지 않는다. `rag/beol_rag.html` 안의 키 값을 답변·로그에 적지 않는다.\n"
        "- B6 전에는 화면에서 질문을 보내도 답이 오지 않는 것이 정상이다. 외부 주소로 보내는 호출을 새로 넣지 않는다.\n"
        "- 화면 디자인(HTML·CSS)만 `rag/beol_rag.html`에서 고친다. 이 파일은 업그레이드(CU) 때 상태 파일로 이어받는다. "
        "그 밖의 코드는 폐쇄망에서 고치지 않는다.\n"
        "- 본문·답변 내용은 로그에 남기지 않는다. 건수·사유 코드만 전한다.\n\n"
        "## 절차\n\n"
        "### 1. 무엇을 하려는지 가른다\n\n"
        "- 화면 모양(HTML·CSS)을 고쳤거나 보려는 것이면 2번만 한다.\n"
        "- 답변 프롬프트·검색 로직·배포 요청이면 \"답변 서버(ragsrv) 준비 전: 화면 디자인 수정만 가능\"이라고 한 줄로 "
        "알리고 끝낸다.\n\n"
        "### 2. 화면 실행\n\n"
        "정적 서버는 끝날 때까지 막히므로(" + SEP_TERMINAL + ") 사용자에게 별도 VS Code 터미널에서 실행해 달라고 "
        "안내한다.\n\n"
        "```bash\npython -m http.server 8795 --bind 127.0.0.1 --directory rag\n```\n\n"
        "- 주소 `http://127.0.0.1:8795/beol_rag.html`(프록시 뒤면 포트 패널·프록시 URL)을 출력하고 사용자가 브라우저에서 연다.\n"
        "- 8795가 이미 다른 서버(예: taxonomy 보드 서버)로 쓰이고 있으면 다른 포트로 띄운다.\n"
        "- 이 정적 서버는 마일스톤 줄을 내지 않는다(아래 \"마일스톤\").\n\n"
        "### 3. 마무리 보고\n\n"
        "한 줄씩만 전한다.\n\n"
        "- 화면: 주소와 서버 상태\n"
        "- 배포: \"답변 서버(ragsrv) 준비 전: 배포 없음\"\n\n"
        "## 하지 않는 일\n\n"
        "- 답변 함수·서버 배포, 답변 시스템 프롬프트 수정(B6 전)\n"
        "- 슬라이드 적재·임베딩: `beol-labeling-feedback` 스킬\n\n"
        "## 관계\n\n"
        "- 라벨링 실행은 `beol-labeling` 스킬, 라벨링 결과 적재는 `beol-labeling-feedback` 스킬이 맡는다.\n"),
}

# 명령에서 마일스톤을 찾지 못하는(또는 아직 줄을 내지 않는) skill
MILESTONE_OVERRIDES = {
    "BEOL-labeling-RAG-html": (
        ("ragsrv serve", "ragsrv /api/ask"),
        "B6 릴리스부터. 지금 정적 화면 서버(`python -m http.server`)는 마일스톤 줄을 내지 않는다."),
}
# 명령 없이 단계 스킬을 차례로 따르는 skill: 단계 스킬 원문의 명령으로 센다
MILESTONE_DELEGATES = {
    "BEOL-labeling-run-labeling": ("BEOL-labeling", "BEOL-labeling-feedback"),
}

# 루트 CLAUDE.md → .roo/rules/00-beol-governing.md
GOVERNING_RULES = [
    (r"^# CLAUDE\.md — BEOL AX governing rule$", "# BEOL AX governing rule (Roo)"),
    (r"서브 에이전트", "하위 작업"),
    (r"사내 파일을 Read 도구로 직접 열기", "사내 파일을 파일 읽기 도구로 직접 열기"),
    (r"`\.claude/skills/BEOL-\*`", "`.claude/skills/BEOL-*`·`.roo/skills/beol-*`"),
    (r"(?<![A-Za-z])Claude(?![A-Za-z])", "Roo"),
]
GOVERNING_APPENDIX = (
    "## 폐쇄망 운영 규칙 (Roo)\n\n"
    "- 폐쇄망에서 코드를 고치지 않는다. 코드 문제는 `CLOSED_NETWORK_RUNBOOK.md`의 반출 절차로 로컬에 넘기고 다음 "
    "릴리스로 고친다. 설정만으로 고칠 수 있는 것은 그 문서의 \"설정만으로 고칠 수 있는 것\" 표를 따른다.\n"
    "- 명령은 Roo 명령 도구로 사용자 승인 후 실행한다. 오래 걸리는 명령(라벨링·재라벨링·완료 대기·화면 서버)은 "
    + SEP_TERMINAL + ". 사용자에게 별도 VS Code 터미널에서 실행해 달라고 안내하고, 끝나면(또는 안내한 로그 줄이 "
    "보이면) 알려 달라고 한다.\n"
    "- 화면(HTML)은 Roo가 읽지 않는다. URL이나 파일 경로를 출력하고 사용자가 VS Code나 브라우저에서 연다.\n"
    "- 실패하면 터미널의 `[Mxx …] 실패` 블록과 `python -m labelbot status --workspace <작업 폴더>` 출력(Python 3.14가 "
    "없으면 `python3 tools/beol_status.py status --workspace <작업 폴더>`)으로 판단한다. 환경 문제면 "
    "`python3 tools/beol_doctor.py`.\n"
    "- `BEOL_TRACE=1`은 Roo 명령으로 실행하지 않는다(traceback이 대화 기록·사내 LLM 맥락에 들어간다). 일반 터미널에서만 "
    "켜고, 그 출력은 반출하지 않는다.\n"
    "- 저장소는 공개다. 사내 호스트·IP·키·내부 경로를 저장소 파일에 쓰지 않는다. 실제 값은 비추적 `workspaces/_site/`에만 "
    "둔다.\n"
    "- `.roo/skills/.generated.json`에 있는 skill과 이 파일은 생성물이다. 고치지 않는다.\n")


# ---- 변환 ------------------------------------------------------------------------

def _read(rel):
    with open(os.path.join(CODE_ROOT, rel), "rb") as f:
        return f.read().decode("utf-8").replace("\r\n", "\n")


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def split_frontmatter(text):
    if not text.startswith("---\n"):
        raise GenError("FRONTMATTER_MISSING")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise GenError("FRONTMATTER_MISSING")
    fm, body = text[4:end], text[end + 5:]
    meta = {}
    for line in fm.split("\n"):
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            meta[k.strip()] = unquote(v.strip())
    return meta, body


def unquote(v):
    if len(v) >= 2 and v[0] == v[-1] == "'":
        return v[1:-1].replace("''", "'")
    if len(v) >= 2 and v[0] == v[-1] == '"':
        return json.loads(v)
    return v


def replace_section(text, heading, new_body):
    """제목 줄이 정확히 heading인 절의 본문(다음 같은·상위 제목 전까지, 코드 블록 안 제외)을 바꾼다."""
    lines = text.split("\n")
    level = len(heading) - len(heading.lstrip("#"))
    try:
        start = lines.index(heading)
    except ValueError:
        raise GenError("SECTION_NOT_FOUND %s" % heading)
    end, fence = len(lines), False
    for i in range(start + 1, len(lines)):
        s = lines[i]
        if s.startswith("```"):
            fence = not fence
        if fence:
            continue
        m = re.match(r"^(#+) ", s)
        if m and len(m.group(1)) <= level:
            end = i
            break
    new = lines[:start + 1] + [""] + new_body.strip("\n").split("\n") + [""] + lines[end:]
    return "\n".join(new)


def apply_rules(orig, desc, body):
    """RULES를 설명·본문에 차례로 적용. 스킬 지정 줄은 원문에 맞아야 한다."""
    for rid, skills, pat, repl, flags in RULES:
        if skills is not None and orig not in skills:
            continue
        rx = re.compile(pat, flags)
        desc, n1 = rx.subn(repl, desc)
        body, n2 = rx.subn(repl, body)
        if skills is not None and n1 + n2 == 0:
            raise GenError("RULE_ANCHOR_MISSING %s %s" % (orig, rid))
    return desc, body


def rewrite_relative_paths(orig, body):
    """skill 폴더 기준 scripts/·assets/ 참조 → 저장소 기준 .claude/skills/<원래 이름>/…"""
    return re.sub(r"(?<![\w./-])(scripts|assets)/", ".claude/skills/%s/\\1/" % orig, body)


# 명령으로 쓴 꼴만 센다("python -m labelbot X" 또는 백틱 안 "`labelbot X`"). 산문 속 "labelbot ingest 경로"는 아니다.
_CMD_RE = re.compile(r"(?:python -m |`)(labelbot|domain_engrbot|code_engrbot) ([a-z][a-z-]*)(?: ([a-z][a-z-]*))?")
_SCRIPT_RE = re.compile(r"\.claude/skills/[A-Za-z0-9_-]+/scripts/[A-Za-z0-9_]+\.py")
_S_RE = re.compile(r"<S>/(\w+\.py)")
_ROOT_RE = re.compile(r"(?<![\w/])((?:nightly_run|daily_report)\.py)")
_TOOL_RE = re.compile(r"(?<![\w/.])(tools/\w+\.py)")


def _entry_key(bot, a, b):
    for key in (("%s %s %s" % (bot, a, b)) if b else None, "%s %s" % (bot, a)):
        if key and key in milestones.ENTRYPOINTS:
            return key
    key = "%s %s" % (bot, a)
    if any(k.startswith(key + " ") for k in milestones.ENTRYPOINTS):
        return key
    return None


def find_milestones(text):
    """본문의 명령·스크립트 → [(진입점 키, (Mxx…))], 처음 나온 순서."""
    found = []
    for m in _CMD_RE.finditer(text):
        k = _entry_key(m.group(1), m.group(2), m.group(3))
        if k:
            found.append((m.start(), k))
    for rx, fix in ((_SCRIPT_RE, None), (_S_RE, CLAUDE_SKILLS + "/BEOL-labeling/scripts/"),
                    (_ROOT_RE, ""), (_TOOL_RE, "")):
        for m in rx.finditer(text):
            k = (fix + m.group(1)) if fix is not None else m.group(0)
            if k in milestones.ENTRYPOINTS:
                found.append((m.start(), k))
    out, seen = [], set()
    for _, k in sorted(found):
        if k not in seen:
            seen.add(k)
            ids = milestones.ENTRYPOINTS[k] if k in milestones.ENTRYPOINTS else milestones.lookup(*k.split(" "))
            out.append((k, tuple(ids)))
    return out


def milestone_section(orig, body):
    if orig in MILESTONE_OVERRIDES:
        keys, note = MILESTONE_OVERRIDES[orig]
        rows = [(k, milestones.ENTRYPOINTS[k]) for k in keys]
    elif orig in MILESTONE_DELEGATES:
        subs = MILESTONE_DELEGATES[orig]
        rows = find_milestones("\n".join(split_frontmatter(_read("%s/%s/SKILL.md" % (CLAUDE_SKILLS, s)))[1]
                                         for s in subs))
        note = "명령은 단계 스킬(%s)이 낸다." % ", ".join("`%s`" % roo_name(s) for s in subs)
    else:
        rows, note = find_milestones(body), None
    if not rows:
        raise GenError("NO_MILESTONE %s" % orig)
    ids = []
    for _, ms in rows:
        ids.extend(m for m in ms if m not in ids)
    ids.sort()
    lines = ["## 마일스톤", "",
             "이 스킬의 명령은 터미널에 `[Mxx 이름] 시작·완료·실패` 줄을 낸다. 실패하면 아래 ID로 어느 단계인지 보고, "
             "`python -m labelbot codes --milestone <Mxx>`로 사유 코드와 조치를 본다.", "",
             "| 명령 | 마일스톤 |", "|---|---|"]
    for k, ms in rows:
        lines.append("| `%s` | %s |" % (k, " · ".join(milestones.label(m) for m in ms)))
    lines += ["", "담당 마일스톤: %s" % "·".join(ids)]
    if note:
        lines += ["", note]
    return "\n".join(lines) + "\n"


def check_text(label, text):
    """금지 구문·참조 경로·skill 이름 검사. 문제 목록을 돌려준다."""
    problems = []
    for tok, rx in FORBIDDEN:
        for m in rx.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            problems.append("%s:%d FORBIDDEN %s" % (label, line, tok))
    for m in re.finditer(r"\.claude/skills/[A-Za-z0-9_.-]+/(?:scripts|assets)/[A-Za-z0-9_.-]*[A-Za-z0-9_]", text):
        if not os.path.exists(os.path.join(CODE_ROOT, m.group(0))):
            problems.append("%s PATH_MISSING %s" % (label, m.group(0)))
    known = set(roo_name(n) for n in INCLUDED) | set(HANDWRITTEN)
    for m in re.finditer(r"(?<![\w-])`?(beol-[a-z0-9-]+)`? 스킬", text):
        if m.group(1) not in known:
            problems.append("%s SKILL_UNKNOWN %s" % (label, m.group(1)))
    return problems


def validate_name(name, dirname):
    if not (1 <= len(name) <= 64) or not NAME_RE.match(name) or name != dirname:
        raise GenError("NAME_INVALID %s" % name)


def _yaml_single(s):
    return "'" + s.replace("'", "''") + "'"


def build_skill(orig):
    src_rel = "%s/%s/SKILL.md" % (CLAUDE_SKILLS, orig)
    raw = _read(src_rel)
    meta, body = split_frontmatter(raw)
    if meta.get("name") != orig:
        raise GenError("SOURCE_NAME_MISMATCH %s" % orig)
    desc = DESC_OVERRIDES.get(orig, meta.get("description", ""))
    if orig in BODY_OVERRIDES:
        body = BODY_OVERRIDES[orig]
    for heading, new_body in SECTIONS.get(orig, {}).items():
        body = replace_section(body, heading, new_body)
    if orig not in DESC_OVERRIDES or orig not in BODY_OVERRIDES:
        desc, body = apply_rules(orig, desc, body)
    body = rewrite_relative_paths(orig, body)
    desc = rewrite_relative_paths(orig, desc)
    name = roo_name(orig)
    validate_name(name, name)
    desc = desc.strip()
    if not (1 <= len(desc) <= 1024):
        raise GenError("DESCRIPTION_LENGTH %s %d" % (name, len(desc)))

    milestone_text = milestone_section(orig, body)  # 머리 줄(생성기 이름)을 넣기 전 본문으로 센다
    # 머리 줄: 첫 H1 바로 뒤
    head = [HEADER.format(src=src_rel)]
    if any(h in body for h in GATED_HINTS):
        head.append(NOTE_GATED)
    lines = body.lstrip("\n").split("\n")
    if not lines or not lines[0].startswith("# "):
        raise GenError("H1_MISSING %s" % orig)
    body = "\n".join([lines[0], ""] + [x for h in head for x in (h, "")] + lines[1:]).rstrip("\n") + "\n"
    body += "\n" + milestone_text + "\n" + FAILURE_SECTION
    text = "---\nname: %s\ndescription: %s\n---\n\n%s" % (name, _yaml_single(desc), body)
    text = re.sub(r"\n{3,}", "\n\n", text)
    problems = check_text(name, text)
    if problems:
        raise GenError("\n".join(problems))
    return name, src_rel, _sha(raw), text


def build_rules():
    raw = _read(GOVERNING_SOURCE)
    text = raw
    for pat, repl in GOVERNING_RULES:
        text = re.sub(pat, repl, text, flags=re.M)
    lines = text.split("\n")
    lines = [lines[0], "", HEADER.format(src=GOVERNING_SOURCE)] + lines[1:]
    text = "\n".join(lines).rstrip("\n") + "\n\n" + GOVERNING_APPENDIX
    text = re.sub(r"\n{3,}", "\n\n", text)
    problems = check_text(ROO_RULES, text)
    if problems:
        raise GenError("\n".join(problems))
    return text, _sha(raw)


def build_all():
    """{저장소 기준 경로: 내용}. 원본 skill 폴더 목록과 INCLUDED·EXCLUDED가 맞는지도 본다."""
    src_dir = os.path.join(CODE_ROOT, CLAUDE_SKILLS)
    present = sorted(d for d in os.listdir(src_dir) if os.path.isfile(os.path.join(src_dir, d, "SKILL.md")))
    unknown = sorted(set(present) - set(INCLUDED) - set(EXCLUDED))
    missing = sorted(set(INCLUDED) - set(present))
    if unknown or missing:
        raise GenError("SKILL_SET_CHANGED unknown=%s missing=%s" % (",".join(unknown), ",".join(missing)))
    if set(roo_name(n) for n in INCLUDED) & set(HANDWRITTEN):
        raise GenError("NAME_COLLISION")
    files, manifest = {}, {"generator": "tools/gen_roo_skills.py", "generator_version": GENERATOR_VERSION,
                           "skills": {}, "rules": {}, "excluded": EXCLUDED}
    for orig in INCLUDED:
        name, src_rel, sha, text = build_skill(orig)
        files["%s/%s/SKILL.md" % (ROO_SKILLS, name)] = text
        manifest["skills"][name] = {"source": src_rel, "source_sha256": sha, "generator_version": GENERATOR_VERSION}
    rules_text, rules_sha = build_rules()
    files[ROO_RULES] = rules_text
    manifest["rules"][ROO_RULES] = {"source": GOVERNING_SOURCE, "source_sha256": rules_sha,
                                    "generator_version": GENERATOR_VERSION}
    files[MANIFEST] = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return files


def _stale_generated(files):
    """예전 .generated.json에는 있었지만 이번에 만들지 않는 skill 폴더(지워야 할 것)."""
    path = os.path.join(CODE_ROOT, MANIFEST)
    if not os.path.isfile(path):
        return []
    try:
        old = json.loads(_read(MANIFEST)).get("skills", {})
    except ValueError:
        return []
    return sorted("%s/%s/SKILL.md" % (ROO_SKILLS, n) for n in old
                  if "%s/%s/SKILL.md" % (ROO_SKILLS, n) not in files)


def _current(rel):
    path = os.path.join(CODE_ROOT, rel)
    return _read(rel) if os.path.isfile(path) else None


def cmd_check(files):
    drift = [rel for rel, text in sorted(files.items()) if _current(rel) != text]
    drift += ["%s (stale)" % rel for rel in _stale_generated(files)]
    for rel in drift:
        print("[gen-roo] DRIFT %s" % rel)
    print(json.dumps({"check": "drift" if drift else "ok", "files": len(files), "drift": len(drift)}))
    return 1 if drift else 0


def cmd_write(files):
    written = 0
    for rel in _stale_generated(files):
        os.remove(os.path.join(CODE_ROOT, rel))
        written += 1
    for rel, text in sorted(files.items()):
        if _current(rel) == text:
            continue
        path = os.path.join(CODE_ROOT, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        written += 1
    print(json.dumps({"generated": len(INCLUDED), "rules": 1, "files": len(files), "written": written}))
    return 0


def _main(argv):
    ap = argparse.ArgumentParser(prog="gen_roo_skills", description="Roo Code skill·rules 생성(M25, 로컬 전용)")
    ap.add_argument("--check", action="store_true", help="다시 만들어 저장소 파일과 비교만 한다(차이 있으면 종료 1)")
    args = ap.parse_args(argv)
    try:
        files = build_all()
    except GenError as e:
        print("[오류] %s" % e, file=sys.stderr)
        return 2
    return cmd_check(files) if args.check else cmd_write(files)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    try:
        from labelbot import trace
    except (ImportError, SyntaxError):
        trace = None
    if trace is None or not hasattr(trace, "run_main"):
        return _main(argv)
    return trace.run_main(MILESTONE, lambda: _main(argv), argv)


if __name__ == "__main__":
    sys.exit(main())
