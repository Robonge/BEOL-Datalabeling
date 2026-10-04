"""L5 중복 묶음 일관성(상위 계획 4.2절). 같은 dup_group 레코드끼리 분류 축 값 집합이 어긋나는지 본다.

- 묶음 키는 번들 unit의 dup_group이다. 값이 없거나 빈 것은 묶지 않는다.
- 내용 chunk만 보고, critical 이슈가 있는 레코드는 뺀다. 레코드는 정규화 뒤 작업본을 쓴다.
- 어긋난 묶음의 모든 레코드에 L5_DUP_GROUP_DISAGREE를 낸다. evidence에는 건수만 넣고 값·본문은 넣지 않는다.
"""
from engrbot import model
from engrbot.registry import Check, register


def _axis_values(target, axis):
    """그 축의 값 집합. 축이 없거나 L1에서 깨졌으면 None이다."""
    if "axis:%s" % axis in target.broken:
        return None
    a = (target.record.get("axes") or {}).get(axis)
    if a is None:
        return None
    return frozenset(a.get("values") or [])


def groups(bt, ctx):
    """반환: {dup_group: [RecordTarget …]} (레코드가 2개 이상인 묶음만)."""
    ct = ctx.schema["content_chunk_type"]
    out = {}
    for rid in sorted(bt.targets):
        t = bt.targets[rid]
        key = (bt.bundle.units.get(rid) or {}).get("dup_group")
        if not key or (t.record or {}).get("chunk_type") != ct or t.has_critical():
            continue
        out.setdefault(key, []).append(t)
    return {k: v for k, v in out.items() if len(v) >= 2}


@register
class DupGroupCheck(Check):
    id = "l5.dup_group"
    layer = "L5"
    scope = "batch"

    def run(self, target, ctx):
        axes = [a["name"] for a in ctx.tax.classification_axes()]
        issues = []
        grouped = groups(target, ctx)
        for key in sorted(grouped):
            members = grouped[key]
            diff = {}
            for name in axes:
                sets = [s for s in (_axis_values(t, name) for t in members) if s is not None]
                variants = len(set(sets))
                if variants > 1:
                    diff[name] = variants
            for name in sorted(diff):
                for t in members:
                    issues.append(model.issue("L5_DUP_GROUP_DISAGREE", field="axis:%s" % name, record_id=t.record_id,
                                              evidence={"group_size": len(members), "variants": diff[name]}))
        return issues
