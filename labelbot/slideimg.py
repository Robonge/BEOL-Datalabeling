"""슬라이드 근사 미리보기 JPG 렌더(python -m labelbot slide-images). LLM 호출 0회.

검수 화면과 같은 미리보기(screens/slide_preview.js)를 headless 브라우저로 그려 JPEG으로 캡처한다.
JPEG bytes는 slide_images/<jpg_sha256>.b64에만 둔다(CLAUDE.md: .jpg로 쓰지 않는다). 캡처 결과가 이미
base64이므로 그대로 쓰고, 시그니처·sha256·크기 확인만 메모리에서 디코딩해 한다.
같은 chunk의 text_hash·layout_hash·렌더 설정이 같으면 다시 그리지 않는다.
"""
import base64
import json
import os
import pathlib
import struct

from labelbot import cdp, review, store, util
from labelbot.embed import run_chunks

STAGE = "slide_image"
VERSION = "slides-v1"


def renderer_base(quality, width):
    """렌더 설정 버전. 화면 템플릿이 바뀌면 다시 그린다(브라우저 버전은 기록만 한다)."""
    h = util.sha256_text("".join(
        review._template(n) for n in ("slides.html", "slide_preview.js", "slide_preview.css")))[:12]
    return "%s|%s|q%d|w%d" % (VERSION, h, quality, width)


def jpeg_size(data):
    """JPEG SOF 마커에서 (너비, 높이). 못 찾으면 (None, None)."""
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            return None, None
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg = struct.unpack("!H", data[i + 2:i + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            h, w = struct.unpack("!HH", data[i + 5:i + 9])
            return w, h
        i += 2 + seg
    return None, None


def _targets(ws, con, run_id, base):
    """반환: (파일별 렌더 목록, 대상 수, 건너뜀 수, 실패 목록[(chunk_id, 코드)]).

    그림 data URL은 여기서 읽지 않는다(파일마다 렌더 직전에 읽고 버린다).
    """
    limit = int(ws.config["limits"]["images_per_chunk"])
    layouts, by_file, failed = {}, {}, []
    total = skipped = 0
    for c in run_chunks(con, run_id):
        total += 1
        row = con.execute("SELECT part_name, images FROM chunks WHERE chunk_id=?", (c["chunk_id"],)).fetchone()
        fi = con.execute("SELECT file_name FROM files WHERE file_id=?", (c["file_id"],)).fetchone()
        layout = review._slide_layout(ws, layouts, c["file_id"], fi["file_name"] if fi else "", row["part_name"])
        if not layout or not layout.get("w") or not layout.get("h") or not (layout.get("items") or layout.get("pics")):
            failed.append((c["chunk_id"], "NO_LAYOUT"))
            continue
        img_ids = json.loads(row["images"] or "[]")[:limit]
        lh = util.hash_obj({"layout": layout, "images": img_ids})
        prev = con.execute("SELECT text_hash, layout_hash, renderer_version, rel_file FROM slide_images WHERE chunk_id=?",
                           (c["chunk_id"],)).fetchone()
        same = bool(prev) and prev["text_hash"] == c["text_hash"] and prev["layout_hash"] == lh
        if same and (prev["renderer_version"] or "").startswith(base + "|") and os.path.isfile(ws.path(prev["rel_file"])):
            skipped += 1
            continue
        by_file.setdefault(c["file_id"], []).append({
            "chunk_id": c["chunk_id"], "file_id": c["file_id"], "seq": c["seq"], "text_hash": c["text_hash"],
            "layout_hash": lh, "layout": layout, "image_ids": img_ids, "stale": bool(prev) and not same})
    return by_file, total, skipped, failed


def _store(ws, con, it, b64, quality, version):
    data = base64.b64decode(b64)
    if data[:3] != b"\xff\xd8\xff":
        return "JPEG_SIGNATURE"
    sha = util.sha256_bytes(data)
    w, h = jpeg_size(data)
    rel = "slide_images/%s.b64" % sha
    if not os.path.isfile(ws.path(rel)):
        util.write_text(ws.path(rel), b64)
    con.execute(
        "INSERT OR REPLACE INTO slide_images(chunk_id, file_id, seq, jpg_sha256, width, height, quality, rel_file,"
        " text_hash, layout_hash, renderer_version, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (it["chunk_id"], it["file_id"], it["seq"], sha, w, h, quality, rel, it["text_hash"], it["layout_hash"],
         version, util.now_iso()))
    return "OK"


# 페이지(WebSocket)를 더는 쓸 수 없는 오류. 남은 파일은 같은 코드로 실패 처리한다.
_FATAL = ("WS_CLOSED", "RENDER_TIMEOUT", "CDP_BAD_MESSAGE")


def _render_file(ws, con, page, run_id, fid, items, width, quality, version, outcome):
    """한 파일의 슬라이드를 그린다. outcome[chunk_id] = 'OK' 또는 사유 코드. _FATAL 오류는 그대로 올린다."""
    path = ws.path("screens", "slides_%s.html" % fid[:16])
    nonce = util.sha256_text("%s|%s|%s" % (run_id, fid, util.now_iso()))[:16]
    slides = []
    for it in items:
        imap = {}
        for iid in it["image_ids"]:
            for u in review._data_urls(ws, con, [iid], 1):
                imap[iid] = u
        slides.append({"chunk_id": it["chunk_id"], "layout": it["layout"], "image_map": imap})
    data = {"kind": "slides", "run_id": run_id, "nonce": nonce, "width_px": width, "slides": slides}
    util.write_text(path, review.fill_template("slides.html", data))
    del slides, data
    try:
        page.open(pathlib.Path(path).as_uri(), width, 1600, "window.slidesReady === %s" % json.dumps(nonce))
        for i, it in enumerate(items):
            try:
                info = page.evaluate("window.renderOne(%d)" % i) or {}
                if info.get("skip"):
                    code = info["skip"]
                elif info.get("chunk_id") != it["chunk_id"]:
                    code = "RENDER_MISMATCH"
                elif not info.get("rect"):
                    code = "RENDER_EMPTY"
                else:
                    code = _store(ws, con, it, page.capture_jpeg(info["rect"], quality), quality, version)
            except cdp.CdpError as e:
                if e.reason_code in _FATAL:
                    raise
                code = e.reason_code
            outcome[it["chunk_id"]] = code
    finally:
        con.commit()
        # 캡처용 임시 화면(그림 data URL이 들어 있어 크다)은 남기지 않는다.
        try:
            os.remove(path)
        except OSError:
            pass


def render(ws, con, run_id, browser_factory=None, log=None):
    cfg = ws.config.get("render") or {}
    quality = int(cfg.get("jpeg_quality") or 85)
    width = int(cfg.get("width_px") or 1280)
    timeout = float(cfg.get("timeout") or 30)
    base = renderer_base(quality, width)
    by_file, total, skipped, failed = _targets(ws, con, run_id, base)
    outcome = {}  # 이번 실행에서 그리려 한 대상의 결과(chunk_id → OK 또는 사유 코드)
    if by_file:
        if browser_factory is None:
            def browser_factory():
                return cdp.launch_browser(cfg.get("browser_path"), timeout)
        fatal = None
        try:
            browser = browser_factory()
        except cdp.CdpError as e:
            browser, fatal = None, e.reason_code
        if browser is not None:
            try:
                page = browser.new_page()
                version = "%s|%s" % (base, getattr(browser, "version", "") or "unknown")
                for fid, items in by_file.items():
                    try:
                        _render_file(ws, con, page, run_id, fid, items, width, quality, version, outcome)
                    except cdp.CdpError as e:
                        if e.reason_code in _FATAL:
                            fatal = e.reason_code
                            break
                        for it in items:
                            outcome.setdefault(it["chunk_id"], e.reason_code)
            except cdp.CdpError as e:
                fatal = e.reason_code
            finally:
                browser.close()
        stale = set()
        for items in by_file.values():
            for it in items:
                outcome.setdefault(it["chunk_id"], fatal or "RENDER_EMPTY")
                if it["stale"]:
                    stale.add(it["chunk_id"])
        for cid, code in outcome.items():
            if code != "OK":
                failed.append((cid, code))
                if cid in stale:  # 본문·배치가 바뀌었는데 새로 못 그렸으면 예전 그림을 이 chunk에 남기지 않는다
                    con.execute("DELETE FROM slide_images WHERE chunk_id=?", (cid,))
    rendered = sum(1 for c in outcome.values() if c == "OK")
    # 같은 실행을 다시 돌려도 실패 행이 쌓이지 않게, 이 단계의 이전 실패는 지우고 이번 결과만 남긴다.
    con.execute("DELETE FROM failures WHERE run_id=? AND stage=?", (run_id, STAGE))
    codes = {}
    for cid, code in failed:
        store.add_failure(con, run_id, STAGE, cid, code)
        codes[code] = codes.get(code, 0) + 1
        if log:
            log(STAGE, cid, code)
    con.commit()
    print("[slide-images] 대상 %d, 렌더 %d, 건너뜀 %d, 실패 %d%s" % (
        total, rendered, skipped, len(failed),
        " (%s)" % ", ".join("%s %d" % kv for kv in sorted(codes.items())) if codes else ""))
    return {"target": total, "rendered": rendered, "skipped": skipped, "failed": len(failed), "codes": codes}


def slide_image_meta(con, chunk_id, bucket=None):
    """산출·적재용 메타데이터. 없으면 None."""
    r = con.execute("SELECT * FROM slide_images WHERE chunk_id=?", (chunk_id,)).fetchone()
    if not r:
        return None
    meta = {"kind": "approx_preview", "rel_file": r["rel_file"], "sha256": r["jpg_sha256"],
            "width": r["width"], "height": r["height"]}
    if bucket:
        # Storage에 실제로 올라간(push-slides OK) 경우에만 객체 위치를 적는다.
        path = object_path(r["file_id"], r["seq"])
        if con.execute("SELECT 1 FROM slide_image_push_log WHERE chunk_id=? AND jpg_sha256=? AND bucket=? AND object_path=?"
                       " AND result_code='OK'", (chunk_id, r["jpg_sha256"], bucket, path)).fetchone():
            meta.update({"bucket": bucket, "object_path": path})
    return meta


def object_path(file_id, seq):
    """Storage 객체 경로. 파일명·chunk_id 원문(슬래시·콜론)을 쓰지 않는다."""
    return "%s/%04d.jpg" % (file_id[:16], int(seq or 0))
