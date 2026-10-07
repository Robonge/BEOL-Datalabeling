"""labelbot 작업 폴더 adapter 통합 테스트(QM3).

합성 pptx(pptx_writer, 메모리에서만 만든다)를 labelbot 수집·파싱·라벨링(mock)에 넣어 임시 작업 폴더를 만들고,
adapter가 번들로 바꾼 결과를 본다. 작업 폴더는 코드 폴더 밖(tempfile.mkdtemp)에 둔다.
원본은 .pptx로 디스크에 쓰지 않고 labelbot과 같은 방식으로 b64/<file_id>.b64만 쓴다.
"""
import base64
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import unittest

from labelbot import ingest, pipeline, store, util
from labelbot.mock import MockChatTransport
from labelbot.workspace import CODE_ROOT, Workspace

from domain_engrbot import model, runner
from domain_engrbot import policy as policy_mod
from domain_engrbot.adapters import labelbot_ws
from domain_engrbot import pptx_writer

TAXONOMY = os.path.join(CODE_ROOT, "taxonomy", "taxonomy.json")
FOOTER = "사내 테스트용 더미 자료"


def _specs(seed):
    slides = [{"title": "과제 보고 %d" % seed, "lines": ["작성 부서 공정기술팀"], "footer": FOOTER}]
    for n in range(2, 7):
        spec = {"title": "주간 보고 %d-%d" % (seed, n), "footer": FOOTER,
                "lines": ["M2 배선층에서 저항 측정 진행 %d" % n, "CMP 공정 조건 재점검 진행", "Short 불량 발생 위치 분석",
                          "다음 주 일정 재확인 %d" % (seed * 10 + n)]}
        if n == 3:
            spec["table"] = [["항목", "측정값"], ["Rs", "%d.5" % (10 + seed)], ["Rc", "2.%d" % seed]]
        if n == 4:
            spec["images"] = [pptx_writer.fake_png("adapter-%d-%d" % (seed, n))]
            spec["notes"] = "발표자 메모 슬라이드 %d 내용 정리" % n
        if n == 5:
            spec["hidden"] = True
        slides.append(spec)
    return slides


def responder(body, hint):
    """chunk 본문 해시로 일부 chunk는 1차 분류 축을 빠뜨려 실패시킨다(모집단에 실패 chunk를 넣기 위해서다).
    분류·라벨 외 작업(검증 질문 생성 등)은 labelbot mock 기본 응답을 쓴다."""
    if hint.get("task") not in ("classify", "label"):
        return MockChatTransport().send(body, hint)
    obj = MockChatTransport._classify(hint) if hint["task"] == "classify" else MockChatTransport._label(hint)
    bucket = int(hashlib.sha256(hint["text"].encode("utf-8")).hexdigest(), 16) % 4
    if hint["task"] == "classify" and bucket == 0:
        obj["axes"].pop(next(iter(obj["axes"])))
    elif hint["task"] == "classify":
        # labelbot은 확신도가 낮은 라벨에만 검증 질문(Q-GEN-)을 만든다. 값이 붙은 축을 낮춰 검증 질문이 생기게 한다.
        for a in obj["axes"].values():
            if a["values"] != ["해당 없음"]:
                a["confidence"] = 0.6
    return json.dumps(obj, ensure_ascii=False)


def ingest_bytes(ws, con, run_id, name, data):
    """ingest.collect와 같은 기록을 bytes에서 직접 만든다(원본 파일을 디스크에 두지 않기 위해서다)."""
    fid = util.sha256_bytes(data)
    util.write_text(ingest.b64_path(ws, fid), base64.b64encode(data).decode("ascii"))
    reason = ingest.signature_reason(ingest.load_b64(ws, fid), os.path.splitext(name)[1])
    con.execute("INSERT INTO files(file_id, file_name, rel_path, ext, size, status, reason_code, first_seen_run)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (fid, name, name, os.path.splitext(name)[1], len(data), "failed" if reason else "ok", reason, run_id))
    con.execute("INSERT INTO file_locations(file_id, rel_path, file_name, first_seen_run, last_seen_run)"
                " VALUES(?,?,?,?,?)", (fid, name, name, run_id, run_id))
    if reason:
        store.add_failure(con, run_id, "ingest", fid, reason)
    con.commit()
    return fid


def build_workspace():
    """반환: (작업 폴더 경로, 라벨러 실행 ID, 정상 파일 ID 목록, 암호 파일 ID)."""
    root = tempfile.mkdtemp(prefix="domain_engrbot_ws_")
    with open(os.path.join(root, "pipeline.json"), "w", encoding="utf-8") as f:
        # 합성 파일은 더미 해시 목록에 없으므로 사내 호스트로 둔다(mock transport라 실제 전송은 없다)
        json.dump({"taxonomy_path": TAXONOMY,
                   "llm": {"transport": "mock", "model": "mock", "max_retries": 1, "workers": 1,
                           "base_url": "https://llm.corp.test/v1", "internal_host_suffixes": ["corp.test"]},
                   "embedding": {"transport": "mock"}, "supabase": {"enabled": False}}, f)
    ws = Workspace(root)
    con = store.connect(ws.work_db)
    try:
        tax, _ = pipeline.load_taxonomy(ws)
        run_id = pipeline.start_run(con, ws, "run")
        log = pipeline.Logger(ws)
        fids = [ingest_bytes(ws, con, run_id, "합성%d.pptx" % k, pptx_writer.build_pptx(_specs(k))) for k in (1, 2)]
        enc = ingest_bytes(ws, con, run_id, "암호.pptx", pptx_writer.encrypted_bytes())
        ingest.parse_files(ws, con, run_id, fids + [enc], log=log)
        ctx = pipeline.Ctx(ws, con, run_id, tax=tax, transport=MockChatTransport(responder), log=log)
        pipeline.run_labeling(ctx, pipeline.content_chunks(con, fids))
        pipeline.finish_run(con, run_id, tax.sheet_hashes, ctx.chat.sent_params())
        # 사람 교정 1건, 같은 축 중복 행 1건, JSON이 깨진 축 값 1건을 넣는다(adapter 변환 확인용)
        cid = con.execute("SELECT chunk_id FROM labels WHERE run_id=? AND kind='axis' ORDER BY id LIMIT 1",
                          (run_id,)).fetchone()[0]
        con.execute("INSERT INTO corrections(review_run_id, chunk_id, target_kind, target_key, human_value)"
                    " VALUES(?,?,?,?,?)", ("R1", cid, "chunk", "status", '"confirmed"'))
        row = con.execute("SELECT * FROM labels WHERE run_id=? AND chunk_id=? AND kind='axis' ORDER BY id LIMIT 1",
                          (run_id, cid)).fetchone()
        cols = [k for k in row.keys() if k != "id"]
        con.execute("INSERT INTO labels(%s) VALUES(%s)" % (",".join(cols), ",".join("?" * len(cols))),
                    [row[k] for k in cols])
        con.execute("UPDATE labels SET value='[깨진' WHERE id=(SELECT MAX(id) FROM labels WHERE run_id=? AND chunk_id=?"
                    " AND kind='axis' AND key<>?)", (run_id, cid, row["key"]))
        con.commit()
    finally:
        con.close()
    return root, run_id, fids, enc, cid, row["key"]


class AdapterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root, cls.run_id, cls.fids, cls.enc, cls.cid, cls.dup_axis = build_workspace()
        cls.db = os.path.join(cls.root, "work.sqlite")
        with open(cls.db, "rb") as f:
            cls.db_before = f.read()
        cls.files_before = sorted(os.listdir(cls.root))
        cls.bundle = labelbot_ws.load(cls.root)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def _con(self):
        return sqlite3.connect(self.db)

    def test_workspace_outside_code(self):
        self.assertFalse(os.path.abspath(self.root).startswith(os.path.abspath(CODE_ROOT)))

    def test_record_count_equals_population(self):
        con = self._con()
        try:
            pop = {r[0] for r in con.execute("SELECT DISTINCT chunk_id FROM labels WHERE run_id=?", (self.run_id,))}
            failed = {r[0] for r in con.execute("SELECT DISTINCT target_id FROM failures WHERE run_id=? AND stage IN"
                                                " ('classify','label')", (self.run_id,))}
            n_chunks = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        finally:
            con.close()
        self.assertTrue(failed, "실패 chunk가 모집단에 있어야 한다")
        self.assertEqual(len(self.bundle.records), len(pop | failed))
        self.assertEqual({r["record_id"] for r in self.bundle.records}, pop | failed)
        self.assertEqual(len(self.bundle.units), n_chunks)
        self.assertEqual(self.bundle.labeler_run_id, self.run_id)

    def test_failed_record_shape(self):
        con = self._con()
        try:
            fid = con.execute("SELECT target_id FROM failures WHERE run_id=? AND stage='classify'",
                              (self.run_id,)).fetchone()[0]
        finally:
            con.close()
        rec = next(r for r in self.bundle.records if r["record_id"] == fid)
        self.assertIsNone(rec["chunk_type"])
        self.assertEqual(rec["axes"], {})
        self.assertEqual(rec["failures"][0]["stage"], "classify")

    def test_record_fields(self):
        rec = next(r for r in self.bundle.records if r["record_id"] == self.cid)
        self.assertTrue(rec["human_reviewed"])
        self.assertIn("axis:%s" % self.dup_axis, rec["duplicate_fields"])
        self.assertIn(self.cid, self.bundle.meta["corrections"])
        raw = [a for a in rec["axes"].values() if isinstance(a["values"], str)]
        self.assertEqual(len(raw), 1, "JSON이 깨진 축 값은 원문 문자열로 둔다")
        ok = [a for a in rec["axes"].values() if isinstance(a["values"], list)]
        self.assertTrue(ok and all(set(a["evidence"]) == {"quote", "unit_id", "start", "end"} for a in ok))
        lab = rec["labeler"]
        self.assertEqual(lab["agent"], "labelbot")
        self.assertIn("classify", lab["prompt_versions"])
        self.assertEqual(set(lab["sheet_hashes"]) >= {"taxonomy", "questions", "synonyms"}, True)
        others = [r for r in self.bundle.records if r["record_id"] != self.cid]
        self.assertFalse(any(r["human_reviewed"] for r in others))

    def test_units_and_sources(self):
        b = self.bundle
        self.assertEqual(set(b.sources), set(self.fids) | {self.enc})
        self.assertEqual(b.sources[self.enc]["status"], "failed")
        self.assertEqual(b.sources[self.enc]["reason_code"], "ENCRYPTED")
        units = b.units_of(self.fids[0])
        self.assertEqual(len(units), 6)
        self.assertTrue(any(u["tables"] for u in units))
        img_units = [u for u in units if u["images"]]
        self.assertEqual(len(img_units), 1)
        img = img_units[0]["images"][0]
        self.assertEqual(set(img), {"image_id", "ext", "size", "rel_file"})
        self.assertEqual(hashlib.sha256(b.loader.image_bytes(img)).hexdigest(), img["image_id"])
        self.assertTrue(any("HIDDEN_SLIDE" in u["warnings"] for u in units))
        for u in units:
            self.assertEqual(u["text"], model.nfc(u["text"]))
            self.assertEqual(u["unit_id"], "%s:%s" % (u["file_id"][:16], u["part_name"]))
            self.assertNotIn(FOOTER, u["text"])
        self.assertEqual(hashlib.sha256(b.loader.source_bytes(b.sources[self.fids[0]])).hexdigest(), self.fids[0])
        snap = b.taxonomy
        self.assertTrue(snap["version"] and snap["axes"] and snap["questions"] is not None)
        self.assertEqual(set(snap["axes"][0]), {"name", "kind", "multi", "hierarchical", "active", "definition", "values"})
        self.assertEqual(b.meta["adapter"], "labelbot_ws")
        self.assertIn("llm_cfg", b.meta)
        self.assertIn("limits", b.meta)

    def test_generated_questions_in_snapshot(self):
        """labelbot 검증 질문(gen_questions)이 스냅샷에 들어가 L1이 모르는 질문으로 보지 않고, judge가 문장을 쓴다."""
        from domain_engrbot.checks import l1_schema
        from domain_engrbot.judge import build_items, render_item

        gen = [q for q in self.bundle.taxonomy["questions"] if q.get("generated")]
        self.assertTrue(gen)
        self.assertTrue(all(q["qid"].startswith("Q-GEN-") and q["text"] and len(q["target"]) == 2 for q in gen))
        recs = [r for r in self.bundle.records if any(k.startswith("Q-GEN-") for k in r.get("answers") or {})]
        self.assertTrue(recs)
        tax = model.TaxIndex(self.bundle.taxonomy)
        sch = policy_mod.validate_schema({})
        for r in recs:
            out = l1_schema.evaluate(r, tax, sch)
            self.assertFalse([i for i in out["issues"] if i["code"] == "L1_UNKNOWN_FIELD"
                              and (i["field"] or "").startswith("answer:Q-GEN-")])
        from domain_engrbot.engine import RecordTarget

        gen_q = {q["qid"]: q for q in gen}
        for r in recs:
            for it in build_items(RecordTarget(r, self.bundle.units.get(r["record_id"])), tax):
                if it["qid"] in gen_q:
                    self.assertTrue(it["generated"])
                    self.assertEqual([it["axis"], it["value"]], list(gen_q[it["qid"]]["target"]))
                    text = render_item(it, tax)
                    self.assertIn(gen_q[it["qid"]]["text"].split()[0], text)
                    self.assertIn("검증 질문", text)

    def test_generated_questions_table_optional(self):
        """gen_questions 표가 없는 작업 DB(이전 labelbot)도 그대로 읽는다."""
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        dst = os.path.join(tmp, "ws")
        shutil.copytree(self.root, dst)
        con = sqlite3.connect(os.path.join(dst, "work.sqlite"))
        con.execute("DROP TABLE IF EXISTS gen_questions")
        con.commit()
        con.close()
        b = labelbot_ws.load(dst)
        self.assertFalse([q for q in b.taxonomy["questions"] if q.get("generated")])

    def test_run_layers_and_db_unchanged(self):
        pol = policy_mod.validate_policy({"layers": ["L0", "L1", "L2", "L3A"]})
        sch = policy_mod.validate_schema({})
        res = runner.execute(self.bundle, pol, sch, layers=["L0", "L1", "L2", "L3A"])
        self.assertEqual(len(res.verdicts), len(self.bundle.records))
        codes = {(i["file_id"], i["code"]) for i in res.file_issues}
        self.assertIn((self.enc, "L0_SIGNATURE_MISMATCH"), codes)
        l0_major = [i for v in res.verdicts for i in v["issues"] if i["layer"] == "L0"
                    and model.SEVERITY_RANK[i["severity"]] >= model.SEVERITY_RANK["minor"]]
        self.assertEqual(l0_major, [], "합성 pptx에서 L0 minor 이상 이슈가 나오면 안 된다")
        labelbot_ws.load(self.root, self.run_id)
        with open(self.db, "rb") as f:
            self.assertEqual(f.read(), self.db_before)
        self.assertEqual(sorted(os.listdir(self.root)), self.files_before)

    def test_unknown_run(self):
        with self.assertRaises(model.BundleError) as cm:
            labelbot_ws.load(self.root, "19990101T000000-0000")
        self.assertEqual(cm.exception.reason_code, "LABELER_RUN_NOT_FOUND")

    def test_schema_mismatch(self):
        other = tempfile.mkdtemp(prefix="domain_engrbot_ws_mis_")
        try:
            shutil.copy(os.path.join(self.root, "pipeline.json"), other)
            shutil.copy(self.db, os.path.join(other, "work.sqlite"))
            con = sqlite3.connect(os.path.join(other, "work.sqlite"))
            con.execute("ALTER TABLE labels DROP COLUMN prompt_version")
            con.execute("ALTER TABLE chunks DROP COLUMN view")
            con.commit()
            con.close()
            with self.assertRaises(model.BundleError) as cm:
                labelbot_ws.load(other)
            self.assertEqual(cm.exception.reason_code, "ADAPTER_SCHEMA_MISMATCH")
            self.assertIn("labels.prompt_version", cm.exception.detail)
            self.assertIn("chunks.view", cm.exception.detail)
        finally:
            shutil.rmtree(other, ignore_errors=True)

    def test_empty_workspace(self):
        other = tempfile.mkdtemp(prefix="domain_engrbot_ws_empty_")
        try:
            with self.assertRaises(model.BundleError) as cm:
                labelbot_ws.load(other)
            self.assertEqual(cm.exception.reason_code, "ADAPTER_TAXONOMY_MISSING")
            self.assertFalse(os.path.exists(os.path.join(other, "pipeline.json")), "pipeline.json을 만들면 안 된다")
            shutil.copy(os.path.join(self.root, "pipeline.json"), other)
            with self.assertRaises(model.BundleError) as cm:
                labelbot_ws.load(other)
            self.assertEqual(cm.exception.reason_code, "ADAPTER_DB_MISSING")
            self.assertFalse(os.path.exists(os.path.join(other, "work.sqlite")), "work.sqlite를 만들면 안 된다")
        finally:
            shutil.rmtree(other, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
