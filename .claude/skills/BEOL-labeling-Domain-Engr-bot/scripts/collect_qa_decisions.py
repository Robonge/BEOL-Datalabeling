"""검토 화면(review.html)의 결정 파일 qa_decisions_<QA>.json을 찾는다.

- `domain_engrbot serve`로 연 화면은 검수 완료 때 작업 폴더 qa/inbox/에 바로 쓴다. 이 파일은 where="inbox" 후보로
  맨 앞에 나오고, --pick으로 골라도 옮기지 않는다(이미 제자리).
- 파일로 연 화면(또는 서버 저장 실패)은 내려받기 폴더에 쓴다. 이 파일은 where="downloads" 후보이고,
  --pick으로 고르면 qa/inbox/로 옮긴다.

사용:
  python collect_qa_decisions.py --workspace "<WS>" [--qa-run <QA>] [--downloads <폴더>]          # 후보 목록만
  python collect_qa_decisions.py --workspace "<WS>" [--qa-run <QA>] --pick "<파일 이름>" [--where inbox]  # 고름(내려받기면 옮김)

- --qa-run이 없으면 작업 폴더 qa/runs/에서 가장 최근 검수 실행을 쓴다.
- 내려받기 후보는 이 검수 실행의 결정 파일(qa_decisions_<QA>.json, 브라우저가 붙인 " (1)" 같은 접미 포함)이다.
- 출력은 JSON 한 줄이고 건수·이름·시각만 담는다. 결정 파일의 값·근거 인용은 출력하지 않는다.
- 옮긴 파일 이름은 qa_decisions_<QA>.json이고, 이미 있으면 _<시각>을 붙인다(golden·feedback은 가장 최근 파일을 쓴다).
"""
import argparse
import datetime
import glob
import json
import os
import re
import shutil
import sys

KIND = "qa_decisions"


def latest_qa_run(ws):
    runs = [os.path.basename(p) for p in glob.glob(os.path.join(ws, "qa", "runs", "QA-*")) if os.path.isdir(p)]
    return max(runs) if runs else None


def read_doc(path):
    with open(path, encoding="utf-8-sig") as f:  # 화면이 쓴 결정 JSON(사내 파일 아님)
        return json.loads(f.read())


def summarize(path, qa_run):
    """결정 파일 → 건수만 담은 dict. 형식이 맞지 않으면 reason에 사유 코드."""
    st = os.stat(path)
    info = {"name": os.path.basename(path), "saved_at": datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "mtime": st.st_mtime, "size": st.st_size, "reason": None}
    try:
        doc = read_doc(path)
    except (OSError, ValueError, UnicodeDecodeError):
        info["reason"] = "DECISIONS_JSON_INVALID"
        return info
    if not isinstance(doc, dict) or doc.get("kind") != KIND or not isinstance(doc.get("decisions"), list):
        info["reason"] = "DECISIONS_FORMAT_INVALID"
        return info
    if doc.get("qa_run_id") != qa_run:
        info["reason"] = "DECISIONS_OTHER_RUN"
    n = {}
    for d in doc["decisions"]:
        if isinstance(d, dict):
            n[d.get("decision")] = n.get(d.get("decision"), 0) + 1
    info["counts"] = {"confirm": n.get("confirm", 0), "correct": n.get("correct", 0), "cannot_judge": n.get("cannot_judge", 0),
                      "reject_decisions": len(doc.get("reject_decisions") or []),
                      "autofix_decisions": len(doc.get("autofix_decisions") or []),
                      "proposal_decisions": len(doc.get("proposal_decisions") or [])}
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--qa-run")
    ap.add_argument("--downloads", default=os.path.join(os.path.expanduser("~"), "Downloads"))
    ap.add_argument("--pick", help="고를 파일 이름(목록에 나온 name)")
    ap.add_argument("--where", choices=("downloads", "inbox"), default="downloads",
                    help="--pick 파일의 위치(목록에 나온 where). inbox면 옮기지 않는다")
    a = ap.parse_args()
    ws = os.path.abspath(a.workspace)
    qa = a.qa_run or latest_qa_run(ws)
    if not qa or not os.path.isdir(os.path.join(ws, "qa", "runs", qa)):
        print(json.dumps({"error": "QA_RUN_NOT_FOUND", "qa_run_id": qa}, ensure_ascii=False))
        return 1
    screen = os.path.join(ws, "qa", "runs", qa, "review.html")
    screen_mtime = os.path.getmtime(screen) if os.path.isfile(screen) else 0
    pat = re.compile(r"^qa_decisions_%s( ?\(\d+\))?\.json$" % re.escape(qa), re.I)
    inbox = os.path.join(ws, "qa", "inbox")
    in_inbox = os.path.join(inbox, "qa_decisions_%s.json" % qa)
    cands = [dict(summarize(in_inbox, qa), where="inbox")] if os.path.isfile(in_inbox) else []
    names = [n for n in os.listdir(a.downloads) if pat.match(n)] if os.path.isdir(a.downloads) else []
    cands += sorted((dict(summarize(os.path.join(a.downloads, n), qa), where="downloads") for n in names),
                    key=lambda x: -x["mtime"])
    for c in cands:
        c["after_screen"] = c["mtime"] >= screen_mtime
        del c["mtime"]
    if not a.pick:
        print(json.dumps({"qa_run_id": qa, "inbox": len(cands) - len(names), "downloads": len(names),
                          "candidates": cands}, ensure_ascii=False))
        return 0
    where = "inbox" if a.where == "inbox" else "downloads"
    chosen = next((c for c in cands if c["name"] == a.pick and c["where"] == where), None)
    if chosen is None:
        print(json.dumps({"error": "PICK_NOT_FOUND", "qa_run_id": qa}, ensure_ascii=False))
        return 1
    if chosen["reason"]:
        print(json.dumps({"error": chosen["reason"], "qa_run_id": qa}, ensure_ascii=False))
        return 1
    if where == "inbox":
        print(json.dumps({"qa_run_id": qa, "kept": chosen["name"], "counts": chosen["counts"]}, ensure_ascii=False))
        return 0
    os.makedirs(inbox, exist_ok=True)
    dest = os.path.join(inbox, "qa_decisions_%s.json" % qa)
    if os.path.exists(dest):
        dest = os.path.join(inbox, "qa_decisions_%s_%s.json" % (qa, datetime.datetime.now().strftime("%Y%m%d-%H%M%S")))
    shutil.move(os.path.join(a.downloads, a.pick), dest)
    print(json.dumps({"qa_run_id": qa, "moved": os.path.basename(dest), "counts": chosen["counts"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
