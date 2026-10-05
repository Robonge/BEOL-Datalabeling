"""여러 테스트가 같이 쓰는 엔진 실행 도우미(test_core, test_l5)."""
from engrbot import engine, policy, synthetic


def small_bundle():
    return synthetic.generate(seed=3, n_files=3, slides_range=(3, 4)).bundle


def run(bundle, layers, **pol):
    p = policy.validate_policy(dict(pol, layers=layers))
    s = policy.validate_schema({})
    ctx = engine.Ctx(bundle, p, s, qa_run_id="QA-test")
    return engine.run(bundle, ctx), ctx
