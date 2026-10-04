"""QM7: 검토 대기열, 재작업 목록, 검토 화면(review.html)."""
import json
import os
import re
import unittest

from qabot import io, queue, screen
from qabot.tests import pptx_writer
from qabot.tests import reviewfix as rf


def screen_data(html):
    m = re.search(r"const DATA = (.*?);\n\n\(function", html, re.S)
    return json.loads(m.group(1))


class QueueTest(unittest.TestCase):
    def setUp(self):
        self.res, self.fx, self.roles = rf.scenario()

    def test_queue_has_exactly_unreviewed_review_records(self):
        rows, rework = queue.write(self.res)
        vm = self.res.verdict_map()
        expected = {v["record_id"] for v in self.res.verdicts if v["verdict"] == "REVIEW" and not v["human_reviewed"]}
        self.assertEqual({r["record_id"] for r in rows}, expected)
        self.assertEqual(expected, set(self.roles["review"]))
        self.assertNotIn(self.roles["review_human"], {r["record_id"] for r in rows})  # A13
        for r in rows:
            self.assertEqual(vm[r["record_id"]]["verdict"], "REVIEW")
            self.assertEqual(r["issue_codes"], ["L1_DUPLICATE_FIELD"])
            self.assertTrue(r["fields"][0].startswith("axis:"))
            self.assertEqual(set(r), {"record_id", "file_id", "priority", "score", "issue_codes", "fields", "group"})
        on_disk = io.read_own_jsonl(self.res.path("review_queue.jsonl"))
        self.assertEqual(on_disk, rows)

    def test_rework_lists_reject_issues(self):
        _rows, rework = queue.write(self.res)
        self.assertEqual([r["record_id"] for r in rework], sorted(self.roles["reject"]))
        for r in rework:
            self.assertEqual(r["labeler_run_id"], self.res.labeler_run_id)
            iss = r["issues"][0]
            self.assertEqual(iss["code"], "L3_SPAN_NOT_FOUND")
            self.assertTrue(iss["field"].startswith("axis:"))
            self.assertTrue(iss["reason"] and iss["suggested_fix"])
            self.assertIn("quote_sha256", iss["evidence"])

    def test_queue_order_is_deterministic(self):
        queue.write(self.res)
        with open(self.res.path("review_queue.jsonl"), "rb") as f:
            a = f.read()
        queue.write(self.res)
        with open(self.res.path("review_queue.jsonl"), "rb") as f:
            self.assertEqual(f.read(), a)

    def test_priority_file_scope_and_failsafe(self):
        res = self.res
        r_file, r_judge = self.roles["review"][0], self.roles["review"][1]
        vm = res.verdict_map()
        vm[r_file]["issues"] = []
        rf.inject(res, r_file, "L0_PAGE_COUNT_MISMATCH", "file")
        vm[r_judge]["issues"] = []
        rf.inject(res, r_judge, "L3_JUDGE_SKIPPED", "answer:Q-COM-001")
        rows, _ = queue.build(res)
        pr = {r["record_id"]: r["priority"] for r in rows}
        self.assertEqual(pr[self.roles["review"][2]], 1)
        self.assertEqual(pr[r_file], 2)
        self.assertEqual(pr[r_judge], 3)
        self.assertEqual([r["priority"] for r in rows], sorted(r["priority"] for r in rows))


class ScreenTest(unittest.TestCase):
    def build(self, res, n=0):
        count = screen.build(res, pass_sample=n)
        with open(res.path("review.html"), encoding="utf-8") as f:
            html = f.read()
        return count, html

    def test_sections_match_verdicts(self):
        res, _fx, roles = rf.scenario()
        count, html = self.build(res)
        data = screen_data(html)
        sec = {}
        for r in data["records"]:
            sec.setdefault(r["section"], set()).add(r["record_id"])
        self.assertEqual(sec["REVIEW"], set(roles["review"]))
        self.assertEqual(sec["REJECT"], set(roles["reject"]))
        self.assertEqual(sec["AUTO_FIX"], set(roles["autofix_case"]) | set(roles["autofix_date"]))
        self.assertNotIn("PASS_SAMPLE", sec)
        vm = res.verdict_map()
        for r in data["records"]:
            self.assertNotEqual(vm[r["record_id"]]["verdict"], "PASS")
        self.assertNotIn(roles["review_human"], {r["record_id"] for r in data["records"]})
        self.assertEqual(count, len(data["records"]))
        self.assertEqual(count, 3 + 2 + 5)
        rules = {g["rule"]: len(g["items"]) for g in data["autofix"]}
        self.assertEqual(rules, {"date_iso": 3, "taxonomy_case": 2})
        rej = [r for r in data["records"] if r["section"] == "REJECT"][0]
        self.assertTrue(rej["rework"][0]["suggested_fix"])
        self.assertTrue(rej["file_name"].startswith("합성 파일"))
        self.assertIsInstance(rej["slide_no"], int)
        # 문제가 된 인용이 이슈에 실려 강조된다
        self.assertEqual(rej["issues"][0]["quote"], rf.MISSING_QUOTE)

    def test_no_external_address_even_with_url_in_text(self):
        def prepare(b, roles):
            u = b.units[roles["review"][0]]
            u["title"] = "참고 HTTPS://intra.example/x"
            u["text"] = u["text"] + "\n링크 http://a.example/b </script><!-- x"
        res, _fx, roles = rf.scenario(prepare=prepare)
        _count, html = self.build(res, 5)
        self.assertNotIn("http", html.lower())
        self.assertEqual(html.lower().count("</script>"), 1)
        self.assertNotIn("<!-- x", html)
        data = screen_data(html)
        rec = [r for r in data["records"] if r["record_id"] == roles["review"][0]][0]
        self.assertIn("http://a.example/b </script>", rec["text"])  # 화면 안에서는 원래 글자로 보인다
        self.assertIsNone(re.search(r"<(?:script|link|img|iframe|object|embed)[^>]*\s(?:src|href)\s*=", html, re.I))
        self.assertNotIn("@import", html)
        self.assertNotIn("url(", html)

    def test_images_are_data_urls_within_limit(self):
        extra = [pptx_writer.fake_png("qm7-img-%d" % i) for i in range(3)]

        def prepare(b, roles):
            u = b.units[roles["review"][0]]
            u["images"] = []
            for i, data in enumerate(extra):
                rel = "images/qm7_%d.b64" % i
                b.loader.images[rel] = data
                u["images"].append({"image_id": "qm7-%d" % i, "ext": "png", "size": len(data), "rel_file": rel})
            b.meta["limits"] = {"images_per_chunk": 2}

        res, _fx, roles = rf.scenario(prepare=prepare)
        _c, html = self.build(res)
        data = screen_data(html)
        self.assertEqual(data["images_per_chunk"], 2)
        for r in data["records"]:
            self.assertLessEqual(len(r["images"]), 2)
            for u in r["images"]:
                self.assertTrue(u.startswith("data:image/"), u[:30])
        rec = [r for r in data["records"] if r["record_id"] == roles["review"][0]][0]
        self.assertEqual(len(rec["images"]), 2)
        self.assertEqual(rec["image_total"], 3)
        self.assertTrue(rec["images"][0].startswith("data:image/png;base64,"))

    def test_pass_sample_same_seed_same_records(self):
        res, _fx, _roles = rf.scenario()
        _c, html1 = self.build(res, 20)
        res2, _fx2, _r2 = rf.scenario()  # 같은 검수 실행 ID로 다시 판정
        c2, html2 = self.build(res2, 20)
        self.assertEqual(html1, html2)
        data = screen_data(html1)
        sample = [r["record_id"] for r in data["records"] if r["section"] == "PASS_SAMPLE"]
        self.assertEqual(len(sample), 20)
        vm = res.verdict_map()
        self.assertTrue(all(vm[s]["verdict"] == "PASS" for s in sample))
        self.assertEqual(c2, 10 + 20)
        self.assertEqual(sample, screen.pass_sample_ids(res2, 20))
        other = rf.scenario(qa_run_id="QA-20261004T010203-ffff")[0]
        self.assertNotEqual(screen.pass_sample_ids(other, 20), sample)

    def test_file_scope_issues_grouped_per_file(self):
        res, _fx, roles = rf.scenario()
        rid = roles["review"][0]
        fid = res.verdict_map()[rid]["file_id"]
        rf.inject(res, rid, "L0_PAGE_COUNT_MISMATCH", "file")
        res.file_issues = [{"code": "L0_PAGE_COUNT_MISMATCH", "severity": "major", "file_id": fid, "reason": "슬라이드 수 불일치"}]
        _c, html = self.build(res)
        data = screen_data(html)
        self.assertEqual([x["code"] for x in data["files"][fid]["file_issues"]], ["L0_PAGE_COUNT_MISMATCH"])
        self.assertIn("L0_PAGE_COUNT_MISMATCH", data["codes"])

    def test_screen_output_format_has_no_file_names(self):
        with open(screen.TEMPLATE_PATH, encoding="utf-8") as f:
            tpl = f.read()
        self.assertNotIn("http", tpl.lower())
        body = tpl[tpl.index("function buildOutput(){"):tpl.index("function download(){")]
        self.assertIn('kind:"qa_decisions"', body)
        for key in ("decisions:", "reject_decisions:", "autofix_decisions:", "proposal_decisions:", "qa_run_id:"):
            self.assertIn(key, body)
        for banned in ("file_name", "slide_no", "rel_path", "title", "text"):
            self.assertNotIn("." + banned, body)
        # 진행 상황 자동 저장은 try/catch 안에서만 한다
        for m in re.finditer(r"localStorage\.\w+", tpl):
            before = tpl[max(0, m.start() - 120):m.start()]
            self.assertIn("try", before)

    def test_screen_file_written_with_allowed_extension(self):
        res, _fx, _roles = rf.scenario()
        screen.build(res)
        self.assertTrue(os.path.isfile(res.path("review.html")))
        self.assertEqual(sorted(os.listdir(res.run_dir)), ["review.html"])


def tearDownModule():
    rf.cleanup()


if __name__ == "__main__":
    unittest.main()
