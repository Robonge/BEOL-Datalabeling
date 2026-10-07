"""슬라이드 미리보기 JPG(slide-images)와 Storage 적재(push-slides). 브라우저·네트워크 없이 가짜 CDP·sink로 검사한다."""
import base64
import json
import os
import re
import shutil
import struct
import tempfile
import unittest
from unittest import mock
import urllib.parse
import urllib.request

from labelbot import cdp, export, llm, pipeline, review, slideimg, slidepush, store, util
from labelbot.workspace import CODE_ROOT, Workspace

DUMMY_DIR = os.path.join(CODE_ROOT, "dummy pptx files")
TAXONOMY = os.path.join(CODE_ROOT, "taxonomy", "taxonomy.json")


def fake_jpeg(w=1280, h=720, salt=b""):
    """SOI + APP0 + SOF0만 있는 최소 JPEG 머리(크기 확인용)."""
    app0 = b"\xff\xe0" + struct.pack("!H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = b"\xff\xc0" + struct.pack("!HBHHB", 11, 8, h, w, 1) + b"\x01\x11\x00"
    return b"\xff\xd8" + app0 + sof + salt + b"\xff\xd9"


class FakePage:
    def __init__(self, owner):
        self.owner = owner
        self.i = None

    def open(self, url, width, height, ready_expr):
        self.owner.opened.append(url)
        # 테스트 작업 폴더(더미)의 캡처 화면에서 슬라이드 순서만 읽는다.
        path = urllib.request.url2pathname(urllib.parse.urlsplit(url).path)
        with open(path, encoding="utf-8") as f:
            html = f.read()
        data = json.loads(re.search(r"const DATA = (\{.*?\});\n", html, re.S).group(1))
        self.ids = [s["chunk_id"] for s in data["slides"]]
        assert ready_expr == "window.slidesReady === %s" % json.dumps(data["nonce"])

    def evaluate(self, expr):
        self.i = int(re.search(r"renderOne\((\d+)\)", expr).group(1))
        self.owner.n += 1
        return {"chunk_id": self.ids[self.i], "rect": {"x": 0, "y": 0, "width": 1280, "height": 720}}

    def capture_jpeg(self, rect, quality):
        self.owner.captures += 1
        if self.owner.bad_first and self.owner.captures == 1:
            return base64.b64encode(b"\x89PNG not jpeg").decode("ascii")
        return base64.b64encode(fake_jpeg(salt=b"%d" % self.owner.n)).decode("ascii")


class FakeBrowser:
    version = "FakeBrowser/1"

    def __init__(self, bad_first=False):
        self.opened, self.n, self.captures, self.closed = [], 0, 0, False
        self.bad_first = bad_first

    def new_page(self):
        return FakePage(self)

    def close(self):
        self.closed = True


class WebSocketFrameTests(unittest.TestCase):
    def _reader(self, data):
        buf = [data]

        def recv(n):
            out, buf[0] = buf[0][:n], buf[0][n:]
            self.assertEqual(len(out), n)
            return out
        return recv

    def test_roundtrip_lengths(self):
        for n in (0, 5, 125, 126, 300, 65535, 70000):
            payload = os.urandom(n)
            frame = cdp.encode_frame(payload, mask_key=b"\x01\x02\x03\x04")
            fin, op, data = cdp.read_frame(self._reader(frame))
            self.assertTrue(fin)
            self.assertEqual(op, 1)
            self.assertEqual(data, payload, n)

    def test_fragmented_unmasked_server_message(self):
        def frame(fin, op, payload):
            n = len(payload)
            hdr = struct.pack("!BB", (0x80 if fin else 0) | op, 126) + struct.pack("!H", n) if n >= 126 else \
                struct.pack("!BB", (0x80 if fin else 0) | op, n)
            return hdr + payload
        data = frame(False, 1, b"a" * 200) + frame(True, 9, b"") + frame(True, 0, b"bc")
        sent = []
        op, msg = cdp.read_message(self._reader(data), sent.append)
        self.assertEqual((op, msg), (1, b"a" * 200 + b"bc"))
        self.assertEqual(len(sent), 1)  # ping → pong

    def test_close_frame(self):
        with self.assertRaises(cdp.CdpError) as cm:
            cdp.read_message(self._reader(b"\x88\x00"))
        self.assertEqual(cm.exception.reason_code, "WS_CLOSED")

    def test_accept_key_rfc6455(self):
        self.assertEqual(cdp.accept_key("dGhlIHNhbXBsZSBub25jZQ=="), "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")

    def test_launch_browser_falls_back_when_first_exits(self):
        # Edge가 포트 파일 없이 즉시 종료해도 다음 후보(Chrome)로 넘어간다.
        tmp = tempfile.gettempdir()
        a, b = os.path.join(tmp, "a_browser.exe"), os.path.join(tmp, "b_browser.exe")
        tried = []

        def fake(exe, timeout):
            tried.append(exe)
            if exe == a:
                raise cdp.CdpError("RENDERER_EXITED")
            return "browser"
        with mock.patch.object(cdp, "browser_candidates", return_value=[a, b]),                 mock.patch.object(os.path, "isfile", return_value=True),                 mock.patch.object(cdp, "Browser", fake):
            self.assertEqual(cdp.launch_browser(None, 5), "browser")
            self.assertEqual(tried, [a, b])
            with self.assertRaises(cdp.CdpError) as cm:  # 경로를 지정하면 그 브라우저만 쓴다
                cdp.launch_browser(a, 5)
            self.assertEqual(cm.exception.reason_code, "RENDERER_EXITED")

    def test_launch_browser_missing_explicit_path(self):
        with self.assertRaises(cdp.CdpError) as cm:
            cdp.launch_browser(os.path.join(tempfile.gettempdir(), "no_such_browser.exe"), 5)
        self.assertEqual(cm.exception.reason_code, "RENDERER_MISSING")

    def test_missing_browser(self):
        with self.assertRaises(cdp.CdpError) as cm:
            cdp.find_browser(os.path.join(tempfile.gettempdir(), "no_such_browser.exe"))
        self.assertEqual(cm.exception.reason_code, "RENDERER_MISSING")


class _SlideWs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="labelbot_ws_")
        # 입력은 커밋된 더미 해시 스냅샷의 파일로 고정한다(폴더에 새 파일이 들어와도 결과가 흔들리지 않게).
        with open(llm.DUMMY_HASHES_PATH, encoding="utf-8") as f:
            include = [json.loads(line)["file_id"] for line in f if line.strip()]
        cfg = {"taxonomy_path": TAXONOMY, "input_root": DUMMY_DIR, "include_file_ids": include,
               "llm": {"transport": "mock", "model": "mock"}, "embedding": {"transport": "mock"},
               "supabase": {"enabled": False, "storage_enabled": True, "url": "https://example.supabase.co",
                            "table": "beol_chunk_embeddings"}}
        with open(os.path.join(cls.dir, "pipeline.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        cls.ws = Workspace(cls.dir)
        cls.run_id = pipeline.run_ingest(cls.ws, DUMMY_DIR)
        cls.con = store.connect(cls.ws.work_db)
        cls.browser = FakeBrowser(bad_first=True)
        cls.first = slideimg.render(cls.ws, cls.con, cls.run_id, browser_factory=lambda: cls.browser)
        cls.first_rows = cls.con.execute("SELECT COUNT(*) FROM slide_images").fetchone()[0]
        cls.first_failures = cls.con.execute(
            "SELECT COUNT(*) FROM failures WHERE run_id=? AND stage='slide_image'", (cls.run_id,)).fetchone()[0]

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        shutil.rmtree(cls.dir, ignore_errors=True)


class SlideImageTests(_SlideWs):

    def test_counts_and_codes(self):
        r = self.first
        self.assertGreater(r["target"], 0)
        self.assertEqual(r["target"], r["rendered"] + r["skipped"] + r["failed"])
        self.assertEqual(r["codes"].get("JPEG_SIGNATURE"), 1)
        self.assertEqual(self.first_rows, r["rendered"])
        self.assertEqual(self.first_failures, r["failed"])
        self.assertTrue(self.browser.closed)

    def test_b64_only_no_jpg(self):
        for row in self.con.execute("SELECT * FROM slide_images"):
            with open(self.ws.path(row["rel_file"]), encoding="ascii") as f:
                data = base64.b64decode(f.read())
            self.assertEqual(data[:3], b"\xff\xd8\xff")
            self.assertEqual(util.sha256_bytes(data), row["jpg_sha256"])
            self.assertEqual(row["rel_file"], "slide_images/%s.b64" % row["jpg_sha256"])
            self.assertEqual((row["width"], row["height"]), (1280, 720))
            self.assertTrue(row["renderer_version"].endswith("|FakeBrowser/1"))
        for root, _, files in os.walk(self.ws.root):
            for name in files:
                self.assertFalse(name.lower().endswith((".jpg", ".jpeg")), name)
        self.assertFalse([n for n in os.listdir(self.ws.path("screens")) if n.startswith("slides_")])

    def test_review_file_slides(self):
        """검수 화면의 '같은 파일 슬라이드': seq 순 JPG data URL, 본문이 바뀐 예전 그림은 뺀다."""
        fids = [r[0] for r in self.con.execute("SELECT DISTINCT file_id FROM slide_images")]
        self.assertTrue(fids)
        got = review._file_slides(self.ws, self.con, fids)
        for fid in fids:
            seqs = [s["seq"] for s in got[fid]]
            self.assertEqual(seqs, sorted(seqs))
            self.assertTrue(all(s["src"].startswith("data:image/jpeg;base64,/9j/") for s in got[fid]))
        row = self.con.execute("SELECT chunk_id, file_id, text_hash FROM slide_images LIMIT 1").fetchone()
        self.con.execute("UPDATE slide_images SET text_hash='stale' WHERE chunk_id=?", (row["chunk_id"],))
        try:
            stale = review._file_slides(self.ws, self.con, [row["file_id"]])[row["file_id"]]
            self.assertNotIn(row["chunk_id"], [s["chunk_id"] for s in stale])
        finally:
            self.con.execute("UPDATE slide_images SET text_hash=? WHERE chunk_id=?", (row["text_hash"], row["chunk_id"]))
        self.assertEqual(review._file_slides(self.ws, self.con, ["nofile"]), {"nofile": []})

    def test_rerun_renders_nothing(self):
        def boom():
            raise AssertionError("다시 그리면 안 된다")
        slideimg.render(self.ws, self.con, self.run_id, browser_factory=lambda: FakeBrowser())
        self.con.execute("DELETE FROM slide_images WHERE chunk_id=(SELECT chunk_id FROM slide_images LIMIT 1)")
        r = slideimg.render(self.ws, self.con, self.run_id, browser_factory=lambda: FakeBrowser())
        # 지운 1건만 다시 그리고, 나머지는 건너뛴다.
        self.assertEqual(r["rendered"], 1)
        r = slideimg.render(self.ws, self.con, self.run_id, browser_factory=boom)
        self.assertEqual(r["rendered"], 0)
        self.assertEqual(r["skipped"], r["target"])

    def test_renderer_missing_is_reason_code(self):
        self.con.execute("DELETE FROM slide_images WHERE chunk_id=(SELECT chunk_id FROM slide_images LIMIT 1)")

        def missing():
            raise cdp.CdpError("RENDERER_MISSING")
        r = slideimg.render(self.ws, self.con, self.run_id, browser_factory=missing)
        self.assertEqual(r["codes"], {"RENDERER_MISSING": 1})
        slideimg.render(self.ws, self.con, self.run_id, browser_factory=lambda: FakeBrowser())

    def test_jpeg_size(self):
        self.assertEqual(slideimg.jpeg_size(fake_jpeg(800, 600)), (800, 600))
        self.assertEqual(slideimg.jpeg_size(b"\xff\xd8garbage"), (None, None))

    def test_object_path_has_no_name(self):
        self.assertEqual(slideimg.object_path("ab" * 32, 7), "abababababababab/0007.jpg")

    def _export_vals(self):
        import sqlite3

        tax, _ = pipeline.load_taxonomy(self.ws)
        out = sqlite3.connect(export.export(self.ws, self.con, self.run_id, tax))
        try:
            return [json.loads(r[0]) for r in out.execute("SELECT slide_image FROM chunks WHERE slide_image IS NOT NULL")]
        finally:
            out.close()

    def test_export_has_slide_image(self):
        slideimg.render(self.ws, self.con, self.run_id, browser_factory=lambda: FakeBrowser())
        self.con.execute("DELETE FROM slide_image_push_log")
        vals = self._export_vals()
        self.assertTrue(vals)
        for v in vals:
            self.assertTrue(os.path.isfile(os.path.join(self.ws.path("out"), v["rel_file"])))
            self.assertNotIn("object_path", v)  # 올리기 전에는 Storage 위치를 적지 않는다
        slidepush.push(self.ws, self.con, self.run_id, sink=FakeSink())
        vals = self._export_vals()
        for v in vals:
            self.assertEqual(v["bucket"], "BEOL-labeling")
            self.assertRegex(v["object_path"], r"^[0-9a-f]{16}/\d{4}\.jpg$")

    def _drop(self, n):
        rows = self.con.execute("SELECT chunk_id, file_id FROM slide_images GROUP BY file_id LIMIT ?", (n,)).fetchall()
        for r in rows:
            self.con.execute("DELETE FROM slide_images WHERE chunk_id=?", (r[0],))
        return [r[0] for r in rows]

    def _stage_failures(self):
        return self.con.execute("SELECT COUNT(*) FROM failures WHERE run_id=? AND stage='slide_image'",
                                (self.run_id,)).fetchone()[0]

    def test_failures_do_not_accumulate(self):
        def missing():
            raise cdp.CdpError("RENDERER_MISSING")
        self._drop(1)
        slideimg.render(self.ws, self.con, self.run_id, browser_factory=missing)
        slideimg.render(self.ws, self.con, self.run_id, browser_factory=missing)
        self.assertEqual(self._stage_failures(), 1)
        slideimg.render(self.ws, self.con, self.run_id, browser_factory=lambda: FakeBrowser())
        self.assertEqual(self._stage_failures(), 0)

    def test_stale_image_removed_when_rerender_fails(self):
        def missing():
            raise cdp.CdpError("RENDERER_MISSING")
        cid = self.con.execute("SELECT chunk_id FROM slide_images LIMIT 1").fetchone()[0]
        self.con.execute("UPDATE slide_images SET text_hash='old' WHERE chunk_id=?", (cid,))
        r = slideimg.render(self.ws, self.con, self.run_id, browser_factory=missing)
        self.assertEqual(r["codes"], {"RENDERER_MISSING": 1})
        self.assertIsNone(self.con.execute("SELECT 1 FROM slide_images WHERE chunk_id=?", (cid,)).fetchone())
        slideimg.render(self.ws, self.con, self.run_id, browser_factory=lambda: FakeBrowser())

    def test_fatal_error_fails_all_remaining_and_closes(self):
        class DeadPage(FakePage):
            def open(self, url, width, height, ready_expr):
                raise cdp.CdpError("RENDER_TIMEOUT")
        b = FakeBrowser()
        b.new_page = lambda: DeadPage(b)
        dropped = self._drop(2)
        self.assertEqual(len(dropped), 2)
        r = slideimg.render(self.ws, self.con, self.run_id, browser_factory=lambda: b)
        self.assertEqual(r["codes"], {"RENDER_TIMEOUT": 2})
        self.assertTrue(b.closed)
        self.assertFalse([n for n in os.listdir(self.ws.path("screens")) if n.startswith("slides_")])
        slideimg.render(self.ws, self.con, self.run_id, browser_factory=lambda: FakeBrowser())


class FakeSink:
    def __init__(self, rows_per_patch=1):
        self.uploads, self.patches = [], []
        self.rows_per_patch = rows_per_patch

    def upload(self, bucket, path, data):
        self.uploads.append((bucket, path, data[:3]))

    def patch_row(self, chunk_id, fields):
        self.patches.append((chunk_id, fields))
        return self.rows_per_patch


class SlidePushTests(_SlideWs):
    """같은 작업 폴더로 Storage 적재를 본다(SlideImageTests의 setUpClass를 재사용)."""

    def test_push_idempotent_and_fields(self):
        slideimg.render(self.ws, self.con, self.run_id, browser_factory=lambda: FakeBrowser())
        self.con.execute("DELETE FROM slide_image_push_log")
        n = self.con.execute("SELECT COUNT(*) FROM slide_images").fetchone()[0]
        s1 = FakeSink(rows_per_patch=0)
        r = slidepush.push(self.ws, self.con, self.run_id, sink=s1)
        self.assertEqual(r["failed"], n)  # 벡터 행이 아직 없으면 ROW_MISSING
        codes = {c for (c,) in self.con.execute("SELECT DISTINCT result_code FROM slide_image_push_log")}
        self.assertEqual(codes, {"ROW_MISSING"})
        s2 = FakeSink()
        r = slidepush.push(self.ws, self.con, self.run_id, sink=s2)
        self.assertEqual((r["uploaded"], r["patched"]), (n, n))
        for bucket, path, head in s2.uploads:
            self.assertEqual(bucket, "BEOL-labeling")
            self.assertRegex(path, r"^[0-9a-f]{16}/\d{4}\.jpg$")
            self.assertEqual(head, b"\xff\xd8\xff")
        cid, fields = s2.patches[0]
        self.assertEqual(set(fields), {"slide_image_bucket", "slide_image_path", "slide_image_sha256",
                                       "slide_image_width", "slide_image_height"})
        s3 = FakeSink()
        r = slidepush.push(self.ws, self.con, self.run_id, sink=s3)
        self.assertEqual((r["uploaded"], r["skipped"]), (0, n))
        self.assertFalse(s3.uploads)

    def test_non_dummy_is_sent(self):
        # PoC: 사외·사내 구분 없음(2026-10-05). 더미 해시 밖 파일도 올라간다.
        row = self.con.execute("SELECT * FROM slide_images LIMIT 1").fetchone()
        fake_fid = "f" * 64
        self.con.execute("UPDATE slide_images SET file_id=? WHERE chunk_id=?", (fake_fid, row["chunk_id"]))
        self.con.execute("DELETE FROM slide_image_push_log WHERE chunk_id=?", (row["chunk_id"],))
        try:
            s = FakeSink()
            r = slidepush.push(self.ws, self.con, self.run_id, sink=s)
            self.assertEqual(r["blocked"], 0)
            self.assertIn(fake_fid[:16], {p.split("/")[0] for _, p, _ in s.uploads})
        finally:
            self.con.execute("UPDATE slide_images SET file_id=? WHERE chunk_id=?", (row["file_id"], row["chunk_id"]))

    def test_disabled_does_nothing(self):
        self.ws.config["supabase"]["storage_enabled"] = False
        try:
            r = slidepush.push(self.ws, self.con, self.run_id, sink=FakeSink())
            self.assertEqual(r["uploaded"], 0)
        finally:
            self.ws.config["supabase"]["storage_enabled"] = True


class TemplateTests(unittest.TestCase):
    def test_shared_preview_inlined(self):
        for name in ("review.html", "slides.html"):
            html = review.fill_template(name, {"kind": name.split(".")[0]})
            self.assertNotIn("__SLIDE_PREVIEW", html, name)
            self.assertIn("var SlidePreview", html, name)
            self.assertIn(".slide .sb{", html, name)


if __name__ == "__main__":
    unittest.main()
