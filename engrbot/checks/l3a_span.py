"""L3(a) 근거 span 실재(5.4절). 결정론 검사다.

축 근거는 원문 text와 동의어 치환본 text_canonical 중 하나에 있으면 통과다. 질문 답과 추출값의 근거는 원문에서만 찾는다.
"""
import hashlib
import re

from engrbot import model, textmatch
from engrbot.checks.l1_schema import ALL
from engrbot.registry import Check, register

_DATE_IN_QUOTE = re.compile(r"(\d{4})\s*(?:[.\-/]|년)\s*(\d{1,2})(?:\s*(?:[.\-/]|월)\s*(\d{1,2})\s*일?)?")
_WS = re.compile(r"\s+")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")


def _texts(unit, with_canonical):
    out = [model.nfc(unit.get("text") or "")]
    if with_canonical and unit.get("text_canonical"):
        out.append(unit["text_canonical"])
    return out


def _extract_in_quote(item, value, quote):
    if item == "date":
        if not _ISO_DATE.match(value):
            return True  # 형식 오류는 L1_DATE_FORMAT이 이미 올린다
        for m in _DATE_IN_QUOTE.finditer(model.nfkc(quote)):
            y, mo, d = m.group(1), int(m.group(2)), m.group(3)
            found = "%s-%02d-%02d" % (y, mo, int(d)) if d else "%s-%02d" % (y, mo)
            if found == value or (d and found[:7] == value):
                return True
        return False
    if item == "lot_id":
        return _WS.sub("", value).upper() in _WS.sub("", model.nfkc(quote)).upper()
    return textmatch.norm(value) in textmatch.norm(quote)


def evaluate(rec, unit, file_units, policy, broken=()):
    issues = []
    if ALL in broken or unit is None:
        return issues
    l3 = policy["l3"]
    excerpt = policy["output"]["excerpt_chars"]
    own_id = unit["unit_id"]
    others = [u for u in file_units if u["unit_id"] != own_id]

    def ev(quote, tier=None, found=None, extra=None):
        out = {"unit_id": own_id, "quote_sha256": hashlib.sha256(quote.encode("utf-8")).hexdigest(),
               "quote_len": len(quote), "match_tier": tier or "none", "found_in_unit": found,
               "text": quote[:excerpt]}
        out.update(extra or {})
        return out

    def check(field, evidence, with_canonical, answer_label):
        if not isinstance(evidence, dict):
            return
        quote = evidence.get("quote")
        if not isinstance(quote, str) or not quote.strip():
            return
        own_text = model.nfc(unit.get("text") or "")
        start, end = evidence.get("start"), evidence.get("end")
        ref = evidence.get("unit_id")
        if ref and ref != own_id:
            target = next((u for u in others if u["unit_id"] == ref), None)
            tier = textmatch.find(quote, _texts(target, with_canonical))[0] if target else None
            if tier:
                issues.append(model.issue("L3_SPAN_WRONG_UNIT", field=field, reason="근거가 이 chunk가 아니라 다른 chunk를 가리킨다.",
                    suggested_fix="이 chunk 본문에서 글자 그대로 인용한다. %s" % answer_label, evidence=ev(quote, tier, ref)))
            else:
                issues.append(model.issue("L3_SPAN_NOT_FOUND", field=field, reason="근거 인용이 이 chunk 본문에 없다.",
                    suggested_fix="이 chunk 본문에서 글자 그대로 인용해 다시 라벨링한다.", evidence=ev(quote)))
            return
        if start is not None or end is not None:
            reason = textmatch.check_offset(own_text, start, end, quote)
            if reason:
                issues.append(model.issue("L3_SPAN_OFFSET_INVALID", field=field, reason="근거 offset이 본문 구간과 맞지 않는다.",
                    suggested_fix="offset을 다시 계산하거나 offset 없이 인용만 낸다.", evidence=ev(quote, extra={"offset_reason": reason})))
            elif textmatch.is_long(quote, own_text, l3["long_quote"]["chars"], l3["long_quote"]["ratio"]):
                issues.append(model.issue("L3_SPAN_TOO_LONG", field=field, reason="인용이 chunk 대부분이라 근거가 특정되지 않는다.",
                                          suggested_fix="라벨을 지지하는 문장만 인용한다.", evidence=ev(quote, "offset")))
            return
        sq = l3["short_quote"]
        if textmatch.is_short(quote, sq["hangul_max"], sq["alnum_max"]):
            issues.append(model.issue("L3_SPAN_TOO_SHORT", field=field, reason="인용이 너무 짧아 일치 여부를 믿을 수 없다.",
                                      suggested_fix="라벨을 지지하는 문장을 인용한다.", evidence=ev(quote)))
            return
        tier, _ = textmatch.find(quote, _texts(unit, with_canonical))
        if tier:
            if textmatch.is_long(quote, own_text, l3["long_quote"]["chars"], l3["long_quote"]["ratio"]):
                issues.append(model.issue("L3_SPAN_TOO_LONG", field=field, reason="인용이 chunk 대부분이라 근거가 특정되지 않는다.",
                                          suggested_fix="라벨을 지지하는 문장만 인용한다.", evidence=ev(quote, tier)))
            return
        for u in others:
            t2, _ = textmatch.find(quote, _texts(u, with_canonical))
            if t2:
                issues.append(model.issue("L3_SPAN_WRONG_UNIT", field=field, reason="근거 인용이 이 chunk에 없고 같은 파일의 다른 chunk에 있다.",
                    suggested_fix="이 chunk 본문에서 글자 그대로 인용한다. %s" % answer_label, evidence=ev(quote, t2, u["unit_id"])))
                return
        issues.append(model.issue("L3_SPAN_NOT_FOUND", field=field, reason="근거 인용이 이 chunk 본문에 없다.",
                                  suggested_fix="이 chunk 본문에서 글자 그대로 인용해 다시 라벨링한다.", evidence=ev(quote)))

    axes = rec.get("axes") if isinstance(rec.get("axes"), dict) else {}
    if "axes" not in broken:
        for name in sorted(axes):
            a = axes[name]
            field = "axis:%s" % name
            if field in broken or not isinstance(a, dict) or a.get("status") != "value":
                continue
            check(field, a.get("evidence"), True, "근거가 없으면 unknown으로 둔다.")
    answers = rec.get("answers") if isinstance(rec.get("answers"), dict) else {}
    if "answers" not in broken:
        for qid in sorted(answers):
            a = answers[qid]
            field = "answer:%s" % qid
            if field in broken or not isinstance(a, dict) or a.get("answer") not in ("O", "X"):
                continue
            check(field, a.get("evidence"), False, "근거가 없으면 N/A로 답한다.")
    extracted = rec.get("extracted") if isinstance(rec.get("extracted"), list) else []
    if "extracted" not in broken:
        for i, e in enumerate(extracted):
            if not isinstance(e, dict):
                continue
            field = "extract:%s#%d" % (e.get("item"), i)
            if field in broken:
                continue
            before = len(issues)
            check(field, e.get("evidence"), False, "근거가 없으면 추출하지 않는다.")
            quote = (e.get("evidence") or {}).get("quote") or ""
            if len(issues) == before and quote.strip() and not _extract_in_quote(e.get("item"), e.get("value") or "", quote):
                issues.append(model.issue("L3_EXTRACT_NOT_IN_QUOTE", field=field, reason="추출값이 인용 안에 없다.",
                                          suggested_fix="인용에 나온 표기에서 추출한다.", evidence=ev(quote)))
    return issues


@register
class SpanCheck(Check):
    id = "l3a.span_exists"
    layer = "L3A"
    scope = "record"

    def run(self, target, ctx):
        return evaluate(target.record, target.unit, ctx.units_by_file.get(target.file_id, []), ctx.policy,
                        target.broken)
