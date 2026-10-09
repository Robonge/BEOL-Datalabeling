"""Domain-Engr-bot 명령: 검수 결과로 엔지니어에게 질문해 도메인 지식을 규칙·taxonomy 제안으로 돌려준다.
실행: python -m domain_engrbot <명령> --workspace <작업 폴더>

콘솔에는 실행 ID, 건수, 코드만 낸다. 본문, 파일명, 경로는 내지 않는다.
"""
import argparse
import datetime
import json
import os
import re
import sys

from domain_engrbot import io, model, trace

_CODE = re.compile(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+")


def say(msg):
    """stdout 한 줄. "[오류] <코드>" 줄이면 그 코드를 지금 마일스톤의 사유로 남긴다(반환값은 그대로)."""
    print(msg, file=sys.stdout, flush=True)
    if msg.startswith("[오류] "):
        m = _CODE.search(msg)
        trace.fail_code(m.group(0) if m else "RC_1")


def _parser():
    p = argparse.ArgumentParser(prog="python -m domain_engrbot", description="Domain-Engr-bot: 검수 결과로 엔지니어에게 질문해 도메인 지식을 규칙·taxonomy 제안으로 돌려준다")
    sub = p.add_subparsers(dest="cmd")

    def ws(sp):
        sp.add_argument("--workspace", required=True, help="labelbot 작업 폴더(코드 폴더의 workspaces/ 아래)")

    r = sub.add_parser("run", help="검사, 판정, 대기열, 리포트, 검토 화면 (옛 QA 흐름. 스킬은 부르지 않음)")
    ws(r)
    r.add_argument("--run", dest="labeler_run", help="라벨러 실행 ID(기본: 최근 run)")
    r.add_argument("--bundle", help="jsonl 번들 폴더(labelbot 작업 DB 대신)")
    r.add_argument("--layers", help="예: L0,L1,L2")
    r.add_argument("--no-judge", action="store_true", help="L3b judge를 부르지 않는다(이 실행의 PASS는 0건)")
    r.add_argument("--pass-sample", type=int, default=0, help="검토 화면에 올릴 PASS 표본 수")

    rp = sub.add_parser("report", help="verdicts.jsonl에서 리포트를 다시 만든다(LLM 0회) (옛 QA 흐름. 스킬은 부르지 않음)")
    ws(rp)
    rp.add_argument("--qa-run", required=True)
    rp.add_argument("--bundle")

    b = sub.add_parser("baseline", help="L6 기준선 (옛 QA 흐름. 스킬은 부르지 않음)")
    bsub = b.add_subparsers(dest="action")
    bs = bsub.add_parser("set", help="검수 실행을 기준선으로 올린다")
    ws(bs)
    bs.add_argument("--qa-run", required=True)
    bs.add_argument("--bundle")

    rv = sub.add_parser("review", help="검토 화면 review.html을 다시 만든다 (옛 QA 흐름. 스킬은 부르지 않음)")
    ws(rv)
    rv.add_argument("--qa-run", required=True)
    rv.add_argument("--pass-sample", type=int, default=0)
    rv.add_argument("--bundle")

    sv = sub.add_parser("serve", help="검토 화면 서버. 검수 완료 결정을 qa/inbox/에 바로 쓴다 (옛 QA 흐름. 스킬은 부르지 않음)")
    ws(sv)
    sv.add_argument("--qa-run", help="검수 실행 ID(기본: 가장 최근 실행)")
    sv.add_argument("--port", type=int, help="포트(기본: 실행 ID로 정한 8700~8899, 쓰고 있으면 빈 포트)")

    sub.add_parser("workspaces", help="작업 폴더 목록과 검수 상태(JSON, 사람이 고를 때 쓴다)")

    g = sub.add_parser("golden", help="골든셋 (옛 QA 흐름. 스킬은 부르지 않음)")
    gsub = g.add_subparsers(dest="action")
    ga = gsub.add_parser("add", help="qa/inbox 결정과 corrections를 골든셋에 추가한다")
    ws(ga)
    ga.add_argument("--qa-run", required=True)
    ga.add_argument("--bundle")

    fb = sub.add_parser("feedback", help="승인된 결정만 모아 피드백 묶음을 만든다 (옛 QA 흐름. 스킬은 부르지 않음)")
    ws(fb)
    fb.add_argument("--qa-run", required=True)
    fb.add_argument("--bundle")

    ev = sub.add_parser("eval", help="mutation 하네스(층별 탐지율, 오탐률) (옛 QA 흐름. 스킬은 부르지 않음)")
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
    lr.add_argument("action", choices=("candidates", "approve", "reject", "status", "review", "apply"),
                    help="review: 최종 검수 화면(labeling_review.html), apply: 화면의 결정 JSON 반영")
    lr.add_argument("--ids", action="append", help="approve·reject: 규칙 ID(FR-)·사례 ID(EX-), 쉼표로 여러 개")
    lr.add_argument("--all", action="store_true", help="approve·reject: 지금 규칙 후보 전부(approve는 상충 제외)")
    lr.add_argument("--examples", choices=("all", "none"), default="none", help="approve·reject: 사례 후보도 전부 같은 결정")
    lr.add_argument("--decisions", help="apply: 최종 검수 화면에서 저장한 결정 JSON(labeling_decisions_*.json)")

    qs = sub.add_parser("questions", help="도메인 질문 루프: 검수 결과 → 엔지니어 질문(LLM) → 질문 화면 → 확정 답 반영")
    ws(qs)
    qs.add_argument("action", choices=("generate", "status", "screen", "serve", "apply"),
                    help="generate: 질문 묶음, status: 건수, screen: 화면만 다시, serve: 질문 서버, apply: 답 파일 반영")
    qs.add_argument("--force", action="store_true", help="generate: 입력이 그대로여도 LLM을 다시 부른다")
    qs.add_argument("--max", type=int, help="generate: 묶음의 질문 수 상한(기본: policy questions.max, 10)")
    qs.add_argument("--port", type=int, help="serve: 포트(기본: set_id로 정한 8900~9099, 쓰고 있으면 빈 포트)")
    qs.add_argument("--no-draft", action="store_true", help="serve: 자유 답 초안 만들기(LLM)를 끈다")
    qs.add_argument("--no-apply", action="store_true",
                    help="serve: '답변 완료 · 저장' 때 저장만 하고 반영하지 않는다(기본: 저장하자마자 반영하고 서버를 닫는다)")
    qs.add_argument("--answers", help="apply: 답 파일(기본: qa/inbox의 engr_answers_*.json 중 가장 최근 것)")

    tb = sub.add_parser("taxonomy-board",
                        help="taxonomy 수정 보드: 흩어진 수정 제안을 한 화면에 모으고, 고른 것만 taxonomy.json에 반영(LLM 0회)")
    tb.add_argument("--workspace", action="append", help="작업 폴더(여러 번 가능, 기본: workspaces/ 아래 전부)")
    tb.add_argument("--taxonomy", help="taxonomy.json 경로(기본: 저장소 taxonomy/taxonomy.json)")
    tb.add_argument("--out-dir", help="출력 폴더(기본: workspaces/_domain_engrbot/taxonomy_board)")
    tb.add_argument("--open", action="store_true", help="보드를 브라우저로 연다(--serve면 서버 주소)")
    tb.add_argument("--reset", action="store_true", help="지금 항목을 모두 초기화(화면에서 뺀다). 새로 올라오는 제안만 다시 보인다")
    tb.add_argument("--serve", action="store_true",
                    help="보드 서버(127.0.0.1)로 연다. 화면의 '최종 완료'가 변경 미리보기를 보여 주고 확인하면 taxonomy.json에 쓴다")

    te = sub.add_parser("taxonomy-editor",
                        help="taxonomy 편집기: taxonomy.json(taxonomy·questions·synonyms)을 보고 고친다(127.0.0.1, LLM 0회)")
    te.add_argument("--taxonomy", help="taxonomy.json 경로(기본: 저장소 taxonomy/taxonomy.json)")
    te.add_argument("--port", type=int, help="포트(기본 8796, 쓰고 있으면 빈 포트)")
    te.add_argument("--open", action="store_true", help="브라우저로 편집기를 연다")

    c = sub.add_parser("codes", help="issue code 카탈로그를 .md로 낸다")
    c.add_argument("--out", help="출력 .md 경로(기본: domain_engrbot/docs/issue_codes.md)")
    return p


def _run(args, paths):
    from domain_engrbot import runner

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


def _report(args, paths):
    from domain_engrbot import report, runner

    res = runner.reload(paths, args.qa_run, bundle_dir=args.bundle)
    report.write(res, append_history=False)
    say("[report] %s 리포트를 다시 만들었다(LLM 0회)." % args.qa_run)
    return 0


def _baseline(args, paths):
    from domain_engrbot import report, runner

    if args.action != "set":
        say("baseline set --qa-run <ID>")
        return 2
    res = runner.reload(paths, args.qa_run, bundle_dir=args.bundle)
    report.set_baseline(res)
    say("[baseline] %s를 기준선으로 올렸다." % args.qa_run)
    return 0


def _review(args, paths):
    from domain_engrbot import runner, screen

    res = runner.reload(paths, args.qa_run, bundle_dir=args.bundle, recompute_batch=False)
    n = screen.build(res, pass_sample=args.pass_sample)
    say("[review] 검토 화면을 만들었다(레코드 %d건)." % n)
    return 0


def _serve(args, paths):
    from domain_engrbot import serve

    qa = args.qa_run or (paths.list_runs() or [None])[-1]
    if not qa or not os.path.isdir(paths.run_dir(qa)):
        say("[오류] QA_RUN_NOT_FOUND")
        return 1
    if not os.path.isfile(os.path.join(paths.run_dir(qa), "review.html")):
        say("[오류] REVIEW_SCREEN_MISSING (review --qa-run %s로 다시 만든다)" % qa)
        return 1
    return serve.serve(paths, qa, args.port)


def _workspaces():
    from domain_engrbot import workspaces

    say(json.dumps({"workspaces": workspaces.scan(), "questions": workspaces.questions_summary()}, ensure_ascii=False))
    return 0


def _golden(args, paths):
    from domain_engrbot import golden, runner

    if args.action != "add":
        say("golden add --qa-run <ID>")
        return 2
    res = runner.reload(paths, args.qa_run, bundle_dir=args.bundle, recompute_batch=False)
    out = golden.add(res)
    say("[golden] 추가 %d건, 건너뜀 %d건." % (out["added"], out["skipped"]))
    return 0


def _feedback(args, paths):
    from domain_engrbot import feedback, runner

    res = runner.reload(paths, args.qa_run, bundle_dir=args.bundle, recompute_batch=False)
    out = feedback.build(res)
    say("[feedback] 교정 %d건, 재작업 %d건, 제안 %d건." % (
        len(out["corrections"]), len(out["rework"]), len(out["proposals"])))
    return 0


def _labeling_rules(args, paths):
    if args.action in ("review", "apply"):
        from domain_engrbot import labeling_review

        return labeling_review.main_cli(args, paths, say)
    from domain_engrbot import labeling_rules

    return labeling_rules.main_cli(args, paths, say)


def _questions(args, paths):
    from domain_engrbot import questions

    return questions.main_cli(args, paths, say)


def main(argv=None):
    """명령 하나를 마일스톤(M11 DOMAIN_QA, taxonomy 보드·편집기 M12, 목록 M00) 안에서 돌린다."""
    from domain_engrbot import policy as policy_mod
    from domain_engrbot import runner

    args = _parser().parse_args(argv)
    if not args.cmd:
        _parser().print_help()
        return 2
    milestones = trace.milestones
    key = ("domain_engrbot", args.cmd, getattr(args, "action", None) if args.cmd in ("baseline", "golden") else None)
    ws = getattr(args, "workspace", None)
    return trace.run(milestones.lookup(*key)[0], lambda: _main(args, policy_mod, runner),
                     workspace=ws if isinstance(ws, str) else None, quiet=milestones.is_quiet(*key))


def _main(args, policy_mod, runner):
    commands = {"run": _run, "report": _report, "baseline": _baseline, "review": _review, "golden": _golden,
                "feedback": _feedback, "eval": _eval, "intake": _ledger, "ledger": _ledger,
                "labeling-rules": _labeling_rules, "serve": _serve, "questions": _questions}
    try:
        if args.cmd == "codes":
            return _codes(args)
        if args.cmd == "workspaces":
            return _workspaces()
        if args.cmd == "taxonomy-board":
            from domain_engrbot import taxonomy_board

            return taxonomy_board.main_cli(args, say)
        if args.cmd == "taxonomy-editor":
            from domain_engrbot import taxonomy_editor

            return taxonomy_editor.main_cli(args, say)
        paths = io.QaPaths(args.workspace)
        if args.cmd in commands:
            return commands[args.cmd](args, paths)
    except (io.QaPathError, runner.RunError, model.BundleError, policy_mod.PolicyError) as e:
        say("[오류] %s" % e)
        return 1
    return 2


def _skipped_text(skipped):
    return ", ".join("%s %d" % (k, v) for k, v in sorted((skipped or {}).items())) or "없음"


def _ledger_line(st):
    return "[ledger] 누적 작업 폴더 %d, 사례 %d(근거 있음 %d), 골든 %d, judge 예시 %d, L4 후보 %d → %s" % (
        st["sources"], st["cases"], st.get("evidence", 0), st["golden"], st["examples"], st["candidates"], st["dir"])


def _ledger(args, paths):
    """intake, ledger status|rebuild. 건수·코드·작업 폴더 이름만 낸다. 장부 오류는 [오류] <코드>, 종료 코드 1."""
    from domain_engrbot import ledger

    try:
        return _ledger_cmd(args, paths, ledger)
    except ledger.LedgerError as e:
        say("[오류] %s" % e.reason_code)
        return 1


def _ledger_cmd(args, paths, ledger):
    from domain_engrbot import policy as policy_mod

    pol, sch = policy_mod.load(paths)
    if args.cmd == "intake":
        out = ledger.intake(paths.root, pol, args.labeler_run, schema=sch)
        if out.get("reason"):
            what = "이 작업 폴더의 장부 행을 지웠다" if out["changed"] else "장부에 이 작업 폴더 행이 없다(그대로)"
            say("[intake] %s: %s." % (out["reason"], what))
        else:
            say("[intake] 교정 %d건 → 사례 %d(교정 %d, 확인 %d, 근거 있음 %d), 골든 %d, judge 예시 %d, 동의어 %d, 재검토 %d"
                " / 건너뜀 %s" % (out["corrections"], out["cases"], out["corrected"], out["confirmed"],
                                 out.get("evidence", 0), out["golden"], out["examples"], out["synonyms"], out["revisits"],
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
    from domain_engrbot import codes

    out = args.out or codes.DOC_PATH
    io.write_text(out, codes.render_md() + "\n")
    say("[codes] 카탈로그 문서를 만들었다.")
    return 0


def _eval(args, paths):
    from domain_engrbot import harness
    from domain_engrbot import policy as policy_mod
    from domain_engrbot import runner

    pol, sch = policy_mod.load(paths)
    g = args.golden
    if g.startswith("synthetic"):
        from domain_engrbot import synthetic

        seed = int(g.split(":", 1)[1]) if ":" in g else 7
        bundle = synthetic.generate(seed=seed).bundle
    else:
        from domain_engrbot import golden

        if g == "ledger":
            from domain_engrbot import ledger

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
        from domain_engrbot.llm import MockJudgeLLM

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
