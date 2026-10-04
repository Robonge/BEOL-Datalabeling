"""0단계 수집: 원본과 사람 입력을 여는 유일한 곳(read_input). base64 저장, 시그니처 판정, 위치 기록, 파싱·chunk 저장.

원본 경로를 여는 코드는 이 모듈의 read_input 하나뿐이다(CLAUDE.md). 이후 단계는 b64/의 .b64만 읽는다.
"""
import base64
import os

from labelbot import util

OOXML_SIG = b"PK\x03\x04"
OLE_SIG = b"\xd0\xcf\x11\xe0"
OOXML_EXT = (".pptx", ".docx", ".xlsx")
OLE_EXT = (".ppt", ".doc", ".xls")
PARSED_EXT = (".pptx", ".docx")
TEXT_EXT = (".json", ".txt", ".csv", ".md")


class InputError(Exception):
    def __init__(self, reason_code):
        Exception.__init__(self, reason_code)
        self.reason_code = reason_code


def signature_reason(data, ext):
    """디코딩 직후 시그니처 판정. 맞으면 None, 아니면 사유 코드."""
    ext = ext.lower()
    if ext in OOXML_EXT:
        if data.startswith(OOXML_SIG):
            return None
        if data.startswith(OLE_SIG):
            return "ENCRYPTED"
        return "NOT_OOXML"
    if ext in OLE_EXT:
        return "OLE_LEGACY"
    return "UNSUPPORTED_FORMAT"


def read_input(path, snapshot_dir=None, expect=None):
    """사람 입력·원본을 open(path,'rb')로 읽는 유일한 함수.

    expect: '.xlsx' 등 확장자를 주면 시그니처를 확인해 InputError를 낸다. 'text'면 utf-8-sig→cp949로 디코딩해 str을 돌려준다.
    snapshot_dir가 있으면 <sha256>.b64로 보관하고(같은 해시 재사용), None이면 아무것도 쓰지 않는다.
    """
    with open(path, "rb") as f:
        data = f.read()
    if expect and expect != "text":
        reason = signature_reason(data, expect)
        if reason:
            raise InputError(reason)
    if snapshot_dir:
        sha = util.sha256_bytes(data)
        snap = os.path.join(snapshot_dir, sha + ".b64")
        if not os.path.exists(snap):
            util.write_text(snap, base64.b64encode(data).decode("ascii"))
    if expect == "text":
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return data.decode("cp949")
    return data


def b64_path(ws, file_id):
    return ws.path("b64", file_id + ".b64")


def load_b64(ws, file_id):
    with open(b64_path(ws, file_id), "r", encoding="ascii") as f:
        return base64.b64decode(f.read())


def _iter_inputs(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for fn in sorted(filenames):
            if fn.startswith("~$") or fn.startswith("."):
                continue
            full = os.path.join(dirpath, fn)
            rel = util.nfc(os.path.relpath(full, root).replace(os.sep, "/"))
            yield full, rel, util.nfc(fn)


def collect(ws, con, run_id, input_root, only_ext=None, log=None, excluded=()):
    """입력 루트를 훑어 b64 저장과 files·file_locations 기록. 반환: 이번 실행에서 본 file_id 목록.

    pipeline.json include_file_ids(파일 ID 접두 목록)가 있으면 그 파일만 수집한다(사외 PoC 범위 제한용).
    skip_file_names(파일명 목록, 이전 실행과 겹쳐 건너뛰기로 한 파일)는 열지 않고 건너뛴다.
    """
    include = tuple(ws.config.get("include_file_ids") or ())
    skip_names = {util.nfc(n) for n in ws.config.get("skip_file_names") or ()}
    seen = []
    for full, rel, fname in _iter_inputs(input_root):
        ext = os.path.splitext(fname)[1].lower()
        if only_ext and ext not in only_ext:
            continue
        if fname in skip_names:
            continue
        data = read_input(full, None)
        fid = util.sha256_bytes(data)
        if (include and not fid.startswith(include)) or fid in excluded:
            continue
        bp = b64_path(ws, fid)
        if not os.path.exists(bp):
            util.write_text(bp, base64.b64encode(data).decode("ascii"))
        decoded = load_b64(ws, fid)
        reason = None
        if util.sha256_bytes(decoded) != fid:
            reason = "B64_MISMATCH"
        else:
            reason = signature_reason(decoded, ext)
        row = con.execute("SELECT file_id FROM files WHERE file_id=?", (fid,)).fetchone()
        if not row:
            con.execute(
                "INSERT INTO files(file_id, file_name, rel_path, ext, size, status, reason_code, first_seen_run)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (fid, fname, rel, ext, len(data), "failed" if reason else "ok", reason, run_id),
            )
            if reason:
                from labelbot.store import add_failure

                add_failure(con, run_id, "ingest", fid, reason)
                if log:
                    log("ingest", fid, reason)
        loc = con.execute(
            "SELECT 1 FROM file_locations WHERE file_id=? AND rel_path=?", (fid, rel)
        ).fetchone()
        if loc:
            con.execute(
                "UPDATE file_locations SET last_seen_run=? WHERE file_id=? AND rel_path=?",
                (run_id, fid, rel),
            )
        else:
            con.execute(
                "INSERT INTO file_locations(file_id, rel_path, file_name, first_seen_run, last_seen_run)"
                " VALUES(?,?,?,?,?)",
                (fid, rel, fname, run_id, run_id),
            )
        if fid not in seen:
            seen.append(fid)
    con.commit()
    return seen


def first_seen_rel_path(con, file_id):
    r = con.execute(
        "SELECT rel_path FROM file_locations WHERE file_id=? ORDER BY first_seen_run, rel_path LIMIT 1",
        (file_id,),
    ).fetchone()
    return r[0] if r else None


def parse_files(ws, con, run_id, file_ids, log=None):
    """b64만 읽어 파싱하고 chunk를 저장한다. 같은 chunk 방식으로 이미 파싱한 파일은 건너뛴다."""
    from labelbot import chunker

    method = ws.config["chunking"]["method"]
    parsed = 0
    for fid in file_ids:
        f = con.execute("SELECT ext, status, chunk_method FROM files WHERE file_id=?", (fid,)).fetchone()
        if not f or f["status"] != "ok":
            continue
        if f["chunk_method"] == method:
            continue
        data = load_b64(ws, fid)
        try:
            doc = chunker.parse_document(f["ext"], data, ws.config)
        except Exception as e:  # 파서 오류는 그 파일만 실패
            code = getattr(e, "reason_code", "PARSE_ERROR")
            from labelbot.store import add_failure

            add_failure(con, run_id, "parse", fid, code)
            con.execute("UPDATE files SET status='failed', reason_code=? WHERE file_id=?", (code, fid))
            if log:
                log("parse", fid, code)
            continue
        _store_document(ws, con, fid, doc, method)
        parsed += 1
    _assign_dup_groups(con)
    con.commit()
    return parsed


def _store_document(ws, con, fid, doc, method):
    meta = doc.get("doc") or {}
    con.execute("DELETE FROM chunks WHERE file_id=?", (fid,))
    for u in doc["units"]:
        cid = "%s:%s" % (fid[:16], u["part_name"])
        img_ids = []
        for img in u.get("images") or []:
            iid = img["sha256"]
            rel_file = "images/%s.b64" % iid
            p = ws.path(rel_file)
            if not os.path.exists(p):
                util.write_text(p, base64.b64encode(img["data"]).decode("ascii"))
            con.execute(
                "INSERT OR IGNORE INTO images(image_id, ext, size, rel_file) VALUES(?,?,?,?)",
                (iid, img.get("ext") or "png", len(img["data"]), rel_file),
            )
            img_ids.append(iid)
        text = util.nfc(u["text"])
        con.execute(
            "INSERT INTO chunks(chunk_id, file_id, seq, part_name, title, text, text_hash, dup_hash,"
            " warnings, images, view) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                cid,
                fid,
                u["seq"],
                u["part_name"],
                u.get("title") or "",
                text,
                util.text_hash(text),
                util.dup_hash(text),
                util.dumps(u.get("warnings") or []),
                util.dumps(img_ids),
                util.dumps(u.get("view") or {}),
            ),
        )
    con.execute(
        "UPDATE files SET title=?, author=?, authored_at=?, author_source=?, date_source=?, chunk_method=?"
        " WHERE file_id=?",
        (
            meta.get("title"),
            meta.get("author"),
            meta.get("created"),
            "docprops" if meta.get("author") else None,
            "docprops" if meta.get("created") else None,
            method,
            fid,
        ),
    )


def _assign_dup_groups(con):
    """dup_hash가 같은 chunk 묶음. 그룹 ID는 dup_hash 앞 12자, 묶음이 1개면 NULL."""
    con.execute("UPDATE chunks SET dup_group=NULL")
    con.execute(
        "UPDATE chunks SET dup_group=substr(dup_hash,1,12) WHERE dup_hash IN "
        "(SELECT dup_hash FROM chunks GROUP BY dup_hash HAVING COUNT(*)>1)"
    )
