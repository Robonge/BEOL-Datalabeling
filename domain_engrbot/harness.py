"""mutation 하네스(10.3절). 정답 번들에 오류를 하나씩 주입하고 기대 코드가 붙는지 본다.

지표: 층별 탐지율(recall), 오탐률(주입하지 않은 정답 레코드 중 PASS가 아닌 비율), AUTO_FIX 정확도, 혼동표.
뮤테이터도 등록 방식이라 L4·L5용을 더할 수 있다(11절).
"""
import collections
import json
import random
import zlib

from domain_engrbot import io, model

MUTATORS = collections.OrderedDict()
BAD_SENTENCE = "존재하지 않는 문장으로 근거를 대체함"


class Mutator(object):
    def __init__(self, name, layer, expect, fn, target="record", autofix=False, failsafe=False, needs_mock=False,
                 requires_rule=None):
        self.name = name
        self.layer = layer
        self.expect = tuple(expect)
        self.fn = fn
        self.target = target  # record: 그 레코드에 붙어야 한다, file: 그 파일의 어느 레코드에든 붙으면 된다
        self.autofix = autofix
        self.failsafe = failsafe
        self.needs_mock = needs_mock
        self.requires_rule = requires_rule  # schema rules의 이 값이 꺼져 있으면 주입하지 않는다


def mutator(name, layer, expect, **kw):
    def deco(fn):
        MUTATORS[name] = Mutator(name, layer, expect, fn, **kw)
        return fn

    return deco


# ---- 보조 ------------------------------------------------------------------

def _value_axes(rec, tax, single=False, top_level=False):
    out = []
    for name in sorted(rec.get("axes") or {}):
        a = rec["axes"][name]
        if a.get("status") != "value" or name not in tax.axes:
            continue
        if single and len(a["values"]) != 1:
            continue
        out.append(name)
    return out


def _record(b, rid):
    return next(r for r in b.records if r["record_id"] == rid)


def _retext(unit, text):
    unit["text"] = text
    unit["text_canonical"] = None
    unit["text_hash"] = model.sha256_text(model.nfc(text))


def _is_pptx(b, rec):
    return (b.sources.get(rec["file_id"]) or {}).get("ext") == ".pptx"


def _mentions(text, value, aliases):
    low = model.nfkc(text).lower()
    return any(model.nfkc(x).lower() in low for x in [value] + list(aliases))


def _fullwidth(s):
    return "".join(chr(ord(c) + 0xFEE0) if "!" <= c <= "~" else c for c in s)


# ---- L0 -------------------------------------------------------------------

@mutator("drop_slide", "L0", ["L0_PAGE_COUNT_MISMATCH"], target="file")
def _drop_slide(b, rid, rng, tax):
    rec = _record(b, rid)
    if not _is_pptx(b, rec) or len(b.records_of(rec["file_id"])) < 2:
        return None
    b.records = [r for r in b.records if r["record_id"] != rid]
    b.units.pop(rid, None)
    return {}


@mutator("empty_text", "L0", ["L0_EMPTY_UNIT"])
def _empty_text(b, rid, rng, tax):
    u = b.units[rid]
    if len(u.get("text") or "") < 40:
        return None
    _retext(u, "")
    return {}


@mutator("drop_table", "L0", ["L0_TABLE_LOST"])
def _drop_table(b, rid, rng, tax):
    u = b.units[rid]
    if not u.get("tables"):
        return None
    u["tables"] = []
    return {}


@mutator("garble", "L0", ["L0_GARBLED_TEXT"])
def _garble(b, rid, rng, tax):
    u = b.units[rid]
    text = u.get("text") or ""
    if len(text) < 40:
        return None
    chars = list(text)
    for i in range(0, len(chars), 10):
        if not chars[i].isspace():
            chars[i] = "�"
    _retext(u, "".join(chars))
    return {}


@mutator("break_image_ref", "L0", ["L0_IMAGE_REF_BROKEN"])
def _break_image_ref(b, rid, rng, tax):
    u = b.units[rid]
    if not u.get("images"):
        return None
    img = dict(u["images"][0])
    img["rel_file"] = "images/missing_%s.b64" % img["image_id"][:12]
    u["images"] = [img] + list(u["images"][1:])
    return {}


# ---- L1 -------------------------------------------------------------------

@mutator("drop_field", "L1", ["L1_REQUIRED_MISSING"], requires_rule="all_active_axes_required")
def _drop_field(b, rid, rng, tax):
    rec = _record(b, rid)
    if rec.get("chunk_type") != "내용" or not rec.get("axes"):
        return None
    name = rng.choice(sorted(rec["axes"]))
    del rec["axes"][name]
    return {}


@mutator("bad_type", "L1", ["L1_TYPE_INVALID"])
def _bad_type(b, rid, rng, tax):
    rec = _record(b, rid)
    names = _value_axes(rec, tax)
    if not names:
        return None
    a = rec["axes"][rng.choice(names)]
    a["values"] = a["values"][0]
    return {}


@mutator("bad_enum", "L1", ["L1_ENUM_INVALID"])
def _bad_enum(b, rid, rng, tax):
    rec = _record(b, rid)
    if not rec.get("answers"):
        return None
    qid = rng.choice(sorted(rec["answers"]))
    rec["answers"][qid]["answer"] = "Y"
    return {}


@mutator("bad_confidence", "L1", ["L1_CONFIDENCE_RANGE"])
def _bad_confidence(b, rid, rng, tax):
    rec = _record(b, rid)
    names = _value_axes(rec, tax)
    if not names:
        return None
    rec["axes"][rng.choice(names)]["confidence"] = 1.7
    return {}


@mutator("ambiguous_date", "L1", ["L1_DATE_FORMAT"])
def _ambiguous_date(b, rid, rng, tax):
    rec = _record(b, rid)
    for e in rec.get("extracted") or []:
        if e.get("item") == "date" and len(e.get("value") or "") == 10:
            e["value"] = "%s/%s/%s" % (e["value"][2:4], e["value"][5:7], e["value"][8:10])
            return {}
    return None


@mutator("case_ws_noise", "L1_AUTOFIX", ["L1_FORMAT_NORMALIZED"], autofix=True)
def _case_ws_noise(b, rid, rng, tax):
    rec = _record(b, rid)
    names = _value_axes(rec, tax, single=True)
    if not names:
        return None
    name = rng.choice(names)
    a = rec["axes"][name]
    v = a["values"][0]
    a["values"] = [" %s " % (v.lower() if v.lower() != v else v.upper())]
    return {"field": "axis:%s" % name, "expect_after": [v]}


@mutator("fullwidth", "L1_AUTOFIX", ["L1_FORMAT_NORMALIZED"], autofix=True)
def _fullwidth_mut(b, rid, rng, tax):
    rec = _record(b, rid)
    names = [n for n in _value_axes(rec, tax, single=True) if _fullwidth(rec["axes"][n]["values"][0]) != rec["axes"][n]["values"][0]]
    if not names:
        return None
    name = rng.choice(names)
    a = rec["axes"][name]
    v = a["values"][0]
    a["values"] = [_fullwidth(v)]
    return {"field": "axis:%s" % name, "expect_after": [v]}


@mutator("date_dots", "L1_AUTOFIX", ["L1_FORMAT_NORMALIZED"], autofix=True)
def _date_dots(b, rid, rng, tax):
    rec = _record(b, rid)
    for i, e in enumerate(rec.get("extracted") or []):
        if e.get("item") == "date" and len(e.get("value") or "") == 10:
            v = e["value"]
            e["value"] = "%d.%d.%d" % (int(v[:4]), int(v[5:7]), int(v[8:10]))
            return {"field": "extract:date#%d" % i, "expect_after": v}
    return None


# ---- L2 -------------------------------------------------------------------

@mutator("out_of_taxonomy", "L2", ["L2_LABEL_NOT_IN_TAXONOMY"])
def _out_of_taxonomy(b, rid, rng, tax):
    rec = _record(b, rid)
    names = _value_axes(rec, tax, single=True)
    if not names:
        return None
    rec["axes"][rng.choice(names)]["values"] = ["UnlistedValue"]
    return {}


@mutator("parent_and_child", "L2", ["L2_HIERARCHY_INCONSISTENT"])
def _parent_and_child(b, rid, rng, tax):
    rec = _record(b, rid)
    for name in _value_axes(rec, tax):
        ax = tax.axes[name]
        if not ax.get("hierarchical"):
            continue
        kids = [v for v in ax["values"] if v.get("parent")]
        if not kids:
            continue
        kid = rng.choice(kids)
        rec["axes"][name]["values"] = [kid["parent"], kid["name"]]
        return {}
    return None


@mutator("reserved_plus_value", "L2", ["L2_MUTEX_VIOLATION"])
def _reserved_plus_value(b, rid, rng, tax):
    rec = _record(b, rid)
    names = _value_axes(rec, tax)
    if not names:
        return None
    rec["axes"][rng.choice(names)]["values"].append(tax.unknown)
    return {}


@mutator("single_axis_multi", "L2", ["L2_MUTEX_VIOLATION"])
def _single_axis_multi(b, rid, rng, tax):
    rec = _record(b, rid)
    for name in sorted(rec.get("axes") or {}):
        ax = tax.axes.get(name)
        if ax and ax.get("active") and not ax.get("multi") and len(ax["values"]) >= 2:
            a = rec["axes"][name]
            a["values"] = [ax["values"][0]["name"], ax["values"][1]["name"]]
            a["status"] = "value"
            return {}
    return None


@mutator("unknown_flood", "L2", ["L2_UNKNOWN_OVERUSE"])
def _unknown_flood(b, rid, rng, tax):
    rec = _record(b, rid)
    if rec.get("chunk_type") != "내용":
        return None
    for ax in tax.classification_axes():
        rec["axes"][ax["name"]] = {"values": [tax.unknown], "status": "unknown",
                                   "evidence": {"quote": "", "unit_id": None, "start": None, "end": None},
                                   "confidence": 0.5}
    return {}


# ---- L3A ------------------------------------------------------------------

@mutator("span_other_slide", "L3A", ["L3_SPAN_WRONG_UNIT"])
def _span_other_slide(b, rid, rng, tax):
    from domain_engrbot import textmatch

    rec = _record(b, rid)
    names = _value_axes(rec, tax)
    if not names:
        return None
    own = b.units[rid]
    own_texts = [own.get("text") or "", own.get("text_canonical") or ""]
    pool = []
    for u in b.units_of(rec["file_id"]):
        if u["unit_id"] == rid:
            continue
        for line in (u.get("text") or "").split("\n"):
            if len(line) >= 12 and not textmatch.is_short(line) and not any(textmatch.match(line, t) for t in own_texts):
                pool.append(line)
    if not pool:
        return None
    rec["axes"][rng.choice(names)]["evidence"] = {"quote": rng.choice(sorted(pool)), "unit_id": None, "start": None,
                                                 "end": None}
    return {}


@mutator("span_fabricated", "L3A", ["L3_SPAN_NOT_FOUND"])
def _span_fabricated(b, rid, rng, tax):
    rec = _record(b, rid)
    names = _value_axes(rec, tax)
    if not names:
        return None
    rec["axes"][rng.choice(names)]["evidence"] = {"quote": BAD_SENTENCE, "unit_id": None, "start": None, "end": None}
    return {}


@mutator("offset_shift", "L3A", ["L3_SPAN_OFFSET_INVALID"])
def _offset_shift(b, rid, rng, tax):
    rec = _record(b, rid)
    text = model.nfc(b.units[rid].get("text") or "")
    for name in _value_axes(rec, tax):
        ev = rec["axes"][name].get("evidence") or {}
        q = ev.get("quote") or ""
        i = text.find(q) if q else -1
        if i >= 0 and i + 1 + len(q) <= len(text):
            rec["axes"][name]["evidence"] = dict(ev, start=i + 1, end=i + 1 + len(q))
            return {}
    return None


# ---- L3B ------------------------------------------------------------------

@mutator("label_swap", "L3B", ["L3_NOT_SUPPORTED"])
def _label_swap(b, rid, rng, tax):
    rec = _record(b, rid)
    for name in _value_axes(rec, tax, single=True):
        a = rec["axes"][name]
        quote = (a.get("evidence") or {}).get("quote") or ""
        cands = [v["name"] for v in tax.axes[name]["values"]
                 if v["name"] not in a["values"] and not _mentions(quote, v["name"], tax.synonyms_for(v["name"]))]
        if cands:
            a["values"] = [rng.choice(cands)]
            return {}
    return None


@mutator("answer_flip", "L3B", ["L3_NOT_SUPPORTED"])
def _answer_flip(b, rid, rng, tax):
    rec = _record(b, rid)
    for qid in sorted(rec.get("answers") or {}):
        a = rec["answers"][qid]
        if a.get("answer") in ("O", "X"):
            a["answer"] = "X" if a["answer"] == "O" else "O"
            return {}
    return None


def _judgeable(rec, tax):
    return bool(_value_axes(rec, tax)) or any(a.get("answer") in ("O", "X") for a in (rec.get("answers") or {}).values())


def _failing_llm(rid, mode):
    from domain_engrbot.llm import LLMError, MockJudgeLLM

    base = MockJudgeLLM()

    def responder(messages, file_ids, hint):
        if (hint or {}).get("record_id") != rid:
            return base.complete(messages, file_ids, hint)
        if mode == "timeout":
            raise LLMError("TIMEOUT")
        if mode == "bad_json":
            return "판정 결과 {items: [broken"
        obj = json.loads(base.complete(messages, file_ids, hint))
        obj["items"] = obj["items"][1:]
        return json.dumps(obj, ensure_ascii=False)

    return MockJudgeLLM(responder=responder)


def _judge_fail_mutator(mode):
    def fn(b, rid, rng, tax):
        rec = _record(b, rid)
        if not _judgeable(rec, tax):
            return None
        return {"llm": _failing_llm(rid, mode)}

    return fn


for _name, _mode in (("judge_timeout", "timeout"), ("judge_bad_json", "bad_json"),
                     ("judge_missing_item", "missing_item")):
    mutator(_name, "L3B_FAILSAFE", ["L3_JUDGE_FAILED"], failsafe=True, needs_mock=True)(_judge_fail_mutator(_mode))


# ---- 실행 ------------------------------------------------------------------

def _seed_for(name, seed):
    return (zlib.crc32(name.encode("utf-8")) + seed) & 0xFFFFFFFF


def _harness_policy(pol):
    return dict(pol, layers=[l for l in pol["layers"] if l not in ("L6",)])


def _layer_false_positive(verdicts, n):
    out = {}
    for layer in ("L0", "L1", "L2", "L3A", "L3B"):
        bad = [v for v in verdicts
               if any(i["layer"] == layer and i["severity"] in ("critical", "major") for i in v["issues"])]
        out[layer] = round(len(bad) / float(n), 4) if n else 0.0
    return out


def _inject(mut, bundle, clean_map, pol, sch, llm, paths, seed, tax, per_mutator):
    """뮤테이터 하나를 PASS 레코드에 주입해 돌린다. 반환: (stat, 혼동 Counter, autofix 주입 수, autofix 정답 수)."""
    from domain_engrbot import runner

    stat = {"layer": mut.layer, "expect": list(mut.expect), "injected": 0, "detected": 0, "pass_after": 0,
            "skipped": None, "misses": []}
    confusion = collections.Counter()
    autofix_total = autofix_ok = 0
    if mut.needs_mock and llm is None:
        stat["skipped"] = "NEEDS_MOCK_JUDGE"
        return stat, confusion, 0, 0
    if mut.requires_rule and not sch["rules"].get(mut.requires_rule):
        stat["skipped"] = "RULE_OFF:%s" % mut.requires_rule
        return stat, confusion, 0, 0
    rng = random.Random(_seed_for(mut.name, seed))
    order = sorted(r["record_id"] for r in bundle.records if clean_map[r["record_id"]]["verdict"] == "PASS")
    rng.shuffle(order)
    for rid in order:
        if stat["injected"] >= per_mutator:
            break
        mb = bundle.copy()
        info = mut.fn(mb, rid, rng, tax)
        if info is None:
            continue
        fid = clean_map[rid]["file_id"]
        # 실패를 주입한 judge는 캐시를 쓰지 않는다(정답 실행의 캐시 응답이 주입을 가린다)
        res = runner.execute(mb.subset([fid]), pol, sch, paths=None if info.get("llm") else paths,
                             llm=info.get("llm") or llm)
        vm = res.verdict_map()
        stat["injected"] += 1
        if mut.target == "file":
            hits = [v for v in res.verdicts if any(i["code"] in mut.expect for i in v["issues"])]
            ok = bool(hits)
            tv = hits[0] if hits else (res.verdicts[0] if res.verdicts else None)
        else:
            tv = vm.get(rid)
            ok = bool(tv) and any(i["code"] in mut.expect for i in tv["issues"])
        if tv:
            base_codes = {i["code"] for i in (clean_map.get(tv["record_id"]) or {}).get("issues", [])}
            confusion.update(sorted({i["code"] for i in tv["issues"]} - base_codes))
        if mut.autofix:
            autofix_total += 1
            fixes = [f for f in (tv or {}).get("auto_fixes", []) if f["field"] == info["field"]]
            good = bool(tv) and tv["verdict"] == "AUTO_FIX" and bool(fixes) and fixes[-1]["after"] == info["expect_after"]
            autofix_ok += int(good)
            ok = ok and good
        if mut.failsafe and tv and tv["verdict"] == "PASS":
            stat["pass_after"] += 1
            ok = False
        stat["detected"] += int(ok)
        if not ok:
            stat["misses"].append(rid)
    stat["recall"] = round(stat["detected"] / float(stat["injected"]), 4) if stat["injected"] else None
    return stat, confusion, autofix_total, autofix_ok


def _layer_recall(per):
    layers = collections.OrderedDict()
    for name, stat in per.items():
        if stat["skipped"]:
            continue
        lay = layers.setdefault(stat["layer"], {"injected": 0, "detected": 0})
        lay["injected"] += stat["injected"]
        lay["detected"] += stat["detected"]
    for lay in layers.values():
        lay["recall"] = round(lay["detected"] / float(lay["injected"]), 4) if lay["injected"] else None
    return layers


def evaluate(bundle, pol, sch, llm=None, per_mutator=10, paths=None, seed=0, mutators=None):
    """반환: 지표 dict. llm이 None이면 정책의 transport(http)로 judge를 만든다."""
    from domain_engrbot import runner

    pol = _harness_policy(pol)
    tax = model.TaxIndex(bundle.taxonomy)
    clean = runner.execute(bundle, pol, sch, paths=paths, llm=llm)
    clean_map = clean.verdict_map()
    n = len(clean.verdicts)
    non_pass = [v for v in clean.verdicts if v["verdict"] != "PASS"]
    layer_fp = _layer_false_positive(clean.verdicts, n)
    selected = [MUTATORS[m] for m in (mutators or MUTATORS)]
    per = collections.OrderedDict()
    confusion = {}
    autofix_total = autofix_ok = 0
    for mut in selected:
        stat, conf, a_total, a_ok = _inject(mut, bundle, clean_map, pol, sch, llm, paths, seed, tax, per_mutator)
        per[mut.name] = stat
        confusion[mut.name] = conf
        autofix_total += a_total
        autofix_ok += a_ok
    layers = _layer_recall(per)
    judge = clean.ctx.judge
    return {
        "records": n,
        "judge": getattr(judge, "name", None),
        "judge_prompt": clean.ctx.versions.get("reviewer"),
        "false_positive_rate": round(len(non_pass) / float(n), 4) if n else 0.0,
        "false_positives": [v["record_id"] for v in non_pass],
        "layer_false_positive": layer_fp,
        "layers": layers,
        "mutators": per,
        "autofix_accuracy": round(autofix_ok / float(autofix_total), 4) if autofix_total else None,
        "confusion": {k: dict(sorted(v.items())) for k, v in confusion.items()},
        "judge_calls": getattr(judge, "calls", 0),
    }


def write_report(res, base_path):
    """eval_<시각>.json과 .md. 레코드 ID, 코드, 수치만 넣는다."""
    io.write_json(base_path + ".json", res)
    lines = [
        "# 검수봇 mutation 하네스 결과",
        "",
        "- 레코드 수: %d" % res["records"],
        "- judge: %s" % (res["judge"] or "미실행"),
        "- reviewer 버전: %s" % res["judge_prompt"],
        "- 오탐률(정답 레코드 중 PASS가 아닌 비율): %.4f" % res["false_positive_rate"],
        "- AUTO_FIX 정확도: %s" % ("-" if res["autofix_accuracy"] is None else "%.4f" % res["autofix_accuracy"]),
        "- judge 호출 수(정답 번들): %d" % res["judge_calls"],
        "",
        "## 층별 탐지율",
        "",
        "| 층 | 주입 | 탐지 | 탐지율 | 층별 오탐률 |",
        "|---|---|---|---|---|",
    ]
    for layer, lay in res["layers"].items():
        fp = res["layer_false_positive"].get(layer.split("_")[0], "")
        lines.append("| %s | %d | %d | %s | %s |" % (layer, lay["injected"], lay["detected"], lay["recall"], fp))
    lines += ["", "## 뮤테이터별", "", "| 뮤테이터 | 층 | 기대 코드 | 주입 | 탐지 | 탐지율 | 비고 |", "|---|---|---|---|---|---|---|"]
    for name, s in res["mutators"].items():
        note = s["skipped"] or ("PASS로 남은 fail-safe %d건" % s["pass_after"] if s["pass_after"] else "")
        lines.append("| %s | %s | %s | %d | %d | %s | %s |" % (name, s["layer"], ", ".join(s["expect"]), s["injected"],
                                                             s["detected"], s.get("recall"), note))
    lines += ["", "## 혼동표(주입 종류 × 새로 붙은 코드)", ""]
    for name, c in res["confusion"].items():
        if c:
            lines.append("- %s: %s" % (name, ", ".join("%s %d" % kv for kv in c.items())))
    io.write_text(base_path + ".md", "\n".join(lines) + "\n")
