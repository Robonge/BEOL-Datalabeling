"""QM7·QM8 테스트용 실행 결과 만들기. 합성 fixture에 결함을 심고 runner.execute(L1, L2, L3A)로 판정한다.

작업 폴더는 tempfile.mkdtemp()로 코드 폴더 밖에 만든다. 판정은 실제 검사가 낸다(심은 결함 → REVIEW, REJECT, AUTO_FIX).
"""
import os
import shutil
import tempfile

from engrbot import io, model, runner
from engrbot import policy as policy_mod
from engrbot import synthetic

LAYERS = ["L1", "L2", "L3A"]
QA_RUN_ID = "QA-20261004T010203-0a0b"
MISSING_QUOTE = "본문 어디에도 없는 인용 문장을 일부러 넣었다"
_ROOTS = []


def _value_axis(rec):
    for name in sorted(rec["axes"]):
        if rec["axes"][name]["status"] == "value":
            return name
    return None


def _swapcase_target(rec, tax):
    for name in sorted(rec["axes"]):
        a = rec["axes"][name]
        if a["status"] != "value":
            continue
        for i, v in enumerate(a["values"]):
            m = v.lower() if v.lower() != v else v.upper()
            if m != v and tax.canonical_value(name, m) == v:
                return name, i, m
    return None


def scenario(seed=7, n_files=12, policy_over=None, qa_run_id=QA_RUN_ID, root=None, prepare=None):
    """반환: (RunResult, fixture, roles). roles: review, review_human, reject, autofix_case, autofix_date."""
    fx = synthetic.generate(seed=seed, n_files=n_files)
    b = fx.bundle
    tax = model.TaxIndex(b.taxonomy)
    content = sorted((r for r in b.records if r["chunk_type"] == "내용"), key=lambda r: r["record_id"])
    used = set()
    roles = {"review": [], "review_human": None, "reject": [], "autofix_case": [], "autofix_date": []}

    def take(pred, n):
        out = []
        for r in content:
            if len(out) == n:
                break
            if r["record_id"] not in used and pred(r):
                used.add(r["record_id"])
                out.append(r)
        return out

    for r in take(lambda r: _value_axis(r), 3):
        r["duplicate_fields"] = ["axis:%s" % _value_axis(r)]
        roles["review"].append(r["record_id"])
    for r in take(lambda r: _value_axis(r), 1):
        r["duplicate_fields"] = ["axis:%s" % _value_axis(r)]
        r["human_reviewed"] = True
        roles["review_human"] = r["record_id"]
    for r in take(lambda r: _value_axis(r), 2):
        r["axes"][_value_axis(r)]["evidence"]["quote"] = MISSING_QUOTE
        roles["reject"].append(r["record_id"])
    for r in take(lambda r: _swapcase_target(r, tax) is not None and not r["extracted"], 2):
        name, i, m = _swapcase_target(r, tax)
        r["axes"][name]["values"][i] = m
        roles["autofix_case"].append(r["record_id"])
    for r in take(lambda r: any(e["item"] == "date" for e in r["extracted"]), 3):
        for e in r["extracted"]:
            if e["item"] == "date":
                y, mo, d = e["value"].split("-")
                e["value"] = "%s.%d.%d" % (y, int(mo), int(d))
        roles["autofix_date"].append(r["record_id"])
    if prepare:
        prepare(b, roles)
    pol = policy_mod.validate_policy(policy_over or {})
    sch = policy_mod.validate_schema({})
    if root is None:
        root = tempfile.mkdtemp(prefix="engrbot_qm78_")
        _ROOTS.append(root)
    paths = io.QaPaths(root)
    res = runner.execute(b, pol, sch, paths=paths, qa_run_id=qa_run_id, layers=LAYERS)
    res.run_dir = paths.run_dir(qa_run_id, create=True)
    res.log = io.Logger(paths.log_path)
    return res, fx, roles


def inject(res, record_id, code, field, reason=None):
    """판정 dict에 이슈를 더하고 판정·점수를 다시 계산한다(L3B 등 이 테스트에서 돌리지 않는 층의 이슈)."""
    v = res.verdict_map()[record_id]
    v["issues"].append(model.issue(code, field=field, reason=reason))
    v["issues"].sort(key=model.issue_sort_key)
    v["verdict"], v["score"] = model.decide(v["issues"], res.policy)


def decisions_doc(qa_run_id, decisions=(), rejects=(), autofix=(), props=()):
    """검토 화면 buildOutput()과 같은 형식(4.5절)."""
    return {"kind": "qa_decisions", "qa_run_id": qa_run_id, "reviewer": "tester",
            "decisions": list(decisions), "reject_decisions": list(rejects),
            "autofix_decisions": list(autofix), "proposal_decisions": list(props)}


def put_inbox(res, doc, name="qa_decisions.json"):
    path = os.path.join(res.paths.inbox, name)
    io.write_json(path, doc)
    return path


def read_log(res):
    if not os.path.isfile(res.paths.log_path):
        return ""
    with open(res.paths.log_path, encoding="utf-8") as f:
        return f.read()


def cleanup():
    """scenario()가 만든 임시 작업 폴더를 지운다."""
    while _ROOTS:
        shutil.rmtree(_ROOTS.pop(), ignore_errors=True)
