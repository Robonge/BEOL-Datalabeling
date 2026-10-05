"""실행 맥락과 전 단계 오케스트레이션(ingest, run)."""
import concurrent.futures
import os
import sys
import threading

from labelbot import classify, feedback, ingest, label, prompts, questions, store, util
from labelbot.llm import ChatClient


class PipelineError(Exception):
    pass


class Logger:
    """logs/labelbot.log. 파일 ID·chunk ID와 사유 코드만 남긴다."""

    def __init__(self, ws):
        self.path = ws.path("logs", "labelbot.log")
        self.lock = threading.Lock()

    def __call__(self, stage, target_id, reason):
        line = "%s\t%s\t%s\t%s\n" % (util.now_iso(), stage, target_id, reason)
        with self.lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line)


def say(msg):
    print(msg, file=sys.stdout, flush=True)


def load_taxonomy(ws):
    from labelbot import taxonomy

    p = ws.taxonomy_path
    if not os.path.isfile(p):
        raise PipelineError("taxonomy.xlsx가 없습니다. taxonomy/taxonomy.xlsx를 작업 폴더로 복사하세요.")
    try:
        data = ingest.read_input(p, ws.path("inputs"), expect=".xlsx")
    except ingest.InputError as e:
        raise PipelineError("taxonomy.xlsx 읽기 실패: %s" % e.reason_code)
    try:
        tax = taxonomy.parse_bytes(data)
    except taxonomy.TaxonomyError as e:
        lines = ["taxonomy.xlsx 오류(시트, 행, 코드):"]
        for issue in e.issues:
            lines.append("  - %s %s %s %s" % tuple(issue[:4]))
        raise PipelineError("\n".join(lines))
    for w in tax.warnings:
        say("[경고] taxonomy %s %s %s" % tuple(w[:3]))
    return tax, util.sha256_bytes(data)


class Ctx:
    def __init__(self, ws, con, run_id, tax=None, transport=None, log=None):
        from labelbot.synonyms import SynonymTable

        self.ws, self.con, self.run_id, self.tax = ws, con, run_id, tax
        self.cfg = ws.config
        self.log = log or Logger(ws)
        self.lock = threading.RLock()
        self.chat = ChatClient(self.cfg["llm"], con, transport=transport, log=self.log)
        self.chat_lock = self.lock
        # 검수 피드백(승인 규칙·사례). run_all이 feedback.load로 바꾼다. 기본은 블록이 '(없음)'.
        self.feedback = feedback.NullFeedback()
        if tax is not None:
            self.syn = SynonymTable(tax.synonyms)
            self.sheet_hashes = dict(tax.sheet_hashes)
            self.file_memos = {f.file_id: f.memo for f in tax.files if f.memo}
            self.taxonomy_text = classify.taxonomy_block(tax)

    def label_base(self):
        sh = util.dumps(self.sheet_hashes)
        model = self.cfg["llm"]["model"]

        def base(stage):
            return (sh, prompts.version(stage), model, util.now_iso())

        return base


class _LockedCon:
    """여러 스레드가 같은 sqlite 연결을 쓰도록 모든 호출을 잠금으로 직렬화한다."""

    def __init__(self, con, lock):
        self._con, self._lock = con, lock

    def execute(self, *a):
        with self._lock:
            return _Rows(self._con.execute(*a).fetchall())

    def commit(self):
        with self._lock:
            self._con.commit()


class _Rows(list):
    def fetchone(self):
        return self[0] if self else None

    def fetchall(self):
        return list(self)


def start_run(con, ws, command, input_root=None):
    run_id = util.new_run_id()
    con.execute(
        "INSERT INTO runs(run_id, command, started_at, config_hash, input_root) VALUES(?,?,?,?,?)",
        (run_id, command, util.now_iso(), ws.config_hash(), os.path.abspath(input_root) if input_root else None),
    )
    con.commit()
    return run_id


def finish_run(con, run_id, sheet_hashes=None, sent_params=None):
    con.execute(
        "UPDATE runs SET finished_at=?, sheet_hashes=?, sent_params=? WHERE run_id=?",
        (util.now_iso(), util.dumps(sheet_hashes or {}), util.dumps(sent_params or {}), run_id),
    )
    con.commit()


def do_ingest(ws, con, run_id, input_root, log, excluded=()):
    if not os.path.isdir(input_root):
        raise PipelineError("입력 폴더가 없습니다(--input).")
    seen = ingest.collect(ws, con, run_id, input_root, log=log, excluded=set(excluded))
    n = ingest.parse_files(ws, con, run_id, seen, log=log)
    ok = con.execute(
        "SELECT COUNT(*) FROM files WHERE status='ok' AND file_id IN (%s)" % ",".join("?" * len(seen)), seen
    ).fetchone()[0] if seen else 0
    say("[ingest] 파일 %d개 (정상 %d, 새로 파싱 %d)" % (len(seen), ok, n))
    return seen


def content_chunks(con, file_ids):
    if not file_ids:
        return []
    q = (
        "SELECT c.* FROM chunks c JOIN files f ON f.file_id=c.file_id WHERE f.status='ok' AND c.file_id IN (%s)"
        " ORDER BY f.rel_path, c.seq" % ",".join("?" * len(file_ids))
    )
    return [dict(r) for r in con.execute(q, file_ids)]


def _parallel(fn, items, workers):
    if workers <= 1:
        return [fn(it) for it in items]
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fn, items))


def run_labeling(ctx, chunks):
    """1차 분류 → 2차 매핑 → 3차 라벨링. 반환: 통계 dict."""
    from labelbot import candidates

    con, tax = ctx.con, ctx.tax
    workers = int(ctx.cfg["llm"].get("workers") or 4)
    raw_con = ctx.con
    ctx.con = _LockedCon(raw_con, ctx.lock)
    ctx.chat.con = ctx.con
    try:
        cls_results = _parallel(lambda c: classify.classify_chunk(ctx, c), chunks, workers)
    finally:
        ctx.con = raw_con
        ctx.chat.con = raw_con
    stats = {"chunks": len(chunks), "classify_failed": 0, "label_failed": 0, "excluded_type": 0, "labeled": 0,
             "no_questions": False, "truncated": {}}
    limit = int(ctx.cfg["limits"]["questions_per_chunk"])
    approved = []
    for c, res in zip(chunks, cls_results):
        if res is None:
            stats["classify_failed"] += 1
            continue
        classify.store_result(ctx, c["chunk_id"], res)
        candidates.collect_from_classify(ctx, c["chunk_id"], res)
        if res["chunk_type"] != "내용":
            stats["excluded_type"] += 1
            continue
        mapped, cut = questions.map_questions(tax, res["axes"], limit)
        for q in cut:
            stats["truncated"][q.qid] = stats["truncated"].get(q.qid, 0) + 1
        approved.append((c, res, mapped))
    con.commit()
    say("[classify] chunk %d개 중 실패 %d, 비내용 %d" % (len(chunks), stats["classify_failed"], stats["excluded_type"]))
    # 2차: 승인 질문(규칙) + 1차 라벨 검증 질문(LLM, 남은 상한만큼)
    ctx.con = _LockedCon(raw_con, ctx.lock)
    ctx.chat.con = ctx.con
    try:
        gen_results = _parallel(lambda t: questions.generate_questions(ctx, t[0], t[1]["axes"], limit - len(t[2])),
                                approved, workers)
    finally:
        ctx.con = raw_con
        ctx.chat.con = raw_con
    con.commit()
    to_label = [(c, res, mapped + gen) for (c, res, mapped), gen in zip(approved, gen_results) if mapped + gen]
    stats["generated_questions"] = sum(len(g) for g in gen_results)
    say("[question] 검증 질문 %d개 생성(chunk %d개)" % (stats["generated_questions"], len(approved)))
    if not to_label:
        stats["no_questions"] = True
        say("[label] 물을 질문이 없어 3차 라벨링을 건너뜁니다.")
        return stats
    ctx.con = _LockedCon(raw_con, ctx.lock)
    ctx.chat.con = ctx.con
    try:
        lab_results = _parallel(lambda t: label.label_chunk(ctx, t[0], t[1], t[2]), to_label, workers)
    finally:
        ctx.con = raw_con
        ctx.chat.con = raw_con
    for (c, _, _), res in zip(to_label, lab_results):
        if res is None:
            stats["label_failed"] += 1
            continue
        label.store_result(ctx, c["chunk_id"], res)
        candidates.collect_from_label(ctx, c["chunk_id"], res)
        stats["labeled"] += 1
    con.commit()
    say("[label] 대상 %d개 중 실패 %d" % (len(to_label), stats["label_failed"]))
    return stats


def run_all(ws, input_root, transport=None, command="run", use_feedback=True):
    """수집부터 분류·라벨링·알림·불량 목록·후보·산출·리포트까지. push-vectors는 부르지 않는다.

    승인된 검수 피드백 사례가 있고 임베딩을 쓸 수 있으면, 사례 유사도를 재려고 이번 chunk를 임베딩한다(embed와 같은 가드·저장).
    use_feedback=False(run --no-feedback)면 승인 규칙·사례를 넣지 않는다.
    """
    from labelbot import alerts, candidates, export, report, review

    con = store.connect(ws.work_db)
    try:
        tax, tax_sha = load_taxonomy(ws)
        run_id = start_run(con, ws, command, input_root)
        log = Logger(ws)
        excluded = {f.file_id for f in tax.files if f.exclude}
        seen = do_ingest(ws, con, run_id, input_root, log, excluded)
        ctx = Ctx(ws, con, run_id, tax=tax, transport=transport, log=log)
        store.meta_set(con, "taxonomy_sha256", tax_sha)
        store.meta_set(con, "inactive_axes", util.dumps([a.name for a in tax.axes if not a.active]))
        store.meta_set(con, "sent_params", util.dumps(ctx.chat.sent_params()))
        store.meta_set(con, "axis_kinds", util.dumps({a.name: a.kind for a in tax.axes}))
        chunks = content_chunks(con, seen)
        try:
            ctx.feedback = feedback.load(ws, tax, ctx.chat, enabled=use_feedback)
        except feedback.FeedbackError as e:
            raise PipelineError("검수 피드백 규칙 파일(labeling_rules.json) 오류: %s" % e)
        ctx.feedback.prepare(ws, con, run_id, chunks, log=log)
        if ctx.feedback.enabled:
            ctx.sheet_hashes["labeling_rules"] = ctx.feedback.digest()
        say(ctx.feedback.summary_line())
        stats = run_labeling(ctx, chunks)
        store.meta_set(con, "feedback_applied:" + run_id, util.dumps(ctx.feedback.applied()))
        alerts.evaluate(ctx)
        review.compute_flags(con, run_id, ws.config, tax, ws.path("reports"))
        candidates.write_reports(ctx)
        export.export(ws, con, run_id, tax)
        report.write_report(ws, con, run_id, tax, stats=stats)
        finish_run(con, run_id, ctx.sheet_hashes, ctx.chat.sent_params())
        say("[run] 완료 run_id=%s LLM 호출 %d회 (캐시 %d회)" % (run_id, ctx.chat.calls, ctx.chat.cache_hits))
        return run_id, ctx
    finally:
        con.close()


def run_ingest(ws, input_root):
    con = store.connect(ws.work_db)
    try:
        excluded = set()
        if os.path.isfile(ws.taxonomy_path):
            tax, _ = load_taxonomy(ws)
            excluded = {f.file_id for f in tax.files if f.exclude}
        run_id = start_run(con, ws, "ingest", input_root)
        do_ingest(ws, con, run_id, input_root, Logger(ws), excluded)
        finish_run(con, run_id)
        return run_id
    finally:
        con.close()
