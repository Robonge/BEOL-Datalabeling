"""명령 진입점: python -m labelbot <명령> --workspace <작업 폴더>."""
import argparse
import json
import os
import sys

from labelbot import store
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
    ap = add("apply", "inbox/의 교정·대조 .json 반영")
    ap.add_argument("--kind", choices=("review", "compare"), help="이 종류의 파일만 반영(review: 검수, compare: 파싱 대조)")
    sv = add("serve", "화면 서버(screens/ 제공, 검수·대조 JSON을 inbox/에 저장)")
    sv.add_argument("--port", type=int, default=8770, help="포트(127.0.0.1 전용)")
    return p


def main(argv=None):
    args = _parser().parse_args(argv)
    load_env_file()
    try:
        ws = Workspace(args.workspace)
    except WorkspaceError as e:
        msg = {"WORKSPACE_INSIDE_CODE": "작업 폴더는 코드 폴더의 workspaces/ 아래에만 둘 수 있습니다."}.get(str(e), str(e))
        print("[오류] %s" % msg, file=sys.stderr)
        return 2
    from labelbot.pipeline import Logger, PipelineError, load_taxonomy, run_all, run_ingest, say

    try:
        if args.command == "selfcheck":
            from labelbot import selfcheck

            ok, _ = selfcheck.run(ws, probe_llm=args.probe_llm)
            return 0 if ok else 1
        if args.command == "probe":
            return _probe(ws, args.input or ws.input_root)
        if args.command == "serve":
            from labelbot import serve

            return serve.serve(ws, args.port)
        if args.command == "ingest":
            run_ingest(ws, args.input or ws.input_root)
            return 0
        if args.command == "run":
            run_all(ws, args.input or ws.input_root, use_feedback=not args.no_feedback)
            return 0
        con = store.connect(ws.work_db)
        try:
            run_id = getattr(args, "run", None) or store.latest_run(con)
            if args.command != "apply" and not run_id:
                raise PipelineError("실행 기록이 없습니다. 먼저 run 또는 ingest를 실행하세요.")
            if args.command == "compare":
                from labelbot import review

                path, n = review.build_compare(ws, con, run_id)
                say("[compare] chunk %d개 → screens/compare.html" % n)
            elif args.command == "review":
                from labelbot import review

                tax, _ = load_taxonomy(ws)
                rows = review.compute_flags(con, run_id, ws.config, tax, ws.path("reports"))
                path, n = review.build_review(ws, con, run_id, tax)
                say("[review] run_id=%s 불량 chunk %d개 → screens/review.html, reports/flagged_%s.*" % (run_id, n, run_id))
            elif args.command == "apply":
                from labelbot import candidates, review, revisit
                from labelbot.pipeline import Ctx

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
            elif args.command == "dashboard":
                from labelbot import dashboard

                tax, _ = load_taxonomy(ws)
                path, n = dashboard.build_results(ws, con, run_id, tax)
                say("[dashboard] chunk %d개 → screens/results.html" % n)
            elif args.command == "report":
                from labelbot import report, revisit

                tax, _ = load_taxonomy(ws)
                path = report.write_report(ws, con, run_id, tax)
                say("[report] reports/%s" % os.path.basename(path))
                n = revisit.write_reports(ws, con, tax)
                say("[report] taxonomy 재검토 요청 누적 %d건 → reports/taxonomy_revisit.md" % n)
            elif args.command == "embed":
                from labelbot import embed

                embed.embed(ws, con, run_id, log=Logger(ws))
            elif args.command == "push-vectors":
                from labelbot import vectorpush

                vectorpush.push(ws, con, run_id, log=Logger(ws))
            elif args.command == "slide-images":
                from labelbot import export, slideimg

                slideimg.render(ws, con, run_id, log=Logger(ws))
                tax, _ = load_taxonomy(ws)
                export.export(ws, con, run_id, tax)
                say("[slide-images] out/labeling.sqlite chunks.slide_image 갱신")
            elif args.command == "push-slides":
                from labelbot import slidepush

                slidepush.push(ws, con, run_id, log=Logger(ws))
        finally:
            con.close()
        return 0
    except PipelineError as e:
        print("[오류] %s" % e, file=sys.stderr)
        return 1


def _probe(ws, root):
    from labelbot import ingest, probe

    if not os.path.isdir(root):
        print("[오류] 입력 폴더가 없습니다.", file=sys.stderr)
        return 1
    for full, rel, fname in ingest._iter_inputs(root):
        ext = os.path.splitext(fname)[1].lower()
        data = ingest.read_input(full, None)
        from labelbot.util import sha256_bytes

        fid = sha256_bytes(data)[:16]
        reason = ingest.signature_reason(data, ext)
        stats = {"reason": reason} if reason else probe.probe_bytes(data, ext)
        print("%s %s" % (fid, json.dumps(stats, ensure_ascii=False, sort_keys=True)))
    return 0
