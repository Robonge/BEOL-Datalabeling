"""교정 장부(ledger): 사람 검수 교정(work.sqlite corrections) → Engr-bot 입력(누적 골든셋, judge 예시, L4 규칙 후보).

- 작업 DB는 adapter(labelbot_ws)로만 읽는다(읽기 전용). 이 모듈은 labelbot을 import하지 않는다.
- 장부 파일은 정렬된 jsonl이다. 쓰기는 잠금(.ledger.lock.json) 안에서 파일마다 <이름>.<pid>.tmp.<확장자>에 쓴 뒤
  os.replace로 바꾸고, 내용이 같으면 쓰지 않는다.
- 행은 (작업 폴더, 라벨러 실행)별로 둔다. 같은 레코드·예시가 여러 곳에 있으면 읽을 때(read_golden, read_examples)
  labeler_run_id가 큰 쪽을 고른다. 그래서 한 작업 폴더를 지워도 다른 작업 폴더 행은 그대로 남는다.
- 인용 발췌를 담는 파일은 golden.jsonl과 judge_examples.jsonl뿐이다. 문서 파일명·경로는 어느 파일에도 넣지 않는다.
- 같은 입력으로 다시 돌리면 장부 파일 바이트가 같다. 시각은 intake_at뿐이고 corrections_sha가 바뀔 때만 갱신한다.
- 장부 위치는 <코드 폴더>/workspaces/ 아래나 <작업 폴더>/qa/ 아래만 허용한다.
- 규칙 후보는 모두 draft다. 봇은 어떤 규칙도 approved로 올리지 않는다.
"""
import contextlib
import json
import os
import re
import time

from engrbot import domain_rules, golden, io, model
from engrbot import policy as policy_mod
from engrbot.adapters import labelbot_ws
from engrbot.llm import term_in

CODE_ROOT = io.CODE_ROOT
WORKSPACES_DIR = os.path.join(CODE_ROOT, "workspaces")

SOURCES = "sources.jsonl"
CASES = "cases.jsonl"
RECORDS = "records.jsonl"
GOLDEN = "golden.jsonl"
EXAMPLES = "judge_examples.jsonl"
SYNONYMS = "synonyms.jsonl"
REVISITS = "revisits.jsonl"
CANDIDATES = "rule_candidates.json"
CANDIDATES_MD = "rule_candidates.md"
LOCK_NAME = ".ledger.lock.json"
LOCK_WAIT = 30.0     # 잠금을 기다리는 최대 초
LOCK_STALE = 600.0   # 이보다 오래된 잠금(mtime)은 죽은 프로세스의 것으로 본다

# 파일별 필수 키. 빠진 행이 있으면 LEDGER_FILE_INVALID
REQUIRED_KEYS = {
    SOURCES: ("source_ws",),
    CASES: ("case_id", "source_ws", "labeler_run_id", "record_id", "field", "kind"),
    RECORDS: ("record_id", "source_ws", "labeler_run_id", "file_id", "final_axes"),
    GOLDEN: ("golden_id", "record_id", "source_ws", "labeler_run_id", "labels"),
    EXAMPLES: ("example_id", "source_ws", "labeler_run_id", "kind", "verdict", "quote"),
    SYNONYMS: ("alias", "canonical", "sources"),
    REVISITS: ("source_ws", "reason", "target_kind", "target_key", "count"),
}

CONFIRMED, CORRECTED = "confirmed", "corrected"
OX = ("O", "X")
CAND_TYPES = ("expect", "forbid", "title", "synonym")
CAND_NOTE_TAIL = "승인하려면 engrbot/defaults/domain_rules.json에 옮기고 status를 approved로 바꾼다."


class LedgerError(Exception):
    def __init__(self, reason_code):
        Exception.__init__(self, reason_code)
        self.reason_code = reason_code


# ---- 설정과 위치 -------------------------------------------------------------

def config(policy):
    """policy["ledger"]를 기본값 위에 병합한다(정책 dict에 ledger 블록이 없어도 쓴다)."""
    base = policy_mod.default_policy()["ledger"]
    return policy_mod.merge(base, (policy or {}).get("ledger") or {})


def _inside(child, parent):
    child = os.path.normcase(os.path.realpath(child))
    parent = os.path.normcase(os.path.realpath(parent))
    try:
        return os.path.commonpath([child, parent]) == parent
    except ValueError:
        return False


def ledger_dir(ws_root, policy):
    """장부 위치. ① policy ledger.dir(상대 경로는 <코드 폴더>/workspaces 기준) ② 코드 폴더 workspaces/ 아래
    작업 폴더면 workspaces/_engrbot/ledger ③ 그 밖(테스트 임시 폴더 등)은 <작업 폴더>/qa/ledger.
    결과가 workspaces/ 아래도 <작업 폴더>/qa/ 아래도 아니면 LedgerError(LEDGER_DIR_OUTSIDE_WORKSPACES)."""
    ws = os.path.abspath(ws_root)
    d = config(policy).get("dir")
    if d:
        d = os.path.abspath(d if os.path.isabs(d) else os.path.join(WORKSPACES_DIR, d))
    elif _inside(ws, WORKSPACES_DIR) and not _inside(WORKSPACES_DIR, ws):
        d = os.path.join(WORKSPACES_DIR, "_engrbot", "ledger")
    else:
        d = os.path.join(ws, "qa", "ledger")
    in_ws = _inside(d, WORKSPACES_DIR) and not _inside(WORKSPACES_DIR, d)
    in_qa = _inside(d, os.path.join(ws, "qa"))
    if not (in_ws or in_qa) or io.is_forbidden_inside_code(d):
        raise LedgerError("LEDGER_DIR_OUTSIDE_WORKSPACES")
    return d


def dir_label(d):
    """콘솔·manifest용 표시 이름 "<부모 이름>/<이름>"(경로 전체를 쓰지 않는다)."""
    d = os.path.abspath(d)
    return "%s/%s" % (os.path.basename(os.path.dirname(d)), os.path.basename(d))


def golden_path(d):
    return os.path.join(d, GOLDEN)


def examples_path(d):
    return os.path.join(d, EXAMPLES)


def candidates_path(d):
    return os.path.join(d, CANDIDATES)


# ---- 읽기 ----------------------------------------------------------------------

def _read(d, name):
    """장부 파일 행. 깨졌거나 필수 키가 빠진 행이 있으면 LedgerError(LEDGER_FILE_INVALID)."""
    try:
        rows = io.read_own_jsonl(os.path.join(d, name))
    except (ValueError, UnicodeDecodeError):
        raise LedgerError("LEDGER_FILE_INVALID")
    keys = REQUIRED_KEYS.get(name, ())
    for r in rows:
        if not isinstance(r, dict) or any(k not in r for k in keys):
            raise LedgerError("LEDGER_FILE_INVALID")
    return rows


def _latest(rows, key):
    """같은 key는 (labeler_run_id, source_ws)가 큰 행 하나. key 순으로 돌려준다."""
    best = {}
    for r in rows:
        k = r[key]
        old = best.get(k)
        if old is None or (r["labeler_run_id"], r["source_ws"]) > (old["labeler_run_id"], old["source_ws"]):
            best[k] = r
    return [best[k] for k in sorted(best)]


def read_golden(d):
    """누적 골든셋. golden_id마다 labeler_run_id가 큰(그다음 source_ws가 큰) 행 하나."""
    return _latest(_read(d, GOLDEN), "golden_id")


def read_examples(d):
    """judge 예시(없으면 []). example_id에는 판정이 없으므로, 최근 라벨러 실행의 사람 판정이 이긴다."""
    return _latest(_read(d, EXAMPLES), "example_id")


def read_candidates(d):
    """rule_candidates.json 문서 또는 None."""
    try:
        doc = io.read_own_json(candidates_path(d), default=None)
    except (ValueError, UnicodeDecodeError):
        raise LedgerError("LEDGER_FILE_INVALID")
    if doc is not None and not (isinstance(doc, dict) and isinstance(doc.get("rules"), list)):
        raise LedgerError("LEDGER_FILE_INVALID")
    return doc


# ---- 쓰기 ----------------------------------------------------------------------

@contextlib.contextmanager
def _locked(d):
    """장부 쓰기 잠금(한 번에 한 프로세스). LOCK_WAIT초 안에 못 잡으면 LEDGER_LOCKED."""
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, LOCK_NAME)
    deadline = time.monotonic() + LOCK_WAIT
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(path) > LOCK_STALE:
                    os.remove(path)
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise LedgerError("LEDGER_LOCKED")
            time.sleep(0.05)
            continue
        try:
            os.write(fd, ('{"pid": %d}\n' % os.getpid()).encode("ascii"))
        finally:
            os.close(fd)
        break
    try:
        yield
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _tmp(path):
    base, ext = os.path.splitext(path)
    return "%s.%d.tmp%s" % (base, os.getpid(), ext)


def _replace_text(path, text):
    tmp = _tmp(path)
    io.write_text(tmp, text)
    os.replace(tmp, path)


def _write_jsonl(path, rows):
    """내용이 같으면 쓰지 않는다. 반환: 썼으면 True."""
    new = [json.loads(io.dumps(r)) for r in rows]
    if os.path.isfile(path):
        try:
            if io.read_own_jsonl(path) == new:
                return False
        except (ValueError, UnicodeDecodeError):
            pass
    _replace_text(path, "".join(io.dumps(r) + "\n" for r in rows))
    return True


def _write_json(path, doc):
    if os.path.isfile(path):
        try:
            if io.read_own_json(path) == json.loads(io.dumps(doc)):
                return False
        except (ValueError, UnicodeDecodeError):
            pass
    _replace_text(path, io.dumps(doc, indent=2) + "\n")
    return True


# ---- 값 도우미 -----------------------------------------------------------------

def _axis_list(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return list(value)
    return None


def _real(values, tax):
    """예약어(해당 없음, unknown)를 뺀 실제 값 집합. 목록이 아닌 값(깨진 JSON 문자열 등)은 빈 집합이다."""
    if not isinstance(values, list):
        return set()
    return {v for v in values if isinstance(v, str) and v and not tax.is_reserved(v)}


def _bot_value(rec, field):
    """(봇 값, 인용). golden.bot_value와 같되, 목록이 아닌 축 값(깨진 JSON 문자열)은 글자 목록으로 바꾸지 않고 그대로 둔다."""
    value, quote = golden.bot_value(rec, field)
    kind, _, key = field.partition(":")
    if kind == "axis":
        raw = ((rec.get("axes") or {}).get(key) or {}).get("values")
        if raw is not None and not isinstance(raw, list):
            return raw, quote
    return value, quote


def _undecidable(value):
    vals = value if isinstance(value, list) else [value]
    return any(v in golden.CANNOT_JUDGE for v in vals)


def _row_key(row):
    return (row.get("review_run_id") or "", row.get("chunk_id") or "", row.get("target_kind") or "",
            row.get("target_key") or "")


def _plus(acc, more):
    for k, v in (more or {}).items():
        acc[k] = acc.get(k, 0) + v
    return acc


# ---- 한 작업 폴더 몫 모으기 ----------------------------------------------------------

class _Intake(object):
    """한 작업 폴더의 교정을 사례·레코드·골든·예시로 바꾼다. 건너뛴 것은 실행별 사유 코드로 센다."""

    def __init__(self, source, cfg, content_type):
        self.source = source
        self.cfg = cfg
        self.content_type = content_type
        self.cases, self.records = [], []
        self.examples, self.golden = {}, {}   # (id, 실행) → 행
        self.runs = {}                          # 실행 → {corrections_sha, corrections, skipped}
        self.cur = None
        self.tax = None
        self.taxonomy_version = None

    def skip(self, code, n=1):
        if n:
            sk = self.runs[self.cur]["skipped"]
            sk[code] = sk.get(code, 0) + n

    def begin(self, run_id):
        self.cur = run_id
        self.runs[run_id] = {"corrections_sha": None, "corrections": 0, "skipped": {}}

    # -- 실행 하나 --
    def add_bundle(self, run_id, bundle):
        tax = model.TaxIndex(bundle.taxonomy)
        self.tax = tax
        self.taxonomy_version = (bundle.taxonomy or {}).get("version")
        recs = {r["record_id"]: r for r in bundle.records}
        corr = {}
        for cid, rows in ((bundle.meta or {}).get("corrections") or {}).items():
            mine = [r for r in rows if r.get("review_run_id") == run_id]
            if mine:
                corr[cid] = sorted(mine, key=_row_key)
        all_rows = [r for cid in sorted(corr) for r in corr[cid]]
        self.runs[run_id]["corrections"] = len(all_rows)
        self.runs[run_id]["corrections_sha"] = model.hash_obj(all_rows)
        for cid in sorted(corr):
            rows = corr[cid]
            rec, unit = recs.get(cid), bundle.units.get(cid)
            if rec is None or unit is None:
                self.skip("SKIP_RECORD_MISSING", len(rows))
                continue
            if rec.get("chunk_type") != self.content_type:
                self.skip("SKIP_NOT_CONTENT", len(rows))
                continue
            self._record(run_id, rec, unit, rows, tax, bundle.taxonomy)

    def _record(self, run_id, rec, unit, rows, tax, snap):
        status_row, image, fields, used = None, False, {}, []
        for row in rows:
            if row.get("recheck") or (row.get("text_hash") and row["text_hash"] != unit.get("text_hash")):
                self.skip("SKIP_RECHECK")
                continue
            kind, key, hv = row.get("target_kind"), row.get("target_key"), golden._human_value(row)
            if kind == "chunk":
                if hv == "confirmed":
                    status_row = row
                elif hv == "undecidable_image":
                    image = True
                else:
                    self.skip("SKIP_STATUS_OTHER")
                    continue
            elif kind in ("axis", "answer") and key:
                fields["%s:%s" % (kind, key)] = (row, hv)
            else:
                self.skip("SKIP_TARGET_OTHER")
                continue
            used.append(row)
        if image:
            self.skip("SKIP_UNDECIDABLE_IMAGE", len(used))
            return
        cases = {}
        if status_row is not None:
            for name in sorted(rec.get("axes") or {}):
                bv, _ = _bot_value(rec, "axis:" + name)
                if isinstance(bv, list):
                    cases["axis:" + name] = (CONFIRMED, bv, bv, status_row)
            for qid in sorted(rec.get("answers") or {}):
                bv, _ = _bot_value(rec, "answer:" + qid)
                if isinstance(bv, str) and bv:
                    cases["answer:" + qid] = (CONFIRMED, bv, bv, status_row)
        # 필드 교정은 같은 레코드의 chunk 확인보다 우선한다
        for field in sorted(fields):
            row, hv = fields[field]
            kind, _, key = field.partition(":")
            bv, _ = _bot_value(rec, field)
            if _undecidable(hv):
                self.skip("SKIP_UNDECIDABLE")
                cases.pop(field, None)
                continue
            if kind == "axis":
                hv = _axis_list(hv)
                if hv is None:
                    self.skip("SKIP_VALUE_INVALID")
                    cases.pop(field, None)
                    continue
                known = tax.values.get(key) or {}
                if any(v not in known and not tax.is_reserved(v) for v in hv):
                    self.skip("SKIP_VALUE_UNKNOWN")
                    cases.pop(field, None)
                    continue
                same = isinstance(bv, list) and sorted(bv) == sorted(hv)
            else:
                if not isinstance(hv, str) or not hv:
                    self.skip("SKIP_VALUE_INVALID")
                    cases.pop(field, None)
                    continue
                same = hv == bv
            cases[field] = (CONFIRMED if same else CORRECTED, bv, hv, row)
        if not cases:
            return
        self._emit(run_id, rec, unit, cases, tax, snap)

    def _gen_target(self, qid, tax):
        """Q-GEN 답의 목표 (축, 값). 승인 질문이면 (None, None). 목표를 못 찾으면 False."""
        q = tax.questions.get(qid)
        if q is None:
            return False if qid.startswith(labelbot_ws.GEN_PREFIX) else (None, None)
        if not q.get("generated"):
            return None, None
        t = q.get("target")
        if isinstance(t, (list, tuple)) and len(t) == 2 and all(isinstance(x, str) and x for x in t):
            return t[0], t[1]
        return False

    def _question_changed(self, row, qid, tax):
        """승인 질문 답 교정 행의 question_hash가 지금 taxonomy 질문 문장과 다르면 True(문장이 바뀐 뒤의 교정)."""
        if row.get("target_kind") != "answer":
            return False
        q = tax.questions.get(qid) or {}
        return row.get("question_hash") != model.sha256_text(q.get("text") or "")[:16]

    def _emit(self, run_id, rec, unit, cases, tax, snap):
        rid, th, fid = rec["record_id"], unit.get("text_hash"), rec.get("file_id")
        labels, evidence = {"axes": {}, "answers": {}}, {}
        final = {}
        for name in sorted(rec.get("axes") or {}):
            bv, _ = _bot_value(rec, "axis:" + name)
            if isinstance(bv, list):
                final[name] = list(bv)
        corrected_axes, added, removed = [], {}, {}
        applied = []
        n_cases = 0
        for field in sorted(cases):
            kind_, bv, hv, row = cases[field]
            kind, _, key = field.partition(":")
            gen_axis = gen_value = None
            q_changed = False
            if kind == "answer":
                tgt = self._gen_target(key, tax)
                if tgt is False:
                    self.skip("SKIP_GEN_UNRESOLVED")
                    continue
                gen_axis, gen_value = tgt
                q_changed = gen_axis is None and self._question_changed(row, key, tax)
            n_cases += 1
            applied.append(row.get("applied_at") or "")
            self.cases.append({
                "case_id": model.hash_obj([self.source, run_id, rid, field])[:16], "source_ws": self.source,
                "labeler_run_id": run_id, "record_id": rid, "file_id": fid, "text_hash": th, "field": field,
                "kind": kind_, "bot_value": bv, "human_value": hv, "gen_axis": gen_axis, "gen_value": gen_value,
                "applied_at": row.get("applied_at"),
            })
            _, quote = _bot_value(rec, field)
            golden._put(labels, evidence, field, hv, quote if kind_ == CONFIRMED else None)
            if kind == "axis" and kind_ == CORRECTED:
                corrected_axes.append(key)
                final[key] = list(hv)
                a = sorted(_real(hv, tax) - _real(bv, tax))
                r = sorted(_real(bv, tax) - _real(hv, tax))
                if a:
                    added[key] = a
                if r:
                    removed[key] = r
            self._examples(run_id, rec, unit, field, kind_, bv, hv, quote, gen_axis, gen_value, tax, q_changed)
        if not n_cases:
            return
        title = unit.get("title") or ""
        hits = {k: [v for v in vs if term_in(v, title)] for k, vs in added.items()}
        self.records.append({
            "source_ws": self.source, "labeler_run_id": run_id, "record_id": rid, "file_id": fid, "text_hash": th,
            "final_axes": final, "corrected_axes": sorted(corrected_axes), "added": added, "removed": removed,
            "title_hits": {k: v for k, v in hits.items() if v},
        })
        if labels["axes"] or labels["answers"]:
            gid = model.hash_obj([rid, th])[:32]
            self.golden[(gid, run_id)] = {
                "golden_id": gid, "record_id": rid, "file_id": fid, "text_hash": th, "labels": labels,
                "evidence": evidence, "source": "ledger:%s" % self.source, "confirmed_at": max(applied) or None,
                "taxonomy_version": snap.get("version"), "questions_version": snap.get("questions_version"),
                "source_ws": self.source, "labeler_run_id": run_id,
            }

    def _examples(self, run_id, rec, unit, field, kind_, bv, hv, quote, gen_axis, gen_value, tax, q_changed):
        """사람 판정이 붙은 (라벨, 인용) 예시. 인용이 없으면 만들지 않는다.
        인용이 길면 SKIP_LONG_QUOTE, 승인 질문 문장이 바뀌었으면 SKIP_QUESTION_CHANGED로 센다."""
        if not isinstance(quote, str) or not quote.strip():
            return
        kind, _, key = field.partition(":")
        out = []
        if kind == "axis":
            status = ((rec.get("axes") or {}).get(key) or {}).get("status")
            if kind_ == CONFIRMED and status == "value":
                out = [(key, v, None, None, "supported") for v in sorted(_real(bv, tax))]
            elif kind_ == CORRECTED:
                keep = set(hv or [])
                out = [(key, v, None, None, "supported" if v in keep else "unsupported")
                       for v in sorted(_real(bv, tax))]
        elif bv in OX:
            if kind_ == CONFIRMED:
                out = [(gen_axis, gen_value, key, bv, "supported")]
            elif hv != bv:
                out = [(gen_axis, gen_value, key, bv, "unsupported")]
        if not out:
            return
        if len(quote) > self.cfg["quote_chars"]:
            self.skip("SKIP_LONG_QUOTE")  # 필드마다 한 번 센다
            return
        if q_changed:
            self.skip("SKIP_QUESTION_CHANGED", len(out))
            return
        for axis, value, qid, answer, verdict in out:
            ek = "axis" if kind == "axis" else "answer"
            eid = model.hash_obj([ek, axis, value, qid, answer, unit.get("text_hash"), quote])[:16]
            row = {"example_id": eid, "source_ws": self.source, "labeler_run_id": run_id,
                   "record_id": rec["record_id"], "file_id": rec.get("file_id"), "text_hash": unit.get("text_hash"),
                   "kind": ek, "axis": axis, "value": value, "qid": qid,
                   "generated": gen_axis is not None and ek == "answer", "answer": answer, "quote": quote,
                   "verdict": verdict, "origin": kind_}
            old = self.examples.get((eid, run_id))
            if old is None or (row["verdict"], row["origin"]) < (old["verdict"], old["origin"]):
                self.examples[(eid, run_id)] = row


def _synonym_axis(canonical, tax):
    if tax is None:
        return ""
    hits = [name for name, vals in tax.values.items() if canonical in vals]
    return hits[0] if len(hits) == 1 else ""


# ---- 장부 합치기 ---------------------------------------------------------------

SORT_KEYS = {
    CASES: lambda r: (r["case_id"], r["source_ws"], r["labeler_run_id"]),
    RECORDS: lambda r: (r["record_id"], r.get("text_hash") or "", r["source_ws"], r["labeler_run_id"]),
    GOLDEN: lambda r: (r["golden_id"], r["source_ws"], r["labeler_run_id"]),
    EXAMPLES: lambda r: (r["example_id"], r["source_ws"], r["labeler_run_id"]),
}


def _source_row(d_rows, source, runs_meta, old, part_source):
    """sources.jsonl의 그 작업 폴더 행을 장부 행에서 다시 센다. 실행 기록이 없으면 None(행을 지운다)."""
    if not runs_meta:
        return None
    mine = {name: [r for r in rows if r.get("source_ws") == source] for name, rows in d_rows.items()}
    cases = mine[CASES]
    n_conf = sum(1 for c in cases if c["kind"] == CONFIRMED)
    syn = [s for s in d_rows[SYNONYMS] if source in (s.get("sources") or [])]
    counts = {"cases": len(cases), "confirmed": n_conf, "corrected": len(cases) - n_conf,
              "golden": len({g["golden_id"] for g in mine[GOLDEN]}),
              "examples": len({e["example_id"] for e in mine[EXAMPLES]}), "synonyms": len(syn),
              "revisits": sum(r["count"] for r in mine[REVISITS])}
    skipped = {}
    for meta in runs_meta.values():
        _plus(skipped, meta.get("skipped"))
    sha = model.hash_obj({k: runs_meta[k].get("corrections_sha") for k in sorted(runs_meta)})
    if old and old.get("corrections_sha") == sha:
        intake_at = old.get("intake_at")
    else:
        intake_at = model.now_iso()
    tv = part_source.get("taxonomy_version") or (old or {}).get("taxonomy_version")
    return {"source_ws": source, "labeler_runs": sorted(runs_meta), "corrections_sha": sha, "taxonomy_version": tv,
            "intake_at": intake_at, "counts": counts, "skipped": dict(sorted(skipped.items())),
            "runs": {k: runs_meta[k] for k in sorted(runs_meta)}}


def _merge_source(d, source, part, run=None):
    """장부에서 그 작업 폴더(run을 주면 그 실행만)의 행을 part로 바꾼다. 다른 행은 그대로 둔다.
    part가 None이면 그 작업 폴더 행을 모두 지운다. 반환: 바뀐 파일이 있으면 True."""
    full = part is None or run is None
    part = part or {}

    def mine(r):
        return r.get("source_ws") == source and (run is None or r.get("labeler_run_id") == run)

    rows = {}
    changed = False
    for name in (CASES, RECORDS, GOLDEN, EXAMPLES):
        merged = [r for r in _read(d, name) if not mine(r)] + part.get(name, [])
        merged.sort(key=SORT_KEYS[name])
        rows[name] = merged
        changed |= _write_jsonl(os.path.join(d, name), merged)
    # 재검토·동의어는 작업 폴더 단위다(실행 구분이 없다). part에 있으면 그 작업 폴더 몫을 새로 바꾼다
    revs = _read(d, REVISITS)
    if REVISITS in part or full:
        revs = [r for r in revs if r.get("source_ws") != source] + part.get(REVISITS, [])
    revs.sort(key=lambda r: (r["source_ws"], r["reason"], r["target_kind"], r["target_key"]))
    rows[REVISITS] = revs
    changed |= _write_jsonl(os.path.join(d, REVISITS), revs)
    syn = {(s["alias"], s["canonical"]): s for s in _read(d, SYNONYMS)}
    if SYNONYMS in part or full:
        keep = {}
        for k, s in syn.items():
            srcs = [x for x in s.get("sources") or [] if x != source]
            if srcs:
                keep[k] = dict(s, sources=srcs)
        for s in part.get(SYNONYMS, []):
            k = (s["alias"], s["canonical"])
            cur = keep.get(k)
            if cur is None:
                keep[k] = dict(s, sources=[source])
            else:
                cur["sources"] = sorted(set(cur["sources"]) | {source})
                cur["axis"] = cur.get("axis") or s["axis"]
        syn = keep
    # count는 그 동의어를 등록한 작업 폴더 수다
    rows[SYNONYMS] = [dict(syn[k], sources=sorted(syn[k]["sources"]), count=len(syn[k]["sources"]))
                      for k in sorted(syn)]
    changed |= _write_jsonl(os.path.join(d, SYNONYMS), rows[SYNONYMS])
    srcs = _read(d, SOURCES)
    old = next((s for s in srcs if s["source_ws"] == source), None)
    runs_meta = {} if full else dict((old or {}).get("runs") or {})
    runs_meta.update(part.get("runs") or {})
    new = _source_row(rows, source, runs_meta, old, part.get("source") or {})
    srcs = [s for s in srcs if s["source_ws"] != source] + ([new] if new else [])
    changed |= _write_jsonl(os.path.join(d, SOURCES), sorted(srcs, key=lambda r: r["source_ws"]))
    return changed


def _write_candidates(d, policy):
    doc = build_candidates(d, policy)
    changed = _write_json(candidates_path(d), doc)
    if changed or not os.path.isfile(os.path.join(d, CANDIDATES_MD)):
        _replace_text(os.path.join(d, CANDIDATES_MD), render_candidates_md(doc))
        changed = True
    return changed


# ---- intake ------------------------------------------------------------------

def intake(ws_root, policy, labeler_run_id=None, schema=None):
    """작업 폴더 교정을 장부에 반영한다(LLM 0회). labeler_run_id를 주면 그 실행의 행만 바꾼다.
    schema를 주면 그 content_chunk_type을 쓴다(없으면 기본 스키마). 반환: 이번에 반영한 건수 dict(본문 없음)."""
    cfg = config(policy)
    ws_root = os.path.abspath(ws_root)
    d = ledger_dir(ws_root, policy)
    source = os.path.basename(ws_root.rstrip("\\/"))
    runs = labelbot_ws.correction_runs(ws_root)
    if labeler_run_id is not None:
        if labeler_run_id not in runs:
            raise LedgerError("LEDGER_RUN_NO_CORRECTIONS")
        runs = [labeler_run_id]
    out = {"source_ws": source, "runs": [], "corrections": 0, "cases": 0, "confirmed": 0, "corrected": 0,
           "golden": 0, "examples": 0, "synonyms": 0, "revisits": 0, "skipped": {}, "reason": None}
    if not runs:
        # 장부에 이 작업 폴더 행이 없으면 아무것도 쓰지 않는다
        if not any(s["source_ws"] == source for s in _read(d, SOURCES)):
            out.update(reason="NO_CORRECTIONS", changed=False, totals=status(d))
            return out
        with _locked(d):
            changed = _merge_source(d, source, None)
            changed |= _write_candidates(d, policy)
        out.update(reason="NO_CORRECTIONS", changed=changed, totals=status(d))
        return out
    content_type = (schema or policy_mod.default_schema())["content_chunk_type"]
    acc = _Intake(source, cfg, content_type)
    for run_id in runs:
        acc.begin(run_id)
        try:
            b = labelbot_ws.load(ws_root, run_id)
        except model.BundleError as e:
            if e.reason_code != "LABELER_RUN_NOT_FOUND":
                raise
            acc.skip("SKIP_RUN_NOT_FOUND")
            continue
        acc.add_bundle(run_id, b)
    synonyms = [{"alias": a, "canonical": c, "axis": _synonym_axis(c, acc.tax), "count": 1, "sources": [source]}
                for a, c in labelbot_ws.review_synonyms(ws_root)]
    revisits = [{"source_ws": source, "reason": r, "target_kind": k, "target_key": t, "count": n}
                for r, k, t, n in labelbot_ws.revisit_counts(ws_root)]
    n_conf = sum(1 for c in acc.cases if c["kind"] == CONFIRMED)
    skipped = {}
    for meta in acc.runs.values():
        _plus(skipped, meta["skipped"])
    part = {
        CASES: acc.cases, RECORDS: acc.records, GOLDEN: list(acc.golden.values()),
        EXAMPLES: list(acc.examples.values()), SYNONYMS: synonyms, REVISITS: revisits, "runs": acc.runs,
        "source": {"taxonomy_version": acc.taxonomy_version},
    }
    with _locked(d):
        changed = _merge_source(d, source, part, run=labeler_run_id)
        changed |= _write_candidates(d, policy)
    out.update({"cases": len(acc.cases), "confirmed": n_conf, "corrected": len(acc.cases) - n_conf,
                "golden": len({k[0] for k in acc.golden}), "examples": len({k[0] for k in acc.examples}),
                "synonyms": len(synonyms), "revisits": sum(r["count"] for r in revisits)})
    out.update(runs=sorted(acc.runs), corrections=sum(m["corrections"] for m in acc.runs.values()),
               skipped=dict(sorted(skipped.items())), changed=changed, totals=status(d))
    return out


def counts_only(result):
    """intake 반환에서 manifest에 넣을 건수 부분(작업 폴더 이름, 누적 합계는 뺀다)."""
    if not result:
        return None
    out = {k: v for k, v in result.items() if k not in ("source_ws", "totals", "runs")}
    out["runs"] = len(result.get("runs") or [])
    return out


def status(d):
    """장부 누적 건수(본문 없음). 골든·예시는 고유 ID 수다."""
    cand = read_candidates(d)
    srcs = _read(d, SOURCES)
    return {
        "dir": dir_label(d), "sources": len(srcs), "cases": len(_read(d, CASES)),
        "golden": len({g["golden_id"] for g in _read(d, GOLDEN)}),
        "examples": len({e["example_id"] for e in _read(d, EXAMPLES)}),
        "synonyms": len(_read(d, SYNONYMS)), "revisits": len(_read(d, REVISITS)),
        "candidates": len((cand or {}).get("rules") or []),
        "per_source": [{"source_ws": s["source_ws"], "runs": len(s.get("labeler_runs") or []),
                        "counts": s.get("counts") or {}} for s in srcs],
    }


def rebuild(d, policy):
    """장부 행은 그대로 두고 규칙 후보만 다시 만든다. 반환: 바뀌었으면 True."""
    with _locked(d):
        return _write_candidates(d, policy)


# ---- 규칙 후보 (LLM 0회) ---------------------------------------------------------

def _latest_records(d):
    """같은 (record_id, text_hash)는 labeler_run_id가 큰 것 하나."""
    best = {}
    for r in _read(d, RECORDS):
        k = (r["record_id"], r.get("text_hash") or "")
        old = best.get(k)
        if old is None or (r["labeler_run_id"], r["source_ws"]) > (old["labeler_run_id"], old["source_ws"]):
            best[k] = r
    return [best[k] for k in sorted(best)]


def _cand_id(kind, core):
    abbr = {"expect": "exp", "forbid": "forb", "title": "title", "synonym": "syn"}[kind]
    return "cand-%s-%s" % (abbr, model.hash_obj(core)[:8])


def _note(head):
    return ("%s %s" % (head, CAND_NOTE_TAIL))[:300]


def _combo_candidates(recs, finals, cc):
    """axis_combo expect·forbid 후보. 반환: [(유형, 지지, 규칙, 작업 폴더 집합, note 머리)]."""
    found = []
    axes = sorted({a for f in finals for a in f})
    n_all = len(finals)
    for a in axes:
        for v in sorted({v for f in finals for v in f.get(a, ())}):
            idx = [i for i, f in enumerate(finals) if v in f.get(a, ())]
            if len(idx) < cc["min_support"]:
                continue
            idx_set = set(idx)
            outside = None  # R 밖 레코드(필요할 때만 만든다)
            m = len(idx)
            for b in axes:
                if b == a:
                    continue
                n_corr = sum(1 for i in idx if b in (recs[i].get("corrected_axes") or []))
                if n_corr >= cc["min_corrected"]:
                    if outside is None:
                        outside = [i for i in range(n_all) if i not in idx_set]
                    w_set = []
                    for w in sorted({w for i in idx for w in finals[i].get(b, ())}):
                        conf = sum(1 for i in idx if w in finals[i].get(b, ())) / m
                        base = (sum(1 for i in outside if w in finals[i].get(b, ())) / len(outside)) if outside else 0.0
                        # 어디서나 흔한 값은 A=v 조건과 상관이 없으므로 lift로 거른다
                        if conf >= cc["min_confidence"] and conf - base >= cc["min_lift"]:
                            w_set.append(w)
                    sup = [i for i in idx if finals[i].get(b, set()) & set(w_set)]
                    # 한 파일의 슬라이드끼리는 라벨이 같이 움직이므로 서로 다른 파일 수로 거른다
                    if w_set and len({recs[i].get("file_id") for i in sup}) >= cc["min_files"]:
                        srcs = {recs[i]["source_ws"] for i in sup}
                        rule = {"id": _cand_id("expect", ["expect", a, v, b, w_set]), "type": "axis_combo",
                                "status": "draft", "severity": "major", "when": {"axis": a, "value_in": [v]},
                                "expect": {"axis": b, "value_in": w_set}}
                        head = "지지 %d/%d건(작업 폴더 %d곳), 근거 교정 %d건." % (len(sup), m, len(srcs), n_corr)
                        found.append(("expect", len(sup), rule, srcs, head))
                removed = sorted({x for i in idx for x in (recs[i].get("removed") or {}).get(b, [])})
                for x in removed:
                    rm = [i for i in idx if x in (recs[i].get("removed") or {}).get(b, [])]
                    if len(rm) < cc["min_forbid"] or len({recs[i].get("file_id") for i in rm}) < cc["min_files"]:
                        continue
                    # R 안에 final B ∋ x가 있으면 금지가 아니다
                    if any(x in finals[i].get(b, ()) for i in idx):
                        continue
                    # R 밖에서도 x가 한 번도 맞지 않으면 A=v 조건이 뜻이 없다(무조건 금지)
                    if outside is None:
                        outside = [i for i in range(n_all) if i not in idx_set]
                    if not any(x in finals[i].get(b, ()) for i in outside):
                        continue
                    srcs = {recs[i]["source_ws"] for i in rm}
                    rule = {"id": _cand_id("forbid", ["forbid", a, v, b, x]), "type": "axis_combo",
                            "status": "draft", "severity": "major", "when": {"axis": a, "value_in": [v]},
                            "forbid": {"axis": b, "value_in": [x]}}
                    head = "사람이 뺀 레코드 %d건(모수 %d, 작업 폴더 %d곳)." % (len(rm), m, len(srcs))
                    found.append(("forbid", len(rm), rule, srcs, head))
    return found


def _title_candidates(recs, cc, ok):
    """title_label 후보. 패턴은 대소문자를 가리지 않는다((?i))."""
    found = []
    for a in sorted({a for r in recs for a in (r.get("title_hits") or {})}):
        hits, srcs, n_recs = {}, set(), 0
        for r in recs:
            vals = [v for v in (r.get("title_hits") or {}).get(a, []) if ok(a, v)]
            if vals:
                n_recs += 1
                srcs.add(r["source_ws"])
            for v in vals:
                hits[v] = hits.get(v, 0) + 1
        total = sum(hits.values())
        if not hits or total < cc["min_title"]:
            continue
        vals = sorted(hits, key=lambda v: (-len(v), v))
        pat = r"(?i)(?<![A-Za-z0-9])(%s)(?![A-Za-z0-9])" % "|".join(re.escape(v) for v in vals)
        rule = {"id": _cand_id("title", ["title", a, pat]), "type": "title_label", "status": "draft",
                "severity": "minor", "title_pattern": pat, "axis": a}
        head = "제목 적중 %d건(레코드 %d건, 작업 폴더 %d곳)." % (total, n_recs, len(srcs))
        found.append(("title", total, rule, srcs, head))
    return found


def _synonym_candidates(d):
    """synonym_suggest 후보(축 하나로 해석되는 검수 등록 동의어가 있는 축)."""
    by_axis = {}
    for s in _read(d, SYNONYMS):
        if s.get("axis"):
            by_axis.setdefault(s["axis"], []).append(s)
    found = []
    for a in sorted(by_axis):
        rows = by_axis[a]
        srcs = {x for s in rows for x in s.get("sources") or []}
        rule = {"id": _cand_id("synonym", ["synonym", a]), "type": "synonym_suggest", "status": "draft",
                "severity": "minor", "axis": a}
        head = "검수 등록 동의어 %d쌍(작업 폴더 %d곳). 동의어 시트에 붙여넣은 뒤 효력이 있다." % (len(rows), len(srcs))
        found.append(("synonym", len(rows), rule, srcs, head))
    return found


def build_candidates(d, policy, tax_values=None):
    """records.jsonl·synonyms.jsonl에서 L4 규칙 후보 문서를 만든다. 모두 draft이고 domain_rules.validate를 통과한다.
    tax_values({축: 값 집합})를 주면 그 안의 값만 후보에 쓴다."""
    cc = config(policy)["candidates"]
    recs = _latest_records(d)
    reserved = set(model.RESERVED)

    def ok(axis, v):
        return v not in reserved and (tax_values is None or v in (tax_values.get(axis) or ()))

    finals = [{a: {v for v in vs if ok(a, v)} for a, vs in (r.get("final_axes") or {}).items()} for r in recs]
    # finals에는 ok인 값만 있으므로, ok가 아닌 금지값은 "R 밖에서 맞는 값" 조건에서 빠진다
    found = _combo_candidates(recs, finals, cc) + _title_candidates(recs, cc, ok) + _synonym_candidates(d)
    # 유형 순서로만 자르면 expect가 상한을 다 채우므로, 작업 폴더 수·지지 수가 큰 후보부터 고른다
    found.sort(key=lambda f: (-len(f[3]), -f[1], CAND_TYPES.index(f[0]), f[2]["id"]))
    rules, seen = [], set()
    for kind, n, rule, srcs, head in found:
        if rule["id"] in seen:
            continue
        seen.add(rule["id"])
        rule["note"] = _note(head)
        rules.append(rule)
        if len(rules) >= cc["max_rules"]:
            break
    doc = {"version": "ledger-%s" % model.hash_obj(rules)[:12], "rules": rules}
    try:
        domain_rules.validate(doc)
    except policy_mod.PolicyError:
        raise LedgerError("LEDGER_CANDIDATES_INVALID")
    return doc


def render_candidates_md(doc):
    """후보 표(.md). 축·값 이름과 건수만 쓴다."""
    lines = ["# L4 규칙 후보 (교정 장부, draft)", "",
             "봇은 후보를 approved로 올리지 않는다. %s" % CAND_NOTE_TAIL, "",
             "버전: `%s` · 후보 %d개" % (doc["version"], len(doc["rules"])), "",
             "| id | 유형 | 축·값 | 지지·근거 |", "|---|---|---|---|"]
    for r in doc["rules"]:
        if r["type"] == "axis_combo":
            c = r.get("expect") or r.get("forbid")
            verb = "expect" if "expect" in r else "forbid"
            what = "%s=%s → %s %s=%s" % (r["when"]["axis"], ",".join(r["when"]["value_in"]), verb, c["axis"],
                                         ",".join(c["value_in"]))
        elif r["type"] == "title_label":
            what = "%s (제목 패턴)" % r["axis"]
        else:
            what = "%s (동의어)" % r["axis"]
        lines.append("| `%s` | %s | %s | %s |" % (r["id"], r["type"], what.replace("|", "\\|"),
                                                  r.get("note", "").split(". ")[0]))
    return "\n".join(lines) + "\n"
