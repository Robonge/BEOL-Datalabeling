"""전체 실행(run → verdicts, manifest, 대기열, 리포트, 검토 화면)과 CLI, 산출물 규칙(4.6절, 10.2절)."""
import contextlib
import io as stdio
import json
import os
import shutil
import tempfile
import unittest

from qabot import cli, io, runner
from qabot.adapters import bundle_files
from qabot.tests import fixturegen

ALLOWED = (".b64", ".sqlite", ".json", ".jsonl", ".html", ".md", ".log")
NO_TEXT_FILES = ("manifest.json", "report.md", "report.json")


def _files(root):
    out = {}
    for d, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(d, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, root)] = fh.read()
    return out


class RunTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.fx = fixturegen.generate(seed=7, n_files=4)
        cls.bdir = os.path.join(cls.tmp, "bundle")
        bundle_files.save(cls.fx.bundle, cls.bdir, blobs=cls.fx.blobs, images=cls.fx.images)
        cls.ws = os.path.join(cls.tmp, "ws")
        cls.paths = io.QaPaths(cls.ws)
        cls.r1 = runner.run(cls.paths, bundle_dir=cls.bdir)
        cls.r2 = runner.run(cls.paths, bundle_dir=cls.bdir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def test_outputs_exist(self):
        for name in ("verdicts.jsonl", "manifest.json", "review_queue.jsonl", "rework.jsonl", "report.md",
                     "report.json", "review.html", "proposals.jsonl", "taxonomy_candidates.jsonl",
                     "taxonomy_candidates.md", "file_issues.jsonl"):
            self.assertTrue(os.path.isfile(self.r1.path(name)), name)
        self.assertEqual(len(io.read_own_jsonl(self.paths.history)), 2)
        self.assertTrue(os.path.isfile(self.paths.policy) and os.path.isfile(self.paths.schema))

    def test_clean_batch_all_pass(self):
        c = self.r1.manifest["counts"]
        self.assertEqual(c["PASS"], c["records"], [v["issues"] for v in self.r1.verdicts if v["verdict"] != "PASS"][:2])
        self.assertTrue(self.r1.manifest["judge_ran"])
        self.assertGreater(self.r1.manifest["judge"]["calls"], 0)

    def test_rerun_identical_and_cached(self):
        with open(self.r1.path("verdicts.jsonl"), "rb") as a, open(self.r2.path("verdicts.jsonl"), "rb") as b:
            v1, v2 = a.read(), b.read()
        self.assertEqual(v1.replace(self.r1.qa_run_id.encode(), b"X"), v2.replace(self.r2.qa_run_id.encode(), b"X"))
        self.assertEqual(self.r2.manifest["judge"]["calls"], 0)
        self.assertGreater(self.r2.manifest["judge"]["cache_hits"], 0)

    def test_manifest_versions_and_fingerprint(self):
        m = self.r1.manifest
        self.assertEqual(set(m["versions"]), {"taxonomy", "schema", "labeler_prompt", "reviewer", "policy"})
        self.assertEqual(m["input_fingerprint"], self.fx.bundle.fingerprint())
        self.assertTrue(m["qa_run_id"].startswith("QA-"))
        self.assertIsNotNone(m["finished_at"])

    def test_no_text_class_has_no_body_or_names(self):
        sentences = set()
        for u in self.fx.bundle.units.values():
            sentences |= {l for l in u["text"].split("\n") if len(l) >= 8}
        names = set(self.fx.bundle.meta["file_names"].values())
        for name in NO_TEXT_FILES:
            with open(self.r1.path(name), encoding="utf-8") as f:
                body = f.read()
            for s in sentences:
                self.assertNotIn(s, body, (name, s))
            for n in names:
                self.assertNotIn(n, body, name)
            self.assertNotIn(self.tmp, body)
            self.assertNotIn(self.tmp.replace("\\", "\\\\"), body)
        with open(self.paths.history, encoding="utf-8") as f:
            hist = f.read()
        for s in sentences:
            self.assertNotIn(s, hist)
        with open(self.paths.log_path, encoding="utf-8") as f:
            log = f.read()
        for s in sentences:
            self.assertNotIn(s, log)

    def test_only_allowed_extensions(self):
        for rel in _files(self.ws):
            self.assertTrue(rel.lower().endswith(ALLOWED), rel)

    def test_review_html_offline(self):
        with open(self.r1.path("review.html"), encoding="utf-8") as f:
            html = f.read()
        self.assertNotIn("http", html)

    def test_report_rebuild_same(self):
        with open(self.r1.path("report.json"), "rb") as f:
            before = f.read()
        with open(self.r1.path("report.md"), "rb") as f:
            before_md = f.read()
        out = stdio.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cli.main(["report", "--workspace", self.ws, "--qa-run", self.r1.qa_run_id, "--bundle", self.bdir])
        self.assertEqual(rc, 0)
        with open(self.r1.path("report.json"), "rb") as f:
            self.assertEqual(f.read(), before)
        with open(self.r1.path("report.md"), "rb") as f:
            self.assertEqual(f.read(), before_md)


class ZeroLayerAndNoJudgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        fx = fixturegen.generate(seed=9, n_files=2)
        self.bdir = os.path.join(self.tmp, "bundle")
        bundle_files.save(fx.bundle, self.bdir, blobs=fx.blobs, images=fx.images)
        self.paths = io.QaPaths(os.path.join(self.tmp, "ws"))

    def test_zero_layers_all_pass(self):
        res = runner.run(self.paths, bundle_dir=self.bdir, layers=[])
        self.assertEqual(res.manifest["counts"]["PASS"], res.manifest["counts"]["records"])
        self.assertTrue(os.path.isfile(res.path("verdicts.jsonl")) and os.path.isfile(res.path("manifest.json")))

    def test_no_judge_zero_pass(self):
        out = stdio.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cli.main(["run", "--workspace", self.paths.root, "--bundle", self.bdir, "--no-judge"])
        self.assertEqual(rc, 0)
        self.assertIn("judge 미실행", out.getvalue())
        run_id = self.paths.list_runs()[-1]
        verdicts = io.read_own_jsonl(os.path.join(self.paths.run_dir(run_id), "verdicts.jsonl"))
        self.assertTrue(verdicts)
        self.assertEqual([v for v in verdicts if v["verdict"] == "PASS"], [])
        with open(os.path.join(self.paths.run_dir(run_id), "report.md"), encoding="utf-8") as f:
            head = "".join(f.readlines()[:20])
        self.assertIn("judge 미실행", head)

    def test_layers_without_l3b_never_pass(self):
        """L3B를 뺀 층 구성(--layers나 policy.json)에서도 judge를 거치지 않은 레코드는 PASS가 되지 않는다."""
        out = stdio.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cli.main(["run", "--workspace", self.paths.root, "--bundle", self.bdir, "--layers", "L0,L1,L2,L3A"])
        self.assertEqual(rc, 0)
        self.assertIn("L3B_OFF", out.getvalue())
        run_id = self.paths.list_runs()[-1]
        verdicts = io.read_own_jsonl(os.path.join(self.paths.run_dir(run_id), "verdicts.jsonl"))
        self.assertTrue(verdicts)
        self.assertEqual([v for v in verdicts if v["verdict"] == "PASS"], [])
        self.assertTrue(all(any(i["code"] == "L3_JUDGE_SKIPPED" for i in v["issues"]) for v in verdicts))

    def test_report_rebuild_uses_run_policy(self):
        """실행 뒤에 policy.json을 고쳐도 report --qa-run은 그 실행의 정책으로 같은 리포트를 만든다."""
        res = runner.run(self.paths, bundle_dir=self.bdir)
        with open(res.path("report.json"), "rb") as f:
            before = f.read()
        with open(self.paths.policy, "w", encoding="utf-8") as f:
            json.dump({"l6": {"min_n": 1, "jsd_alert": 0.5}}, f)
        with contextlib.redirect_stdout(stdio.StringIO()):
            self.assertEqual(cli.main(["report", "--workspace", self.paths.root, "--qa-run", res.qa_run_id,
                                       "--bundle", self.bdir]), 0)
        with open(res.path("report.json"), "rb") as f:
            self.assertEqual(f.read(), before)

    def test_include_text_false_strips_excerpts(self):
        with open(os.path.join(self.paths.qa, "policy.json"), "w", encoding="utf-8") as f:
            json.dump({"output": {"include_text": False}}, f)
        fx = fixturegen.generate(seed=9, n_files=2)
        b = fx.bundle.copy()
        b.records[1]["axes"]["불량 모드"] = {"values": ["Short"], "status": "value",
                                         "evidence": {"quote": "존재하지 않는 문장으로 근거를 대체함"}, "confidence": 0.9}
        bundle_files.save(b, self.bdir)
        res = runner.run(self.paths, bundle_dir=self.bdir)
        with open(res.path("verdicts.jsonl"), encoding="utf-8") as f:
            body = f.read()
        self.assertIn("L3_SPAN_NOT_FOUND", body)
        self.assertNotIn("존재하지 않는 문장으로", body)

    def test_eval_command_writes_json_and_md(self):
        with contextlib.redirect_stdout(stdio.StringIO()):
            rc = cli.main(["eval", "--workspace", self.paths.root, "--golden", "synthetic:7", "--per-mutator", "2"])
        self.assertEqual(rc, 0)
        names = os.listdir(self.paths.qa)
        self.assertTrue(any(n.startswith("eval_") and n.endswith(".md") for n in names))
        res = io.read_own_json(os.path.join(self.paths.qa, [n for n in names if n.startswith("eval_")
                                                            and n.endswith(".json")][0]))
        # 작업 폴더에 judge 캐시가 있어도 fail-safe 주입이 가려지지 않는다
        self.assertTrue(os.path.isfile(self.paths.judge_cache))
        for layer, lay in res["layers"].items():
            self.assertEqual(lay["recall"], 1.0, layer)

    def test_codes_command(self):
        out_md = os.path.join(self.tmp, "codes.md")
        with contextlib.redirect_stdout(stdio.StringIO()):
            self.assertEqual(cli.main(["codes", "--out", out_md]), 0)
        with open(out_md, encoding="utf-8") as f:
            self.assertIn("L0_SIGNATURE_MISMATCH", f.read())

    def test_workspace_error_message(self):
        out = stdio.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cli.main(["report", "--workspace", self.paths.root, "--qa-run", "QA-none", "--bundle", self.bdir])
        self.assertEqual(rc, 1)
        self.assertIn("QA_RUN_NOT_FOUND", out.getvalue())


if __name__ == "__main__":
    unittest.main()
