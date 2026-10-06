"""axis-update 화면 회귀: 검수 화면의 대상 축 잠금(US-006)과 축 변경 현황판 axis_update.html(US-007).

test_axis_update와 같은 합성 taxonomy(메모리 xlsx)·mock 실행으로 기준 실행 A(검수 확인 1건)와 axis-update 실행 B를 만든다.
현황판은 검수 전(B 교정 없음)과 검수 뒤(B 교정·확인·완료 신호)를 한 번씩 만들어 DATA를 비교한다.
슬라이드 JPG는 합성 JPEG 머리 bytes를 slide_images/<sha256>.b64로 하나만 넣어 이미지·근사 미리보기 두 경로를 본다.
"""
import base64
import os
import shutil
import unittest

from labelbot import axisboard, axisupdate, finals, pipeline, review, store, util
from labelbot.mock import MockChatTransport
from tests.test_axis_update import (CHANGED, GONE, KEEP, NEW, ONLY, after_sheets, apply_doc, before_sheets, make_ws,
                                    signal, write_tax)
from tests.test_new_axis_flow import page_data, run_cli
from tests.test_pipeline import DUMMY_DIR, responder

FAKE_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16 + b"\xff\xd9"


class AxisUpdateScreensTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir, tax_path, cls.ws = make_ws(before_sheets())
        cls.run_a, _ = pipeline.run_all(cls.ws, DUMMY_DIR, transport=MockChatTransport(responder), use_feedback=False)
        cls.con = con = store.connect(cls.ws.work_db)
        tax_a, _ = pipeline.load_taxonomy(cls.ws)
        first = con.execute("SELECT chunk_id FROM flagged_chunks WHERE run_id=? ORDER BY chunk_id", (cls.run_a,)).fetchone()[0]
        apply_doc(cls.ws, con, tax_a, {"kind": "review", "run_id": cls.run_a, "corrections": [],
                                       "chunk_status": [{"chunk_id": first, "status": "confirmed"}]}, "review_a.json")
        cls.review_a = page_data(review.build_review(cls.ws, con, cls.run_a, tax_a)[0])
        write_tax(tax_path, after_sheets())
        _, cls.run_b, _ = pipeline.run_axis_update(cls.ws, transport=MockChatTransport(responder), use_feedback=False)
        cls.tax = tax = pipeline.load_taxonomy(cls.ws)[0]
        cls.info = axisupdate.run_info(con, cls.run_b)
        cls.review_b = page_data(review.build_review(cls.ws, con, cls.run_b, tax)[0])
        # JPG가 있는 chunk 하나(본문 해시가 같아야 쓴다)
        cls.c_img = con.execute("SELECT chunk_id FROM labels WHERE run_id=? ORDER BY chunk_id", (cls.run_b,)).fetchone()[0]
        th, fid, seq = con.execute("SELECT text_hash, file_id, seq FROM chunks WHERE chunk_id=?", (cls.c_img,)).fetchone()
        sha = util.sha256_bytes(FAKE_JPEG)
        rel = "slide_images/%s.b64" % sha
        os.makedirs(cls.ws.path("slide_images"), exist_ok=True)
        with open(cls.ws.path(rel), "w", encoding="ascii") as f:
            f.write(base64.b64encode(FAKE_JPEG).decode("ascii"))
        con.execute("INSERT INTO slide_images(chunk_id, file_id, seq, jpg_sha256, width, height, quality, rel_file, text_hash)"
                    " VALUES(?,?,?,?,?,?,?,?,?)", (cls.c_img, fid, seq, sha, 1, 1, 80, rel, th))
        con.commit()
        cls.before = page_data(axisboard.build_board(cls.ws, con, cls.run_b, tax)[0])
        # 검수 뒤: 대상 축 교정 1건, 확인 1건, 비대상 축 교정 1건(AXIS_NOT_TARGET), 완료 신호
        flagged = [r[0] for r in con.execute("SELECT chunk_id FROM flagged_chunks WHERE run_id=? ORDER BY chunk_id",
                                             (cls.run_b,))]
        cls.c_fix, cls.c_ok = flagged[0], flagged[1]
        cur = (finals.bot_labels(con, cls.run_b, [cls.c_fix])[cls.c_fix]["axes"].get(NEW) or {}).get("values") or []
        cls.fix_value = ["Split"] if cur != ["Split"] else ["POR"]
        res = apply_doc(cls.ws, con, tax, {
            "kind": "review", "run_id": cls.run_b,
            "corrections": [{"chunk_id": cls.c_fix, "target": "axis", "key": NEW, "value": cls.fix_value},
                            {"chunk_id": cls.c_fix, "target": "axis", "key": KEEP, "value": ["V1"]}],
            "chunk_status": [{"chunk_id": cls.c_ok, "status": "confirmed"}]}, "review_b.json")
        cls.apply_codes = {r[1]: r[2] for r in res}
        signal(cls.ws, "done", cls.run_b)
        cls.after = page_data(axisboard.build_board(cls.ws, con, cls.run_b, tax)[0])

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        shutil.rmtree(cls.dir, ignore_errors=True)

    # ---- US-006 검수 화면 잠금 ----
    def test_review_axis_update_locks_non_target(self):
        axes = {a["name"]: a for a in self.review_b["axes"]}
        self.assertEqual(self.review_b["axis_update"]["target"], self.info["target"])
        for name in self.info["target"]:
            self.assertTrue(axes[name]["editable"], name)
            self.assertNotIn("locked", axes[name])
        self.assertTrue(axes[KEEP]["locked"])
        self.assertFalse(axes[KEEP]["editable"])
        self.assertNotIn(GONE, {n for n, a in axes.items() if a.get("editable")})
        locked = {n for n, a in axes.items() if a.get("locked")}
        self.assertEqual(locked & set(self.info["target"]), set())

    def test_review_normal_run_has_no_lock(self):
        self.assertIsNone(self.review_a["axis_update"])
        self.assertFalse(any(a.get("locked") for a in self.review_a["axes"]))

    def test_apply_skips_non_target_correction(self):
        self.assertEqual(self.apply_codes.get(review.AXIS_NOT_TARGET), 1)

    # ---- US-007 현황판 ----
    def test_board_shape_before_review(self):
        d = self.before
        self.assertEqual((d["kind"], d["run_id"], d["parent_run"], d["phase"]), ("axis_update", self.run_b, self.run_a, "before"))
        self.assertFalse(d["review_started"] or d["review_done"])
        cards = {c["name"]: c for c in d["axes_target"]}
        self.assertEqual(sorted(cards), sorted([NEW, CHANGED, ONLY]))
        self.assertEqual((cards[NEW]["kind"], cards[ONLY]["kind"], cards[CHANGED]["kind"]),
                         ("added", "values_added", "values_removed"))
        for c in cards.values():
            self.assertEqual(set(c), {"name", "kind", "reasons", "flagged", "corrected", "confirmed", "undecidable", "remaining"})
            self.assertEqual(c["corrected"] + c["confirmed"] + c["undecidable"] + c["remaining"], 0)  # 검수 대기
            self.assertTrue(set(c["reasons"]) <= set(review.REASONS))
        self.assertEqual([r["name"] for r in d["axes_removed"]], [GONE])
        self.assertGreater(d["axes_removed"][0]["dropped_rows"], 0)
        self.assertEqual(d["dropped_answers"], self.info["dropped_answers"])
        self.assertEqual(set(d["push"]), {"pushed_ok", "total"})
        n_flag = self.con.execute("SELECT COUNT(*) FROM flagged_chunks WHERE run_id=?", (self.run_b,)).fetchone()[0]
        self.assertEqual(d["flagged"], n_flag)
        self.assertEqual(sum(1 for s in d["slides"] if s["flagged"]), n_flag)
        self.assertEqual({s["outcome"] for s in d["slides"] if s["flagged"]}, {"pending"})
        self.assertEqual({s["outcome"] for s in d["slides"] if not s["flagged"]}, {None})

    def test_board_slides_one_per_run_chunk(self):
        pop = review._run_population(self.con, self.run_b)
        self.assertEqual(sorted(s["chunk_id"] for s in self.before["slides"]), sorted(pop))
        s = self.before["slides"][0]
        self.assertEqual(sorted(s["values"]), sorted([NEW, CHANGED, ONLY]))  # 대상 축 값만
        self.assertGreaterEqual(s["file_no"], 1)

    def test_board_image_and_layout_fallback(self):
        by = {s["chunk_id"]: s for s in self.before["slides"]}
        img = by[self.c_img]
        self.assertTrue(img["image"].startswith("data:image/jpeg;base64,"))
        self.assertIsNone(img["layout"])
        other = [s for s in self.before["slides"] if s["chunk_id"] != self.c_img]
        self.assertTrue(all(s["image"] is None for s in other))
        self.assertTrue(any(isinstance(s["layout"], dict) and s["layout"].get("w") for s in other))

    def test_board_after_review(self):
        d = self.after
        self.assertEqual(d["phase"], "after")
        self.assertTrue(d["review_done"])
        cards = {c["name"]: c for c in d["axes_target"]}
        self.assertGreaterEqual(sum(c["corrected"] for c in cards.values()), 1)
        for c in cards.values():
            self.assertEqual(c["corrected"] + c["confirmed"] + c["undecidable"] + c["remaining"], c["flagged"])
        by = {s["chunk_id"]: s for s in d["slides"]}
        self.assertEqual(by[self.c_fix]["outcome"], "corrected")
        self.assertEqual(by[self.c_fix]["values"][NEW], self.fix_value)
        self.assertEqual(by[self.c_ok]["outcome"], "confirmed")
        self.assertNotIn("pending", {s["outcome"] for s in d["slides"]})

    def test_shared_slide_preview_injected(self):
        for name in ("axis_update.html", "review.html"):
            with open(self.ws.path("screens", name), encoding="utf-8") as f:
                html = f.read()
            self.assertIn("var SlidePreview", html, name)
            self.assertNotIn("__SLIDE_PREVIEW", html, name)
            src = review._template(name)  # 템플릿은 표시만 두고 공용 조각을 복사해 두지 않는다
            self.assertIn("/*__SLIDE_PREVIEW_JS__*/", src, name)
            self.assertNotIn("var SlidePreview", src, name)

    # ---- CLI ----
    def test_cli_axis_board(self):
        code, out, err = run_cli("axis-board", "--workspace", self.dir)  # 기본: 최신 라벨 실행(B)
        self.assertEqual(code, 0, err)
        self.assertTrue(any(line.startswith("[axis-board] run_id=%s" % self.run_b) for line in out), out)
        code, out, err = run_cli("axis-board", "--workspace", self.dir, "--run", self.run_a)
        self.assertEqual(code, 1)
        self.assertIn("NOT_AXIS_UPDATE_RUN", err)


if __name__ == "__main__":
    unittest.main()
