"""검토 화면 review.html 생성(4.5절, 6.6절). labelbot 검수 화면과 같은 방식이다.

- 템플릿 screens/qa_review.html의 `/*__DATA__*/null` 자리에 표시할 데이터(JSON)를 넣는다. 서버 없이 파일을 열어 쓴다.
- 이미지는 data URL로 넣고 chunk당 bundle.meta["limits"]["images_per_chunk"]개까지만 넣는다.
  화면에 올린 레코드의 파일마다 그 파일의 모든 슬라이드(전체 미리보기 + 슬라이드 안 그림)를
  files[file_id]["slides"]에 한 번만 넣는다(레코드는 자기 슬라이드를, 같은 파일의 다른 슬라이드도 여기서 찾아 보여 준다).
- 외부 주소를 참조하지 않는다. 데이터 안의 "http" 글자도 \\u 이스케이프로 바꿔 파일에 남기지 않는다.
- 네 구역: REVIEW 대기열(+PASS 표본), REJECT 목록(재작업 지시), AUTO_FIX(정규화 규칙별 묶음), 규칙 제안.
- 파일 표시 이름과 슬라이드 번호는 이 화면에만 넣는다. 결정 파일에는 넣지 않는다.
- 화면은 표시와 내려받기만 한다. 판정 로직을 넣지 않는다(R12).
"""
import base64
import hashlib
import json
import os
import random
import re

from domain_engrbot import codes, golden, io, model, normalize, queue

PKG_ROOT = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(PKG_ROOT, "screens", "qa_review.html")
DATA_MARK = "/*__DATA__*/null"
DEFAULT_IMAGES_PER_CHUNK = 4  # labelbot pipeline.json limits.images_per_chunk 기본값
FILE_IMAGES_MAX = 60  # 같은 파일의 슬라이드 이미지를 화면에 넣는 최대 장수(화면 파일 크기 상한)
FILE_PREVIEWS_MAX = 40  # 같은 파일의 슬라이드 전체 미리보기를 화면에 넣는 최대 장수
_MIME = {"jpg": "jpeg", "jpeg": "jpeg", "gif": "gif", "svg": "svg+xml", "bmp": "bmp", "png": "png", "emf": "emf",
         "wmf": "wmf", "tif": "tiff", "tiff": "tiff", "webp": "webp"}
_HTTP = re.compile(r"(?i)htt(p)")


def pass_sample_ids(run, n):
    """PASS 레코드 n건. 시드는 검수 실행 ID에서 정하므로 같은 실행과 같은 n이면 같은 표본이다."""
    if not n or n <= 0:
        return []
    pool = sorted(v["record_id"] for v in run.verdicts if v["verdict"] == "PASS" and not v.get("human_reviewed"))
    seed = int(hashlib.sha256(("pass-sample:%s" % run.qa_run_id).encode("utf-8")).hexdigest()[:16], 16)
    return sorted(random.Random(seed).sample(pool, min(int(n), len(pool))))


def images_limit(bundle):
    lim = ((bundle.meta or {}).get("limits") or {}).get("images_per_chunk")
    return int(lim) if isinstance(lim, int) and lim >= 0 else DEFAULT_IMAGES_PER_CHUNK


def _data_urls(bundle, unit, limit):
    out = []
    loader = bundle.loader
    for img in (unit.get("images") or [])[:limit]:
        if loader is None:
            break
        try:
            data = loader.image_bytes(img)
        except model.LoaderError:
            continue
        if not data:
            continue
        mime = _MIME.get(str(img.get("ext") or "png").lower().lstrip("."), "png")
        out.append("data:image/%s;base64,%s" % (mime, base64.b64encode(data).decode("ascii")))
    return out


def _file_slides(bundle, file_id, limit):
    """같은 파일의 슬라이드 목록(슬라이드 순). 레코드 이미지도 여기에만 넣어 화면 파일에 한 번만 들어간다.

    슬라이드마다 슬라이드 전체 미리보기(labelbot slide-images JPG, bundle.meta["slide_previews"])와
    슬라이드 안 그림을 넣는다. 미리보기는 파일당 FILE_PREVIEWS_MAX장, 그림은 FILE_IMAGES_MAX장까지 넣고,
    넘는 것은 이미지 없이 개수만 남긴다. 미리보기도 그림도 없는 슬라이드는 제목만 남긴다.
    """
    previews = (bundle.meta or {}).get("slide_previews") or {}
    units = sorted(((rid, u) for rid, u in bundle.units.items() if u.get("file_id") == file_id),
                   key=lambda x: (x[1].get("seq") is None, x[1].get("seq") or 0, x[0]))
    out, used, shown = [], 0, 0
    for rid, u in units:
        total = len(u.get("images") or [])
        urls = _data_urls(bundle, u, min(limit, max(0, FILE_IMAGES_MAX - used))) if total else []
        used += len(urls)
        preview = None
        if rid in previews and shown < FILE_PREVIEWS_MAX:
            got = _data_urls(bundle, {"images": [{"rel_file": previews[rid], "ext": "jpg"}]}, 1)
            preview = got[0] if got else None
            shown += 1 if preview else 0
        out.append({"record_id": rid, "slide_no": u.get("seq"), "title": u.get("title") or "", "preview": preview,
                    "images": urls, "image_total": total})
    return out


def _labels(rec):
    axes = {}
    for name, a in sorted((rec.get("axes") or {}).items()):
        if isinstance(a, dict):
            axes[name] = {"values": list(a.get("values") or []) if isinstance(a.get("values"), list) else [],
                          "status": a.get("status"), "quote": ((a.get("evidence") or {}).get("quote") or ""),
                          "confidence": a.get("confidence")}
    answers = {}
    for qid, a in sorted((rec.get("answers") or {}).items()):
        if isinstance(a, dict):
            answers[qid] = {"answer": a.get("answer"), "quote": ((a.get("evidence") or {}).get("quote") or ""),
                            "confidence": a.get("confidence")}
    extracted = []
    for i, e in enumerate(rec.get("extracted") or []):
        if isinstance(e, dict):
            extracted.append({"field": "extract:%s#%d" % (e.get("item"), i), "item": e.get("item"),
                              "value": e.get("value"), "quote": ((e.get("evidence") or {}).get("quote") or "")})
    return {"chunk_type": rec.get("chunk_type"), "axes": axes, "answers": answers, "extracted": extracted}


def _fields(rec, axis_order):
    names = list((rec.get("axes") or {}).keys())
    names.sort(key=lambda n: (axis_order.get(n, 999), n))
    out = ["axis:%s" % n for n in names]
    out += ["answer:%s" % q for q in sorted(rec.get("answers") or {})]
    out += ["extract:%s#%d" % (e.get("item"), i) for i, e in enumerate(rec.get("extracted") or []) if isinstance(e, dict)]
    return out


def _issue_view(i, rec):
    quote = None
    if i.get("field") and rec is not None:
        quote = golden.bot_value(rec, i["field"])[1]
    return {"code": i["code"], "severity": i["severity"], "layer": i.get("layer"), "scope": i.get("scope"),
            "field": i.get("field"), "reason": i.get("reason"), "suggested_fix": i.get("suggested_fix"),
            "judge_reason": i.get("judge_reason"), "quote": quote or None}


def _record_view(run, recs, v, section, axis_order, limit, extra=None):
    rid = v["record_id"]
    rec = recs.get(rid)
    unit = run.bundle.units.get(rid) or {}
    names = (run.bundle.meta or {}).get("file_names") or {}
    issues = [_issue_view(i, rec) for i in v["issues"] if i["severity"] != "info"]
    out = {
        "record_id": rid, "file_id": v["file_id"], "file_name": names.get(v["file_id"]) or (v["file_id"] or "")[:16],
        "slide_no": unit.get("seq"), "title": unit.get("title") or "", "text": unit.get("text") or "",
        "section": section, "verdict": v["verdict"], "score": v["score"], "judge": v.get("judge"),
        "issues": issues, "issue_codes": sorted({i["code"] for i in issues}),
        "labels": _labels(rec or {}), "fields": _fields(rec or {}, axis_order),
        "problem_fields": sorted({i["field"] for i in issues if i.get("field") and i["severity"] in ("critical", "major")}),
        "image_total": len(unit.get("images") or []),
        "priority": None, "group": None,
    }
    out.update(extra or {})
    return out


def data(run, pass_sample=0):
    """화면에 넣을 데이터 dict. 시각을 넣지 않아 같은 입력이면 같은 HTML이 나온다."""
    tax = run.ctx.tax if run.ctx is not None else model.TaxIndex(run.bundle.taxonomy)
    recs = {r["record_id"]: r for r in run.bundle.records}
    axis_order = {a["name"]: i for i, a in enumerate((run.bundle.taxonomy or {}).get("axes") or [])}
    limit = images_limit(run.bundle)
    vmap = run.verdict_map()
    queue_rows, rework_rows = queue.build(run)
    records = []
    for q in queue_rows:
        records.append(_record_view(run, recs, vmap[q["record_id"]], "REVIEW", axis_order, limit,
                                    {"priority": q["priority"], "group": q["group"]}))
    for rid in pass_sample_ids(run, pass_sample):
        records.append(_record_view(run, recs, vmap[rid], "PASS_SAMPLE", axis_order, limit))
    for r in rework_rows:
        records.append(_record_view(run, recs, vmap[r["record_id"]], "REJECT", axis_order, limit,
                                    {"rework": r["issues"]}))
    approved_rules = list(run.policy["autofix"]["approved_rules"])
    groups = {}
    for v in run.verdicts:
        if v["verdict"] != "AUTO_FIX" or v.get("human_reviewed"):
            continue
        records.append(_record_view(run, recs, v, "AUTO_FIX", axis_order, limit))
        for fx in v.get("auto_fixes") or []:
            g = groups.setdefault(fx["rule"], {"rule": fx["rule"], "rules": normalize.rules_of(fx),
                                               "approved": normalize.is_approved(fx, approved_rules), "items": []})
            g["items"].append({"record_id": v["record_id"], "field": fx["field"], "before": fx["before"],
                               "after": fx["after"]})
    autofix = [groups[k] for k in sorted(groups)]
    for g in autofix:
        g["items"].sort(key=lambda x: (x["record_id"], x["field"]))

    used_codes = sorted({i["code"] for r in records for i in r["issues"]} |
                        {fi["code"] for fi in run.file_issues or []})
    files = {}
    names = (run.bundle.meta or {}).get("file_names") or {}
    for r in records:
        files.setdefault(r["file_id"], {"name": r["file_name"], "file_issues": []})
    for fi in run.file_issues or []:
        if fi.get("file_id") in files and fi["severity"] in ("critical", "major", "minor"):
            files[fi["file_id"]]["file_issues"].append({"code": fi["code"], "severity": fi["severity"],
                                                        "reason": fi.get("reason")})
    for fid in files:
        files[fid]["name"] = names.get(fid) or files[fid]["name"]
        files[fid]["file_issues"].sort(key=lambda x: x["code"])
        files[fid]["slides"] = _file_slides(run.bundle, fid, limit)

    return {
        "kind": "qa_review",
        "qa_run_id": run.qa_run_id,
        "labeler_run_id": run.labeler_run_id,
        "na": tax.na, "unknown": tax.unknown,
        "answers_allowed": list(run.schema["answers"]) if run.schema else ["O", "X", "N/A"],
        "codes": {c: codes.get(c)["desc"] for c in used_codes},
        "axes": [{"name": a["name"], "kind": a.get("kind"), "multi": a.get("multi"), "definition": a.get("definition") or "",
                  "values": [{"name": x["name"], "parent": x.get("parent"), "definition": x.get("definition") or ""}
                             for x in a.get("values") or []]}
                 for a in (run.bundle.taxonomy or {}).get("axes") or []],
        "questions": [{"qid": q["qid"], "text": q.get("text") or ""} for q in (run.bundle.taxonomy or {}).get("questions") or []],
        "files": files,
        "records": records,
        "autofix": autofix,
        "approved_rules": approved_rules,
        "proposals": list(run.proposals or []),
        "images_per_chunk": limit,
    }


def embed(obj):
    """JSON을 <script> 안에 안전하게 넣는다. '<'와 'http'를 \\u 이스케이프로 바꾼다(둘 다 문자열 안에만 나온다)."""
    js = json.dumps(obj, ensure_ascii=False, sort_keys=True)
    js = js.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return _HTTP.sub(lambda m: m.group(0)[:3] + "\\u%04x" % ord(m.group(1)), js)


def render(obj):
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        tpl = f.read()
    if DATA_MARK not in tpl:
        raise ValueError("TEMPLATE_MARK_MISSING")
    return tpl.replace(DATA_MARK, embed(obj), 1)


def build(run, pass_sample=0):
    """review.html을 쓴다. 반환: 화면에 올린 레코드 수."""
    obj = data(run, pass_sample=pass_sample)
    io.write_text(run.path("review.html"), render(obj))
    return len(obj["records"])
