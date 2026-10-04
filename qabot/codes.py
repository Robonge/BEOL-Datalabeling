"""issue code 카탈로그(defaults/issue_codes.json) 읽기와 사람용 문서 생성."""
import json
import os

from qabot import model

PKG_ROOT = os.path.dirname(os.path.abspath(__file__))
CATALOG_PATH = os.path.join(PKG_ROOT, "defaults", "issue_codes.json")
DOC_PATH = os.path.join(PKG_ROOT, "docs", "issue_codes.md")

_cache = {}


def catalog():
    if "cat" not in _cache:
        with open(CATALOG_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        _cache["raw"] = raw
        _cache["cat"] = raw["codes"]
        _cache["hash"] = model.hash_obj(raw)
    return _cache["cat"]


def catalog_hash():
    catalog()
    return _cache["hash"]


def get(code):
    try:
        return catalog()[code]
    except KeyError:
        raise KeyError("UNKNOWN_ISSUE_CODE:%s" % code)


def allowed_severities(code):
    c = get(code)
    return c.get("severities") or [c["severity"]]


def is_fail_safe(code):
    return bool(get(code).get("fail_safe"))


def effect(severity, policy=None):
    mapping = (policy or {}).get("verdict", {}).get("severity_to_verdict") or model.DEFAULT_SEVERITY_TO_VERDICT
    v = mapping.get(severity, "PASS")
    return "리포트에만" if severity == "info" and v == "PASS" else v


def render_md():
    """사람용 카탈로그. 손으로 고치지 않고 `python -m qabot codes`로 만든다."""
    cat = catalog()
    lines = [
        "# 검수봇 issue code 카탈로그",
        "",
        "이 문서는 `qabot/defaults/issue_codes.json`에서 `python -m qabot codes`로 생성한다. 손으로 고치지 않는다.",
        "",
        "- 카탈로그 버전: %s" % _cache["raw"].get("version", ""),
        "- 카탈로그 해시: %s" % catalog_hash()[:12],
        "- severity의 판정 영향: critical → REJECT, major → REVIEW, fixable → AUTO_FIX, minor·info → PASS(기록)",
        "- fail-safe 코드는 major 아래로 내릴 수 없다.",
        "",
    ]
    for layer in model.LAYERS:
        rows = [(k, v) for k, v in sorted(cat.items()) if v["layer"] == layer]
        if not rows:
            continue
        lines += ["## %s" % layer, "", "| code | severity | scope | 판정 영향 | 설명 |", "|---|---|---|---|---|"]
        for k, v in rows:
            sevs = v.get("severities") or [v["severity"]]
            eff = " / ".join(effect(s) for s in sevs)
            note = " (fail-safe)" if v.get("fail_safe") else ""
            lines.append("| `%s` | %s | %s | %s | %s%s |" % (k, "/".join(sevs), v["scope"], eff, v["desc"], note))
        lines.append("")
    return "\n".join(lines)
