"""L2 taxonomy 정합성(5.3절). 정규화 뒤의 레코드로 한 축 안만 본다. 축 사이 조합은 L4의 일이다."""
from engrbot import model
from engrbot.checks.l1_schema import ALL
from engrbot.registry import Check, register


def evaluate(rec, tax, schema, policy, broken=()):
    issues = []
    if ALL in broken or "axes" in broken:
        return issues
    l2 = policy["l2"]
    axes = rec.get("axes") or {}
    is_content = rec.get("chunk_type") == schema["content_chunk_type"]

    def add(code, field, reason, fix=None, severity=None, evidence=None):
        issues.append(model.issue(code, field=field, reason=reason, suggested_fix=fix, severity=severity,
                                  evidence=evidence))

    for name in sorted(axes):
        field = "axis:%s" % name
        if field in broken:
            continue
        a = axes[name]
        vals = list(a.get("values") or [])
        ax = tax.axes.get(name)
        if ax is None or not ax.get("active"):
            if ax is not None and vals == [tax.na]:
                continue  # 비활성 축은 해당 없음으로만 저장된다
            add("L2_AXIS_UNKNOWN", field, "taxonomy의 활성 축이 아니다.", "taxonomy 시트의 축 이름을 확인한다.",
                evidence={"axis": name[:40]})
            continue
        known = tax.values.get(name, {})
        bad = [v for v in vals if v not in known and not tax.is_reserved(v)]
        for v in bad:
            add("L2_LABEL_NOT_IN_TAXONOMY", field, "그 축의 활성 값도 예약어도 아니다.",
                "taxonomy 값 그대로 쓰거나 새 값 후보로 올린다.", evidence={"value": v[:40]})
        good = [v for v in vals if v in known]
        # 계층
        for v in good:
            parent = known[v].get("parent")
            if not parent:
                continue
            if not ax.get("hierarchical"):
                add("L2_HIERARCHY_INCONSISTENT", field, "계층이 아닌 축에 상위값을 가진 값이 있다.", evidence={"value": v[:40]})
            elif parent not in known:
                add("L2_HIERARCHY_INCONSISTENT", field, "하위값의 상위값이 taxonomy에 없다.",
                    evidence={"value": v[:40], "parent": parent[:40]})
            elif parent in vals:
                add("L2_HIERARCHY_INCONSISTENT", field, "같은 축에 상위값과 하위값이 함께 있다(하위만 저장한다).",
                    "하위값만 남긴다.", evidence={"value": v[:40], "parent": parent[:40]})
        # 상호배타(구조 규칙)
        reserved = [v for v in vals if tax.is_reserved(v)]
        if reserved and len(vals) > 1:
            add("L2_MUTEX_VIOLATION", field, "예약어가 다른 값과 함께 있다.", "예약어만 쓰거나 값만 쓴다.",
                severity="critical", evidence={"values": [v[:40] for v in vals]})
        elif not ax.get("multi") and len(vals) > 1:
            add("L2_MUTEX_VIOLATION", field, "다중값이 아닌 축에 값이 둘 이상이다.", "값을 하나만 낸다.",
                severity="critical", evidence={"values": [v[:40] for v in vals]})
        for g in l2["mutex_groups"]:
            if g["axis"] == name:
                hit = [v for v in g["values"] if v in vals]
                if len(hit) >= 2:
                    add("L2_MUTEX_VIOLATION", field, "정책의 상호배타 값이 함께 있다.", severity="major",
                        evidence={"values": hit})
        # 상태
        status = a.get("status")
        if status == "value" and (not good or reserved):
            add("L2_STATUS_MISMATCH", field, "상태는 값인데 값이 예약어거나 taxonomy 밖이다.")
        elif status == "unknown" and vals != [tax.unknown]:
            add("L2_STATUS_MISMATCH", field, "상태는 unknown인데 값이 unknown이 아니다.")
        elif status == "na" and vals != [tax.na]:
            add("L2_STATUS_MISMATCH", field, "상태는 해당 없음인데 값이 해당 없음이 아니다.")

    if is_content:
        cls_axes = [ax["name"] for ax in tax.classification_axes()]
        labeled = {n: axes[n] for n in cls_axes if n in axes and ("axis:%s" % n) not in broken}
        catch = set(l2["catchall_values"])
        unknown = sum(1 for a in labeled.values() if set(a.get("values") or []) & catch)
        na = sum(1 for a in labeled.values() if (a.get("values") or []) == [tax.na])
        denom = len(cls_axes) - na
        if denom > 0 and unknown / float(denom) >= l2["unknown_ratio_major"] - 1e-12:
            add("L2_UNKNOWN_OVERUSE", "axes", "unknown 비율이 기준 이상이다.", "근거가 있는 축은 값을 붙인다.",
                evidence={"unknown": unknown, "denominator": denom})
        if cls_axes and labeled and na == len(cls_axes):
            add("L2_ALL_NOT_APPLICABLE", "axes", "내용 chunk인데 모든 분류 축이 해당 없음이다.")
    lab_tax = ((rec.get("labeler") or {}).get("sheet_hashes") or {}).get("taxonomy")
    if lab_tax and tax.version and lab_tax != tax.version:
        add("L2_TAXONOMY_STALE", "axes", "라벨링 때의 taxonomy와 지금 taxonomy가 다르다.", "labelbot을 다시 돌린다.")
    return issues


@register
class TaxonomyCheck(Check):
    id = "l2.taxonomy"
    layer = "L2"
    scope = "record"

    def run(self, target, ctx):
        return evaluate(target.record, ctx.tax, ctx.schema, ctx.policy, target.broken)
