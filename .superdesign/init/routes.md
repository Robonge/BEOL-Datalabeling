# routes.md - screens as routes

No framework router. `python -m labelbot serve --workspace <ws> --port 8770` (alias: `.claude/skills/BEOL-labeling/scripts/serve_screens.py`, which just calls `labelbot.cli.main(["serve", ...])`)
starts a `http.server.ThreadingHTTPServer` on 127.0.0.1 (default port 8770, `labelbot/serve.py` `make_server`/`serve`; `labelbot/cli.py` `_cmd_serve`).
It statically serves `<workspace>/screens/` (`SimpleHTTPRequestHandler(directory=<ws>/screens)`, `Cache-Control: no-store`). The HTML files there are generated
(not edited by hand): a Python builder collects data from the workspace SQLite, then `review.fill_template(name, data)` writes the template with
`/*__DATA__*/null` replaced by the JSON blob (`<` escaped as `\u003c`), and `/*__SLIDE_PREVIEW_CSS__*/` / `/*__SLIDE_PREVIEW_JS__*/` replaced by the partials.

| Route (served from `<ws>/screens/`) | Template | Builder (fills DATA) | CLI | What it renders |
|---|---|---|---|---|
| `/results.html` | `labelbot/screens/results.html` (293 lines) | `dashboard.build_results(ws, con, run_id, tax)` in `labelbot/dashboard.py:10` | `python -m labelbot dashboard` | Results dashboard: KPI row (files, chunks, flagged donut), alert line, flag-reason bars, per-question O/X/N-A stacks, per-axis value/unknown/NA stacks, per-axis value bars (folded), filterable chunk table with expandable detail (body with quote highlights, evidence, answers). Read-only. |
| `/review.html` | `labelbot/screens/review.html` (~1589 lines) | `review.build_review(ws, con, run_id, tax)` in `labelbot/review.py:276` | `python -m labelbot review` | Human review screen: left list of flagged chunks with reason-code filters; right detail with slide preview, same-file slide strip, highlighted body, axis correction editors, question answer editors, synonym suggestions, taxonomy revisit requests, evidence capture. Autosaves to `localStorage` and POSTs to `/inbox/review`; "검수 완료" posts `/inbox/review/done`. |
| `/compare.html` | `labelbot/screens/compare.html` (484 lines) | `review.build_compare(ws, con, run_id)` in `labelbot/review.py:340` | `python -m labelbot compare` | Parse comparison: per file, per slide parsed body/tables/notes/charts/images next to the extracted text, for human parse check. POSTs to `/inbox/compare`. |
| `/slides_<file_id16>.html` (and conceptually `slides.html`) | `labelbot/screens/slides.html` (50 lines) | inline in `labelbot/slideimg.py:_render_file` (data dict `{kind:"slides", run_id, nonce, width_px, slides:[{chunk_id, layout, image_map}]}`) | `python -m labelbot slide-images` | Headless-capture page: stacks `SlidePreview` slides at fixed width, exposes `window.renderOne(i)` for CDP screenshot. Not meant for people. |

Server-side endpoints (JSON, same-origin only), `labelbot/serve.py`: `GET /inbox/status` -> `{ok, kinds, done}`; `POST /inbox/review`, `POST /inbox/compare`, `POST /inbox/review/done`
(writes `<ws>/inbox/<kind>_<run_id>.json`, and for `/done` a `signals/review_done_<run_id>.json`). Host must be 127.0.0.1/localhost.

## Template filling (shared by every screen)

`labelbot/review.py:198-214`
```python
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
```

## Server routing (verbatim)

`labelbot/serve.py:33-66`
```python
class _Handler(http.server.SimpleHTTPRequestHandler):
    inbox = None
    ws_root = None
    tmp_dir = None
    lock = None

    def log_message(self, fmt, *args):
        sys.stderr.write("[serve] %s %s %s\n" % (self.command, self.path.split("?")[0], args[1] if len(args) > 1 else ""))

    def end_headers(self):
        # 다시 만든 화면이 바로 보이도록 캐시하지 않는다.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._local_host():
            return self._json(403, {"ok": False, "code": "HOST_REJECTED"})
        if self.path.split("?")[0] == "/inbox/status":
            # done: 검수 완료 버튼(POST /inbox/review/done)을 받는 서버라는 표시. 예전 서버에는 없어 버튼이 숨는다.
            return self._json(200, {"ok": True, "kinds": list(KINDS), "done": True})
        return super().do_GET()

    def do_HEAD(self):
        if not self._local_host():
            # HEAD 응답에는 본문을 쓰지 않는다.
            self.send_response(403)
```

`labelbot/serve.py:80-90`
```python

    def do_POST(self):
        m = re.match(r"^/inbox/(review|compare)(/done)?$", self.path.split("?")[0])
        if not m or (m.group(2) and m.group(1) != "review"):
            return self._json(404, {"ok": False, "code": "NOT_FOUND"})
        kind, done = m.group(1), bool(m.group(2))
        if not self._same_origin():
            return self._json(403, {"ok": False, "code": "ORIGIN_REJECTED"})
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self._json(415, {"ok": False, "code": "CONTENT_TYPE"})
        try:
```

`labelbot/serve.py:132-152`
```python
def make_server(ws_root, port, host="127.0.0.1"):
    inbox = os.path.join(ws_root, "inbox")
    os.makedirs(inbox, exist_ok=True)
    os.makedirs(os.path.dirname(done_signal_path(ws_root, "")), exist_ok=True)
    handler = type("Handler", (_Handler,), {"inbox": inbox, "ws_root": ws_root, "tmp_dir": ws_root,
                                            "lock": threading.Lock()})
    handler = functools.partial(handler, directory=os.path.join(ws_root, "screens"))
    return http.server.ThreadingHTTPServer((host, port), handler)


def serve(ws, port):
    srv = make_server(ws.root, port)
    print("[serve] 127.0.0.1:%d screens/ 제공, 교정 JSON은 inbox/에 저장" % srv.server_address[1], flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0

```

## DATA builder: results.html - `build_results` (full)

`labelbot/dashboard.py:1-88`
```python
"""결과 대시보드(screens/results.html). 한 실행의 전체 chunk 라벨과 분포를 보여 준다. LLM 호출 0회."""
import json

from labelbot import alerts, finals, review, util
from labelbot.questions import CTL_PREFIX, GEN_PREFIX, all_questions

ALERT_LABELS = {"NA_RATIO_LOW": "N/A 비율이 기준 이하", "DUP_LABEL_HIGH": "중복 라벨링 비율이 기준 이상"}


def build_results(ws, con, run_id, tax):
    pop = sorted(review._run_population(con, run_id))
    labels = finals.final_labels(con, run_id, pop, {q.qid: q.text for q in all_questions(con, tax)})
    flagged = {r["chunk_id"]: json.loads(r["reason_codes"])
               for r in con.execute("SELECT chunk_id, reason_codes FROM flagged_chunks WHERE run_id=?", (run_id,))}
    files = con.execute(
        "SELECT DISTINCT f.file_id, f.file_name, f.status FROM files f JOIN file_locations l ON l.file_id=f.file_id "
        "WHERE l.last_seen_run=? ORDER BY f.file_name", (run_id,)).fetchall()
    names = {f["file_id"]: f["file_name"] for f in files}
    chunks = []
    for cid in pop:
        c = con.execute("SELECT chunk_id, file_id, seq, title, text FROM chunks WHERE chunk_id=?", (cid,)).fetchone()
        if not c:
            continue
        d = labels.get(cid) or {"chunk_type": None, "axes": {}, "answers": {}, "extracted": []}
        chunks.append({
            "chunk_id": cid, "file_id": c["file_id"], "file_name": names.get(c["file_id"], ""), "slide_no": c["seq"],
            "title": c["title"], "text": c["text"], "chunk_type": d["chunk_type"],
            "axes": {k: {"values": v["values"], "status": v["status"], "evidence": v.get("evidence") or "",
                         "confidence": v.get("confidence")} for k, v in d["axes"].items()},
            "answers": {k: {"answer": v["answer"], "quote": v.get("quote") or "", "confidence": v.get("confidence")}
                        for k, v in d["answers"].items()},
            "extracted": [{"item": e["item"], "value": e["value"]} for e in d["extracted"]],
            "reasons": flagged.get(cid, []),
        })
    chunks.sort(key=lambda c: (c["file_name"], c["slide_no"]))
    axes = []
    for a in tax.axes:
        st = {"value": 0, "unknown": 0, "na": 0}
        counts = {v.name: 0 for v in a.values}
        for c in chunks:
            v = c["axes"].get(a.name)
            if not v:
                continue
            st[v["status"]] = st.get(v["status"], 0) + 1
            for x in v["values"]:
                if x in counts:
                    counts[x] += 1
        axes.append({"name": a.name, "kind": a.kind, "multi": a.multi, "active": a.active, "states": st,
                     "values": [{"name": v.name, "n": counts[v.name], "definition": v.definition or ""} for v in a.values]})
    qs = []
    for q in tax.questions:
        ans = [c["answers"][q.qid]["answer"] for c in chunks if q.qid in c["answers"]]
        qs.append({"qid": q.qid, "text": q.text, "O": ans.count("O"), "X": ans.count("X"), "NA": ans.count("N/A")})
    gen = [a["answer"] for c in chunks for qid, a in c["answers"].items() if qid.startswith(GEN_PREFIX)]
    if gen:
        qs.append({"qid": GEN_PREFIX + "*", "text": "1차 라벨 검증 질문(LLM 생성, 전체 합산). X는 1차 라벨이 본문과 어긋난 것이다",
                   "O": gen.count("O"), "X": gen.count("X"), "NA": gen.count("N/A")})
    ctl = [r[0] for r in con.execute("SELECT value FROM labels WHERE run_id=? AND kind='control'", (run_id,))]
    if ctl:
        qs.append({"qid": CTL_PREFIX + "*", "text": "대조 질문(붙지 않은 라벨, 전체 합산). O는 1차 분류 누락이나 3차 과잉 판정 신호다",
                   "O": ctl.count("O"), "X": ctl.count("X"), "NA": ctl.count("N/A")})
    reasons = {code: sum(1 for c in chunks if code in c["reasons"]) for code in review.REASONS}
    na_r, _ = alerts.na_ratio(con, run_id)
    dup_r, _ = alerts.dup_ratio(con, run_id, tax)
    risk = [c["answers"]["Q-COM-001"]["answer"] for c in chunks if "Q-COM-001" in c["answers"]]
    fails = {r[0]: r[1] for r in con.execute(
        "SELECT stage, COUNT(DISTINCT target_id) FROM failures WHERE run_id=? AND stage IN ('classify','label') GROUP BY stage",
        (run_id,))}
    data = {
        "kind": "results", "run_id": run_id, "generated_at": util.now_iso(), "model": ws.config["llm"]["model"],
        "kpi": {
            "files": sum(1 for f in files if f["status"] == "ok"), "failed_files": sum(1 for f in files if f["status"] != "ok"),
            "chunks": len(chunks), "content": sum(1 for c in chunks if c["chunk_type"] == "내용"),
            "classify_failed": sum(1 for c in chunks if not c["chunk_type"]),
            "label_failed": min(fails.get("label", 0), sum(1 for c in chunks if c["chunk_type"] and not c["answers"])),
            "flagged": len(flagged), "answers": len(risk), "risk_o": risk.count("O"),
            "na_ratio": na_r, "dup_ratio": dup_r,
        },
        "alerts": [dict(r) for r in con.execute("SELECT condition, value, threshold FROM alerts WHERE run_id=?", (run_id,))],
        "alert_labels": ALERT_LABELS,
        "axes": axes, "questions": qs, "reasons": reasons, "reason_labels": review.REASON_LABELS,
        "files": [{"file_id": f["file_id"], "file_name": f["file_name"],
                   "chunks": sum(1 for c in chunks if c["file_id"] == f["file_id"])} for f in files if f["status"] == "ok"],
        "chunks": chunks,
    }
    path = ws.path("screens", "results.html")
    util.write_text(path, review.fill_template("results.html", data))
    return path, len(chunks)
```

## DATA builder: review.html - `build_review` (full; the `data = {...}` dict is lines 319-334)

`labelbot/review.py:276-337`
```python
def build_review(ws, con, run_id, tax):
    flagged = con.execute("SELECT * FROM flagged_chunks WHERE run_id=?", (run_id,)).fetchall()
    if not flagged and not con.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone():
        raise ReviewError("RUN_NOT_FOUND")
    from labelbot.questions import control_answers, map_questions
    from labelbot.synonyms import SynonymTable

    syn = SynonymTable(tax.synonyms)
    ids = [r["chunk_id"] for r in flagged]
    bots = finals.bot_labels(con, run_id, ids)
    controls = control_answers(con, run_id, set(ids))
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
            # 대조 질문 답(읽기 전용). O면 그 라벨을 축 교정으로 더할지 사람이 판단한다.
            "controls": controls.get(f["chunk_id"], []),
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
        "file_ctx": _file_ctx(con, sorted({c["file_id"] for c in chunks})),
        "evidence_max": EVIDENCE_MAX, "evidence_quote_max": EVIDENCE_QUOTE_MAX, "evidence_reason_max": EVIDENCE_REASON_MAX,
    }
    path = ws.path("screens", "review.html")
    util.write_text(path, fill_template("review.html", data))
    return path, len(chunks)
```

## DATA builder: compare.html - `build_compare` (full)

`labelbot/review.py:340-361`
```python
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
```

## DATA shapes (summary)

- results: `{kind:"results", run_id, generated_at, model, kpi{files,failed_files,chunks,content,classify_failed,label_failed,flagged,answers,risk_o,na_ratio,dup_ratio}, alerts[{condition,value,threshold}], alert_labels, axes[{name,kind,multi,active,states{value,unknown,na},values[{name,n,definition}]}], questions[{qid,text,O,X,NA}], reasons{code:n}, reason_labels, files[{file_id,file_name,chunks}], chunks[{chunk_id,file_id,file_name,slide_no,title,text,chunk_type,axes{name:{values,status,evidence,confidence}},answers{qid:{answer,quote,confidence}},extracted[{item,value}],reasons[]}]}`
- review: `{kind:"review", run_id, generated_at, flag{unknown_ratio_min,confidence_min}, reason_labels, revisit_reasons, revisit_rules, revisit_memo_max, revisit_short_max, axes[{name,kind,multi,hierarchical,definition,values[{name,parent,definition,include,exclude}]}], questions[{qid,text}], chunks[...], file_slides{file_id:[{seq,chunk_id,src}]}, file_ctx{file_id:{file_name,rel_path,doc_title,slides[]}}, evidence_max, evidence_quote_max, evidence_reason_max}`
