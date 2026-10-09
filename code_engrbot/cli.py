"""code_engrbot 명령줄: review, rules."""
import argparse
import json
import sys

from code_engrbot import model, registry, report, review, scan


def _merge(base, extra):
    """값이 dict인 키는 키 단위로 깊게 합치고, 그 밖은 덮어쓴다."""
    for key, val in extra.items():
        if isinstance(val, dict) and isinstance(base.get(key), dict):
            _merge(base[key], val)
        else:
            base[key] = val
    return base


def _load_policy(path):
    policy = model.default_policy()
    if path:
        with open(path, "r", encoding="utf-8-sig") as fh:
            _merge(policy, json.load(fh))
    return policy


def _split_paths(values):
    """--paths의 공백 구분 항목과 항목 안의 쉼표 구분을 모두 받는다."""
    return [p for v in values for p in v.split(",") if p]


def _cmd_review(args):
    policy = _load_policy(args.policy)
    targets = _split_paths(args.paths) if args.paths else policy["targets"]
    layers = args.layers.split(",") if args.layers else policy["layers"]
    index = scan.build(args.root, targets, policy["exclude"])
    ctx = model.Ctx(policy=policy, root=args.root)
    result = review.run(index, ctx, layers=layers)
    result["policy_version"] = policy.get("version")
    review_id, _ = report.write(args.out, result, targets, layers)
    c = result["counts"]
    errors = len(result["errors"])
    line = "%s %s critical=%d major=%d minor=%d info=%d suppressed=%d" % (
        review_id, result["verdict"], c["critical"], c["major"], c["minor"], c["info"], c["suppressed"])
    print(line + (" errors=%d" % errors if errors else ""))
    if result["verdict"] == "REQUEST_CHANGES":
        _fail_code("REVIEW_REQUEST_CHANGES")
        return 1
    if errors:
        _fail_code("REVIEW_ERRORS")
    return 2 if errors else 0


def _fail_code(code):
    """마일스톤(M20)에 사유를 남긴다. labelbot.trace가 없으면 아무 일도 하지 않는다(반환값은 그대로)."""
    try:
        from labelbot import trace
    except ImportError:
        return
    trace.fail_code(code)


def _cmd_rules(args):
    registry.load_builtin()
    report.write_rules(args.out)
    print("rules=%d out=%s" % (len(registry.all_rules()), args.out))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="code_engrbot")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("review")
    r.add_argument("--root", default=".")
    r.add_argument("--paths", nargs="+", default=None)
    r.add_argument("--layers", default=None)
    r.add_argument("--out", default=report.DEFAULT_OUT)
    r.add_argument("--policy", default=None)
    r.set_defaults(fn=_cmd_review)
    u = sub.add_parser("rules")
    u.add_argument("--out", default="code_engrbot/docs/rules.md")
    u.set_defaults(fn=_cmd_rules)
    args = p.parse_args(argv)
    try:
        from labelbot import trace
    except ImportError:  # labelbot 없이 code_engrbot만 쓸 때
        return args.fn(args)
    return trace.run("M20", lambda: args.fn(args))  # M20 CODE_REVIEW: 시작·완료·실패 줄은 stderr


if __name__ == "__main__":
    sys.exit(main())
