"""L3(b) 근거의 라벨 지지(5.5절). critical이 없는 레코드만 엔진이 넘긴다.

judge가 없으면(--no-judge, 설정 없음) 레코드마다 L3_JUDGE_SKIPPED 하나를 붙인다. judge를 거치지 않은 레코드는 PASS가 되지 않는다.
"""
from domain_engrbot import model
from domain_engrbot.registry import Check, register


@register
class JudgeCheck(Check):
    id = "l3b.judge"
    layer = "L3B"
    scope = "record"
    parallel = True

    def run(self, target, ctx):
        if ctx.judge is None:
            return [model.issue("L3_JUDGE_SKIPPED", field=None, evidence={"reason_code": ctx.judge_skip_reason},
                                suggested_fix="judge를 켜고 다시 돌린다.")]
        return ctx.judge.evaluate(target, ctx)
