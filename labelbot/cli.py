"""명령 진입점: python -m labelbot <명령> --workspace <작업 폴더>."""
import argparse
import json
import os
import sys

from labelbot import milestones, status, store, trace
from labelbot.workspace import Workspace, WorkspaceError, load_env_file


def _parser():
    p = argparse.ArgumentParser(prog="labelbot", description="BEOL 자료 자동 라벨링 (사외 구동 기준)")
    sub = p.add_subparsers(dest="command", required=True)

    def add(name, help_text):
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("--workspace", required=True, help="작업 폴더(코드 폴더의 workspaces/ 아래)")
        return sp

    sc = add("selfcheck", "환경 점검")
    sc.add_argument("--probe-llm", action="store_true", help="고정 probe 문장으로 LLM을 1회 호출")
    pr = add("probe", "파일 구조 통계(본문 미출력)")
    pr.add_argument("--input", help="입력 폴더(기본: 작업 폴더 raw/)")
    for name, h in (("ingest", "수집·파싱·chunk"), ("run", "전 단계 실행")):
        sp = add(name, h)
        sp.add_argument("--input", help="입력 폴더(기본: pipeline.json input_root 또는 작업 폴더 raw/)")
        if name == "run":
            sp.add_argument("--no-feedback", action="store_true", help="승인된 검수 피드백 규칙·사례를 이번 실행에 넣지 않는다")
    for name, h in (("compare", "파싱 대조 화면"), ("review", "불량 목록과 검수 화면"), ("report", "기준선 리포트 재계산"),
                    ("dashboard", "결과 대시보드 화면"),
                    ("embed", "chunk 임베딩"), ("push-vectors", "Supabase 벡터 적재"),
                    ("slide-images", "슬라이드 미리보기 JPG 렌더(slide_images/*.b64)"),
                    ("push-slides", "슬라이드 JPG를 Supabase Storage에 올리고 행에 slide_image_* 기록")):
        sp = add(name, h)
        sp.add_argument("--run", help="실행 ID(기본: 최신)")
        if name == "push-vectors":
            sp.add_argument("--force", action="store_true",
                            help="rules-update 변경 비율 상한(RULES_CHANGE_RATIO_HIGH)으로 막힌 적재를 확인 뒤 보낸다")
    ap = add("apply", "inbox/의 교정·대조 .json 반영")
    ap.add_argument("--kind", choices=("review", "compare"), help="이 종류의 파일만 반영(review: 검수, compare: 파싱 대조)")
    add("taxonomy-diff", "마지막 실행 대비 taxonomy 축 변경(추가·삭제·종류/설정·값)")
    au = add("axis-update", "taxonomy 축 변경분만 1차 분류로 다시 라벨링(이전 실행 이어받기, 입력 폴더를 읽지 않음)")
    au.add_argument("--dry-run", action="store_true", help="대상·삭제 축과 건수(plan JSON)만 출력하고 실행을 만들지 않는다")
    au.add_argument("--no-feedback", action="store_true", help="승인된 검수 피드백 규칙·사례를 이번 실행에 넣지 않는다")
    add("rules-diff", "마지막 라벨 실행 대비 라벨링 규칙 변경(추가·수정·끄기·기각)과 다시 라벨할 범위")
    ru = add("rules-update", "라벨링 규칙 변경분만 다시 라벨링(축 규칙은 그 축 1차, 답 규칙은 그 질문 3차, 사람 검수 없이 반영)")
    ru.add_argument("--dry-run", action="store_true", help="바뀐 규칙·대상 건수(plan JSON)만 출력하고 실행을 만들지 않는다")
    ab = add("axis-board", "축 변경 현황판(screens/axis_update.html): 대상 축 카드와 슬라이드별 새 축 값")
    ab.add_argument("--run", help="axis-update 실행 ID(기본: 최신 라벨 실행)")
    rb = add("rules-board", "규칙 변경 현황판(screens/rules_update.html): 바뀐 규칙 카드와 값이 바뀐 슬라이드(이전 → 지금)")
    rb.add_argument("--run", help="rules-update 실행 ID(기본: 최신 라벨 실행)")
    sv = add("serve","화면 서버(screens/ 제공, 검수·대조 JSON을 inbox/에 저장)")
    sv.add_argument("--port", type=int, default=8770, help="포트(127.0.0.1 전용)")
    mg = sub.add_parser("taxonomy-migrate", help="예전 taxonomy.xlsx를 taxonomy.json으로 1회 변환(작업 폴더 pipeline.json 경로도 바꿈)")
    mg.add_argument("--xlsx", help="변환할 xlsx(기본: 코드 폴더 taxonomy/taxonomy.xlsx)")
    mg.add_argument("--out", help="쓸 JSON(기본: xlsx와 같은 폴더·이름의 .json)")
    mg.add_argument("--force", action="store_true", help="JSON이 이미 있으면 덮어쓴다")
    st = sub.add_parser("status", help="마일스톤 상태 표: 처음 실패한 단계·사유 코드·다음에 할 일(읽기 전용)")
    status.add_status_args(st)
    cd = sub.add_parser("codes", help="사유 코드 카탈로그(원인·조치)와 진입점 → 마일스톤 표")
    status.add_codes_args(cd)
    return p


def main(argv=None):
    """모든 출구(taxonomy-migrate, 작업 폴더 오류, 작업 폴더 명령, 실행 명령)를 마일스톤 하나로 감싼다.
    argparse 종료(SystemExit)는 그대로 지나가고, 잡히지 않은 예외는 실패 블록 + 종료 코드 1이다.
    run은 run_all의 M01–M04가 각자 줄을 내므로 CLI 줄을 내지 않는다(실패만 M01로 받는다)."""
    args = _parser().parse_args(argv)
    key = ("labelbot", args.command)
    quiet = milestones.is_quiet(*key) or args.command == "run"
    return trace.run(milestones.lookup(*key)[0], lambda: _main(args), quiet=quiet, defer=True)


def _main(args):
    if args.command == "status":
        return status.cmd_status(args)
    if args.command == "codes":
        return status.cmd_codes(args)
    load_env_file()
    if args.command == "taxonomy-migrate":
        trace.begin()
        return _cmd_taxonomy_migrate(args)
    try:
        ws = Workspace(args.workspace)
    except WorkspaceError as e:
        msg = {"WORKSPACE_INSIDE_CODE": "작업 폴더는 코드 폴더의 workspaces/ 아래에만 둘 수 있습니다."}.get(str(e), str(e))
        print("[오류] %s" % msg, file=sys.stderr)
        trace.fail_code(trace.safe_code(str(e)) or "WORKSPACE_INVALID")  # 작업 폴더가 없으니 workspaces/_trace/에 기록
        return 2
    trace.set_workspace(ws)
    from labelbot.pipeline import PipelineError

    try:
        if args.command in _WS_COMMANDS:
            trace.begin()
            return _WS_COMMANDS[args.command](ws, args)
        con = store.connect(ws.work_db)
        try:
            run_id = getattr(args, "run", None) or _default_run(con)
            if args.command != "apply" and not run_id:
                raise PipelineError("실행 기록이 없습니다. 먼저 run 또는 ingest를 실행하세요.", reason_code="RUN_RECORD_MISSING")
            trace.set_run(run_id)
            trace.begin()
            rc = _RUN_COMMANDS[args.command](ws, con, run_id, args)
        finally:
            con.close()
        return rc or 0
    except PipelineError as e:
        print("[오류] %s" % e, file=sys.stderr)
        trace.fail_code(e.reason_code or "PIPELINE_ERROR", e.detail)
        return 1


def _default_run(con):
    """기본 --run: 끝난 최신 실행. 더 최신의 미완료 실행을 건너뛰면 stderr에 사유 코드 한 줄을 낸다."""
    run_id, newest = store.latest_run(con), store.latest_run(con, finished=False)
    if run_id and newest and newest != run_id:
        print("[run] LATEST_UNFINISHED_SKIPPED %s" % newest, file=sys.stderr)
    return run_id


# ---- 작업 폴더만 쓰는 명령: (ws, args) → 종료 코드 ----------------------------------

def _cmd_selfcheck(ws, args):
    from labelbot import selfcheck

    ok, _ = selfcheck.run(ws, probe_llm=args.probe_llm)
    if not ok:
        trace.fail_code("SELFCHECK_FAILED")
    return 0 if ok else 1


def _cmd_probe(ws, args):
    return _probe(ws, args.input or ws.input_root)


def _cmd_taxonomy_diff(ws, args):
    from labelbot import taxdiff
    from labelbot.pipeline import load_taxonomy, say

    tax, _ = load_taxonomy(ws)
    d, run_id = taxdiff.compare_workspace(ws, tax)
    say(json.dumps(dict(d, run_id=run_id), ensure_ascii=False))
    say(taxdiff.summary_line(d))
    return 0


def _cmd_taxonomy_migrate(args):
    """건수·코드·작업 폴더 이름만 낸다(셀 내용은 내지 않는다)."""
    from labelbot import taxmigrate
    from labelbot.workspace import CODE_ROOT, WORKSPACES_DIR

    src = os.path.abspath(args.xlsx) if args.xlsx else os.path.join(CODE_ROOT, "taxonomy", "taxonomy.xlsx")
    try:
        res = taxmigrate.migrate(src, os.path.abspath(args.out) if args.out else None, WORKSPACES_DIR, force=args.force)
    except taxmigrate.MigrateError as e:
        print("[오류] %s%s" % (e.reason_code, " %s" % e.detail if e.detail else ""), file=sys.stderr)
        trace.fail_code(e.reason_code, trace.safe_code(e.detail))
        return 1
    r, d = res["rows"], res["dropped"]
    print("[taxonomy-migrate] taxonomy %d행 · questions %d행 · synonyms %d행 · rejected %d행, 시트 해시 같음"
          % (r["taxonomy"], r["questions"], r["synonyms"], res["rejected"]))
    if d["files"] or d["queries"]:
        print("[taxonomy-migrate] 버린 행: files %d(제외=Y %d) · queries %d" % (d["files"], d["files_excluded"], d["queries"]))
    if res["warnings"]:
        print("[taxonomy-migrate] 경고 코드: %s" % ", ".join(res["warnings"]))
    print("[taxonomy-migrate] pipeline.json 경로 바꾼 작업 폴더 %d: %s" % (len(res["workspaces"]), ", ".join(res["workspaces"]) or "-"))
    for name, code in res["skipped"]:
        print("[taxonomy-migrate] 건너뜀 %s %s" % (name, code))
    return 0


def _cmd_axis_update(ws, args):
    from labelbot.pipeline import run_axis_update, say

    p, run_id, _ = run_axis_update(ws, use_feedback=not args.no_feedback, dry_run=args.dry_run)
    if args.dry_run:
        say(json.dumps({k: p[k] for k in ("code", "prev_run", "target", "removed", "values_added_only", "chunks",
                                         "dropped_answers", "dropped_corrections")}, ensure_ascii=False))
        if p["code"]:
            trace.skip_code(p["code"])
        return 3 if p["code"] else 0
    if p["code"]:
        say("[axis-update] 건너뜀 %s" % p["code"])
        trace.skip_code(p["code"])
        return _skip_code(p["code"])
    return 0


def _skip_code(code):
    """건너뜀 종료 코드: 잠금을 잃음(AXIS_UPDATE_LOCK_LOST)은 4, 그 밖의 멈춤 사유는 3."""
    from labelbot import axisupdate

    return 4 if code == axisupdate.AXIS_UPDATE_LOCK_LOST else 3


def _cmd_rules_diff(ws, args):
    from labelbot import feedback, rulesdiff
    from labelbot.pipeline import PipelineError, load_taxonomy, say

    tax, _ = load_taxonomy(ws)
    con = store.connect(ws.work_db)
    try:
        res = rulesdiff.compare(ws, con, tax)
    except feedback.FeedbackError as e:
        raise PipelineError("검수 피드백 규칙 파일(labeling_rules.json) 오류: %s" % e,
                            reason_code="LABELING_RULES_INVALID", detail=trace.safe_code(str(e)))
    finally:
        con.close()
    say(json.dumps(rulesdiff.public(res), ensure_ascii=False))
    say(rulesdiff.summary_line(res))
    # 변경이 있으면 0(축 없는 규칙만 바뀐 STAGE_WIDE_ONLY 포함), 없거나 기준을 모르면 3
    if res["code"] not in (None, rulesdiff.STAGE_WIDE_ONLY):
        trace.skip_code(res["code"])
    return 0 if res["code"] in (None, rulesdiff.STAGE_WIDE_ONLY) else 3


def _cmd_rules_update(ws, args):
    from labelbot import rulesupdate
    from labelbot.pipeline import run_rules_update, say

    p, run_id, _ = run_rules_update(ws, dry_run=args.dry_run)
    if args.dry_run:
        say(json.dumps(rulesupdate.summary(p), ensure_ascii=False))
        if p["code"]:
            trace.skip_code(p["code"])
        return 3 if p["code"] else 0
    if p["code"]:
        say("[rules-update] 건너뜀 %s%s" % (p["code"], rulesupdate.skip_reason(p)))
        trace.skip_code(p["code"])
        return _skip_code(p["code"])
    return 0


def _cmd_serve(ws, args):
    from labelbot import serve

    return serve.serve(ws, args.port)


def _cmd_ingest(ws, args):
    from labelbot.pipeline import run_ingest

    run_ingest(ws, args.input or ws.input_root)
    return 0


def _cmd_run(ws, args):
    from labelbot.pipeline import run_all

    run_all(ws, args.input or ws.input_root, use_feedback=not args.no_feedback)
    return 0


# ---- work.sqlite와 실행 ID를 쓰는 명령: (ws, con, run_id, args) ----------------------

def _cmd_compare(ws, con, run_id, args):
    from labelbot import review
    from labelbot.pipeline import say

    path, n = review.build_compare(ws, con, run_id)
    say("[compare] chunk %d개 → screens/compare.html" % n)


def _cmd_review(ws, con, run_id, args):
    from labelbot import review
    from labelbot.pipeline import load_taxonomy, say

    tax, _ = load_taxonomy(ws)
    rows = review.compute_flags(con, run_id, ws.config, tax, ws.path("reports"))
    path, n = review.build_review(ws, con, run_id, tax)
    say("[review] run_id=%s 불량 chunk %d개 → screens/review.html, reports/flagged_%s.*" % (run_id, n, run_id))


def _cmd_apply(ws, con, run_id, args):
    from labelbot import candidates, review, revisit
    from labelbot.pipeline import Ctx, load_taxonomy, say

    tax, _ = load_taxonomy(ws)
    rv_runs = []
    results = review.apply_inbox(ws, con, tax, kind=args.kind, revisit_runs=rv_runs)
    if not results:
        say("[apply] inbox/에 반영할 %s 파일이 없습니다." % ({"review": "검수(review_*.json)", "compare": "파싱 대조(compare_*.json)"}.get(args.kind, ".json")))
    for sha, code, n, kind, rid in results:
        say("[apply] %s 파일 %s run_id=%s: %s (%d건)" % (kind or "?", sha, rid or "-", code, n))
    latest = store.latest_run(con)
    if latest:
        candidates.write_reports(Ctx(ws, con, latest, tax=tax))
    else:
        revisit.write_reports(ws, con, tax)
    say("[apply] taxonomy 재검토 요청 누적 %d건 → reports/taxonomy_revisit.md" % revisit.count(con))
    # 이번 apply에서 반영한 검수 실행별 파일(taxonomy.xlsx 옆 폴더). 요청 0건·revisits 없는 파일은 쓰지 않는다.
    rv_dir = revisit.requests_dir(ws)
    written = revisit.write_run_files(rv_dir, con, tax, rv_runs)
    if written:
        say("[apply] taxonomy 재검토 요청 파일 %d개 → %s/%s/" % (
            len(written), os.path.basename(os.path.dirname(rv_dir)), os.path.basename(rv_dir)))


def _cmd_axis_board(ws, con, run_id, args):
    from labelbot import axisboard
    from labelbot.pipeline import PipelineError, load_taxonomy, say

    run_id = args.run or store.latest_label_run(con, finished=True)
    tax, _ = load_taxonomy(ws)
    try:
        path, n_axes, n_slides = axisboard.build_board(ws, con, run_id, tax)
    except axisboard.BoardError as e:
        raise PipelineError("run_id=%s는 axis-update 실행이 아닙니다(%s). --run으로 axis-update 실행 ID를 주세요." % (run_id, e),
                            reason_code="AXIS_BOARD_RUN_INVALID", detail=trace.safe_code(str(e)))
    say("[axis-board] run_id=%s 대상 축 %d개, 슬라이드 %d개 → screens/axis_update.html" % (run_id, n_axes, n_slides))


def _cmd_rules_board(ws, con, run_id, args):
    from labelbot import rulesboard
    from labelbot.pipeline import PipelineError, load_taxonomy, say

    run_id = args.run or store.latest_label_run(con, finished=True)
    tax, _ = load_taxonomy(ws)
    try:
        path, n_rules, n_slides = rulesboard.build_board(ws, con, run_id, tax)
    except rulesboard.BoardError as e:
        raise PipelineError("run_id=%s는 rules-update 실행이 아닙니다(%s). --run으로 rules-update 실행 ID를 주세요." % (run_id, e),
                            reason_code="RULES_BOARD_RUN_INVALID", detail=trace.safe_code(str(e)))
    say("[rules-board] run_id=%s 규칙 카드 %d개, 바뀐 슬라이드 %d개 → screens/rules_update.html" % (run_id, n_rules, n_slides))


def _cmd_dashboard(ws, con, run_id, args):
    from labelbot import dashboard
    from labelbot.pipeline import load_taxonomy, say

    tax, _ = load_taxonomy(ws)
    path, n = dashboard.build_results(ws, con, run_id, tax)
    say("[dashboard] chunk %d개 → screens/results.html" % n)


def _cmd_report(ws, con, run_id, args):
    from labelbot import report, revisit
    from labelbot.pipeline import load_taxonomy, say

    tax, _ = load_taxonomy(ws)
    path = report.write_report(ws, con, run_id, tax)
    say("[report] reports/%s" % os.path.basename(path))
    n = revisit.write_reports(ws, con, tax)
    say("[report] taxonomy 재검토 요청 누적 %d건 → reports/taxonomy_revisit.md" % n)


def _since(con):
    return con.execute("SELECT COALESCE(MAX(id), 0) FROM failures").fetchone()[0]


def _target_failures(con, run_id, stages, since, all_failed=False):
    """이 명령이 남긴 대상별 실패(failures, id > since)를 마일스톤에 붙인다: 전부 실패면 실패, 일부면 부분 실패.
    반환값(종료 코드)은 바꾸지 않는다."""
    row = con.execute("SELECT reason_code, COUNT(*) AS n FROM failures WHERE run_id=? AND id>? AND stage IN (%s)"
                      " GROUP BY reason_code ORDER BY n DESC, reason_code LIMIT 1" % ",".join("?" * len(stages)),
                      [run_id, since] + list(stages)).fetchone()
    if row is None:
        return
    if all_failed:
        trace.fail_code(row[0])
    else:
        trace.note_partial(row[0])


def _cmd_embed(ws, con, run_id, args):
    from labelbot import embed
    from labelbot.pipeline import Logger

    since = _since(con)
    res = embed.embed(ws, con, run_id, log=Logger(ws))
    m = trace.current()
    if m is not None:
        m.n = res.get("stored")
    _target_failures(con, run_id, ("embed",), since, all_failed=res.get("called", 0) > 0 and not res.get("stored"))


def _cmd_push_vectors(ws, con, run_id, args):
    from labelbot import vectorpush
    from labelbot.pipeline import Logger

    since = _since(con)
    res = vectorpush.push(ws, con, run_id, log=Logger(ws), force=args.force)
    if res.get("reason"):
        (trace.skip_code if res["reason"] == "RULES_CHANGE_RATIO_HIGH" else trace.fail_code)(res["reason"])
    _target_failures(con, run_id, ("push",), since)
    return 3 if res.get("reason") == "RULES_CHANGE_RATIO_HIGH" else 0  # 변경 비율 상한으로 막히면 3


def _cmd_slide_images(ws, con, run_id, args):
    from labelbot import export, slideimg
    from labelbot.pipeline import Logger, load_taxonomy, say

    since = _since(con)
    slideimg.render(ws, con, run_id, log=Logger(ws))
    _target_failures(con, run_id, ("slide_image",), since)
    tax, _ = load_taxonomy(ws)
    export.export(ws, con, run_id, tax)
    say("[slide-images] out/labeling.sqlite chunks.slide_image 갱신")


def _cmd_push_slides(ws, con, run_id, args):
    from labelbot import slidepush
    from labelbot.pipeline import Logger

    since = _since(con)
    slidepush.push(ws, con, run_id, log=Logger(ws))
    _target_failures(con, run_id, ("push_slides",), since)


_WS_COMMANDS = {"selfcheck": _cmd_selfcheck, "probe": _cmd_probe, "serve": _cmd_serve, "ingest": _cmd_ingest,
                "run": _cmd_run, "taxonomy-diff": _cmd_taxonomy_diff, "axis-update": _cmd_axis_update,
                "rules-diff": _cmd_rules_diff, "rules-update": _cmd_rules_update}
_RUN_COMMANDS = {"compare": _cmd_compare, "review": _cmd_review, "apply": _cmd_apply, "dashboard": _cmd_dashboard,
                 "report": _cmd_report, "axis-board": _cmd_axis_board, "rules-board": _cmd_rules_board,
                 "embed": _cmd_embed, "push-vectors": _cmd_push_vectors,
                 "slide-images": _cmd_slide_images, "push-slides": _cmd_push_slides}


def _probe(ws, root):
    from labelbot import ingest, probe

    if not os.path.isdir(root):
        print("[오류] 입력 폴더가 없습니다.", file=sys.stderr)
        trace.fail_code("INPUT_DIR_NOT_FOUND")
        return 1
    for full, rel, fname in ingest.iter_inputs(root):
        ext = os.path.splitext(fname)[1].lower()
        data = ingest.read_input(full, None)
        from labelbot.util import sha256_bytes

        fid = sha256_bytes(data)[:16]
        reason = ingest.signature_reason(data, ext)
        stats = {"reason": reason} if reason else probe.probe_bytes(data, ext)
        print("%s %s" % (fid, json.dumps(stats, ensure_ascii=False, sort_keys=True)))
    return 0
