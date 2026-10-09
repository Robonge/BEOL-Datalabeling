"""마일스톤 등록부와 진입점 표(L3c). 폐쇄망 터미널에서 "어느 단계가" 실패했는지 가리키는 고정 ID.

- ID는 계약이다(Roo skill 문구·런북·반출 status가 참조한다): **추가만** 하고 재번호·재사용하지 않는다.
  tests/contracts/snapshots/milestone_ids.json이 앞부분이 그대로인지(늘어나기만 하는지) 검사한다.
- ENTRYPOINTS: 명령·스크립트 → 마일스톤 ID들. 테스트가 모든 argparse 하위 명령과 스크립트 main을 덮는지 검사한다.
- Python 3.8 문법·표준 라이브러리만 쓰고 다른 labelbot 모듈을 import하지 않는다(배포판 python3의
  tools/beol_status.py가 이 모듈을 읽는다).
"""

# (ID, 이름, 한 줄 설명). 순서 = 번호 순서. 끝에만 덧붙인다.
MILESTONES = (
    ("M00", "ENV/CLI", "환경 점검·명령 진입(읽기 전용 목록·요약 포함)"),
    ("M01", "INGEST", "입력 폴더 수집·DRM 확인·파싱·chunk"),
    ("M02", "CLASSIFY", "1차 분류(LLM, taxonomy 축)"),
    ("M03", "LABEL", "2차 질문 매핑·생성과 3차 라벨링(LLM)"),
    ("M04", "REPORT", "알림·불량 목록·후보·산출물·리포트·화면 생성"),
    ("M05", "REVIEW_SERVE", "검수 화면 서버와 검수 완료 대기"),
    ("M06", "FEEDBACK_APPLY", "inbox 교정·대조 JSON 반영"),
    ("M07", "EMBED", "chunk 임베딩(임베딩 API)"),
    ("M08", "PUSH_VECTORS", "벡터 저장소 적재"),
    ("M09", "SLIDE_IMAGES", "슬라이드 미리보기 JPG 렌더(chromium)"),
    ("M10", "PUSH_SLIDES", "슬라이드 JPG를 저장소에 올리기"),
    ("M11", "DOMAIN_QA", "Domain-Engr-bot 장부·규칙 후보·도메인 질문"),
    ("M12", "TAXONOMY_BOARD", "taxonomy 수정 보드·편집기·변환"),
    ("M13", "RULES_UPDATE", "라벨링 규칙 변경분 재라벨링"),
    ("M14", "AXIS_UPDATE", "taxonomy 축 변경분 재라벨링"),
    ("M15", "RAG_SERVE", "RAG 대화 화면 서버"),
    ("M16", "RAG_ASK", "RAG 답변 요청(/api/ask)"),
    ("M17", "BACKUP", "벡터·작업 DB 백업과 복원 리허설"),
    ("M18", "NIGHTLY_REPORT", "야간 실행과 daily report"),
    ("M19", "IMPORT", "반입 확인·상태 이어받기·경로 변환"),
    ("M20", "CODE_REVIEW", "Code-Engr-bot 코드 검수"),
    ("M21", "PROJECT_HTML", "프로젝트 소개 HTML 생성"),
    ("M22", "WORKFLOW_HTML", "workflow HTML 생성"),
    ("M23", "DIFF_CHECK", "taxonomy·규칙 변경 점검(읽기)"),
    ("M24", "WORKSPACE_INIT", "작업 폴더 만들기·중복 확인"),
    ("M25", "RELEASE_TOOLS", "릴리스 도구(manifest·push 전 검사·Roo skill 생성, 로컬 전용)"),
    ("M26", "RAG_EVAL", "RAG 검색·답변 평가"),
    ("M27", "ORIGINALS_SYNC", "원본 .b64를 S3에 동기화"),
)

NAMES = dict((mid, name) for mid, name, _ in MILESTONES)
DESCRIPTIONS = dict((mid, desc) for mid, _, desc in MILESTONES)
IDS = tuple(mid for mid, _, _ in MILESTONES)

_SKILLS = ".claude/skills/"

# 진입점 → 마일스톤 ID들. 키는 "<패키지> <하위 명령…>" 또는 저장소 기준 스크립트 경로.
# labelbot run은 run_all의 네 경계(M01–M04)가 각각 줄을 낸다(CLI 줄 없음, 실패만 M01로 받는다).
ENTRYPOINTS = {
    # labelbot (python -m labelbot <명령>)
    "labelbot selfcheck": ("M00",),
    "labelbot probe": ("M00",),
    "labelbot ingest": ("M01",),
    "labelbot run": ("M01", "M02", "M03", "M04"),
    "labelbot compare": ("M04",),
    "labelbot review": ("M04",),
    "labelbot report": ("M04",),
    "labelbot dashboard": ("M04",),
    "labelbot serve": ("M05",),
    "labelbot apply": ("M06",),
    "labelbot embed": ("M07",),
    "labelbot push-vectors": ("M08",),
    "labelbot slide-images": ("M09",),
    "labelbot push-slides": ("M10",),
    "labelbot taxonomy-migrate": ("M12",),
    "labelbot rules-update": ("M13",),
    "labelbot rules-board": ("M13",),
    "labelbot axis-update": ("M14",),
    "labelbot axis-board": ("M14",),
    "labelbot taxonomy-diff": ("M23",),
    "labelbot rules-diff": ("M23",),
    "labelbot status": ("M00",),
    "labelbot codes": ("M00",),
    # domain_engrbot (python -m domain_engrbot <명령>)
    "domain_engrbot run": ("M11",),
    "domain_engrbot report": ("M11",),
    "domain_engrbot baseline set": ("M11",),
    "domain_engrbot review": ("M11",),
    "domain_engrbot serve": ("M11",),
    "domain_engrbot golden add": ("M11",),
    "domain_engrbot feedback": ("M11",),
    "domain_engrbot eval": ("M11",),
    "domain_engrbot intake": ("M11",),
    "domain_engrbot ledger": ("M11",),
    "domain_engrbot labeling-rules": ("M11",),
    "domain_engrbot questions": ("M11",),
    "domain_engrbot taxonomy-board": ("M12",),
    "domain_engrbot taxonomy-editor": ("M12",),
    "domain_engrbot workspaces": ("M00",),
    "domain_engrbot codes": ("M00",),
    # code_engrbot
    "code_engrbot review": ("M20",),
    "code_engrbot rules": ("M20",),
    # skill 스크립트(.claude/skills/*/scripts/*.py). serve_screens.py는 labelbot serve를 그대로 부른다.
    _SKILLS + "BEOL-labeling/scripts/init_workspace.py": ("M24",),
    _SKILLS + "BEOL-labeling/scripts/serve_screens.py": ("M05",),
    _SKILLS + "BEOL-labeling/scripts/record_ingested.py": ("M01",),
    _SKILLS + "BEOL-labeling/scripts/summary.py": ("M00",),
    _SKILLS + "BEOL-labeling-feedback/scripts/wait_review_done.py": ("M05",),
    _SKILLS + "BEOL-labeling-feedback/scripts/collect_inbox.py": ("M06",),
    _SKILLS + "BEOL-labeling-Domain-Engr-bot/scripts/collect_qa_decisions.py": ("M11",),
    _SKILLS + "BEOL-labeling-project-html/scripts/build_project_html.py": ("M21",),
    _SKILLS + "BEOL-labeling-workflow/scripts/build_workflow.py": ("M22",),
    # tools/ (아직 없는 도구도 계획된 ID를 미리 둔다)
    "tools/beol_doctor.py": ("M00",),
    "tools/beol_status.py": ("M00",),
    "tools/cloud_migrate_paths.py": ("M19",),
    "tools/verify_import.py": ("M19",),
    "tools/carry_state.py": ("M19",),
    "tools/gen_roo_skills.py": ("M25",),
    "tools/make_import_manifest.py": ("M25",),
    "tools/prepush_scan.py": ("M25",),
    "tools/rag_eval.py": ("M26",),
    "tools/s3_sync_originals.py": ("M27",),
    "tools/vector_backup.py": ("M17",),
    "tools/vector_restore.py": ("M17",),
    "tools/site_init.py": ("M00",),
    # 저장소 루트 스크립트
    "nightly_run.py": ("M18",),
    "daily_report.py": ("M18",),
    # B6 이후(ragsrv). 그 전 폐쇄망 RAG 화면은 정적 http.server라 마일스톤이 없다.
    "ragsrv serve": ("M15",),
    "ragsrv /api/ask": ("M16",),
}

# 읽기 전용 목록·요약: 시작·완료 줄 없이 실패 블록만 낸다(M00 CLI).
QUIET = frozenset((
    "labelbot status", "labelbot codes", "domain_engrbot workspaces", "domain_engrbot codes",
    "tools/beol_status.py", _SKILLS + "BEOL-labeling/scripts/summary.py",
))

# 실패 블록을 스스로 내는 진입점(labelbot.trace로 감싸지 않는다): beol_doctor는 3.8·labelbot 무관,
# verify_import·carry_state·make_import_manifest·prepush_scan은 trace.fail_block을 직접 부른다.
SELF_REPORTING = frozenset((
    "tools/beol_doctor.py", "tools/verify_import.py", "tools/carry_state.py",
    "tools/make_import_manifest.py", "tools/prepush_scan.py",
))

# work.sqlite failures.stage → 마일스톤(status가 대상별 실패를 마일스톤에 붙인다). stage 문자열은 계약이다.
STAGE_MILESTONE = {
    "ingest": "M01", "parse": "M01",
    "classify": "M02",
    "question_gen": "M03", "question_ctl": "M03", "label": "M03", "extract": "M03",
    "relabel": "M13",
    "embed": "M07",
    "push": "M08",
    "slide_image": "M09",
    "push_slides": "M10",
}

# runs.command → 끝난 실행이 ✔로 보이는 마일스톤(milestones.jsonl이 없는 옛 실행용).
RUN_COMMAND_MILESTONES = {
    "run": ("M01", "M02", "M03", "M04"),
    "ingest": ("M01",),
    "axis-update": ("M14",),
    "rules-update": ("M13",),
}


def name(mid):
    return NAMES.get(mid, "?")


def label(mid):
    """'[M07 EMBED]'에 들어가는 'M07 EMBED'."""
    return "%s %s" % (mid, name(mid))


def lookup(*path):
    """진입점 경로('labelbot', 'embed') → 마일스톤 ID 튜플. 하위 명령의 부모(예: domain_engrbot baseline)는
    그 아래 진입점의 마일스톤을 쓴다. 없으면 KeyError."""
    key = " ".join(p for p in path if p)
    if key in ENTRYPOINTS:
        return ENTRYPOINTS[key]
    children = [v for k, v in ENTRYPOINTS.items() if k.startswith(key + " ")]
    if children:
        return children[0]
    raise KeyError(key)


def is_quiet(*path):
    return " ".join(p for p in path if p) in QUIET
