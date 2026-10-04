"""L4 도메인 규칙 파일 읽기와 검증.

형식은 {"version": str, "rules": [...]}다. 규칙 공통 필드는 id(고유), type, status(draft | approved),
severity(major | minor), note(선택)다. 어긋나면 PolicyError로 멈춘다. 규칙 내용은 도메인 담당자가 정한다.
"""
import json
import os
import re

from engrbot.policy import PolicyError

PKG_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_RULES_PATH = os.path.join(PKG_ROOT, "defaults", "domain_rules.json")

TYPES = ("axis_combo", "title_label", "synonym_suggest")
STATUSES = ("draft", "approved")
RULE_SEVERITIES = ("major", "minor")
COMMON_KEYS = {"id", "type", "status", "severity", "note"}
TYPE_KEYS = {
    "axis_combo": {"when", "expect", "forbid"},
    "title_label": {"title_pattern", "axis"},
    "synonym_suggest": {"axis"},
}


def rules_path(policy):
    return (policy.get("l4") or {}).get("rules_path") or DEFAULT_RULES_PATH


def _str_list(v):
    return isinstance(v, list) and bool(v) and all(isinstance(x, str) and x for x in v)


def _check_cond(cond, where, problems):
    if not isinstance(cond, dict) or set(cond) != {"axis", "value_in"}:
        problems.append("RULE_COND_INVALID:%s" % where)
        return
    if not isinstance(cond["axis"], str) or not cond["axis"]:
        problems.append("RULE_AXIS_INVALID:%s" % where)
    if not _str_list(cond["value_in"]):
        problems.append("RULE_VALUE_IN_INVALID:%s" % where)


def validate(doc):
    """규칙 문서를 검증하고 정규식을 컴파일해 둔 규칙 목록을 돌려준다."""
    problems = []
    if not isinstance(doc, dict) or set(doc) != {"version", "rules"}:
        raise PolicyError(["RULES_DOC_INVALID"])
    if not isinstance(doc["version"], str) or not doc["version"]:
        problems.append("RULES_VERSION_INVALID")
    if not isinstance(doc["rules"], list):
        raise PolicyError(problems + ["RULES_LIST_INVALID"])
    out = []
    seen = set()
    for n, r in enumerate(doc["rules"]):
        if not isinstance(r, dict):
            problems.append("RULE_NOT_OBJECT:%d" % n)
            continue
        rid = r.get("id")
        where = rid if isinstance(rid, str) and rid else "#%d" % n
        if not isinstance(rid, str) or not rid:
            problems.append("RULE_ID_INVALID:%s" % where)
        elif rid in seen:
            problems.append("RULE_ID_DUPLICATE:%s" % where)
        seen.add(rid)
        rtype = r.get("type")
        if rtype not in TYPES:
            problems.append("RULE_TYPE_INVALID:%s" % where)
            continue
        if r.get("status") not in STATUSES:
            problems.append("RULE_STATUS_INVALID:%s" % where)
        if r.get("severity") not in RULE_SEVERITIES:
            problems.append("RULE_SEVERITY_INVALID:%s" % where)
        if "note" in r and not isinstance(r["note"], str):
            problems.append("RULE_NOTE_INVALID:%s" % where)
        for k in sorted(set(r) - COMMON_KEYS - TYPE_KEYS[rtype]):
            problems.append("RULE_UNKNOWN_KEY:%s:%s" % (where, k))
        rule = dict(r)
        if rtype == "axis_combo":
            _check_cond(r.get("when"), where + ".when", problems)
            has = [k for k in ("expect", "forbid") if k in r]
            if len(has) != 1:
                problems.append("RULE_EXPECT_FORBID_INVALID:%s" % where)
            else:
                _check_cond(r[has[0]], "%s.%s" % (where, has[0]), problems)
        elif rtype == "title_label":
            if not isinstance(r.get("axis"), str) or not r.get("axis"):
                problems.append("RULE_AXIS_INVALID:%s" % where)
            pat = r.get("title_pattern")
            try:
                rx = re.compile(pat) if isinstance(pat, str) and pat else None
            except re.error:
                rx = None
            if rx is None or rx.groups < 1:
                problems.append("RULE_PATTERN_INVALID:%s" % where)
            rule["_rx"] = rx
        elif "axis" in r and (not isinstance(r["axis"], str) or not r["axis"]):
            problems.append("RULE_AXIS_INVALID:%s" % where)
        out.append(rule)
    if problems:
        raise PolicyError(problems)
    return out


def load(path):
    """규칙 파일(.json)을 읽어 검증한다. 읽기 실패도 PolicyError다."""
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        raise PolicyError(["RULES_FILE_UNREADABLE"])
    return validate(doc)
