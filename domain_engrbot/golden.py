"""골든셋 추가(golden add)와 골든셋 → 번들 변환(eval용).

- 결정 파일은 qa/inbox/*.json이고 io.read_json_input으로만 읽는다(사람 입력).
- 결정 파일의 qa_run_id가 이 실행이 아니면 건너뛴다(OTHER_RUN). 존재하지 않는 실행이면 거부한다(QA_RUN_NOT_FOUND).
- 같은 실행의 결정 파일이 여럿이면 가장 최근 파일 하나가 그 실행의 결정 전체를 대신한다(labelbot apply와 같다).
- confirm·correct만 골든셋에 넣는다. cannot_judge는 넣지 않는다.
- 검수 실행 때와 지금의 text_hash가 다르면 그 레코드는 넣지 않고 TEXT_CHANGED를 로그에 남긴다.
- 대기열 레코드(REVIEW)의 corrections 표 사람 값도 넣는다. 같은 필드는 결정 파일이 우선한다.
- 같은 결정을 두 번 반영해도 golden.jsonl이 같다(golden_id 순 정렬, 바뀌지 않은 행은 confirmed_at을 유지한다).
"""
import json
import os

from domain_engrbot import io, model

DECISION_KIND = "qa_decisions"
CANNOT_JUDGE = ("판단 불가", "cannot_judge")


# ---- 결정 파일 -------------------------------------------------------------

def read_inbox(run):
    """반환: (이 실행의 결정 dict 또는 None, 상태 dict). 로그에는 실행 ID와 사유 코드만 남긴다."""
    paths = run.paths
    status = {"files": 0, "used": 0, "skipped": 0, "rejected": 0, "reasons": {}}

    def note(reason, target):
        status["reasons"][reason] = status["reasons"].get(reason, 0) + 1
        run.log("decisions", target, reason)

    if not os.path.isdir(paths.inbox):
        return None, status
    names = [fn for fn in os.listdir(paths.inbox) if fn.lower().endswith(".json")]
    names.sort(key=lambda fn: (os.path.getmtime(os.path.join(paths.inbox, fn)), fn))
    runs = set(paths.list_runs())
    chosen = None
    for fn in names:
        status["files"] += 1
        try:
            doc = io.read_json_input(os.path.join(paths.inbox, fn), paths.inputs_dir)
        except (ValueError, UnicodeDecodeError, OSError):
            status["rejected"] += 1
            note("DECISIONS_JSON_INVALID", run.qa_run_id)
            continue
        if not isinstance(doc, dict) or doc.get("kind") != DECISION_KIND:
            status["skipped"] += 1
            note("DECISIONS_KIND_UNKNOWN", run.qa_run_id)
            continue
        rid = doc.get("qa_run_id")
        if rid == run.qa_run_id:
            if chosen is not None:
                status["skipped"] += 1
                note("DECISIONS_SUPERSEDED", rid)
            chosen = doc
            continue
        if isinstance(rid, str) and rid in runs:
            status["skipped"] += 1
            note("DECISIONS_OTHER_RUN", rid)
        else:
            status["rejected"] += 1
            note("QA_RUN_NOT_FOUND", rid if isinstance(rid, str) and len(rid) <= 40 else "-")
    if chosen is not None:
        status["used"] = 1
    return chosen, status


def decisions_sha256(doc):
    return model.hash_obj(doc) if doc is not None else None


def text_changed(vmap, bundle, record_id):
    """검수 실행 때(verdict)와 지금(번들)의 text_hash가 다르면 True."""
    v = vmap.get(record_id)
    unit = bundle.units.get(record_id)
    if v is None or unit is None:
        return True
    return bool(v.get("text_hash")) and v.get("text_hash") != unit.get("text_hash")


# ---- 값 꺼내기 -------------------------------------------------------------

def bot_value(rec, field):
    """(값, 인용). 축은 값 목록, 질문은 답 문자열. 없으면 (None, None)."""
    kind, _, key = field.partition(":")
    if kind == "axis":
        a = (rec.get("axes") or {}).get(key)
        if isinstance(a, dict):
            return list(a.get("values") or []), ((a.get("evidence") or {}).get("quote") or "")
    elif kind == "answer":
        a = (rec.get("answers") or {}).get(key)
        if isinstance(a, dict):
            return a.get("answer"), ((a.get("evidence") or {}).get("quote") or "")
    elif kind == "extract":
        item, _, idx = key.partition("#")
        ex = rec.get("extracted") or []
        if idx.isdigit() and int(idx) < len(ex) and isinstance(ex[int(idx)], dict):
            e = ex[int(idx)]
            return e.get("value"), ((e.get("evidence") or {}).get("quote") or "")
    return None, None


def _axis_values(value):
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str) and v.strip()]
    if isinstance(value, str) and value.strip():
        return [value]
    return []


def _put(labels, evidence, field, value, quote):
    """골든 labels에 필드 하나를 넣는다. 넣었으면 True."""
    kind, _, key = field.partition(":")
    if kind == "axis":
        vals = _axis_values(value)
        if not vals or any(v in CANNOT_JUDGE for v in vals):
            return False
        labels["axes"][key] = vals
    elif kind == "answer":
        if not isinstance(value, str) or not value or value in CANNOT_JUDGE:
            return False
        labels["answers"][key] = value
    else:
        return False
    if isinstance(quote, str) and quote.strip():
        evidence[field] = quote
    else:
        evidence.pop(field, None)
    return True


def _human_value(row):
    v = row.get("human_value")
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


def _from_corrections(run, rec, labels, evidence):
    """bundle.meta["corrections"]의 사람 값. chunk 확인(confirmed)은 봇 값 전체를 확정한 것으로 본다."""
    rows = ((run.bundle.meta or {}).get("corrections") or {}).get(rec["record_id"]) or []
    unit = run.bundle.units.get(rec["record_id"]) or {}
    n = 0
    for row in rows:
        if row.get("text_hash") and row["text_hash"] != unit.get("text_hash"):
            run.log("golden", rec["record_id"], "CORRECTION_TEXT_CHANGED")
            continue
        kind, key, val = row.get("target_kind"), row.get("target_key"), _human_value(row)
        if kind == "chunk" and val == "confirmed":
            for name in sorted(rec.get("axes") or {}):
                bv, bq = bot_value(rec, "axis:" + name)
                n += _put(labels, evidence, "axis:" + name, bv, bq)
            for qid in sorted(rec.get("answers") or {}):
                bv, bq = bot_value(rec, "answer:" + qid)
                n += _put(labels, evidence, "answer:" + qid, bv, bq)
        elif kind in ("axis", "answer") and key:
            n += _put(labels, evidence, "%s:%s" % (kind, key), val, None)
    return n


# ---- golden add -------------------------------------------------------------

def _row(run, rec, labels, evidence):
    unit = run.bundle.units[rec["record_id"]]
    tax = run.bundle.taxonomy or {}
    return {
        "golden_id": model.hash_obj([rec["record_id"], unit.get("text_hash")])[:32],
        "record_id": rec["record_id"], "file_id": rec.get("file_id"), "text_hash": unit.get("text_hash"),
        "labels": labels, "evidence": evidence, "source": "review:%s" % run.qa_run_id,
        "confirmed_at": None, "taxonomy_version": tax.get("version"), "questions_version": tax.get("questions_version"),
    }


def collect(run, doc):
    """반환: ({record_id: (labels, evidence)}, 건너뛴 레코드 수)."""
    recs = {r["record_id"]: r for r in run.bundle.records}
    vmap = run.verdict_map()
    per = {}
    skipped = set()

    def slot(rid):
        return per.setdefault(rid, ({"axes": {}, "answers": {}}, {}))

    # 대기열 레코드의 corrections 표 사람 값
    for v in run.verdicts:
        rid = v["record_id"]
        if v["verdict"] != "REVIEW" or rid not in recs:
            continue
        if not ((run.bundle.meta or {}).get("corrections") or {}).get(rid):
            continue
        if text_changed(vmap, run.bundle, rid):
            skipped.add(rid)
            run.log("golden", rid, "TEXT_CHANGED")
            continue
        labels, evidence = slot(rid)
        _from_corrections(run, recs[rid], labels, evidence)

    # 결정 파일(REVIEW 대기열과 PASS 표본의 필드 결정)
    for d in (doc or {}).get("decisions") or []:
        if not isinstance(d, dict):
            continue
        rid, field, kind = d.get("record_id"), d.get("field") or "", d.get("decision")
        if rid not in recs or rid not in vmap:
            skipped.add(rid)
            run.log("golden", rid if isinstance(rid, str) else "-", "RECORD_UNKNOWN")
            continue
        if kind not in ("confirm", "correct"):
            continue
        if text_changed(vmap, run.bundle, rid):
            if rid not in skipped:
                run.log("golden", rid, "TEXT_CHANGED")
            skipped.add(rid)
            continue
        if kind == "confirm":
            value, quote = bot_value(recs[rid], field)
        else:
            value, quote = d.get("value"), d.get("quote")
        labels, evidence = slot(rid)
        _put(labels, evidence, field, value, quote)
    out = {rid: le for rid, le in per.items() if rid not in skipped and (le[0]["axes"] or le[0]["answers"])}
    return out, len(skipped)


def add(run):
    """반환: {"added", "skipped", "unchanged", "rejected"}. golden.jsonl을 golden_id 순으로 다시 쓴다."""
    doc, status = read_inbox(run)
    found, skipped = collect(run, doc)
    recs = {r["record_id"]: r for r in run.bundle.records}
    path = run.paths.golden
    existing = {g["golden_id"]: g for g in io.read_own_jsonl(path)}
    added = unchanged = 0
    now = model.now_iso()
    for rid in sorted(found):
        labels, evidence = found[rid]
        row = _row(run, recs[rid], labels, evidence)
        old = existing.get(row["golden_id"])
        if old is not None:
            merged_labels = {"axes": dict((old.get("labels") or {}).get("axes") or {}),
                             "answers": dict((old.get("labels") or {}).get("answers") or {})}
            merged_labels["axes"].update(labels["axes"])
            merged_labels["answers"].update(labels["answers"])
            touched = {"axis:" + k for k in labels["axes"]} | {"answer:" + k for k in labels["answers"]}
            merged_ev = {f: q for f, q in (old.get("evidence") or {}).items() if f not in touched}
            merged_ev.update(evidence)
            row["labels"], row["evidence"] = merged_labels, merged_ev
            same = {k: v for k, v in row.items() if k not in ("confirmed_at", "source")} == \
                {k: v for k, v in old.items() if k not in ("confirmed_at", "source")}
            if same:
                unchanged += 1
                continue
        row["confirmed_at"] = now
        existing[row["golden_id"]] = row
        added += 1
        run.log("golden", rid, "ADDED")
    io.write_jsonl(path, [existing[k] for k in sorted(existing)])
    return {"added": added, "skipped": skipped, "unchanged": unchanged, "rejected": status["rejected"]}


# ---- 골든셋 → 번들 ----------------------------------------------------------

def _ev(quote):
    return {"quote": quote or "", "unit_id": None, "start": None, "end": None}


def to_bundle(golden_rows, base_bundle):
    """골든 라벨을 가진 레코드로 번들을 만든다(eval용).

    - base 번들에 레코드 ID가 있고 text_hash가 같은 행만 쓴다.
    - 상태는 값에서 정한다(해당 없음 → na, unknown → unknown, 그 밖 → value).
    - 근거 인용이 없는 value 축과 O·X 답은 뺀다(A12: 근거가 없는 항목은 L3 평가에서 뺀다).
    - 같은 파일의 unit은 모두 넣는다(L3 다른 chunk 검사에 필요하다).
    """
    base_recs = {r["record_id"]: r for r in base_bundle.records}
    tax = model.TaxIndex(base_bundle.taxonomy)
    records = []
    seen = set()
    for g in sorted(golden_rows, key=lambda g: (g.get("record_id") or "", g.get("golden_id") or "")):
        rid = g.get("record_id")
        unit = base_bundle.units.get(rid)
        if unit is None or rid in seen or g.get("text_hash") != unit.get("text_hash"):
            continue
        seen.add(rid)
        base = base_recs.get(rid) or {}
        labels, evidence = g.get("labels") or {}, g.get("evidence") or {}
        axes = {}
        for name, vals in sorted((labels.get("axes") or {}).items()):
            vals = list(vals)
            if vals == [tax.na]:
                axes[name] = {"values": vals, "status": "na", "evidence": _ev(""), "confidence": 1.0}
            elif vals == [tax.unknown]:
                axes[name] = {"values": vals, "status": "unknown", "evidence": _ev(""), "confidence": 1.0}
            elif evidence.get("axis:" + name):
                axes[name] = {"values": vals, "status": "value", "evidence": _ev(evidence["axis:" + name]),
                              "confidence": 1.0}
        answers = {}
        for qid, ans in sorted((labels.get("answers") or {}).items()):
            q = evidence.get("answer:" + qid) or ""
            if ans in ("O", "X") and not q:
                continue
            answers[qid] = {"answer": ans, "evidence": _ev(q), "confidence": 1.0}
        records.append({
            "record_id": rid, "file_id": unit["file_id"], "labeler_run_id": base.get("labeler_run_id"),
            "chunk_type": labels.get("chunk_type") or base.get("chunk_type"), "axes": axes, "answers": answers,
            "extracted": [], "failures": [], "labeler": dict(base.get("labeler") or {}), "human_reviewed": True,
            "duplicate_fields": [],
        })
    fids = {r["file_id"] for r in records}
    meta = dict(base_bundle.meta or {}, golden=True)
    b = model.Bundle(base_bundle.labeler_run_id, {k: v for k, v in base_bundle.sources.items() if k in fids},
                     {k: v for k, v in base_bundle.units.items() if v["file_id"] in fids}, records,
                     base_bundle.taxonomy, base_bundle.loader, meta)
    model.check_bundle(b)
    return b
