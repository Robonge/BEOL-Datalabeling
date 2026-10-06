"""검사 실행, severity 덮어쓰기, 억제, 정렬, 판정."""
from code_engrbot import model, registry, scan

_ORDER = {s: i for i, s in enumerate(model.SEVERITIES)}


def _allowed_by_policy(finding, allow):
    for entry in allow or []:
        if entry.get("rule") != finding["rule"]:
            continue
        pat = entry.get("path")
        if pat is None or pat == finding["path"] or scan.match(finding["path"], pat):
            return True
    return False


def _run_checks(index, ctx, layers):
    raw = []
    errors = []
    for chk in registry.checks():
        if layers is not None and chk.layer not in layers:
            continue
        targets = index.files if chk.scope == "file" else [index]
        for target in targets:
            try:
                raw.extend(chk.run(target, ctx) or [])
            except Exception as e:  # 검사 하나의 실패가 전체를 죽이지 않게 한다
                where = getattr(target, "path", "<repo>")
                errors.append({"check": type(chk).__name__, "layer": chk.layer, "path": where,
                               "error": type(e).__name__})
    return raw, errors


def run(index, ctx, layers=None):
    """→ {"findings", "verdict", "counts", "errors"}. errors는 예외를 낸 검사의 기록이다."""
    layers = list(layers) if layers else None
    raw, errors = _run_checks(index, ctx, layers)
    overrides = ctx.policy.get("severity_overrides") or {}
    allow = ctx.policy.get("allow") or []
    findings = []
    for f in raw:
        f = dict(f)
        sev = overrides.get(f["rule"])
        if sev in model.SEVERITIES:
            f["severity"] = sev
        src = index.get(f["path"])
        if src is not None and src.allowed(f["rule"], f.get("line")):
            f["suppressed"] = True
        elif _allowed_by_policy(f, allow):
            f["suppressed"] = True
        findings.append(f)
    findings.sort(key=lambda f: (f["suppressed"], _ORDER.get(f["severity"], 99), f["path"], f.get("line") or 0, f["rule"]))
    counts = {s: 0 for s in model.SEVERITIES}
    counts["suppressed"] = 0
    for f in findings:
        if f["suppressed"]:
            counts["suppressed"] += 1
        else:
            counts[f["severity"]] += 1
    verdict = model.decide(findings)
    if errors and verdict == "APPROVE":
        verdict = "COMMENT"  # 검사 오류가 있으면 통과로 보지 않는다
    return {"findings": findings, "verdict": verdict, "counts": counts, "errors": errors}
