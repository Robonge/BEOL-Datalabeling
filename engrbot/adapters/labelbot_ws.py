"""labelbot 작업 폴더 → 입력 번들(4.1절 중립 계약).

- work.sqlite는 읽기 전용(mode=ro)으로만 연다. 쓰지 않는다.
- pipeline.json과 taxonomy.xlsx는 labelbot.ingest.read_input으로 읽는다. pipeline.json이 없어도 만들지 않는다.
- 기대하는 표·열이 없으면 BundleError("ADAPTER_SCHEMA_MISMATCH", "<표.열,...>")로 멈춘다(13.1절 R1).
- labelbot을 import할 수 있는 곳은 이 모듈, io.py, llm_http.py뿐이다(2절).
"""
import json
import os
import sqlite3
import urllib.parse

from labelbot import ingest as lb_ingest
from labelbot import taxonomy as lb_taxonomy
from labelbot.synonyms import SynonymTable
from labelbot.workspace import DEFAULT_CONFIG

from engrbot import io, model

REQUIRED = {
    "runs": ("run_id", "command", "sheet_hashes"),
    "files": ("file_id", "file_name", "ext", "status", "reason_code"),
    "chunks": ("chunk_id", "file_id", "seq", "part_name", "title", "text", "text_hash", "dup_group", "warnings",
               "images", "view"),
    "images": ("image_id", "ext", "size", "rel_file"),
    "labels": ("id", "run_id", "chunk_id", "kind", "key", "value", "status", "evidence", "confidence",
               "sheet_hashes", "prompt_version", "model", "created_at"),
    "failures": ("id", "run_id", "stage", "target_id", "reason_code"),
    "corrections": ("chunk_id",),
}
LABEL_STAGE = {"chunk_type": "classify", "axis": "classify", "answer": "label", "extract": "label"}
RECORD_STAGES = ("classify", "label")
SOURCE_FAIL_STAGES = ("ingest", "parse")


# ---- 연결과 스키마 --------------------------------------------------------------

def _ro_uri(path):
    p = os.path.abspath(path).replace("\\", "/")
    if not p.startswith("/"):
        p = "/" + p
    return "file:%s?mode=ro" % urllib.parse.quote(p, safe="/:")


def connect_ro(ws_root):
    path = os.path.join(ws_root, "work.sqlite")
    if not os.path.isfile(path):
        raise model.BundleError("ADAPTER_DB_MISSING")
    con = sqlite3.connect(_ro_uri(path), uri=True)
    con.row_factory = sqlite3.Row
    return con


def check_schema(con):
    """빠진 표·열 이름 목록을 모아 한 번에 알린다."""
    missing = []
    for table, cols in REQUIRED.items():
        have = {r[1] for r in con.execute("PRAGMA table_info(%s)" % table)}
        if not have:
            missing.append(table)
            continue
        missing += ["%s.%s" % (table, c) for c in cols if c not in have]
    if missing:
        raise model.BundleError("ADAPTER_SCHEMA_MISMATCH", ",".join(missing))


# ---- 설정과 taxonomy ------------------------------------------------------------

def _merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def read_config(ws_root):
    """pipeline.json을 기본값 위에 병합한다. 파일이 없으면 기본값만 쓰고 파일을 만들지 않는다."""
    p = os.path.join(ws_root, "pipeline.json")
    user = {}
    if os.path.isfile(p):
        try:
            user = json.loads(lb_ingest.read_input(p, None, expect="text"))
        except ValueError:
            raise model.BundleError("ADAPTER_CONFIG_INVALID")
    return _merge(json.loads(json.dumps(DEFAULT_CONFIG)), user)


def taxonomy_path(ws_root, cfg):
    p = cfg.get("taxonomy_path")
    if p and not os.path.isabs(p):
        p = os.path.join(ws_root, p)
    return p or os.path.join(ws_root, "taxonomy.xlsx")


def snapshot(tax):
    """labelbot Taxonomy → 스냅샷 dict(4.1절)."""
    sh = tax.sheet_hashes
    return {
        "version": sh.get("taxonomy"),
        "questions_version": sh.get("questions"),
        "synonyms_version": sh.get("synonyms"),
        "reserved": {"na": model.NA, "unknown": model.UNKNOWN},
        "axes": [{"name": a.name, "kind": a.kind or "분류", "multi": bool(a.multi),
                  "hierarchical": bool(a.hierarchical), "active": bool(a.active), "definition": a.definition or "",
                  "values": [{"name": v.name, "parent": v.parent or None, "definition": v.definition or ""}
                             for v in a.values]}
                 for a in tax.axes],
        "questions": [{"qid": q.qid, "text": q.text, "target": q.target} for q in tax.questions],
        "synonyms": [{"alias": s.alias, "canonical": s.canonical} for s in tax.synonyms],
    }


GEN_PREFIX = "Q-GEN-"


def generated_questions(con):
    """labelbot이 1차 라벨마다 만든 O/X 검증 질문(gen_questions 표, 선택). 표가 없으면 빈 목록이다.
    O는 본문이 그 라벨(축=값)을 뒷받침한다, X는 반박한다는 뜻이다."""
    cols = {r[1] for r in con.execute("PRAGMA table_info(gen_questions)")}
    if not {"qid", "axis", "value", "text"} <= cols:
        return []
    return [{"qid": r["qid"], "text": r["text"], "target": [r["axis"], r["value"]], "generated": True}
            for r in con.execute("SELECT qid, axis, value, text FROM gen_questions ORDER BY qid")]


def load_taxonomy(ws_root, cfg):
    p = taxonomy_path(ws_root, cfg)
    if not os.path.isfile(p):
        raise model.BundleError("ADAPTER_TAXONOMY_MISSING")
    try:
        data = lb_ingest.read_input(p, None, expect=".xlsx")
    except lb_ingest.InputError as e:
        raise model.BundleError("ADAPTER_TAXONOMY_UNREADABLE", e.reason_code)
    try:
        tax = lb_taxonomy.parse_bytes(data)
    except lb_taxonomy.TaxonomyError:
        raise model.BundleError("ADAPTER_TAXONOMY_INVALID")
    return tax


# ---- loader -------------------------------------------------------------------

class WsLoader(object):
    """작업 폴더의 b64/<file_id>.b64와 images/<id>.b64를 읽는다. 작업 폴더 밖 참조는 거부한다."""

    def __init__(self, root):
        self.root = os.path.abspath(root)

    def _path(self, rel):
        if not rel:
            raise model.LoaderError("REF_MISSING")
        p = os.path.abspath(os.path.join(self.root, rel))
        try:
            inside = os.path.commonpath([p, self.root]) == self.root
        except ValueError:
            inside = False
        if not inside:
            raise model.LoaderError("REF_OUTSIDE_WORKSPACE")
        return p

    def source_bytes(self, source):
        return io.load_b64_file(self._path(source.get("b64_ref")))

    def image_bytes(self, image):
        return io.load_b64_file(self._path(image.get("rel_file")))


# ---- 변환 ---------------------------------------------------------------------

def _json(s, default):
    if s is None or s == "":
        return default
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return default


def _ev(quote):
    return {"quote": quote or "", "unit_id": None, "start": None, "end": None}


def _source(f):
    return {"file_id": f["file_id"], "ext": (f["ext"] or "").lower(), "status": f["status"] or "ok",
            "reason_code": f["reason_code"], "b64_ref": "b64/%s.b64" % f["file_id"]}


def _unit(c, img_rows, synt):
    text = model.nfc(c["text"] or "")
    canon = synt.apply(text)[0] if synt is not None else None
    view = _json(c["view"], {})
    view = view if isinstance(view, dict) else {}
    warnings = _json(c["warnings"], [])
    images = []
    for iid in _json(c["images"], []) or []:
        r = img_rows.get(iid)
        images.append({"image_id": iid, "ext": r["ext"] if r else None, "size": r["size"] if r else None,
                       "rel_file": r["rel_file"] if r else None})
    return {
        "unit_id": c["chunk_id"], "file_id": c["file_id"], "seq": c["seq"], "part_name": c["part_name"],
        "title": c["title"] or "", "text": text,
        "text_canonical": canon if canon is not None and canon != model.nfkc(text) else None,
        "text_hash": c["text_hash"] or model.sha256_text(text),
        "tables": view.get("tables") or [], "notes": view.get("notes") or "", "charts": view.get("charts") or [],
        "images": images, "warnings": warnings if isinstance(warnings, list) else [], "dup_group": c["dup_group"],
    }


def _record(cid, file_id, run_id, rows, failures, inactive, reviewed, run_sheet_hashes):
    rec = {"record_id": cid, "file_id": file_id, "labeler_run_id": run_id, "chunk_type": None, "axes": {},
           "answers": {}, "extracted": [], "failures": failures, "duplicate_fields": [],
           "human_reviewed": reviewed}
    seen, dups = set(), set()
    prompt_versions, model_name, sheet_hashes, created = {}, None, None, None
    for r in rows:
        kind, key = r["kind"], r["key"] or ""
        field = {"chunk_type": "chunk_type", "axis": "axis:%s" % key, "answer": "answer:%s" % key}.get(kind)
        if field:
            if field in seen:
                dups.add(field)
            seen.add(field)
        stage = LABEL_STAGE.get(kind)
        if stage and r["prompt_version"] and stage not in prompt_versions:
            prompt_versions[stage] = r["prompt_version"]
        model_name = model_name or r["model"]
        sheet_hashes = sheet_hashes or _json(r["sheet_hashes"], None)
        if r["created_at"] and (created is None or r["created_at"] > created):
            created = r["created_at"]
        if kind == "chunk_type":
            rec["chunk_type"] = r["value"]
        elif kind == "axis":
            vals = _json(r["value"], r["value"])  # JSON이 깨지면 원문 문자열을 둬서 L1이 TYPE_INVALID로 잡게 한다
            a = {"values": vals, "status": r["status"], "evidence": _ev(r["evidence"]), "confidence": r["confidence"]}
            if key in inactive:
                a["inactive"] = True
            rec["axes"][key] = a
        elif kind == "answer":
            rec["answers"][key] = {"answer": r["value"], "evidence": _ev(r["evidence"]), "confidence": r["confidence"]}
        elif kind == "extract":
            rec["extracted"].append({"item": key, "value": r["value"], "evidence": {"quote": r["evidence"] or ""},
                                     "flag": r["status"] or ""})
    rec["duplicate_fields"] = sorted(dups)
    rec["labeler"] = {"agent": "labelbot", "prompt_versions": prompt_versions, "model": model_name,
                      "sheet_hashes": sheet_hashes or run_sheet_hashes or {}, "created_at": created}
    return rec


def latest_labeler_run(con):
    r = con.execute("SELECT run_id FROM runs WHERE command='run' ORDER BY run_id DESC LIMIT 1").fetchone()
    return r[0] if r else None


def _chunks_and_units(con, file_ids, synt):
    if not file_ids:
        return {}, {}
    marks = ",".join("?" * len(file_ids))
    chunks = [dict(r) for r in con.execute(
        "SELECT * FROM chunks WHERE file_id IN (%s) ORDER BY file_id, seq, chunk_id" % marks, sorted(file_ids))]
    img_ids = sorted({i for c in chunks for i in (_json(c["images"], []) or []) if isinstance(i, str)})
    img_rows = {}
    for k in range(0, len(img_ids), 500):
        part = img_ids[k:k + 500]
        for r in con.execute("SELECT * FROM images WHERE image_id IN (%s)" % ",".join("?" * len(part)), part):
            img_rows[r["image_id"]] = dict(r)
    units = {c["chunk_id"]: _unit(c, img_rows, synt) for c in chunks}
    return {c["chunk_id"]: c for c in chunks}, units


def _files(con, file_ids):
    if not file_ids:
        return {}
    marks = ",".join("?" * len(file_ids))
    return {r["file_id"]: dict(r) for r in con.execute(
        "SELECT * FROM files WHERE file_id IN (%s)" % marks, sorted(file_ids))}


def load(ws_root, labeler_run_id=None):
    """반환: model.Bundle. 레코드는 그 라벨러 실행의 모집단(labels 행 또는 classify·label 실패가 있는 chunk)이다."""
    ws_root = os.path.abspath(ws_root)
    cfg = read_config(ws_root)
    tax = load_taxonomy(ws_root, cfg)
    snap = snapshot(tax)
    synt = SynonymTable(tax.synonyms)
    inactive = {a.name for a in tax.axes if not a.active}
    con = connect_ro(ws_root)
    try:
        check_schema(con)
        run_id = labeler_run_id or latest_labeler_run(con)
        run = con.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone() if run_id else None
        if run is None:
            raise model.BundleError("LABELER_RUN_NOT_FOUND", run_id)
        snap["questions"] += generated_questions(con)
        run_sheet_hashes = _json(run["sheet_hashes"], {}) or {}
        label_rows = {}
        for r in con.execute("SELECT * FROM labels WHERE run_id=? ORDER BY id", (run_id,)):
            label_rows.setdefault(r["chunk_id"], []).append(r)
        fails, src_fail_ids = {}, set()
        for r in con.execute("SELECT stage, target_id, reason_code FROM failures WHERE run_id=? ORDER BY id",
                             (run_id,)):
            if r["stage"] in RECORD_STAGES:
                lst = fails.setdefault(r["target_id"], [])
                item = {"stage": r["stage"], "reason_code": r["reason_code"]}
                if item not in lst:
                    lst.append(item)
            elif r["stage"] in SOURCE_FAIL_STAGES:
                src_fail_ids.add(r["target_id"])
        population = set(label_rows) | set(fails)
        pop_files = set()
        if population:
            for ids in _batches(sorted(population)):
                for r in con.execute("SELECT chunk_id, file_id FROM chunks WHERE chunk_id IN (%s)"
                                     % ",".join("?" * len(ids)), ids):
                    pop_files.add(r["file_id"])
        chunks, units = _chunks_and_units(con, pop_files, synt)
        files = _files(con, pop_files | src_fail_ids)
        reviewed = {}
        if population:
            for ids in _batches(sorted(population)):
                for r in con.execute("SELECT * FROM corrections WHERE chunk_id IN (%s)" % ",".join("?" * len(ids)),
                                     ids):
                    reviewed.setdefault(r["chunk_id"], []).append(dict(r))
        records, missing = [], 0
        for cid in sorted(population):
            c = chunks.get(cid)
            if c is None:
                missing += 1
                continue
            records.append(_record(cid, c["file_id"], run_id, label_rows.get(cid, []), fails.get(cid, []),
                                   inactive, cid in reviewed, run_sheet_hashes))
    finally:
        con.close()
    sources = {fid: _source(f) for fid, f in files.items()}
    meta = {"adapter": "labelbot_ws", "file_names": {fid: f["file_name"] for fid, f in files.items()},
            "llm_cfg": cfg["llm"], "limits": cfg["limits"], "corrections": reviewed,
            "population_missing_chunks": missing}
    b = model.Bundle(run_id, sources, units, records, snap, WsLoader(ws_root), meta=meta)
    model.check_bundle(b)
    return b


def _batches(ids, size=500):
    for k in range(0, len(ids), size):
        yield ids[k:k + size]


def load_units_only(ws_root, file_ids=None):
    """라벨 없이 파싱 결과만 번들로 만든다(L0 실측용). 레코드는 비어 있고 taxonomy는 빈 스냅샷이다."""
    ws_root = os.path.abspath(ws_root)
    con = connect_ro(ws_root)
    try:
        check_schema(con)
        if file_ids is None:
            file_ids = {r[0] for r in con.execute("SELECT file_id FROM files")}
        files = _files(con, set(file_ids))
        _, units = _chunks_and_units(con, set(files), None)
    finally:
        con.close()
    sources = {fid: _source(f) for fid, f in files.items()}
    meta = {"adapter": "labelbot_ws", "file_names": {fid: f["file_name"] for fid, f in files.items()}}
    return model.Bundle(None, sources, units, [], {"axes": []}, WsLoader(ws_root), meta=meta)
