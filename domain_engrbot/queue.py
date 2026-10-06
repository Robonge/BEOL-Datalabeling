"""검토 대기열(review_queue.jsonl)과 재작업 지시(rework.jsonl). 둘 다 작업 폴더 전용이다(4.6절).

- 대기열: REVIEW 레코드 중 사람이 이미 교정·확인하지 않은 것(human_reviewed=false)만 넣는다(A13).
- 우선순위: 1 = record 범위 major 이슈가 있다(라벨 판단이 필요하다), 2 = file 범위 major 이슈만 있다(파일별로 묶어 본다),
  3 = fail-safe 이슈(judge 미실행·실패)만 있다(오류가 탐지된 것이 아니다). 정렬은 (우선순위, 점수, 파일 ID, 레코드 ID)다.
- 재작업: REJECT 레코드 중 human_reviewed=false인 것. 이슈마다 필드, 코드, 사유, 근거, 고칠 방법을 담는다(critical·major).
"""
from domain_engrbot import codes, io

ROUTED_SEVERITIES = ("critical", "major")


def _routed(issues):
    return [i for i in issues if i["severity"] in ROUTED_SEVERITIES]


def priority(verdict):
    issues = _routed(verdict["issues"])
    if any(i["scope"] == "record" and not codes.is_fail_safe(i["code"]) for i in issues):
        return 1
    if any(i["scope"] == "file" for i in issues):
        return 2
    return 3


def _group(run, record_id):
    return ((run.bundle.units or {}).get(record_id) or {}).get("dup_group") if run.bundle else None


def queue_row(run, v):
    issues = _routed(v["issues"])
    return {
        "record_id": v["record_id"],
        "file_id": v["file_id"],
        "priority": priority(v),
        "score": v["score"],
        "issue_codes": sorted({i["code"] for i in issues}),
        "fields": sorted({i["field"] for i in issues if i.get("field")}),
        "group": _group(run, v["record_id"]),
    }


def rework_row(run, v):
    include_text = run.policy["output"]["include_text"]
    out = []
    for i in _routed(v["issues"]):
        item = {"code": i["code"], "severity": i["severity"], "field": i.get("field"), "reason": i.get("reason"),
                "evidence": i.get("evidence") or {}, "suggested_fix": i.get("suggested_fix")}
        out.append(item if include_text else io.strip_text(item))
    return {"record_id": v["record_id"], "file_id": v["file_id"], "labeler_run_id": v.get("labeler_run_id"),
            "score": v["score"], "issues": out}


def build(run):
    """파일을 쓰지 않고 (대기열 행, 재작업 행)을 돌려준다. 검토 화면도 이 순서를 쓴다."""
    queue_rows, rework_rows = [], []
    for v in run.verdicts:
        if v.get("human_reviewed"):
            continue
        if v["verdict"] == "REVIEW":
            queue_rows.append(queue_row(run, v))
        elif v["verdict"] == "REJECT":
            rework_rows.append(rework_row(run, v))
    queue_rows.sort(key=lambda r: (r["priority"], r["score"], r["file_id"] or "", r["record_id"]))
    rework_rows.sort(key=lambda r: r["record_id"])
    return queue_rows, rework_rows


def write(run):
    """review_queue.jsonl, rework.jsonl을 쓴다. 반환: (대기열 행, 재작업 행)."""
    queue_rows, rework_rows = build(run)
    io.write_jsonl(run.path("review_queue.jsonl"), queue_rows)
    io.write_jsonl(run.path("rework.jsonl"), rework_rows)
    return queue_rows, rework_rows
