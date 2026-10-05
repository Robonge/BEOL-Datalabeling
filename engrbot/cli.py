"""검수봇 명령. 실행: python -m engrbot <명령> --workspace <작업 폴더>

콘솔에는 실행 ID, 건수, 코드만 낸다. 본문, 파일명, 경로는 내지 않는다.
"""
import argparse
import datetime
import sys

from engrbot import io, model


def say(msg):
    print(msg, file=sys.stdout, flush=True)


def _parser():
    p = argparse.ArgumentParser(prog="python -m engrbot", description="검수봇(Label QA Agent)")
    sub = p.add_subparsers(dest="cmd")

    def ws(sp):
        sp.add_argument("--workspace", required=True, help="labelbot 작업 폴더(코드 폴더의 workspaces/ 아래)")

    r = sub.add_parser("run", help="검사, 판정, 대기열, 리포트, 검토 화면")
    ws(r)
    r.add_argument("--run", dest="labeler_run", help="라벨러 실행 ID(기본: 최근 run)")
    r.add_argument("--bundle", help="jsonl 번들 폴더(labelbot 작업 DB 대신)")
    r.add_argument("--layers", help="예: L0,L1,L2")
    r.add_argument("--no-judge", action="store_true", help="L3b judge를 부르지 않는다(이 실행의 PASS는 0건)")
    r.add_argument("--pass-sample", type=int, default=0, help="검토 화면에 올릴 PASS 표본 수")

    rp = sub.add_parser("report", help="verdicts.jsonl에서 리포트를 다시 만든다(LLM 0회)")
    ws(rp)
    rp.add_argument("--qa-run", required=True)
    rp.add_argument("--bundle")

    b = sub.add_parser("baseline", help="L6 기준선")
    bsub = b.add_subparsers(dest="action")
    bs = bsub.add_parser("set", help="검수 실행을 기준선으로 올린다")
    ws(bs)
    bs.add_argument("--qa-run", required=True)
    bs.add_argument("--bundle")

    rv = sub.add_parser("review", help="검토 화면 review.html을 다시 만든다")
    ws(rv)
    rv.add_argument("--qa-run", required=True)
    rv.add_argument("--pass-sample", type=int, default=0)
    rv.add_argument("--bundle")

    g = sub.add_parser("golden", help="골든셋")
    gsub = g.add_subparsers(dest="action")
    ga = gsub.add_parser("add", help="qa/inbox 결정과 corrections를 골든셋에 추가한다")
    ws(ga)
    ga.add_argument("--qa-run", required=True)
    ga.add_argument("--bundle")

    fb = sub.add_parser("feedback", help="승인된 결정만 모아 피드백 묶음을 만든다")
    ws(fb)
    fb.add_argument("--qa-run", required=True)
    fb.add_argument("--bundle")

    ev = sub.add_parser("eval", help="mutation 하네스(층별 탐지율, 오탐률)")
    ws(ev)
    ev.add_argument("--golden", required=True, help="synthetic[:시드], ledger(교정 장부 골든셋) 또는 골든셋 .jsonl 경로")
    ev.add_argument("--judge", choices=("mock", "http"), default="mock")
    ev.add_argument("--per-mutator", type=int, default=10)
    ev.add_argument("--bundle", help="골든셋 .jsonl과 함께 쓸 jsonl 번들 폴더")
    ev.add_argument("--run", dest="labeler_run")

    it = sub.add_parser("intake", help="작업 폴더의 사람 교정을 교정 장부에 반영한다(LLM 0회)")
    ws(it)
    it.add_argument("--run", dest="labeler_run", help="라벨러 실행 ID(기본: 교정이 있는 모든 실행)")

    lg = sub.add_parser("ledger", help="교정 장부 상태 보기(status)와 규칙 후보 다시 만들기(rebuild)")
    ws(lg)
    lg.add_argument("action", choices=("status", "rebuild"))

    lr = sub.add_parser("labeling-rules", help="교정 장부 → 라벨링 규칙·few-shot 사례 후보와 사람 승인(LLM 0회)")
    ws(lr)
    lr.add_argument("action", choices=("candidates", "approve", "reject", "status"))
    lr.add_argument("--ids", action="append", help="approve·reject: 규칙 ID(FR-)·사례 ID(EX-), 쉼표로 여러 개")
    lr.add_argument("--all", action="store_true", help="approve·reject: 지금 규칙 후보 전부(approve는 상충 제외)")
    lr.add_argument("--examples", choices=("all", "none"), default="none", help="approve·reject: 사례 후보도 전부 같은 결정")

    c = sub.add_parser("codes", help="issue code 카탈로그를 .md로 낸다")
    c.add_argument("--out", help="출력 .md 경로(기본: engrbot/docs/issue_codes.md)")
    return p


def main(argv=None):
    from engrbot import policy as policy_mod
    from engrbot import runner

    args = _parser().parse_args(argv)
    if not args.cmd:
        _parser().print_help()
        return 2
    try:
        if args.cmd == "codes":
            return _codes(args)
        paths = io.QaPaths(args.workspace)
        if args.cmd == "run":
            layers = [x.strip() for x in args.layers.split(",")] if args.layers else None
            res = runner.run(paths, labeler_run_id=args.labeler_run, bundle_dir=args.bundle, layers=layers,
                             no_judge=args.no_judge, pass_sample=args.pass_sample)
            c = res.manifest["counts"]
            say("[run] qa_run_id=%s 레코드 %d (PASS %d, AUTO_FIX %d, REVIEW %d, REJECT %d)" % (
                res.qa_run_id, c["records"], c["PASS"], c["AUTO_FIX"], c["REVIEW"], c["REJECT"]))
            j = res.manifest["judge"]
            if res.manifest["judge_ran"]:
                say("[run] judge 호출 %d회 (캐시 %d회, 실패 %d건)" % (j["calls"], j["cache_hits"], j["failed"]))
            else:
                say("[run] judge 미실행(%s). judge를 거치지 않은 레코드는 PASS가 되지 않는다(PASS %d건)."
                    % (res.manifest["judge_skip_reason"], c["PASS"]))
            return 0
        if args.cmd == "report":
            from engrbot import report

            res = runner.reload(paths, args.qa_run, bundle_dir=args.bundle)
            report.write(res, append_history=False)
            say("[report] %s 리포트를 다시 만들었다(LLM 0회)." % args.qa_run)
            return 0
        if args.cmd == "baseline":
            from engrbot import report

            if args.action != "set":
                say("baseline set --qa-run <ID>")
                return 2
            res = runner.reload(paths, args.qa_run, bundle_dir=args.bundle)
            report.set_baseline(res)
            say("[baseline] %s를 기준선으로 올렸다." % args.qa_run)
            return 0
        if args.cmd == "review":
            from engrbot import screen

            res = runner.reload(paths, args.qa_run, bundle_dir=args.bundle, recompute_batch=False)
            n = screen.build(res, pass_sample=args.pass_sample)
            say("[review] 검토 화면을 만들었다(레코드 %d건)." % n)
            return 0
        if args.cmd == "golden":
            from engrbot import golden

            if args.action != "add":
                say("golden add --qa-run <ID>")
                return 2
            res = runner.reload(paths, args.qa_run, bundle_dir=args.bundle, recompute_batch=False)
            out = golden.add(res)
            say("[golden] 추가 %d건, 건너뜀 %d건." % (out["added"], out["skipped"]))
            return 0
        if args.cmd == "feedback":
            from engrbot import feedback

            res = runner.reload(paths, args.qa_run, bundle_dir=args.bundle, recompute_batch=False)
            out = feedback.build(res)
            say("[feedback] 교정 %d건, 재작업 %d건, 제안 %d건." % (
                len(out["corrections"]), len(out["rework"]), len(out["proposals"])))
            return 0
        if args.cmd == "eval":
            return _eval(args, paths)
        if args.cmd in ("intake", "ledger"):
            return _ledger(args, paths)
        if args.cmd == "labeling-rules":
            from engrbot import labeling_rules

            return labeling_rules.main_cli(args, paths, say)
    except (io.QaPathError, runner.RunError, model.BundleError, policy_mod.PolicyError) as e:
        say("[오류] %s" % e)
        return 1
    return 2


def _skipped_text(skipped):
    return ", ".join("%s %d" % (k, v) for k, v in sorted((skipped or {}).items())) or "없음"


def _ledger_line(st):
    return "[ledger] 누적 작업 폴더 %d, 사례 %d, 골든 %d, judge 예시 %d, L4 후보 %d → %s" % (
        st["sources"], st["cases"], st["golden"], st["examples"], st["candidates"], st["dir"])


def _ledger(args, paths):
    """intake, ledger status|rebuild. 건수·코드·작업 폴더 이름만 낸다. 장부 오류는 [오류] <코드>, 종료 코드 1."""
    from engrbot import ledger

    try:
        return _ledger_cmd(args, paths, ledger)
    except ledger.LedgerError as e:
        say("[오류] %s" % e.reason_code)
        return 1


def _ledger_cmd(args, paths, ledger):
    from engrbot import policy as policy_mod

    pol, sch = policy_mod.load(paths)
    if args.cmd == "intake":
        out = ledger.intake(paths.root, pol, args.labeler_run, schema=sch)
        if out.get("reason"):
            what = "이 작업 폴더의 장부 행을 지웠다" if out["changed"] else "장부에 이 작업 폴더 행이 없다(그대로)"
            say("[intake] %s: %s." % (out["reason"], what))
        else:
            say("[intake] 교정 %d건 → 사례 %d(교정 %d, 확인 %d), 골든 %d, judge 예시 %d, 동의어 %d, 재검토 %d"
                " / 건너뜀 %s" % (out["corrections"], out["cases"], out["corrected"], out["confirmed"],
                                 out["golden"], out["examples"], out["synonyms"], out["revisits"],
                                 _skipped_text(out["skipped"])))
        say(_ledger_line(out["totals"]))
        return 0
    d = ledger.ledger_dir(paths.root, pol)
    if args.action == "rebuild":
        changed = ledger.rebuild(d, pol)
        say("[ledger] 규칙 후보를 다시 만들었다(%s)." % ("바뀜" if changed else "그대로"))
    st = ledger.status(d)
    say(_ledger_line(st))
    if args.action == "status":
        for s in st["per_source"]:
            c = s["counts"]
            say("[ledger] %s: 실행 %d, 사례 %d(교정 %d, 확인 %d), 골든 %d, judge 예시 %d, 동의어 %d, 재검토 %d" % (
                s["source_ws"], s["runs"], c.get("cases", 0), c.get("corrected", 0), c.get("confirmed", 0),
                c.get("golden", 0), c.get("examples", 0), c.get("synonyms", 0), c.get("revisits", 0)))
    return 0


def _codes(args):
    from engrbot import codes

    out = args.out or codes.DOC_PATH
    io.write_text(out, codes.render_md() + "\n")
    say("[codes] 카탈로그 문서를 만들었다.")
    return 0


def _eval(args, paths):
    from engrbot import harness
    from engrbot import policy as policy_mod
    from engrbot import runner

    pol, sch = policy_mod.load(paths)
    g = args.golden
    if g.startswith("synthetic"):
        from engrbot.tests import fixturegen

        seed = int(g.split(":", 1)[1]) if ":" in g else 7
        bundle = fixturegen.generate(seed=seed).bundle
    else:
        from engrbot import golden

        if g == "ledger":
            from engrbot import ledger

            try:
                rows = ledger.read_golden(ledger.ledger_dir(paths.root, pol))
            except ledger.LedgerError as e:
                say("[오류] %s" % e.reason_code)
                return 1
        else:
            rows = io.read_own_jsonl(g)
        base = runner.load_bundle(paths, args.labeler_run, args.bundle)
        bundle = golden.to_bundle(rows, base)
        # 골든셋 행은 사람이 결정한 필드만 담는다. 빠진 활성 축을 오탐으로 세지 않는다.
        sch = dict(sch, rules=dict(sch["rules"], all_active_axes_required=False))
    llm = None
    if args.judge == "mock":
        from engrbot.llm import MockJudgeLLM

        llm = MockJudgeLLM()
    else:
        pol = dict(pol, judge=dict(pol["judge"], transport="http"))
    res = harness.evaluate(bundle, pol, sch, llm=llm, per_mutator=args.per_mutator, paths=paths)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")
    base_path = paths.q("eval_%s" % stamp)
    harness.write_report(res, base_path)
    say("[eval] 층별 탐지율 %s, 오탐률 %.3f" % (
        # 주입 0건인 층(작은 골든셋)은 recall이 None이다
        ", ".join("%s=%s" % (k, "-" if v["recall"] is None else "%.2f" % v["recall"])
                  for k, v in sorted(res["layers"].items())), res["false_positive_rate"]))
    return 0
