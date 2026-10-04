"""L1 스키마 검사와 포맷 정규화(5.2절).

evaluate()는 순수 함수다. 정규화한 레코드, 정규화 기록, 이슈, 깨진 필드를 돌려준다. L6도 분포 계산에 이것을 쓴다.
"""
import copy
import numbers
import re

from qabot import model, normalize
from qabot.registry import Check, register

KNOWN_KEYS = {"record_id", "file_id", "labeler_run_id", "chunk_type", "axes", "answers", "extracted", "failures",
              "labeler", "human_reviewed", "duplicate_fields"}
ALL = "*"


def _quote(ev):
    if isinstance(ev, dict):
        q = ev.get("quote")
        return q if isinstance(q, str) else ""
    return ""


def _formats_for(schema, kind, name):
    out = []
    for fname, f in sorted(schema["formats"].items()):
        if f.get("enabled", True) and (f.get("applies_to") or {}).get(kind) == name:
            out.append((fname, f))
    return out


class _State(object):
    def __init__(self):
        self.issues = []
        self.fixes = []
        self.broken = set()

    def add(self, code, field, reason=None, fix=None, severity=None, evidence=None):
        self.issues.append(model.issue(code, field=field, reason=reason, suggested_fix=fix, severity=severity,
                                       evidence=evidence))

    def fixed(self, field, before, after, rules):
        self.fixes.append(normalize.fix_entry(field, before, after, rules))


def _confidence(st, field, conf, needed, schema):
    if conf is None:
        if needed:
            st.add("L1_CONFIDENCE_RANGE", field, "확신도가 없다.", severity="minor")
        return
    if not isinstance(conf, numbers.Number) or isinstance(conf, bool):
        st.add("L1_TYPE_INVALID", field, "확신도가 숫자가 아니다.", "확신도를 0~1 숫자로 낸다.")
        return
    lo, hi = schema["confidence"]["min"], schema["confidence"]["max"]
    if not lo <= conf <= hi:
        st.add("L1_CONFIDENCE_RANGE", field, "확신도가 %s~%s 밖이다." % (lo, hi), "확신도를 0~1 사이로 낸다.",
               severity="major")


def evaluate(record, tax, schema):
    """반환: {"record", "fixes", "issues", "broken"}."""
    st = _State()
    rec = copy.deepcopy(record)
    failures = [f for f in rec.get("failures") or [] if isinstance(f, dict)]
    cls_fail = [f for f in failures if f.get("stage") == "classify"]
    lab_fail = [f for f in failures if f.get("stage") == "label"]
    has_cls = rec.get("chunk_type") is not None or bool(rec.get("axes"))
    if cls_fail and not has_cls:
        st.add("L1_LABELER_FAILED", "chunk_type", "1차 분류가 실패해 라벨이 없다.",
               "실패 사유를 확인하고 labelbot을 다시 돌린다.",
               evidence={"stage": "classify", "reason_code": cls_fail[0].get("reason_code")})
        st.broken.add(ALL)
        return {"record": rec, "fixes": [], "issues": st.issues, "broken": st.broken}

    # chunk 유형
    ct = rec.get("chunk_type")
    if ct is None:
        st.add("L1_REQUIRED_MISSING", "chunk_type", "chunk 유형이 없다.", "1차 분류를 다시 돌린다.")
        st.broken.add("chunk_type")
    elif not isinstance(ct, str):
        st.add("L1_TYPE_INVALID", "chunk_type", "chunk 유형이 문자열이 아니다.")
        st.broken.add("chunk_type")
    else:
        new, rules = normalize.enum_value(ct, schema["chunk_types"])
        if rules:
            st.fixed("chunk_type", ct, new, rules)
            rec["chunk_type"] = new
        elif ct not in schema["chunk_types"]:
            st.add("L1_ENUM_INVALID", "chunk_type", "chunk 유형이 허용값 밖이다.", "허용된 chunk 유형 중 하나로 낸다.",
                   evidence={"value": ct[:40]})
            st.broken.add("chunk_type")
    is_content = rec.get("chunk_type") == schema["content_chunk_type"]

    if lab_fail and is_content and not rec.get("answers"):
        st.add("L1_LABELER_FAILED", "answers", "3차 라벨링이 실패해 질문 답이 없다.",
               "실패 사유를 확인하고 labelbot을 다시 돌린다.",
               evidence={"stage": "label", "reason_code": lab_fail[0].get("reason_code")})
        st.broken.add("answers")

    _axes(st, rec, tax, schema, is_content)
    _answers(st, rec, tax, schema)
    _extracted(st, rec, schema)

    for f in sorted(set(rec.get("duplicate_fields") or [])):
        st.add("L1_DUPLICATE_FIELD", f, "같은 필드의 라벨 행이 두 개 이상이다.", "중복 행 중 하나만 남기도록 다시 라벨링한다.")
    for k in sorted(set(rec) - KNOWN_KEYS):
        st.add("L1_UNKNOWN_FIELD", k, "스키마에 없는 필드다.")
    for fx in st.fixes:
        st.add("L1_FORMAT_NORMALIZED", fx["field"], "표기만 다른 값을 표준 표기로 바꿨다.",
               evidence={"before": fx["before"], "after": fx["after"], "rule": fx["rule"]})
    return {"record": rec, "fixes": st.fixes, "issues": st.issues, "broken": st.broken}


def _axes(st, rec, tax, schema, is_content):
    axes = rec.get("axes")
    if axes is None:
        axes = rec["axes"] = {}
    if not isinstance(axes, dict):
        st.add("L1_TYPE_INVALID", "axes", "축 라벨이 객체가 아니다.")
        st.broken.add("axes")
        return
    for name in sorted(axes):
        a = axes[name]
        field = "axis:%s" % name
        if not isinstance(a, dict):
            st.add("L1_TYPE_INVALID", field, "축 라벨이 객체가 아니다.")
            st.broken.add(field)
            continue
        vals = a.get("values")
        if not isinstance(vals, list) or not vals or not all(isinstance(v, str) for v in vals):
            st.add("L1_TYPE_INVALID", field, "값 목록이 비었거나 문자열 목록이 아니다.", "값을 문자열 목록으로 낸다.")
            st.broken.add(field)
            continue
        status = a.get("status")
        if not isinstance(status, str):
            st.add("L1_TYPE_INVALID", field, "상태가 문자열이 아니다.")
            st.broken.add(field)
            continue
        new_status, rules = normalize.enum_value(status, schema["axis_status"])
        if rules:
            st.fixed(field + "#status", status, new_status, rules)
            a["status"] = new_status
        elif status not in schema["axis_status"]:
            st.add("L1_ENUM_INVALID", field, "상태가 허용값 밖이다.", evidence={"value": status[:40]})
            st.broken.add(field)
            continue
        if name in tax.axes:
            new_vals, used = [], []
            for v in vals:
                nv, r = normalize.axis_value(name, v, tax)
                new_vals.append(nv)
                used += [x for x in r if x not in used]
            if used:
                st.fixed(field, list(vals), new_vals, used)
                a["values"] = new_vals
        ev = a.get("evidence")
        if ev is not None and not isinstance(ev, dict):
            st.add("L1_TYPE_INVALID", field, "근거가 객체가 아니다.")
            st.broken.add(field)
            continue
        if isinstance(ev, dict) and ev.get("quote") is not None and not isinstance(ev.get("quote"), str):
            st.add("L1_TYPE_INVALID", field, "근거 인용이 문자열이 아니다.")
            st.broken.add(field)
            continue
        if a.get("inactive"):
            continue
        for fname, f in _formats_for(schema, "axis", name):
            for v in a["values"]:
                if not tax.is_reserved(v) and not re.fullmatch(f["pattern"], v):
                    st.add("L1_PATTERN_MISMATCH", field, "값이 %s 패턴에 맞지 않는다." % fname,
                           "taxonomy 표기 그대로 낸다.", evidence={"value": v[:40], "format": fname})
        is_value = a["status"] == "value"
        if is_value and schema["rules"].get("evidence_required_for_value") and not _quote(ev).strip():
            st.add("L1_EVIDENCE_MISSING", field, "값을 붙였는데 근거 인용이 없다.", "본문에서 근거를 글자 그대로 인용한다.")
        _confidence(st, field, a.get("confidence"), is_value, schema)
    if is_content and schema["rules"].get("all_active_axes_required"):
        for ax in sorted(tax.active_axes(), key=lambda x: x["name"]):
            if ax["name"] not in axes:
                st.add("L1_REQUIRED_MISSING", "axis:%s" % ax["name"], "활성 축의 라벨이 없다.", "모든 활성 축에 값을 낸다.")


def _answers(st, rec, tax, schema):
    answers = rec.get("answers")
    if answers is None:
        answers = rec["answers"] = {}
    if not isinstance(answers, dict):
        st.add("L1_TYPE_INVALID", "answers", "질문 답이 객체가 아니다.")
        st.broken.add("answers")
        return
    for qid in sorted(answers):
        a = answers[qid]
        field = "answer:%s" % qid
        if tax.questions and qid not in tax.questions:
            st.add("L1_UNKNOWN_FIELD", field, "taxonomy에 없는 질문 ID다.")
        if not isinstance(a, dict) or not isinstance(a.get("answer"), str):
            st.add("L1_TYPE_INVALID", field, "답이 문자열이 아니다.")
            st.broken.add(field)
            continue
        ans = a["answer"]
        new, rules = normalize.enum_value(ans, schema["answers"])
        if rules:
            st.fixed(field, ans, new, rules)
            a["answer"] = ans = new
        elif ans not in schema["answers"]:
            st.add("L1_ENUM_INVALID", field, "답이 허용값(O, X, N/A) 밖이다.", evidence={"value": ans[:20]})
            st.broken.add(field)
            continue
        ev = a.get("evidence")
        if (ev is not None and not isinstance(ev, dict)) or (
                isinstance(ev, dict) and ev.get("quote") is not None and not isinstance(ev.get("quote"), str)):
            st.add("L1_TYPE_INVALID", field, "근거가 형식에 맞지 않는다.")
            st.broken.add(field)
            continue
        ox = ans in ("O", "X")
        if ox and schema["rules"].get("quote_required_for_ox") and not _quote(ev).strip():
            st.add("L1_EVIDENCE_MISSING", field, "O나 X로 답했는데 근거 인용이 없다.", "근거가 없으면 N/A로 답한다.")
        _confidence(st, field, a.get("confidence"), ox, schema)


def _extracted(st, rec, schema):
    ex = rec.get("extracted")
    if ex is None:
        ex = rec["extracted"] = []
    if not isinstance(ex, list):
        st.add("L1_TYPE_INVALID", "extracted", "추출값이 목록이 아니다.")
        st.broken.add("extracted")
        return
    for i, e in enumerate(ex):
        item = e.get("item") if isinstance(e, dict) else None
        field = "extract:%s#%d" % (item if isinstance(item, str) else "?", i)
        if not isinstance(e, dict) or not isinstance(item, str) or not isinstance(e.get("value"), str):
            st.add("L1_TYPE_INVALID", field, "추출값의 항목이나 값이 문자열이 아니다.")
            st.broken.add(field)
            continue
        if item not in schema["extracted_items"]:
            st.add("L1_UNKNOWN_FIELD", field, "스키마에 없는 추출 항목이다.")
        val = e["value"]
        fmts = _formats_for(schema, "extracted", item)
        if fmts:
            fname, f = fmts[0]
            if f.get("normalizer") == "date_iso":
                new, rules = normalize.date_value(val, f["pattern"])
            elif f.get("normalizer") == "pattern_case":
                new, rules = normalize.pattern_value(val, f["pattern"])
            else:
                new, rules = val, []
            if rules:
                st.fixed(field, val, new, rules)
                e["value"] = val = new
            if not re.fullmatch(f["pattern"], val):
                if fname == "date":
                    st.add("L1_DATE_FORMAT", field, "날짜의 연월일 순서를 확정할 수 없다.",
                           "연도가 네 자리인 날짜만 추출하거나 원문 표기를 확인한다.", evidence={"value": val[:40]})
                else:
                    st.add("L1_PATTERN_MISMATCH", field, "값이 %s 패턴에 맞지 않는다." % fname,
                           evidence={"value": val[:40], "format": fname})
            elif f.get("common_second_letters") and val.startswith("R") and len(val) > 1 \
                    and val[1] not in f["common_second_letters"]:
                st.add("L1_LOT_ID_UNCOMMON", field, "R 다음 글자가 흔한 글자가 아니다.", evidence={"value": val[:40]})
        else:
            new, rules = normalize.text_value(val)
            if rules:
                st.fixed(field, val, new, rules)
                e["value"] = new
        if not _quote(e.get("evidence")).strip():
            st.add("L1_EVIDENCE_MISSING", field, "추출값에 근거 인용이 없다.", "본문 인용과 함께 추출한다.")


@register
class SchemaCheck(Check):
    id = "l1.schema"
    layer = "L1"
    scope = "record"

    def run(self, target, ctx):
        out = evaluate(target.original, ctx.tax, ctx.schema)
        target.record = out["record"]
        target.auto_fixes = out["fixes"]
        target.broken |= out["broken"]
        return out["issues"]
