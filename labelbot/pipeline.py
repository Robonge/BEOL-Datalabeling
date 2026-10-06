"""실행 맥락과 전 단계 오케스트레이션(ingest, run)."""
import concurrent.futures
import contextlib
import os
import sys
import threading
import time

from labelbot import classify, feedback, ingest, label, prompts, questions, store, taxdiff, util
from labelbot.llm import ChatClient


class PipelineError(Exception):
    pass


class LockLost(Exception):
    """axis-update 실행 중 잠금을 잃었다(다른 실행이 넘겨받음)."""


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

    def fail(self, stage, target_id, reason_code):
        """failures 행을 남기고 같은 사유를 로그에 쓴다. stage 문자열은 계약(vectorpush·domain_engrbot이 읽는다)."""
        store.add_failure(self.con, self.run_id, stage, target_id, reason_code)
        self.log(stage, target_id, reason_code)


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


def start_run(con, ws, command, input_root=None, run_id=None):
    run_id = run_id or util.new_run_id()
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


@contextlib.contextmanager
def _threaded_con(ctx):
    """블록 안에서는 ctx.con과 ctx.chat.con을 잠금 연결로 바꾸고, 끝나면 원래 연결로 되돌린다."""
    raw_con = ctx.con
    ctx.con = _LockedCon(raw_con, ctx.lock)
    ctx.chat.con = ctx.con
    try:
        yield
    finally:
        ctx.con = raw_con
        ctx.chat.con = raw_con


def run_labeling(ctx, chunks):
    """1차 분류 → 2차 매핑 → 3차 라벨링. 반환: 통계 dict."""
    from labelbot import candidates

    con, tax = ctx.con, ctx.tax
    workers = int(ctx.cfg["llm"].get("workers") or 4)
    with _threaded_con(ctx):
        cls_results = _parallel(lambda c: classify.classify_chunk(ctx, c), chunks, workers)
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
    with _threaded_con(ctx):
        gen_results = _parallel(lambda t: questions.generate_questions(ctx, t[0], t[1]["axes"], limit - len(t[2])),
                                approved, workers)
    con.commit()
    to_label = [(c, res, mapped + gen) for (c, res, mapped), gen in zip(approved, gen_results) if mapped + gen]
    stats["control_questions"] = sum(1 for g in gen_results for q in g if questions.is_control(q.qid))
    stats["generated_questions"] = sum(len(g) for g in gen_results) - stats["control_questions"]
    # 검증 대상(unknown 축·저확신 라벨)인데 상한(verify_max·질문 상한) 때문에 빠진 수(질문 생성이 실패한 chunk는 세지 않는다)
    cmin = questions.conf_min(ctx.cfg)
    stats["verify_cut"] = sum(
        len(questions.verify_targets(tax, res["axes"], 10 ** 6, cmin)) - sum(1 for q in gen if not questions.is_control(q.qid))
        for (c, res, mapped), gen in zip(approved, gen_results) if gen)
    say("[question] 검증 질문 %d개, 대조 질문 %d개 생성(chunk %d개, 상한으로 검증하지 못한 대상 %d개)"
        % (stats["generated_questions"], stats["control_questions"], len(approved), stats["verify_cut"]))
    if not to_label:
        stats["no_questions"] = True
        say("[label] 물을 질문이 없어 3차 라벨링을 건너뜁니다.")
        return stats
    with _threaded_con(ctx):
        lab_results = _parallel(lambda t: label.label_chunk(ctx, t[0], t[1], t[2]), to_label, workers)
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
        store.meta_set(con, "sent_params", util.dumps(ctx.chat.sent_params()))
        _save_axis_meta(con, run_id, tax)
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


def _save_axis_meta(con, run_id, tax):
    """전역 axis_kinds·inactive_axes·axes_signature와 실행별 axes_signature:<run_id>."""
    store.meta_set(con, "axis_kinds", util.dumps({a.name: a.kind for a in tax.axes}))
    store.meta_set(con, "inactive_axes", util.dumps([a.name for a in tax.axes if not a.active]))
    sig_json = util.dumps(taxdiff.axes_signature(tax))
    store.meta_set(con, "axes_signature", sig_json)
    store.meta_set(con, "axes_signature:" + run_id, sig_json)


def run_axis_update(ws, transport=None, use_feedback=True, dry_run=False):
    """taxonomy 축 변경분만 1차 분류로 다시 라벨링한다(axisupdate). 2·3차(질문 생성·라벨)는 부르지 않는다.

    반환: (plan, run_id 또는 None, ctx 또는 None). plan["code"]가 있으면(멈출 사유) 또는 dry_run이면 실행을 만들지 않는다.
    다른 axis-update가 잠금을 잡고 있으면 AXIS_UPDATE_LOCKED다. 잠금을 잡은 뒤 plan을 다시 계산해 그 결과로 실행하고,
    그때 멈출 사유가 나오면 그 사유로 끝낸다. 잠금은 끝나거나 예외가 나면 푼다(자기 잠금일 때만).
    """
    from labelbot import axisupdate

    con = store.connect(ws.work_db)
    try:
        tax, tax_sha = load_taxonomy(ws)
        p = axisupdate.plan(ws, con, tax)
        if dry_run or p["code"]:
            return p, None, None
        owner = axisupdate.new_run_id(p["prev_run"])  # 잠금의 주인 = 만들 실행 ID
        if not axisupdate.acquire_lock(ws, owner, con):
            return dict(p, code=axisupdate.AXIS_UPDATE_LOCKED), None, None
        try:
            p = axisupdate.plan(ws, con, tax, own_lock=owner)  # 잠금 밖에서 본 상태가 그 사이 바뀌었을 수 있다
            if p["code"]:
                return p, None, None
            if owner <= p["prev_run"]:  # 기준 실행이 그 사이 더 최신으로 바뀌었다
                new = axisupdate.new_run_id(p["prev_run"])
                axisupdate.touch_lock(ws, owner, new)
                owner = new
            try:
                run_id, ctx = _axis_update(ws, con, tax, tax_sha, p, transport, use_feedback, owner)
            except LockLost:
                # 이번 실행이 쓴 행은 남긴다. 다음 실행이 같은 기준에서 멱등 복사로 덮어쓴다.
                return dict(p, code=axisupdate.AXIS_UPDATE_LOCK_LOST), None, None
        finally:
            axisupdate.release_lock(ws, owner)
        return p, run_id, ctx
    finally:
        con.close()


def _axis_update(ws, con, tax, tax_sha, p, transport, use_feedback, run_id):
    """run_axis_update 본체(잠금 안, 잠금 주인 run_id로 실행을 만든다). 반환: (run_id, ctx)."""
    from labelbot import axisupdate, candidates, export, finals, report, review

    run_id = axisupdate.start(ws, con, p, tax, run_id=run_id)
    target = set(p["target"])
    log = Logger(ws)
    ctx = Ctx(ws, con, run_id, tax=tax, transport=transport, log=log)
    store.meta_set(con, "taxonomy_sha256", tax_sha)
    store.meta_set(con, "sent_params", util.dumps(ctx.chat.sent_params()))
    # 불량 계산용 실행별 축 종류. 전역 축 meta는 끝날 때 쓴다
    store.meta_set(con, "axis_kinds:" + run_id, util.dumps({a.name: a.kind for a in tax.axes}))
    chunks = axisupdate.scope_chunks(con, run_id) if target else []
    say("[axis-update] 기준 run_id=%s 대상 축 %d개, 삭제 축 %d개, chunk %d개, 버린 답 %d건, 버린 교정 %d건" % (
        p["prev_run"], len(target), len(p["removed"]), len(chunks), p["dropped_answers"], p["dropped_corrections"]))
    try:
        ctx.feedback = feedback.load(ws, tax, ctx.chat, enabled=use_feedback, only_axes=target)
    except feedback.FeedbackError as e:
        raise PipelineError("검수 피드백 규칙 파일(labeling_rules.json) 오류: %s" % e)
    ctx.feedback.prepare(ws, con, run_id, chunks, log=log)
    if ctx.feedback.enabled:
        ctx.sheet_hashes["labeling_rules"] = ctx.feedback.digest()
    say(ctx.feedback.summary_line().replace("[feedback]", "[axis-update]", 1))
    # 비대상 축의 확정 값(이어받은 라벨 + 남긴 교정)을 참고 블록으로 준다.
    active = {a.name for a in tax.active_axes()}
    refs = {cid: {k: a["values"] for k, a in d["axes"].items() if k in active and k not in target}
            for cid, d in finals.final_labels(con, run_id, [c["chunk_id"] for c in chunks]).items()}
    workers = int(ctx.cfg["llm"].get("workers") or 4)
    beat = [0, time.time()]

    def classify_one(c):
        res = classify.classify_chunk(ctx, c, target, refs.get(c["chunk_id"]))
        with ctx.lock:  # 긴 실행: chunk 50개마다 또는 5분마다 잠금 mtime을 갱신한다
            beat[0] += 1
            if beat[0] % 50 == 0 or time.time() - beat[1] > 300:
                beat[1] = time.time()
                if not axisupdate.touch_lock(ws, run_id):
                    raise LockLost()
        return res
    with _threaded_con(ctx):
        results = _parallel(classify_one, chunks, workers)
    stats = {"chunks": len(chunks), "classify_failed": 0}
    for c, res in zip(chunks, results):
        if res is None:
            stats["classify_failed"] += 1
            continue
        classify.store_result(ctx, c["chunk_id"], res, target)
        candidates.collect_from_classify(ctx, c["chunk_id"], res)
    con.commit()
    say("[axis-update] 1차 분류 chunk %d개 중 실패 %d" % (len(chunks), stats["classify_failed"]))
    store.meta_set(con, "feedback_applied:" + run_id, util.dumps(ctx.feedback.applied()))
    flags = review.compute_flags(con, run_id, ws.config, tax, ws.path("reports"), axes=target)
    say("[axis-update] 불량 chunk %d개" % len(flags))
    candidates.write_reports(ctx)
    export.export(ws, con, run_id, tax)
    report.write_report(ws, con, run_id, tax, stats=stats)
    if not axisupdate.touch_lock(ws, run_id):  # 끝내기 전에 잠금이 아직 내 것인지 본다
        raise LockLost()
    # 축 서명·전역 축 meta는 끝에 남긴다. 중간에 멈춘 실행은 taxonomy-diff가 계속 변경으로 잡는다.
    _save_axis_meta(con, run_id, tax)
    finish_run(con, run_id, ctx.sheet_hashes, ctx.chat.sent_params())
    say("[axis-update] 완료 run_id=%s LLM 호출 %d회 (캐시 %d회)" % (run_id, ctx.chat.calls, ctx.chat.cache_hits))
    return run_id, ctx


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
