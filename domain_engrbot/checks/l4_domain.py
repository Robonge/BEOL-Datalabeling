"""L4 도메인 규칙(4.1절). 규칙 파일의 축 조합, 제목·라벨, 동의어 제안 규칙을 레코드에 적용한다.

approved 규칙은 유형별 코드에 규칙의 severity를 쓴다. draft 규칙은 L4_RULE_DRAFT_HIT(info)만 내서 판정을 바꾸지 않는다.
evidence에는 rule_id와 값(40자)만 넣고 제목·본문 원문은 넣지 않는다.
교정 장부의 규칙 후보(<ledger_dir>/rule_candidates.json)는 draft로만 더한다. 후보 파일이 없거나 깨지면 기본 규칙만 쓴다.
"""
import os

from domain_engrbot import domain_rules, io, model
from domain_engrbot.checks.l1_schema import ALL
from domain_engrbot.policy import PolicyError
from domain_engrbot.registry import Check, register

CODES = {"axis_combo": "L4_AXIS_COMBO_VIOLATION", "title_label": "L4_TITLE_LABEL_MISMATCH",
         "synonym_suggest": "L4_SYNONYM_SUGGEST"}
CONTENT_ONLY = ("axis_combo", "title_label")
# ledger.candidates_path와 같은 파일 이름이다. ledger를 import하면 adapter(labelbot) 사슬이 검사 모듈까지
# 딸려 오므로 이름만 여기 둔다(교정 장부 계획 6-2절).
CANDIDATES_FILE = "rule_candidates.json"

_cache = {}


def _stat_key(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (path, st.st_mtime_ns, st.st_size)


def candidates_path(policy, ledger_dir):
    """후보를 더할 때만 후보 파일 경로. 끄거나 장부가 없거나 파일이 없으면 None."""
    if not ledger_dir or not (policy.get("l4") or {}).get("include_candidates", True):
        return None
    path = os.path.abspath(os.path.join(ledger_dir, CANDIDATES_FILE))
    return path if os.path.isfile(path) else None


def load_candidates(path, base):
    """후보 규칙. status는 draft로 바꾸고, 기본 규칙과 id가 겹치는 후보는 뺀다. 검증에 실패하면 []."""
    try:
        doc = io.read_own_json(path)
    except (OSError, ValueError):
        return []
    if not isinstance(doc, dict) or not isinstance(doc.get("rules"), list):
        return []
    doc = dict(doc, rules=[dict(r, status="draft") if isinstance(r, dict) else r for r in doc["rules"]])
    try:
        rules = domain_rules.validate(doc)
    except PolicyError:
        return []
    ids = {r["id"] for r in base}
    return [r for r in rules if r["id"] not in ids]


def rules_for(policy, ledger_dir=None):
    """규칙 파일을 읽어 검증하고 장부 후보를 더한다. 같은 파일들(경로·mtime·크기)은 다시 읽지 않는다."""
    path = os.path.abspath(domain_rules.rules_path(policy))
    key = _stat_key(path)
    cand = candidates_path(policy, ledger_dir)
    full = (key, _stat_key(cand) if cand else None)
    if key is None or full not in _cache:
        rules = domain_rules.load(path)
        if cand:
            rules = rules + load_candidates(cand, rules)
        if key is None:
            return rules
        _cache.clear()
        _cache[full] = rules
    return _cache[full]


def _values(axes, name):
    return list((axes.get(name) or {}).get("values") or [])


def _axis_combo(rule, axes, tax):
    """위반이면 (필드, 값 목록), 아니면 None."""
    w = rule["when"]
    if not set(_values(axes, w["axis"])) & set(w["value_in"]):
        return None
    if "expect" in rule:
        c = rule["expect"]
        vals = [v for v in _values(axes, c["axis"]) if not tax.is_reserved(v)]
        if not vals or set(vals) & set(c["value_in"]):
            return None
        return "axis:%s" % c["axis"], vals
    c = rule["forbid"]
    hit = [v for v in _values(axes, c["axis"]) if v in c["value_in"]]
    return ("axis:%s" % c["axis"], hit) if hit else None


def _title_label(rule, axes, tax, title):
    axis = rule["axis"]
    labeled = set(_values(axes, axis))
    missing = []
    for m in rule["_rx"].finditer(title or ""):
        raw = m.group(1)
        v = tax.canonical_value(axis, raw) if raw else None
        if v and not tax.is_reserved(v) and v not in labeled and v not in missing:
            missing.append(v)
    return ("axis:%s" % axis, missing) if missing else None


def _synonym(rule, axes, tax):
    """taxonomy 밖 값이 alias와 같은 (필드, 값, 표준값) 목록."""
    out = []
    names = [rule["axis"]] if rule.get("axis") else sorted(axes)
    alias = {}
    for s in tax.synonyms:
        alias.setdefault(model.norm_key(s.get("alias") or ""), []).append(s.get("canonical") or "")
    for name in names:
        known = tax.values.get(name)
        if known is None:
            continue
        for v in _values(axes, name):
            if v in known or tax.is_reserved(v):
                continue
            for canon in alias.get(model.norm_key(v), []):
                if canon in known:
                    out.append(("axis:%s" % name, v, canon))
                    break
    return out


def evaluate(rec, unit, rules, tax, schema, broken=()):
    issues = []
    if ALL in broken or "axes" in broken:
        return issues
    axes = rec.get("axes") or {}
    is_content = rec.get("chunk_type") == schema["content_chunk_type"]
    title = (unit or {}).get("title") or ""

    def hit(rule, field, value, fix=None, reason=None):
        ev = {"rule_id": rule["id"][:40], "value": value[:40]}
        if rule["status"] == "draft":
            issues.append(model.issue("L4_RULE_DRAFT_HIT", field=field, evidence=ev,
                                      reason="draft 도메인 규칙(%s)에 걸렸다. 판정에 반영하지 않는다." % rule["type"]))
            return
        code = CODES[rule["type"]]
        sev = "info" if code == "L4_SYNONYM_SUGGEST" else rule["severity"]
        issues.append(model.issue(code, field=field, evidence=ev, reason=reason, suggested_fix=fix, severity=sev))

    for rule in rules:
        rtype = rule["type"]
        if rtype in CONTENT_ONLY and not is_content:
            continue
        if rtype == "axis_combo":
            if any("axis:%s" % c["axis"] in broken for c in (rule["when"], rule.get("expect") or rule.get("forbid"))):
                continue
            found = _axis_combo(rule, axes, tax)
            if found:
                field, vals = found
                verb = "기대값이 없다" if "expect" in rule else "금지값이 있다"
                hit(rule, field, ", ".join(vals), reason="축 조합 규칙에서 %s." % verb,
                    fix="규칙의 축 조합을 확인하고 라벨을 고친다.")
        elif rtype == "title_label":
            if "axis:%s" % rule["axis"] in broken:
                continue
            found = _title_label(rule, axes, tax, title)
            if found:
                field, vals = found
                hit(rule, field, ", ".join(vals), reason="chunk 제목의 축 값이 라벨에 없다.",
                    fix="제목의 값을 라벨에 더할지 확인한다.")
        else:
            for field, v, canon in _synonym(rule, axes, tax):
                if field in broken:
                    continue
                hit(rule, field, v, fix="표준값 %s로 바꾼다(자동 교정하지 않는다)." % canon[:40],
                    reason="taxonomy 밖 값이 동의어와 같다.")
    return issues


@register
class DomainRuleCheck(Check):
    id = "l4.domain"
    layer = "L4"
    scope = "record"

    def run(self, target, ctx):
        rules = rules_for(ctx.policy, getattr(ctx, "ledger_dir", None))
        return evaluate(target.record, target.unit, rules, ctx.tax, ctx.schema, target.broken)
