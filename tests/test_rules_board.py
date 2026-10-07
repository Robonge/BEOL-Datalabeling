"""규칙 변경 현황판 rules_update.html(rules-board) 회귀.

test_rules_update와 같은 합성 taxonomy·합성 승인 파일·mock 실행으로 기준 실행 A를 만들고, 축 규칙(FR-AX)·답 규칙(FR-ANS)·
축 없는 규칙(QR-WIDE)을 고친 뒤 rules-update 실행 B를 돌린다. 슬라이드 JPG는 합성 JPEG 머리 bytes를 바뀐 chunk 하나에만
slide_images/<sha256>.b64로 넣어 이미지·근사 미리보기 두 경로를 본다.
"""
import base64
import os
import shutil
import unittest

from labelbot import pipeline, review, rulesboard, rulesupdate, util
from labelbot.mock import MockChatTransport
from tests import test_rules_update as tru
from tests.test_new_axis_flow import page_data, run_cli
from tests.test_rules_update import R_AX, R_ANS, R_FM, R_GEN, R_WIDE, Mock, edit, write_rules

FAKE_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16 + b"\xff\xd9"


def setUpModule():
    tru.setUpModule()


def tearDownModule():
    tru.tearDownModule()


class RulesBoardTest(tru._Case):
    @classmethod
    def setUpClass(cls):
        cls.open_clone()
        write_rules(cls.ws, [edit(R_AX, "MARK-V1"), R_FM, edit(R_ANS, "MARK-O"), R_GEN, edit(R_WIDE, "새")])
        _, cls.run_b, _ = pipeline.run_rules_update(cls.ws, transport=MockChatTransport(Mock()))
        con = cls.con
        cls.info = rulesupdate.run_info(con, cls.run_b)
        cls.changes = rulesupdate.changes(con, cls.run_b)
        cls.c_img = sorted({c["chunk_id"] for c in cls.changes})[0]
        th, fid, seq = con.execute("SELECT text_hash, file_id, seq FROM chunks WHERE chunk_id=?", (cls.c_img,)).fetchone()
        sha = util.sha256_bytes(FAKE_JPEG)
        rel = "slide_images/%s.b64" % sha
        os.makedirs(cls.ws.path("slide_images"), exist_ok=True)
        with open(cls.ws.path(rel), "w", encoding="ascii") as f:
            f.write(base64.b64encode(FAKE_JPEG).decode("ascii"))
        con.execute("INSERT INTO slide_images(chunk_id, file_id, seq, jpg_sha256, width, height, quality, rel_file, text_hash)"
                    " VALUES(?,?,?,?,?,?,?,?,?)", (cls.c_img, fid, seq, sha, 1, 1, 80, rel, th))
        con.commit()
        cls.data = page_data(rulesboard.build_board(cls.ws, con, cls.run_b, cls.tax)[0])

    def test_board_header_and_counts(self):
        d, info = self.data, self.info
        self.assertEqual((d["kind"], d["run_id"], d["parent_run"]), ("rules_update", self.run_b, self.run_a))
        self.assertEqual(set(d["counts"]), {"relabeled", "changed", "skipped_human", "skipped_confirmed",
                                            "skipped_missing", "stale_answers", "unasked_questions", "failed"})
        for k in d["counts"]:
            self.assertEqual(d["counts"][k], int(info.get(k) or 0), k)
        r = d["ratio"]
        self.assertEqual((r["changed"], r["relabeled"], r["blocked"]), (info["changed"], info["relabeled"], True))
        self.assertEqual((r["ratio"], r["limit"]), (info["change_ratio"], 0.3))
        self.assertEqual(d["push"]["state"], "off")  # 합성 설정은 Supabase 꺼짐
        self.assertIsNone(d["push"]["code"])
        self.assertEqual(set(d["push"]), {"state", "pushed_ok", "total", "code"})
        self.assertEqual((d["stage_wide"], d["examples_changed"]), (1, info["examples_changed"]))
        self.assertEqual(set(d["change_labels"]), {"added", "edited", "disabled", "removed"})

    def test_push_blocked_when_supabase_on(self):
        self.ws.config["supabase"].update(tru.SUPABASE)
        try:
            d = page_data(rulesboard.build_board(self.ws, self.con, self.run_b, self.tax)[0])
        finally:
            self.ws.config["supabase"].update({"enabled": False, "url": ""})
            rulesboard.build_board(self.ws, self.con, self.run_b, self.tax)
        self.assertEqual((d["push"]["state"], d["push"]["code"]), ("blocked", rulesupdate.RULES_CHANGE_RATIO_HIGH))

    def test_rule_cards(self):
        cards = {c["rule_id"]: c for c in self.data["rules"]}
        self.assertEqual(sorted(cards), ["FR-ANS", "FR-AX"])  # 축 없는 규칙(QR-WIDE)은 카드가 아니라 한 줄 건수
        src = {r["rule_id"]: r for r in self.info["rules"]}
        for rid, c in cards.items():
            self.assertEqual(c["change"], "edited")
            for k in ("relabeled", "changed", "skipped_human", "skipped_missing", "axes", "keys"):
                self.assertEqual(c[k], src[rid][k], (rid, k))
            self.assertLessEqual(len(c["text"]), rulesboard.TEXT_MAX)
        self.assertEqual(cards["FR-AX"]["axes"], [tru.KEEP])
        self.assertEqual(cards["FR-ANS"]["keys"], ["Q-COM-001"])
        self.assertIn("MARK-V1", cards["FR-AX"]["text"])

    def test_slides_only_changed_chunks(self):
        slides = self.data["slides"]
        self.assertEqual(sorted(s["chunk_id"] for s in slides), sorted({c["chunk_id"] for c in self.changes}))
        self.assertLess(len(slides), len(review._run_population(self.con, self.run_b)))
        n = sum(len(s["changes"]) for s in slides)
        self.assertEqual(n, len(self.changes))
        kinds = {c["kind"] for s in slides for c in s["changes"]}
        self.assertEqual(kinds, {"axis", "answer"})
        for s in slides:
            self.assertGreaterEqual(s["file_no"], 1)
            for c in s["changes"]:
                self.assertEqual(set(c), {"kind", "key", "before", "after", "stale"})
                if c["stale"]:
                    self.assertIsNone(c["after"])

    def test_image_and_layout_fallback(self):
        by = {s["chunk_id"]: s for s in self.data["slides"]}
        img = by[self.c_img]
        self.assertTrue(img["image"].startswith("data:image/jpeg;base64,"))
        self.assertIsNone(img["layout"])
        other = [s for s in self.data["slides"] if s["chunk_id"] != self.c_img]
        self.assertTrue(other and all(s["image"] is None for s in other))
        self.assertTrue(any(isinstance(s["layout"], dict) and s["layout"].get("w") for s in other))

    def test_shared_slide_preview_injected(self):
        with open(self.ws.path("screens", "rules_update.html"), encoding="utf-8") as f:
            html = f.read()
        self.assertIn("var SlidePreview", html)
        self.assertNotIn("__SLIDE_PREVIEW", html)
        self.assertNotIn("__DATA__", html)
        src = review._template("rules_update.html")
        self.assertIn("/*__SLIDE_PREVIEW_JS__*/", src)
        self.assertIn("/*__SLIDE_PREVIEW_CSS__*/", src)
        self.assertNotIn("var SlidePreview", src)
        self.assertNotIn("innerHTML", src)  # 데이터는 textContent로만 넣는다
        self.assertNotIn("검수 시작", src)

    def test_not_rules_update_run(self):
        with self.assertRaises(rulesboard.BoardError) as e:
            rulesboard.build_board(self.ws, self.con, self.run_a, self.tax)
        self.assertEqual(str(e.exception), "NOT_RULES_UPDATE_RUN")

    def test_cli_rules_board(self):
        code, out, err = run_cli("rules-board", "--workspace", self.dir)  # 기본: 최신 라벨 실행(B)
        self.assertEqual(code, 0, err)
        self.assertEqual(out[-1], "[rules-board] run_id=%s 규칙 카드 2개, 바뀐 슬라이드 %d개 → screens/rules_update.html"
                         % (self.run_b, len(self.data["slides"])))
        code, out, err = run_cli("rules-board", "--workspace", self.dir, "--run", self.run_a)
        self.assertEqual(code, 1)
        self.assertIn("[오류]", err)
        self.assertIn("NOT_RULES_UPDATE_RUN", err)


if __name__ == "__main__":
    unittest.main()
