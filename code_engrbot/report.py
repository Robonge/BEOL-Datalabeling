"""리포트 3개(findings.jsonl, review.md, manifest.json)와 규칙 카탈로그를 쓴다."""
import datetime
import hashlib
import json
import os
import platform
import secrets

from code_engrbot import model, registry

DEFAULT_OUT = os.path.join("code_engrbot", "out")


def new_review_id(now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return "CR-%s-%s" % (now.strftime("%Y%m%dT%H%M%S"), secrets.token_hex(2))


def catalog_hash():
    blob = json.dumps(registry.all_rules(), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _md(review_id, result):
    c = result["counts"]
    lines = ["# code_engrbot 검수 %s" % review_id, "",
             "- 판정: %s" % result["verdict"],
             "- critical %d, major %d, minor %d, info %d, 억제 %d" % (
                 c["critical"], c["major"], c["minor"], c["info"], c["suppressed"]), ""]
    live = [f for f in result["findings"] if not f["suppressed"]]
    for sev in model.SEVERITIES:
        group = [f for f in live if f["severity"] == sev]
        if not group:
            continue
        lines += ["## %s (%d)" % (sev, len(group)), ""]
        for f in group:
            lines.append("- `%s:%s` `%s` %s" % (f["path"], f.get("line") or 0, f["rule"], f["message"]))
            if f.get("suggested_fix"):
                lines.append("  - 수정 제안: %s" % f["suggested_fix"])
        lines.append("")
    if result.get("errors"):
        lines += ["## 검사 실행 오류 (%d)" % len(result["errors"]), ""]
        for e in result["errors"]:
            lines.append("- %s %s `%s` %s" % (e["layer"], e["check"], e["path"], e["error"]))
        lines.append("")
    lines += ["## 억제", "", "- 억제된 finding %d건 (줄 주석 또는 정책 allow)" % c["suppressed"], ""]
    return "\n".join(lines)


def write(out_dir, result, targets, layers, now=None):
    """<out_dir>/<review_id>/ 아래에 리포트 3개만 쓴다. (review_id, 폴더)를 낸다."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    review_id = new_review_id(now)
    folder = os.path.join(out_dir, review_id)
    os.makedirs(folder, exist_ok=True)
    rows = "".join(json.dumps(f, ensure_ascii=False, sort_keys=True) + "\n" for f in result["findings"])
    _write(os.path.join(folder, "findings.jsonl"), rows)
    _write(os.path.join(folder, "review.md"), _md(review_id, result))
    manifest = {
        "review_id": review_id,
        "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "targets": list(targets),
        "layers": list(layers),
        "counts": result["counts"],
        "verdict": result["verdict"],
        "check_errors": len(result.get("errors") or []),
        "policy_version": result.get("policy_version"),
        "rules_hash": catalog_hash(),
        "python": platform.python_version(),
    }
    _write(os.path.join(folder, "manifest.json"), json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return review_id, folder


def rules_markdown():
    lines = ["# code_engrbot 규칙 카탈로그", "", "`python -m code_engrbot rules`로 만든다. 직접 고치지 않는다.", "",
             "| 규칙 | 층 | severity | 설명 |", "|---|---|---|---|"]
    for rule, meta in sorted(registry.all_rules().items()):
        lines.append("| `%s` | %s | %s | %s |" % (rule, meta["layer"], meta["severity"], meta["desc"].replace("|", "/")))
    return "\n".join(lines) + "\n"


def write_rules(path):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    _write(path, rules_markdown())
