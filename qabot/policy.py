"""policy.json·schema.json 읽기, 기본값 병합, 검증, 해시.

알 수 없는 키, 범위 밖 값, fail-safe 코드의 하향 설정은 거부한다(6.2절).
"""
import copy
import json
import numbers
import os
import re

from qabot import codes, model

PKG_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_POLICY_PATH = os.path.join(PKG_ROOT, "defaults", "policy.json")
DEFAULT_SCHEMA_PATH = os.path.join(PKG_ROOT, "defaults", "schema.json")

# 기본값에 없는 키를 받는 자리(값 형식은 따로 검사한다)
FREE_MAPS = {("severity_overrides",), ("l0", "warning_severity")}
EXTENSION_BLOCKS = ("l4", "l5")
NULLABLE = {("judge", "temperature")}  # null이면 보내지 않는다(7.1절)
RATIO_KEYS = {
    ("l0", "coverage_major"), ("l0", "coverage_minor"), ("l0", "empty_ratio_major"), ("l0", "repeated_line_ratio"),
    ("l0", "cell_ratio_minor"), ("l0", "garbled_major"), ("l0", "garbled_minor"), ("l2", "unknown_ratio_major"),
    ("l3", "long_quote", "ratio"), ("feedback", "axis_issue_rate"), ("feedback", "question_issue_rate"),
    ("feedback", "quote_issue_rate"), ("l6", "jsd_notice"), ("l6", "jsd_alert"), ("l6", "unknown_rate_alert"),
    ("l6", "pass_rate_drop_alert"),
}
MIN_ONE = {("judge", "max_items_per_call"), ("judge", "workers"), ("judge", "timeout"), ("l6", "min_n"),
           ("feedback", "min_n"), ("l6", "unused_runs"), ("output", "excerpt_chars")}


class PolicyError(Exception):
    def __init__(self, problems):
        self.problems = list(problems)
        Exception.__init__(self, "; ".join(self.problems))


def _load_default(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def default_policy():
    return _load_default(DEFAULT_POLICY_PATH)


def default_schema():
    return _load_default(DEFAULT_SCHEMA_PATH)


def merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and (k,) not in FREE_MAPS:
            out[k] = merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _same_type(default, value):
    if default is None:
        return value is None or isinstance(value, str)
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, numbers.Number):
        return isinstance(value, numbers.Number) and not isinstance(value, bool)
    return isinstance(value, type(default))


def _walk_keys(default, user, path, problems):
    for k, v in user.items():
        p = path + (k,)
        if not path and k in EXTENSION_BLOCKS:
            if not isinstance(v, dict):
                problems.append("TYPE_INVALID:%s" % ".".join(p))
            continue
        if k not in default:
            problems.append("UNKNOWN_KEY:%s" % ".".join(p))
            continue
        d = default[k]
        if p in NULLABLE and v is None:
            continue
        if p in FREE_MAPS:
            if not isinstance(v, dict):
                problems.append("TYPE_INVALID:%s" % ".".join(p))
            continue
        if not _same_type(d, v):
            problems.append("TYPE_INVALID:%s" % ".".join(p))
            continue
        if isinstance(d, dict):
            _walk_keys(d, v, p, problems)


def _get(obj, path):
    for k in path:
        obj = obj[k]
    return obj


def validate_policy(user, merged=None):
    """반환: 병합한 정책. 문제가 있으면 PolicyError."""
    from qabot import normalize

    base = default_policy()
    problems = []
    if not isinstance(user, dict):
        raise PolicyError(["TYPE_INVALID:policy"])
    _walk_keys(base, user, (), problems)
    if problems:
        raise PolicyError(problems)
    pol = merged or merge(base, user)
    for path in RATIO_KEYS:
        v = _get(pol, path)
        if not 0 <= v <= 1:
            problems.append("OUT_OF_RANGE:%s" % ".".join(path))
    for path in MIN_ONE:
        if _get(pol, path) < 1:
            problems.append("OUT_OF_RANGE:%s" % ".".join(path))
    for path in (("l0", "min_raw_chars"), ("l0", "empty_chars"), ("l0", "image_min_bytes"),
                 ("judge", "max_retries"), ("l3", "short_quote", "hangul_max"), ("l3", "short_quote", "alnum_max"),
                 ("l3", "long_quote", "chars"), ("feedback", "format_rule_min_count"),
                 ("l6", "terms", "min_df"), ("l6", "terms", "top_k"), ("l6", "terms", "min_lift")):
        if _get(pol, path) < 0:
            problems.append("OUT_OF_RANGE:%s" % ".".join(path))
    l0 = pol["l0"]
    if l0["coverage_major"] > l0["coverage_minor"]:
        problems.append("OUT_OF_RANGE:l0.coverage_major>coverage_minor")
    if l0["garbled_minor"] > l0["garbled_major"]:
        problems.append("OUT_OF_RANGE:l0.garbled_minor>garbled_major")
    if pol["l6"]["jsd_notice"] > pol["l6"]["jsd_alert"]:
        problems.append("OUT_OF_RANGE:l6.jsd_notice>jsd_alert")
    for layer in pol["layers"]:
        if layer not in model.LAYERS:
            problems.append("LAYER_UNKNOWN:%s" % layer)
    vc = pol["verdict"]
    if set(vc["severity_to_verdict"]) != set(model.SEVERITIES):
        problems.append("SEVERITY_MAP_INCOMPLETE")
    for sev, v in vc["severity_to_verdict"].items():
        if v not in model.VERDICTS:
            problems.append("VERDICT_UNKNOWN:%s" % v)
    if vc["severity_to_verdict"].get("critical") != "REJECT" or vc["severity_to_verdict"].get("major") != "REVIEW":
        problems.append("FAIL_SAFE_MAPPING:critical/major")
    # AUTO_FIX는 허용 목록 정규화기(fixable)에서만 나온다
    for sev in ("minor", "info"):
        if vc["severity_to_verdict"].get(sev) == "AUTO_FIX":
            problems.append("AUTO_FIX_ONLY_FOR_FIXABLE:%s" % sev)
    if vc["severity_to_verdict"].get("fixable") == "PASS":
        problems.append("FIXABLE_TO_PASS")
    for sev, w in vc["score_weights"].items():
        if sev not in model.SEVERITIES or not isinstance(w, numbers.Number) or w < 0:
            problems.append("OUT_OF_RANGE:verdict.score_weights.%s" % sev)
    for code, sev in pol["severity_overrides"].items():
        try:
            codes.get(code)
        except KeyError:
            problems.append("UNKNOWN_CODE:%s" % code)
            continue
        if sev not in model.SEVERITIES:
            problems.append("SEVERITY_UNKNOWN:%s" % code)
        elif codes.is_fail_safe(code) and model.SEVERITY_RANK[sev] < model.SEVERITY_RANK["major"]:
            problems.append("FAIL_SAFE_DOWNGRADE:%s" % code)
        elif sev == "fixable" and code != "L1_FORMAT_NORMALIZED":
            problems.append("FIXABLE_RESERVED:%s" % code)
    for w, sev in pol["l0"]["warning_severity"].items():
        if sev not in ("minor", "info"):
            problems.append("OUT_OF_RANGE:l0.warning_severity.%s" % w)
    j = pol["judge"]
    if j["transport"] not in ("mock", "http"):
        problems.append("OUT_OF_RANGE:judge.transport")
    if j["mode"] not in ("json", "tool"):
        problems.append("OUT_OF_RANGE:judge.mode")
    if j["temperature"] is not None and not (isinstance(j["temperature"], numbers.Number) and 0 <= j["temperature"] <= 2):
        problems.append("OUT_OF_RANGE:judge.temperature")
    for g in pol["l2"]["mutex_groups"]:
        if not (isinstance(g, dict) and isinstance(g.get("axis"), str) and isinstance(g.get("values"), list)
                and len(g["values"]) >= 2 and all(isinstance(v, str) for v in g["values"])):
            problems.append("MUTEX_GROUP_INVALID")
    if not all(isinstance(v, str) for v in pol["l2"]["catchall_values"]):
        problems.append("TYPE_INVALID:l2.catchall_values")
    for r in pol["autofix"]["approved_rules"]:
        if r not in normalize.RULES:
            problems.append("AUTOFIX_RULE_UNKNOWN:%s" % r)
    if not all(isinstance(t, str) for t in pol["l6"]["terms"]["stoplist"]):
        problems.append("TYPE_INVALID:l6.terms.stoplist")
    if problems:
        raise PolicyError(problems)
    return pol


def validate_schema(user):
    from qabot import normalize

    base = default_schema()
    problems = []
    if not isinstance(user, dict):
        raise PolicyError(["TYPE_INVALID:schema"])
    for k in user:
        if k not in base:
            problems.append("UNKNOWN_KEY:%s" % k)
    if problems:
        raise PolicyError(problems)
    sch = copy.deepcopy(base)
    sch.update(copy.deepcopy(user))  # 최상위 블록 단위로 바꾼다(formats를 통째로 갈아 끼울 수 있게)
    for key in ("chunk_types", "answers", "axis_status"):
        if not (isinstance(sch[key], list) and sch[key] and all(isinstance(v, str) for v in sch[key])):
            problems.append("TYPE_INVALID:%s" % key)
    if sch["content_chunk_type"] not in sch["chunk_types"]:
        problems.append("OUT_OF_RANGE:content_chunk_type")
    for name, f in sch["formats"].items():
        if not isinstance(f, dict) or "pattern" not in f:
            problems.append("FORMAT_INVALID:%s" % name)
            continue
        try:
            re.compile(f["pattern"])
        except (re.error, TypeError):
            problems.append("PATTERN_INVALID:%s" % name)
        if f.get("normalizer") and f["normalizer"] not in normalize.RULES:
            problems.append("NORMALIZER_UNKNOWN:%s" % name)
        at = f.get("applies_to") or {}
        if set(at) - {"axis", "extracted"} or len(at) != 1:
            problems.append("APPLIES_TO_INVALID:%s" % name)
    for k in ("min", "max"):
        if not isinstance(sch["confidence"].get(k), numbers.Number):
            problems.append("TYPE_INVALID:confidence.%s" % k)
    if problems:
        raise PolicyError(problems)
    return sch


def policy_version(pol):
    return "%s+%s" % (pol.get("version", ""), model.hash_obj(pol)[:12])


def schema_version(sch):
    return "%s+%s" % (sch.get("version", ""), model.hash_obj(sch)[:12])


def load(qa_paths, policy_path=None, schema_path=None):
    """작업 폴더 qa/policy.json·schema.json. 없으면 기본본을 써 둔다. 반환: (policy, schema)."""
    from qabot import io

    out = []
    for name, path, default, validate in (
        ("policy", policy_path or qa_paths.policy, default_policy, validate_policy),
        ("schema", schema_path or qa_paths.schema, default_schema, validate_schema),
    ):
        if not os.path.isfile(path):
            io.write_json(path, default(), indent=2)
        user = io.read_json_input(path, qa_paths.inputs_dir)
        out.append(validate(user))
    return out[0], out[1]
