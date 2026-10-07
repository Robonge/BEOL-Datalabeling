"""4차 불량 목록 추출(LLM 호출 0회), 검수·대조 화면 생성, 교정 반영(apply)."""
import json
import os
import re

from labelbot import axisupdate, finals, ingest, revisit, store, util
from labelbot.classify import NA, UNKNOWN
from labelbot.questions import GEN_PREFIX, all_questions, is_control
from labelbot.taxonomy import COMMON_TARGET
from labelbot.workspace import CODE_ROOT

# CONTROL_O: 이 chunk에 붙지 않은 라벨로 만든 대조 질문(Q-CTL-)에 O가 나왔다. 1차 분류 누락이나 3차 과잉 판정 신호다.
# UNKNOWN_O: 1차가 unknown이라 한 축에 LLM이 고른 후보 값의 검증 질문이 O다. unknown을 그 값으로 채울 후보다.
REASONS = ("UNKNOWN_HIGH", "LOW_CONFIDENCE", "QUOTE_NOT_FOUND", "PARSE_WARNING", "CLASSIFY_FAILED", "LABEL_FAILED",
           "CONTROL_O", "UNKNOWN_O")
REASON_LABELS = {
    "UNKNOWN_HIGH": "unknown 비율 높음",
    "LOW_CONFIDENCE": "확신도 낮음",
    "QUOTE_NOT_FOUND": "근거 인용 불일치",
    "PARSE_WARNING": "파싱 경고",
    "CLASSIFY_FAILED": "분류 실패",
    "LABEL_FAILED": "라벨 실패",
    "CONTROL_O": "대조 질문 O",
    "UNKNOWN_O": "unknown 축 후보 값 O",
}
# 교정 근거(evidence): 한 교정에 최대 3개, 인용 2~300자(공백 정규화 뒤), 이유 300자 이내.
# typed는 사람이 근거 칸에 직접 친 문장 중 본문·파일명·문서 제목에서 찾지 못한 것(엔지니어 지식)이다. 본문 대조를 하지 않는다.
EVIDENCE_SOURCES = ("chunk", "file_name", "doc_title", "typed")
EVIDENCE_MAX = 3
EVIDENCE_QUOTE_MIN, EVIDENCE_QUOTE_MAX = 2, 300
EVIDENCE_REASON_MAX = 300
EV_QUOTE_NOT_FOUND, EV_OTHER_FILE, EV_FORMAT = "EVIDENCE_QUOTE_NOT_FOUND", "EVIDENCE_OTHER_FILE", "EVIDENCE_FORMAT"
# 검수 실행이 라벨링하지 않은 축의 교정(화면을 거치지 않은 JSON 대비). 건너뛴 수를 apply 결과 행으로 보고한다.
AXIS_NOT_IN_RUN = "AXIS_NOT_IN_RUN"
# axis-update 실행의 비대상 축 교정·질문 답 교정(대상 축만 검수한다). 건너뛴 수를 apply 결과 행으로 보고한다.
AXIS_NOT_TARGET = "AXIS_NOT_TARGET"
# 대조 질문 교정이 그 chunk의 대조 질문이 아니다(화면을 거치지 않은 JSON 대비). 건너뛴 수를 apply 결과 행으로 보고한다.
CONTROL_UNKNOWN = "CONTROL_UNKNOWN"
# 확신도가 높아 확인 필요로 잡히지 않은 O/X 답 중 검수 화면에서 '표본 확인'으로 강조할 비율(flag.ox_sample_rate로 바꾼다).
# LLM이 매긴 확신도는 맞을 확률이 아니어서 0.99여도 틀린다. chunk·질문 ID 해시로 골라 다시 만들어도 같은 카드가 뽑힌다.
OX_SAMPLE_RATE = 0.1
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


def _axis_kinds(con, run_id=None):
    """축 종류. run_id를 주면 실행별 axis_kinds:<run>(axis-update가 실행 중에 남긴다)을 먼저 본다."""
    kinds = store.meta_json(con, "axis_kinds:" + run_id) if run_id else None
    if not isinstance(kinds, dict):
        kinds = store.meta_json(con, "axis_kinds")
    return kinds if isinstance(kinds, dict) else {}


def _signature_axes(sig):
    """축 서명 목록의 활성 축 이름 집합. 목록이 아니면 빈 집합."""
    if not isinstance(sig, list):
        return set()
    return {x["name"] for x in sig if isinstance(x, dict) and x.get("name") and x.get("active", True)}


def run_axes(con, run_id):
    """그 실행이 라벨링한 축 이름 집합. 알 수 없으면(옛 실행) None.

    meta의 실행별 axes_signature:<run_id>를 먼저 본다. 없으면(옛 실행) 작업 폴더에 마지막 실행 것 하나만 남는
    axes_signature(없으면 axis_kinds - inactive_axes)를 그 실행이 마지막 run일 때만 쓴다. 그 밖에는 labels의 축 행으로
    본다(실행마다 모든 chunk의 축 행을 쓴다). 비활성 축도 status='na'·confidence 없음 행으로 남으므로, 그런 행만 있는
    축은 라벨링하지 않은 축으로 본다.
    """
    names = _signature_axes(store.meta_json(con, "axes_signature:" + run_id))
    if names:
        return names
    if run_id == store.latest_label_run(con, finished=True):
        names = _signature_axes(store.meta_json(con, "axes_signature"))
        if names:
            return names
        kinds, inactive = store.meta_json(con, "axis_kinds"), store.meta_json(con, "inactive_axes")
        if isinstance(kinds, dict) and kinds:
            return set(kinds) - set(inactive if isinstance(inactive, list) else [])
    names = {r[0] for r in con.execute(
        "SELECT key FROM labels WHERE run_id=? AND kind='axis' GROUP BY key"
        " HAVING MAX(status <> 'na' OR confidence IS NOT NULL)", (run_id,))}
    return names or None


def primary_qid(tax):
    """questions 시트의 첫 공통 질문 ID(우선순위, 같으면 ID 순 — map_questions와 같은 순서). 없으면 None."""
    common = [q for q in tax.questions if q.target == COMMON_TARGET]
    common.sort(key=lambda q: (q.priority if q.priority is not None else float("inf"), q.qid))
    return common[0].qid if common else None


def judge_chunk(chunk, bot, failed_cls, failed_lab, cfg, kinds, syn=None, control_o=(), unknown_o=(), axes=None,
                reason_axes=None):
    """반환: (사유 코드 목록, unknown_ratio, min_confidence, 약신호 인용 수).

    control_o는 대조 질문 O 답, unknown_o는 unknown 축 후보 값 검증 질문 O 답의 인용 목록이다.
    인용이 본문에 있는(또는 짧은) O만 CONTROL_O·UNKNOWN_O로 올리고, 본문에 없는 인용은 QUOTE_NOT_FOUND로 본다.
    axes(axis-update 대상 축)를 주면 그 축만 보고(답 제외) LABEL_FAILED·PARSE_WARNING은 내지 않는다.
    reason_axes(dict)를 주면 축에서 나온 사유마다 {사유 코드: [축]}을 채운다.
    """
    reasons, weak = [], 0
    by_axis = {}

    def mark(code, name):
        if name not in by_axis.setdefault(code, []):
            by_axis[code].append(name)
    if control_o or unknown_o:
        texts = [chunk["text"]] + ([syn.apply(chunk["text"])[0]] if syn is not None else [])
        for code, quotes in (("CONTROL_O", control_o), ("UNKNOWN_O", unknown_o)):
            for q in quotes:
                reasons.append(code if is_short_quote(q) or quote_found(q, texts) else "QUOTE_NOT_FOUND")
    unknown_ratio = min_conf = None
    if failed_cls:
        reasons.append("CLASSIFY_FAILED")
    if failed_lab and axes is None:
        reasons.append("LABEL_FAILED")
    if axes is None and json.loads(chunk["warnings"] or "[]"):
        reasons.append("PARSE_WARNING")
    if bot:
        bot_axes = {k: a for k, a in bot["axes"].items() if axes is None or k in axes}
        answers = bot["answers"] if axes is None else {}
        cls_axes = [(k, a) for k, a in bot_axes.items() if kinds.get(k, "분류") == "분류" and a["status"] != "na"]
        if cls_axes:
            unknown_ratio = sum(1 for _, a in cls_axes if a["status"] == "unknown") / float(len(cls_axes))
            if unknown_ratio >= cfg["unknown_ratio_min"] - 1e-12:
                reasons.append("UNKNOWN_HIGH")
                for k, a in cls_axes:
                    if a["status"] == "unknown":
                        mark("UNKNOWN_HIGH", k)
        confs = [a["confidence"] for a in list(bot_axes.values()) + list(answers.values())
                 if a.get("confidence") is not None]
        if confs:
            min_conf = min(confs)
            if min_conf < cfg["confidence_min"] - 1e-12:
                reasons.append("LOW_CONFIDENCE")
                for k, a in bot_axes.items():
                    if a.get("confidence") is not None and a["confidence"] < cfg["confidence_min"] - 1e-12:
                        mark("LOW_CONFIDENCE", k)
        texts = [chunk["text"]]
        if syn is not None:
            texts.append(syn.apply(chunk["text"])[0])
        quotes = [(k, a["evidence"]) for k, a in bot_axes.items() if a.get("evidence") and a["status"] == "value"]
        quotes += [(None, a["quote"]) for a in answers.values() if a["answer"] in ("O", "X") and a.get("quote")]
        missing = False
        for k, q in quotes:
            if is_short_quote(q):
                weak += 1
            elif not quote_found(q, texts):
                missing = True
                if k is not None:
                    mark("QUOTE_NOT_FOUND", k)
        if missing:
            reasons.append("QUOTE_NOT_FOUND")
    reasons = [r for r in REASONS if r in reasons]
    if reason_axes is not None:
        reason_axes.update((code, by_axis[code]) for code in reasons if code in by_axis)
    return reasons, unknown_ratio, min_conf, weak


def compute_flags(con, run_id, cfg, tax=None, reports_dir=None, axes=None):
    """flagged_chunks와 reports/flagged_<실행ID>.jsonl·md를 만든다. 상한 없음. LLM을 부르지 않는다.

    axes를 주지 않아도 axis-update 실행이면 그 실행의 대상 축으로 본다(judge_chunk axes). 사유별 축은 reason_axes 열에 둔다.
    """
    if axes is None:
        axes = axisupdate.target_axes(con, run_id)
    syn = None
    if tax is not None:
        from labelbot.synonyms import SynonymTable

        syn = SynonymTable(tax.synonyms)
    pop = sorted(_run_population(con, run_id))
    bots = finals.bot_labels(con, run_id, pop)
    fails = {}
    for r in con.execute("SELECT stage, target_id FROM failures WHERE run_id=? AND stage IN ('classify','label')", (run_id,)):
        fails.setdefault(r[1], set()).add(r[0])
    kinds = _axis_kinds(con, run_id)
    control_o, unknown_o = {}, {}  # axis-update는 2·3차를 다시 돌리지 않으므로 대조·unknown 후보 O를 보지 않는다
    for r in () if axes is not None else con.execute(
            "SELECT chunk_id, evidence FROM labels WHERE run_id=? AND kind='control' AND value='O'", (run_id,)):
        control_o.setdefault(r[0], []).append(r[1] or "")
    for r in () if axes is not None else con.execute(
            "SELECT l.chunk_id, l.evidence FROM labels l JOIN gen_questions g ON g.qid=l.key"
            " JOIN labels a ON a.run_id=l.run_id AND a.chunk_id=l.chunk_id AND a.kind='axis' AND a.key=g.axis"
            " WHERE l.run_id=? AND l.kind='answer' AND l.value='O' AND a.status='unknown'", (run_id,)):
        unknown_o.setdefault(r[0], []).append(r[1] or "")
    con.execute("DELETE FROM flagged_chunks WHERE run_id=?", (run_id,))
    rows = []
    for cid in pop:
        chunk = con.execute("SELECT * FROM chunks WHERE chunk_id=?", (cid,)).fetchone()
        if not chunk:
            continue
        bot = bots.get(cid)
        # axis-update는 chunk_type을 이어받으므로 이번 실행의 분류 실패 기록만 본다
        failed_cls = "classify" in fails.get(cid, ()) and (axes is not None or not (bot and bot["chunk_type"]))
        failed_lab = "label" in fails.get(cid, ()) and not (bot and bot["answers"])
        ra = {}
        reasons, ur, mc, weak = judge_chunk(chunk, bot, failed_cls, failed_lab, cfg["flag"], kinds, syn,
                                            control_o.get(cid, ()), unknown_o.get(cid, ()), axes, ra)
        if not reasons:
            continue
        con.execute(
            "INSERT INTO flagged_chunks(run_id, chunk_id, reason_codes, unknown_ratio, min_confidence, text_hash,"
            " weak_quotes, reason_axes) VALUES(?,?,?,?,?,?,?,?)",
            (run_id, cid, util.dumps(reasons), ur, mc, chunk["text_hash"], weak, util.dumps(ra)),
        )
        rows.append({"chunk_id": cid, "file_id": chunk["file_id"], "reason_codes": reasons,
                     "unknown_ratio": ur, "min_confidence": mc, "reason_axes": ra})
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
        b64 = util.read_b64_text(ws.path(r["rel_file"]))
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
                b64 = util.read_b64_text(ws.path(r["rel_file"]))
            except (OSError, ValueError):
                continue
            rows.append({"seq": r["seq"], "chunk_id": r["chunk_id"], "src": "data:image/jpeg;base64," + b64})
        out[fid] = rows
    return out


def _file_ctx(con, file_ids):
    """검수 화면의 근거 지정용 파일 맥락: 파일명·상대 경로·문서 제목과 같은 파일 모든 슬라이드의 제목·본문(순서대로)."""
    out = {}
    for fid in file_ids:
        f = con.execute("SELECT file_name, rel_path, title FROM files WHERE file_id=?", (fid,)).fetchone()
        slides = [{"chunk_id": r["chunk_id"], "slide_no": r["seq"], "title": r["title"], "text": r["text"]}
                  for r in con.execute("SELECT chunk_id, seq, title, text FROM chunks WHERE file_id=? ORDER BY seq, chunk_id",
                                       (fid,))]
        out[fid] = {"file_name": f["file_name"] if f else "", "rel_path": f["rel_path"] if f else "",
                    "doc_title": (f["title"] if f else None) or "", "slides": slides}
    return out


def review_axes(con, run_id, tax, chunks):
    """검수 DATA.axes. 그 실행이 라벨링한 축만 editable이다(실행 축을 모르는 옛 실행은 모두 editable).

    실행 뒤 taxonomy에 더해진 축은 pending(다음 실행부터 라벨링), 실행에 있었는데 지금 활성 축이 아닌 축은
    removed로 넣는다. 둘 다 읽기 전용이다. removed 축의 값 목록은 지금 taxonomy에 없으므로 라벨 값으로 채운다.
    axis-update 실행이면 대상 축만 editable이고, 실행이 라벨링한 나머지 축은 locked(이번 축 변경 대상 아님, 읽기 전용)다.
    """
    ran = run_axes(con, run_id)
    target = axisupdate.target_axes(con, run_id)
    out = []
    for a in tax.axes:
        if not a.active:
            continue
        item = {"name": a.name, "kind": a.kind, "multi": a.multi, "hierarchical": bool(a.hierarchical),
                "definition": a.definition or "",
                "values": [{"name": v.name, "parent": v.parent or None, "definition": v.definition or "",
                            "include": v.include or "", "exclude": v.exclude or ""} for v in a.values]}
        if (ran is None or a.name in ran) and target is not None and a.name not in target:
            item.update(editable=False, locked=True)
        elif ran is None or a.name in ran:
            item["editable"] = True
        else:
            item.update(editable=False, pending=True)
        out.append(item)
    if ran is None:
        return out
    sig = store.meta_json(con, "axes_signature")
    sig = {x.get("name"): x for x in sig if isinstance(x, dict)} if isinstance(sig, list) else {}
    kinds = _axis_kinds(con)
    for name in sorted(ran - {a["name"] for a in out}):
        seen = []
        for c in chunks:
            for v in (c["axes"].get(name) or {}).get("values") or []:
                if v not in seen and v not in (NA, UNKNOWN):
                    seen.append(v)
        old = tax.axis(name)  # 지금 taxonomy에 있으나 비활성이면 inactive, 아예 없으면 removed
        out.append({"name": name, "kind": old.kind if old else (sig.get(name) or {}).get("kind") or kinds.get(name, "분류"),
                    "multi": bool(old.multi if old else (sig.get(name) or {}).get("multi", True)),
                    "hierarchical": False, "definition": "",
                    "values": [{"name": v, "parent": None, "definition": "", "include": "", "exclude": ""} for v in seen],
                    "editable": False, "removed": old is None, "inactive": old is not None})
    return out


def ox_sampled(chunk_id, qid, rate=OX_SAMPLE_RATE):
    """O/X 답 표본 여부(결정적). chunk·질문 ID 해시의 앞 8자리를 [0, 1)로 바꿔 rate 미만이면 표본이다."""
    h = util.sha256_text("%s|%s" % (chunk_id, qid))[:8]
    return int(h, 16) / 0x100000000 < rate


def attention_for(chunk, gen_map, conf_min, editable, sample_rate=OX_SAMPLE_RATE):
    """검수 화면의 '확인 필요' 판정(순수 함수). {"axes": {축: [코드]}, "questions": {qid: [코드]}}, 빈 목록은 넣지 않는다.

    코드: LOW_CONF(확신도 < conf_min, judge_chunk와 같은 비교식·None은 아님) · UNKNOWN(값에 unknown) ·
    VERIFY_X(검증 질문 Q-GEN 답 X, gen_map {qid: 대상 축}의 축에만) · CONTROL_O(대조 질문 답 O의 대상 축) ·
    OX_SAMPLE(확신도가 낮지 않은 O/X 답 중 ox_sampled로 뽑힌 표본, 과신 점검용).
    editable은 검수에서 고칠 수 있는 축 이름 집합이다. 비활성·잠긴(axis-update) 축은 넣지 않는다.
    """
    low = lambda c: c is not None and c < conf_min - 1e-12
    axes = {}
    for k, a in (chunk.get("axes") or {}).items():
        if k in editable:
            if low(a.get("confidence")):
                axes.setdefault(k, []).append("LOW_CONF")
            if UNKNOWN in (a.get("values") or []):
                axes.setdefault(k, []).append("UNKNOWN")
    qs = {}
    for qid, a in (chunk.get("answers") or {}).items():
        if low(a.get("confidence")):
            qs[qid] = ["LOW_CONF"]
        elif a.get("answer") in ("O", "X") and ox_sampled(chunk.get("chunk_id"), qid, sample_rate):
            qs[qid] = ["OX_SAMPLE"]
        k = gen_map.get(qid)
        if qid.startswith(GEN_PREFIX) and a.get("answer") == "X" and k in editable:
            axes.setdefault(k, []).append("VERIFY_X")
    for c in chunk.get("controls") or ():
        if c.get("answer") == "O" and c.get("axis") in editable:
            axes.setdefault(c["axis"], []).append("CONTROL_O")
    return {"axes": axes, "questions": qs}


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
    pq = primary_qid(tax)
    conf_min = float(ws.config["flag"]["confidence_min"])
    sample_rate = float(ws.config["flag"].get("ox_sample_rate", OX_SAMPLE_RATE))
    gen_map = {}
    want = set(ids)
    for r in con.execute("SELECT qid, chunk_id, axis FROM gen_questions"):  # 본문 열(text)은 읽지 않는다
        if r["chunk_id"] in want:
            gen_map[r["qid"]] = r["axis"]
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
            "mapped_questions": mapped or ([pq] if pq else []),
            # 대조 질문 답. 사람이 답을 교정하면 품질 신호로만 남고(확정 라벨에 들어가지 않는다) 축은 따로 고친다.
            "controls": controls.get(f["chunk_id"], []),
        })

    review_ax = review_axes(con, run_id, tax, chunks)
    editable = {a["name"] for a in review_ax if a.get("editable")}
    for c in chunks:  # 화면 DATA 전용이다. DB·label_hash·내보내기에는 넣지 않는다
        c["attention"] = attention_for(c, gen_map, conf_min, editable, sample_rate)
    info = axisupdate.run_info(con, run_id)
    data = {
        "kind": "review", "run_id": run_id, "generated_at": util.now_iso(), "flag": ws.config["flag"],
        # axis-update 실행이면 대상 축만 검수한다(질문 답 편집 영역을 숨긴다). 보통 실행은 None.
        "axis_update": {"parent": info["parent"], "target": info["target"]} if info else None,
        "reason_labels": REASON_LABELS,
        "revisit_reasons": revisit.REASON_LABELS, "revisit_rules": revisit.TARGET_REASONS,
        "revisit_memo_max": revisit.MEMO_MAX, "revisit_short_max": revisit.SHORT_MAX,
        "axes": review_ax,
        "primary_qid": pq,
        "questions": [{"qid": q.qid, "text": q.text} for q in all_questions(con, tax)],
        "chunks": chunks,
        "file_slides": _file_slides(ws, con, sorted({c["file_id"] for c in chunks})),
        "file_ctx": _file_ctx(con, sorted({c["file_id"] for c in chunks})),
        "evidence_max": EVIDENCE_MAX, "evidence_quote_max": EVIDENCE_QUOTE_MAX, "evidence_reason_max": EVIDENCE_REASON_MAX,
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
    review 파일에서 버린 재검토 요청·교정 근거, 그 실행이 라벨링하지 않은 축의 교정이 있으면 같은 파일로
    (sha, REVISIT_*·EVIDENCE_*·AXIS_NOT_IN_RUN·AXIS_NOT_TARGET 코드, 건수, 종류, 실행 ID) 행을 더한다.
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


def _clean_reason(reason):
    """이유: 공백을 축약하고 300자에서 자른다. 문자열이 아니거나 비면 None."""
    if not isinstance(reason, str):
        return None
    r = " ".join(reason.split())[:EVIDENCE_REASON_MAX].rstrip()
    return r or None


def _check_evidence(con, file_id, item):
    """근거 한 항목을 검증한다. 반환: (저장할 항목 또는 None, 버린 사유 코드 또는 None).

    chunk는 교정 chunk와 같은 파일이고 인용이 그 chunk의 제목·본문에 있어야 한다. file_name은 파일명·상대 경로,
    doc_title은 문서 제목에 있어야 한다. 비교는 util.norm_for_match(인용 검사와 같은 정규화)로 한다.
    """
    if not isinstance(item, dict) or item.get("source") not in EVIDENCE_SOURCES or not isinstance(item.get("quote"), str):
        return None, EV_FORMAT
    quote = " ".join(item["quote"].split())
    if not EVIDENCE_QUOTE_MIN <= len(quote) <= EVIDENCE_QUOTE_MAX:
        return None, EV_FORMAT
    src, cid, slide_no = item["source"], None, None
    if src == "typed":
        return {"source": src, "chunk_id": None, "slide_no": None, "quote": quote}, None
    if src == "chunk":
        cid = item.get("chunk_id")
        if not isinstance(cid, str):
            return None, EV_FORMAT
        r = con.execute("SELECT file_id, seq, title, text FROM chunks WHERE chunk_id=?", (cid,)).fetchone()
        # 이 작업 DB에 없는 chunk도 같은 파일임을 확인할 수 없으므로 다른 파일로 센다.
        if r is None or r["file_id"] != file_id:
            return None, EV_OTHER_FILE
        hay, slide_no = [r["title"], r["text"]], r["seq"]
    else:
        f = con.execute("SELECT file_name, rel_path, title FROM files WHERE file_id=?", (file_id,)).fetchone()
        if f is None:
            return None, EV_QUOTE_NOT_FOUND
        hay = [f["file_name"], f["rel_path"]] if src == "file_name" else [f["title"]]
    needle = util.norm_for_match(quote)
    if not any(needle in util.norm_for_match(h) for h in hay if h):
        return None, EV_QUOTE_NOT_FOUND
    return {"source": src, "chunk_id": cid, "slide_no": slide_no, "quote": quote}, None


def _correction_evidence(con, file_id, c, drop):
    """교정 항목의 evidence·reason → (evidence JSON 또는 None, reason 또는 None, 버린 근거 수 또는 None).

    evidence 키가 없으면 버린 수도 None이다(근거 없는 예전 검수 파일과 같은 행). 목록이 아니면 1건 버린 것으로 센다.
    EVIDENCE_MAX를 넘는 항목은 검증하지 않고 EVIDENCE_FORMAT으로 버린다.
    """
    reason = _clean_reason(c.get("reason"))
    if "evidence" not in c or c["evidence"] is None:
        return None, reason, None
    items = c["evidence"]
    if not isinstance(items, list):
        drop(EV_FORMAT)
        return None, reason, 1
    keep, dropped = [], 0
    for i, item in enumerate(items):
        row, code = (None, EV_FORMAT) if i >= EVIDENCE_MAX else _check_evidence(con, file_id, item)
        if row is None:
            drop(code)
            dropped += 1
        else:
            keep.append(row)
    return (util.dumps(keep) if keep else None), reason, dropped


def _apply_review(con, tax, doc, sha):
    run_id = doc.get("run_id")
    flagged = {r["chunk_id"]: r for r in con.execute("SELECT * FROM flagged_chunks WHERE run_id=?", (run_id,))}
    if not flagged:
        return "NO_FLAGGED_FOR_RUN", 0, {}
    bots = finals.bot_labels(con, run_id, list(flagged))
    ran = run_axes(con, run_id)
    target = axisupdate.target_axes(con, run_id)
    qtext = {q.qid: q.text for q in all_questions(con, tax)}  # export와 같은 출처(생성 질문 포함)
    from labelbot.questions import control_answers
    ctls = {cid: {x["qid"]: x for x in xs} for cid, xs in control_answers(con, run_id, set(flagged)).items()}
    now, n = util.now_iso(), 0
    con.execute("DELETE FROM corrections WHERE review_run_id=?", (run_id,))

    ev_drops = {}

    def drop(code):
        ev_drops[code] = ev_drops.get(code, 0) + 1

    def recheck(cid):
        cur = con.execute("SELECT text_hash FROM chunks WHERE chunk_id=?", (cid,)).fetchone()
        return 0 if cur and cur[0] == flagged[cid]["text_hash"] else 1

    def file_of(cid):
        r = con.execute("SELECT file_id FROM chunks WHERE chunk_id=?", (cid,)).fetchone()
        return r[0] if r else None

    for c in doc.get("corrections") or []:
        cid = c.get("chunk_id")
        if cid not in flagged or c.get("target") not in ("axis", "answer", "control"):
            continue
        if c["target"] == "answer" and is_control(c.get("key")):
            continue  # 대조 질문 답은 target "control"로만 받는다(확정 라벨 답과 섞지 않는다)
        if c["target"] == "control" and (target is not None or c.get("key") not in ctls.get(cid, {})):
            drop(CONTROL_UNKNOWN)  # 이 chunk의 대조 질문이 아니거나 axis-update 실행(대조 질문을 다시 돌리지 않는다)
            continue
        if c["target"] == "axis" and ran is not None and c.get("key") not in ran:
            drop(AXIS_NOT_IN_RUN)  # 이 실행이 라벨링하지 않은 축(실행 뒤 taxonomy에 더해진 축 등)은 고칠 수 없다
            continue
        if target is not None and (c["target"] == "answer" or c.get("key") not in target):
            drop(AXIS_NOT_TARGET)  # axis-update 실행은 대상 축만 고친다(비대상 축·질문 답은 잠금)
            continue
        bot = bots.get(cid) or {"axes": {}, "answers": {}}
        if c["target"] == "axis":
            bv = (bot["axes"].get(c["key"]) or {}).get("values")
            qh = None
        elif c["target"] == "control":
            # 대조 질문 답 교정은 품질 신호로만 남는다(finals는 axis·answer 행만 확정 라벨에 쓴다). Domain-Engr-bot 장부로 간다.
            x = ctls[cid][c["key"]]
            bv = x["answer"]
            qh = util.sha256_text(x["text"] or "")[:16]
        else:
            bv = (bot["answers"].get(c["key"]) or {}).get("answer")
            qh = util.sha256_text(qtext.get(c["key"], ""))[:16]
        ev, reason, ev_dropped = _correction_evidence(con, file_of(cid), c, drop)
        con.execute(
            "INSERT OR REPLACE INTO corrections(review_run_id, chunk_id, target_kind, target_key, human_value, bot_value,"
            " review_status, recheck, text_hash, question_hash, file_sha256, applied_at, evidence, reason, evidence_dropped)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, cid, c["target"], c["key"], util.dumps(c.get("value")), util.dumps(bv), finals.CORRECTED,
             recheck(cid), flagged[cid]["text_hash"], qh, sha, now, ev, reason, ev_dropped),
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
    drops = dict(drops)
    for code, k in ev_drops.items():
        drops[code] = drops.get(code, 0) + k
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
