"""4차 불량 목록 추출(LLM 호출 0회), 검수·대조 화면 생성, 교정 반영(apply)."""
import json
import os
import re

from labelbot import finals, ingest, revisit, store, util
from labelbot.workspace import CODE_ROOT

REASONS = ("UNKNOWN_HIGH", "LOW_CONFIDENCE", "QUOTE_NOT_FOUND", "PARSE_WARNING", "CLASSIFY_FAILED", "LABEL_FAILED")
REASON_LABELS = {
    "UNKNOWN_HIGH": "unknown 비율 높음",
    "LOW_CONFIDENCE": "확신도 낮음",
    "QUOTE_NOT_FOUND": "근거 인용 불일치",
    "PARSE_WARNING": "파싱 경고",
    "CLASSIFY_FAILED": "분류 실패",
    "LABEL_FAILED": "라벨 실패",
}
_ELLIPSIS = re.compile(r"\s*(?:…|\.{3,})\s*")
_HANGUL = re.compile(r"[가-힣]")
_ALNUM = re.compile(r"[0-9A-Za-z]")


class ReviewError(Exception):
    pass


# ---- 인용 검사 -------------------------------------------------------------

def is_short_quote(quote):
    """한글 2자 이하이면서 영숫자 4자 이하인 인용은 약신호로만 본다."""
    q = util.nfkc(quote)
    return len(_HANGUL.findall(q)) <= 2 and len(_ALNUM.findall(q)) <= 4


def quote_found(quote, texts):
    """정규화(NFKC, 공백 축약, 대시 통일) 후 비교. 'A … B'는 조각이 순서대로 있어야 일치.
    줄바꿈으로 나뉜 인용은 줄마다 따로 본문에 있어야 일치한다."""
    lines = [l for l in quote.splitlines() if l.strip()]
    if len(lines) > 1:
        return all(quote_found(l, texts) for l in lines)
    parts = [util.norm_for_match(p) for p in _ELLIPSIS.split(quote) if p.strip()]
    if not parts:
        return True
    for t in texts:
        hay, pos, ok = util.norm_for_match(t), 0, True
        for p in parts:
            i = hay.find(p, pos)
            if i < 0:
                ok = False
                break
            pos = i + len(p)
        if ok:
            return True
    return False


# ---- 불량 판정 --------------------------------------------------------------

def _run_population(con, run_id):
    ids = {r[0] for r in con.execute("SELECT DISTINCT chunk_id FROM labels WHERE run_id=?", (run_id,))}
    ids |= {r[0] for r in con.execute(
        "SELECT DISTINCT target_id FROM failures WHERE run_id=? AND stage IN ('classify','label')", (run_id,))}
    return ids


def _axis_kinds(con):
    try:
        return json.loads(store.meta_get(con, "axis_kinds", "{}"))
    except ValueError:
        return {}


def judge_chunk(chunk, bot, failed_cls, failed_lab, cfg, kinds, syn=None):
    """반환: (사유 코드 목록, unknown_ratio, min_confidence, 약신호 인용 수)."""
    reasons, weak = [], 0
    unknown_ratio = min_conf = None
    if failed_cls:
        reasons.append("CLASSIFY_FAILED")
    if failed_lab:
        reasons.append("LABEL_FAILED")
    if json.loads(chunk["warnings"] or "[]"):
        reasons.append("PARSE_WARNING")
    if bot:
        cls_axes = [a for k, a in bot["axes"].items() if kinds.get(k, "분류") == "분류" and a["status"] != "na"]
        if cls_axes:
            unknown_ratio = sum(1 for a in cls_axes if a["status"] == "unknown") / float(len(cls_axes))
            if unknown_ratio >= cfg["unknown_ratio_min"] - 1e-12:
                reasons.append("UNKNOWN_HIGH")
        confs = [a["confidence"] for a in list(bot["axes"].values()) + list(bot["answers"].values())
                 if a.get("confidence") is not None]
        if confs:
            min_conf = min(confs)
            if min_conf < cfg["confidence_min"] - 1e-12:
                reasons.append("LOW_CONFIDENCE")
        texts = [chunk["text"]]
        if syn is not None:
            texts.append(syn.apply(chunk["text"])[0])
        quotes = [a["evidence"] for a in bot["axes"].values() if a.get("evidence") and a["status"] == "value"]
        quotes += [a["quote"] for a in bot["answers"].values() if a["answer"] in ("O", "X") and a.get("quote")]
        missing = False
        for q in quotes:
            if is_short_quote(q):
                weak += 1
            elif not quote_found(q, texts):
                missing = True
        if missing:
            reasons.append("QUOTE_NOT_FOUND")
    reasons = [r for r in REASONS if r in reasons]
    return reasons, unknown_ratio, min_conf, weak


def compute_flags(con, run_id, cfg, tax=None, reports_dir=None):
    """flagged_chunks와 reports/flagged_<실행ID>.jsonl·md를 만든다. 상한 없음. LLM을 부르지 않는다."""
    syn = None
    if tax is not None:
        from labelbot.synonyms import SynonymTable

        syn = SynonymTable(tax.synonyms)
    pop = sorted(_run_population(con, run_id))
    bots = finals.bot_labels(con, run_id, pop)
    fails = {}
    for r in con.execute("SELECT stage, target_id FROM failures WHERE run_id=? AND stage IN ('classify','label')", (run_id,)):
        fails.setdefault(r[1], set()).add(r[0])
    kinds = _axis_kinds(con)
    con.execute("DELETE FROM flagged_chunks WHERE run_id=?", (run_id,))
    rows = []
    for cid in pop:
        chunk = con.execute("SELECT * FROM chunks WHERE chunk_id=?", (cid,)).fetchone()
        if not chunk:
            continue
        bot = bots.get(cid)
        failed_cls = "classify" in fails.get(cid, ()) and not (bot and bot["chunk_type"])
        failed_lab = "label" in fails.get(cid, ()) and not (bot and bot["answers"])
        reasons, ur, mc, weak = judge_chunk(chunk, bot, failed_cls, failed_lab, cfg["flag"], kinds, syn)
        if not reasons:
            continue
        con.execute(
            "INSERT INTO flagged_chunks(run_id, chunk_id, reason_codes, unknown_ratio, min_confidence, text_hash, weak_quotes)"
            " VALUES(?,?,?,?,?,?,?)",
            (run_id, cid, util.dumps(reasons), ur, mc, chunk["text_hash"], weak),
        )
        rows.append({"chunk_id": cid, "file_id": chunk["file_id"], "reason_codes": reasons,
                     "unknown_ratio": ur, "min_confidence": mc})
    con.commit()
    if reports_dir:
        _write_flag_reports(reports_dir, run_id, rows, len(pop))
    return rows


def _write_flag_reports(rdir, run_id, rows, population):
    util.write_jsonl(os.path.join(rdir, "flagged_%s.jsonl" % run_id), rows)
    lines = ["# 4차 불량 목록", "", "- 실행 ID: %s" % run_id, "- 대상 chunk: %d" % population,
             "- 불량 chunk: %d" % len(rows), "", "| 사유 코드 | 건수 | 비율 |", "|---|---|---|"]
    for code in REASONS:
        n = sum(1 for r in rows if code in r["reason_codes"])
        lines.append("| %s | %d | %s |" % (code, n, "%.1f%%" % (100.0 * n / population) if population else "-"))
    lines += ["", "| chunk ID | 파일 ID | 사유 코드 | unknown_ratio | min_confidence |", "|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (-len(r["reason_codes"]), r["chunk_id"])):
        lines.append("| %s | %s | %s | %s | %s |" % (
            r["chunk_id"], r["file_id"][:16], ", ".join(r["reason_codes"]),
            "-" if r["unknown_ratio"] is None else "%.2f" % r["unknown_ratio"],
            "-" if r["min_confidence"] is None else "%.2f" % r["min_confidence"]))
    util.write_text(os.path.join(rdir, "flagged_%s.md" % run_id), "\n".join(lines) + "\n")


# ---- 화면 생성 ---------------------------------------------------------------

def _template(name):
    with open(os.path.join(CODE_ROOT, "labelbot", "screens", name), encoding="utf-8") as f:
        return f.read()


def fill_template(name, data):
    # JSON 문자열 안의 '<'는 <와 같은 값이다. 모두 바꿔 </script>·<!-- 가 스크립트를 끊지 못하게 한다.
    js = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    html = _template(name)
    # 슬라이드 미리보기는 review.html·slides.html이 같이 쓴다. 화면은 단일 파일로 유지한다.
    # DATA를 넣기 전에 바꿔 본문에 같은 표시가 있어도 건드리지 않는다.
    for mark, part in (("/*__SLIDE_PREVIEW_CSS__*/", "slide_preview.css"), ("/*__SLIDE_PREVIEW_JS__*/", "slide_preview.js")):
        if mark in html:
            html = html.replace(mark, _template(part), 1)
    return html.replace("/*__DATA__*/null", js, 1)


def _data_urls(ws, con, image_ids, limit):
    out = []
    for iid in image_ids[:limit]:
        r = con.execute("SELECT ext, rel_file FROM images WHERE image_id=?", (iid,)).fetchone()
        if not r:
            continue
        with open(ws.path(r["rel_file"]), encoding="ascii") as f:
            b64 = f.read().strip()
        mime = {"jpg": "jpeg", "jpeg": "jpeg", "gif": "gif", "svg": "svg+xml", "bmp": "bmp"}.get((r["ext"] or "png").lower(), "png")
        out.append("data:image/%s;base64,%s" % (mime, b64))
    return out


def _slide_layout(ws, cache, file_id, file_name, part_name):
    """검수 미리보기용 슬라이드 배치. 보관본 .b64를 메모리에서 다시 읽는다(pptx만, 실패하면 None)."""
    if not (file_name or "").lower().endswith(".pptx"):
        return None
    if file_id not in cache:
        try:
            from labelbot import ingest, pptx_parser

            cache[file_id] = pptx_parser.slide_layouts(ingest.load_b64(ws, file_id))
        except Exception:  # 미리보기는 부가 기능이라 실패해도 검수 화면은 만든다
            cache[file_id] = {}
    return cache[file_id].get(part_name)


def _file_slides(ws, con, file_ids):
    """검수 화면의 '같은 파일 슬라이드'용 JPG data URL. slide-images가 만든 .b64만 읽는다.

    본문이 바뀐(text_hash가 다른) 예전 그림은 뺀다(slidepush와 같은 기준). 파일마다 한 번만 넣는다.
    """
    out = {}
    for fid in file_ids:
        rows = []
        for r in con.execute(
                "SELECT s.chunk_id, s.seq, s.rel_file FROM slide_images s JOIN chunks c ON c.chunk_id=s.chunk_id"
                " AND c.text_hash=s.text_hash WHERE s.file_id=? ORDER BY s.seq", (fid,)):
            try:
                with open(ws.path(r["rel_file"]), encoding="ascii") as f:
                    b64 = f.read().strip()
            except (OSError, ValueError):
                continue
            rows.append({"seq": r["seq"], "chunk_id": r["chunk_id"], "src": "data:image/jpeg;base64," + b64})
        out[fid] = rows
    return out


def build_review(ws, con, run_id, tax):
    flagged = con.execute("SELECT * FROM flagged_chunks WHERE run_id=?", (run_id,)).fetchall()
    if not flagged and not con.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone():
        raise ReviewError("RUN_NOT_FOUND")
    from labelbot.questions import all_questions, map_questions
    from labelbot.synonyms import SynonymTable

    syn = SynonymTable(tax.synonyms)
    ids = [r["chunk_id"] for r in flagged]
    bots = finals.bot_labels(con, run_id, ids)
    limit = int(ws.config["limits"]["images_per_chunk"])
    layouts = {}
    chunks = []
    for f in flagged:
        c = con.execute("SELECT * FROM chunks WHERE chunk_id=?", (f["chunk_id"],)).fetchone()
        fi = con.execute("SELECT file_name, rel_path FROM files WHERE file_id=?", (c["file_id"],)).fetchone()
        reasons = json.loads(f["reason_codes"])
        imap = {}
        for iid in json.loads(c["images"] or "[]")[:limit]:
            for u in _data_urls(ws, con, [iid], 1):
                imap[iid] = u
        bot = bots.get(f["chunk_id"]) or {"axes": {}, "answers": {}, "extracted": []}
        mapped = list(bot["answers"].keys())
        if not mapped and bot["axes"]:
            mapped = [q.qid for q in map_questions(tax, bot["axes"], int(ws.config["limits"]["questions_per_chunk"]))[0]]
        chunks.append({
            "chunk_id": c["chunk_id"], "file_id": c["file_id"], "file_name": fi["file_name"], "rel_path": fi["rel_path"],
            "slide_no": c["seq"], "dup_group": c["dup_group"], "reason_codes": reasons,
            "unknown_ratio": f["unknown_ratio"], "min_confidence": f["min_confidence"],
            "title": c["title"], "text": c["text"], "images": list(imap.values()),
            "image_map": imap,
            "layout": _slide_layout(ws, layouts, c["file_id"], fi["file_name"], c["part_name"]),
            "synonym_matches": [{"alias": a, "canonical": b} for a, b in syn.match(c["text"])],
            "classify_failed": "CLASSIFY_FAILED" in reasons, "label_failed": "LABEL_FAILED" in reasons,
            "axes": {k: {"values": v["values"], "evidence": v["evidence"], "confidence": v["confidence"]}
                     for k, v in bot["axes"].items()},
            "answers": bot["answers"],
            "extracted": [{"item": e["item"], "value": e["value"], "quote": e["quote"]} for e in bot["extracted"]],
            "mapped_questions": mapped or ["Q-COM-001"],
        })
    data = {
        "kind": "review", "run_id": run_id, "generated_at": util.now_iso(), "flag": ws.config["flag"],
        "reason_labels": REASON_LABELS,
        "revisit_reasons": revisit.REASON_LABELS, "revisit_rules": revisit.TARGET_REASONS,
        "revisit_memo_max": revisit.MEMO_MAX, "revisit_short_max": revisit.SHORT_MAX,
        "axes": [{"name": a.name, "kind": a.kind, "multi": a.multi, "hierarchical": bool(a.hierarchical),
                  "definition": a.definition or "",
                  "values": [{"name": v.name, "parent": v.parent or None, "definition": v.definition or "",
                              "include": v.include or "", "exclude": v.exclude or ""} for v in a.values]}
                 for a in tax.axes if a.active],
        "questions": [{"qid": q.qid, "text": q.text} for q in all_questions(con, tax)],
        "chunks": chunks,
        "file_slides": _file_slides(ws, con, sorted({c["file_id"] for c in chunks})),
    }
    path = ws.path("screens", "review.html")
    util.write_text(path, fill_template("review.html", data))
    return path, len(chunks)


def build_compare(ws, con, run_id):
    files = con.execute(
        "SELECT DISTINCT f.file_id, f.file_name, f.rel_path FROM files f JOIN file_locations l ON l.file_id=f.file_id "
        "WHERE f.status='ok' AND l.last_seen_run=? ORDER BY f.rel_path", (run_id,)
    ).fetchall()
    limit = int(ws.config["limits"]["images_per_chunk"])
    out = []
    for f in files:
        slides = []
        for c in con.execute("SELECT * FROM chunks WHERE file_id=? ORDER BY seq", (f["file_id"],)):
            view = json.loads(c["view"] or "{}")
            slides.append({
                "chunk_id": c["chunk_id"], "seq": c["seq"], "title": c["title"], "text": c["text"],
                "body": view.get("body") or [], "tables": view.get("tables") or [], "notes": view.get("notes") or "",
                "charts": view.get("charts") or [], "images": _data_urls(ws, con, json.loads(c["images"] or "[]"), limit),
                "warnings": json.loads(c["warnings"] or "[]"),
            })
        out.append({"file_id": f["file_id"], "file_name": f["file_name"], "rel_path": f["rel_path"], "slides": slides})
    data = {"kind": "compare", "run_id": run_id, "generated_at": util.now_iso(), "files": out}
    path = ws.path("screens", "compare.html")
    util.write_text(path, fill_template("compare.html", data))
    return path, sum(len(f["slides"]) for f in out)


# ---- 교정 반영 ----------------------------------------------------------------

def apply_inbox(ws, con, tax, kind=None, revisit_runs=None):
    """inbox/*.json을 반영한다. 같은 파일을 두 번 반영해도 결과가 같다.

    kind('review' 또는 'compare')를 주면 그 종류의 파일만 반영한다.
    revisit_runs(list)를 주면 revisits 키가 있는 review 파일을 OK로 반영한 검수 실행 ID를 거기에 더한다.
    반환: (교정 파일 sha256 앞 12자, 사유 코드, 반영 건수, 종류, 실행 ID) 목록.
    review 파일에서 버린 재검토 요청이 있으면 같은 파일로 (sha, REVISIT_* 코드, 건수, 종류, 실행 ID) 행을 더한다.
    파일마다 SAVEPOINT로 묶어, 한 파일의 형식 오류가 다른 파일의 반영을 되돌리지 않는다.
    파일마다 RELEASE 시점에 commit된다.
    run_id가 화면 서버(serve)의 규칙에 맞지 않는 파일은 RUN_ID_INVALID로 건너뛴다(실행 ID 칸은 빈 문자열).
    """
    from labelbot.serve import _RUN_ID

    results, docs = [], []
    inbox = ws.path("inbox")
    names = [fn for fn in os.listdir(inbox) if fn.lower().endswith(".json")]
    names.sort(key=lambda fn: (os.path.getmtime(os.path.join(inbox, fn)), fn))
    for fn in names:
        text = ingest.read_input(os.path.join(inbox, fn), ws.path("inputs"), expect="text")
        sha = util.sha256_text(text)
        try:
            doc = json.loads(text)
        except ValueError:
            results.append((sha[:12], "JSON_INVALID", 0, None, None))
            continue
        if not isinstance(doc, dict) or doc.get("kind") not in ("review", "compare"):
            results.append((sha[:12], "KIND_UNKNOWN", 0, None, None))
            continue
        if kind and doc["kind"] != kind:
            continue
        rid = doc.get("run_id")
        if not isinstance(rid, str) or not _RUN_ID.fullmatch(rid):
            results.append((sha[:12], "RUN_ID_INVALID", 0, doc["kind"], ""))
            continue
        docs.append((sha, doc))
    # 같은 검수 실행 ID의 교정 파일이 여럿이면 가장 최근 파일 하나가 그 실행의 교정 전체를 대신한다.
    newest = {}
    for sha, doc in docs:
        if doc["kind"] == "review":
            newest[doc.get("run_id")] = sha
    for sha, doc in docs:
        tail = (doc["kind"], str(doc.get("run_id") or ""))
        if doc["kind"] == "review" and newest.get(doc.get("run_id")) != sha:
            results.append((sha[:12], "SUPERSEDED", 0) + tail)
            continue
        con.execute("SAVEPOINT apply_file")
        try:
            if doc["kind"] == "review":
                code, n, drops = _apply_review(con, tax, doc, sha)
            else:
                code, n = _apply_compare(con, doc, sha)
                drops = {}
        except (TypeError, KeyError, AttributeError, ValueError):
            con.execute("ROLLBACK TO apply_file")
            con.execute("RELEASE apply_file")
            results.append((sha[:12], "FORMAT_INVALID", 0) + tail)
            continue
        con.execute("RELEASE apply_file")
        results.append((sha[:12], code, n) + tail)
        if revisit_runs is not None and doc["kind"] == "review" and code == "OK" and "revisits" in doc:
            revisit_runs.append(doc["run_id"])
        for dc in sorted(drops):
            results.append((sha[:12], dc, drops[dc]) + tail)
    con.commit()
    return results


def _apply_review(con, tax, doc, sha):
    run_id = doc.get("run_id")
    flagged = {r["chunk_id"]: r for r in con.execute("SELECT * FROM flagged_chunks WHERE run_id=?", (run_id,))}
    if not flagged:
        return "NO_FLAGGED_FOR_RUN", 0, {}
    bots = finals.bot_labels(con, run_id, list(flagged))
    qtext = {q.qid: q.text for q in tax.questions}
    now, n = util.now_iso(), 0
    con.execute("DELETE FROM corrections WHERE review_run_id=?", (run_id,))

    def recheck(cid):
        cur = con.execute("SELECT text_hash FROM chunks WHERE chunk_id=?", (cid,)).fetchone()
        return 0 if cur and cur[0] == flagged[cid]["text_hash"] else 1

    for c in doc.get("corrections") or []:
        cid = c.get("chunk_id")
        if cid not in flagged or c.get("target") not in ("axis", "answer"):
            continue
        bot = bots.get(cid) or {"axes": {}, "answers": {}}
        if c["target"] == "axis":
            bv = (bot["axes"].get(c["key"]) or {}).get("values")
            qh = None
        else:
            bv = (bot["answers"].get(c["key"]) or {}).get("answer")
            qh = util.sha256_text(qtext.get(c["key"], ""))[:16]
        con.execute(
            "INSERT OR REPLACE INTO corrections(review_run_id, chunk_id, target_kind, target_key, human_value, bot_value,"
            " review_status, recheck, text_hash, question_hash, file_sha256, applied_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, cid, c["target"], c["key"], util.dumps(c.get("value")), util.dumps(bv), finals.CORRECTED,
             recheck(cid), flagged[cid]["text_hash"], qh, sha, now),
        )
        n += 1
    for s in doc.get("chunk_status") or []:
        cid = s.get("chunk_id")
        if cid in flagged:
            con.execute(
                "INSERT OR REPLACE INTO corrections(review_run_id, chunk_id, target_kind, target_key, human_value, bot_value,"
                " review_status, recheck, text_hash, question_hash, file_sha256, applied_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, cid, "chunk", "status", util.dumps(s.get("status")),
                 util.dumps(finals.label_hash(bots[cid]) if cid in bots else None), finals.CONFIRMED,
                 recheck(cid), flagged[cid]["text_hash"], None, sha, now),
            )
            n += 1
    con.execute("DELETE FROM candidates WHERE source='review' AND run_id=?", (run_id,))
    for s in doc.get("synonyms") or []:
        if s.get("alias") and s.get("canonical"):
            con.execute(
                "INSERT INTO candidates(run_id, kind, content, axis, parent, evidence, chunk_id, source) VALUES(?,?,?,?,?,?,?,?)",
                (run_id, "synonym", "%s|%s" % (s["alias"], s["canonical"]), "", "", "review:" + sha[:16], s.get("chunk_id"), "review"),
            )
            n += 1
    saved, drops = revisit.apply_revisits(con, tax, doc, sha, run_id, flagged, bots, now)
    return "OK", n + saved, drops


def _apply_compare(con, doc, sha):
    n = 0
    for m in doc.get("marks") or []:
        if m.get("chunk_id") and m.get("status") in ("ok", "issue"):
            con.execute(
                "INSERT OR REPLACE INTO compare_marks(chunk_id, status, memo, file_sha256, applied_at) VALUES(?,?,?,?,?)",
                (m["chunk_id"], m["status"], (m.get("memo") or "")[:2000], sha, util.now_iso()),
            )
            n += 1
    return "OK", n
