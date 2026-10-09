"""실행 맥락과 전 단계 오케스트레이션(ingest, run)."""
import concurrent.futures
import contextlib
import os
import sys
import threading
import time

from labelbot import classify, feedback, ingest, label, prompts, questions, store, taxdiff, trace, util
from labelbot.llm import ChatClient


class PipelineError(Exception):
    """[오류] 줄로 내는 실행 오류. str(e)는 지금까지의 문장 그대로다(계약). reason_code는 사유 코드(카탈로그
    labelbot/reason_codes.py), detail은 하위 사유 코드(없으면 None)."""

    def __init__(self, message, reason_code=None, detail=None):
        Exception.__init__(self, message)
        self.reason_code = reason_code
        self.detail = detail


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
    if p.lower().endswith(".xlsx"):
        raise PipelineError("taxonomy 원본이 taxonomy.json으로 바뀌었습니다(TAXONOMY_XLSX_NEEDS_MIGRATION). "
                            "python -m labelbot taxonomy-migrate --xlsx \"<이 xlsx 경로>\" 를 한 번 실행하세요.",
                            reason_code="TAXONOMY_XLSX_NEEDS_MIGRATION")
    if not os.path.isfile(p):
        raise PipelineError("taxonomy.json이 없습니다(TAXONOMY_MISSING). pipeline.json의 taxonomy_path를 확인하세요.",
                            reason_code="TAXONOMY_MISSING")
    try:
        data = ingest.read_input(p, ws.path("inputs"))
    except OSError:
        raise PipelineError("taxonomy.json 읽기 실패: OS_ERROR", reason_code="TAXONOMY_READ_FAILED", detail="OS_ERROR")
    try:
        tax = taxonomy.parse_bytes(data)
    except taxonomy.TaxonomyError as e:
        lines = ["taxonomy.json 오류(시트, 행, 코드):"]
        for issue in e.issues:
            lines.append("  - %s %s %s %s" % tuple(issue[:4]))
        raise PipelineError("\n".join(lines), reason_code="TAXONOMY_PARSE_ERROR")
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


def do_ingest(ws, con, run_id, input_root, log):
    if not os.path.isdir(input_root):
        raise PipelineError("입력 폴더가 없습니다(--input).", reason_code="INPUT_DIR_NOT_FOUND")
    seen = ingest.collect(ws, con, run_id, input_root, log=log)
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
    with trace.milestone("M02", run_id=ctx.run_id, workspace=ctx.ws) as m2:
        m2.n = len(chunks)
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
    with trace.milestone("M03", run_id=ctx.run_id, workspace=ctx.ws) as m3:
        # 2차: 승인 질문(규칙) + 1차 라벨 검증 질문(LLM, 남은 상한만큼)
        with _threaded_con(ctx):
            gen_results = _parallel(lambda t: questions.generate_questions(ctx, t[0], t[1]["axes"], limit - len(t[2])),
                                    approved, workers)
        con.commit()
        to_label = [(c, res, mapped + gen) for (c, res, mapped), gen in zip(approved, gen_results) if mapped + gen]
        m3.n = len(to_label)
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
        trace.set_run(run_id)
        log = Logger(ws)
        with trace.milestone("M01", run_id=run_id, workspace=ws) as m:
            seen = do_ingest(ws, con, run_id, input_root, log)
            m.n = len(seen)
        ctx = Ctx(ws, con, run_id, tax=tax, transport=transport, log=log)
        store.meta_set(con, "taxonomy_sha256", tax_sha)
        store.meta_set(con, "sent_params", util.dumps(ctx.chat.sent_params()))
        _save_axis_meta(con, run_id, tax)
        chunks = content_chunks(con, seen)
        try:
            ctx.feedback = feedback.load(ws, tax, ctx.chat, enabled=use_feedback)
        except feedback.FeedbackError as e:
            raise PipelineError("검수 피드백 규칙 파일(labeling_rules.json) 오류: %s" % e,
                                reason_code="LABELING_RULES_INVALID", detail=trace.safe_code(str(e)))
        ctx.feedback.prepare(ws, con, run_id, chunks, log=log)
        if ctx.feedback.enabled:
            ctx.sheet_hashes["labeling_rules"] = ctx.feedback.digest()
        say(ctx.feedback.summary_line())
        stats = run_labeling(ctx, chunks)
        store.meta_set(con, "feedback_applied:" + run_id, util.dumps(ctx.feedback.applied()))
        store.meta_set(con, "rules_applied:" + run_id, util.dumps(ctx.feedback.applied_rules()))
        with trace.milestone("M04", run_id=run_id, workspace=ws) as m:
            alerts.evaluate(ctx)
            m.n = len(review.compute_flags(con, run_id, ws.config, tax, ws.path("reports")))
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
    from labelbot import axisupdate, candidates, export, finals, report, review, rulesdiff

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
        # rules_applied: 실행을 시작할 때의 승인 파일 기록과 기준 실행의 기록(끝에서 다시 읽지 않는다)
        own = rulesdiff.current(ws, tax) if use_feedback else feedback.empty_record()
    except feedback.FeedbackError as e:
        raise PipelineError("검수 피드백 규칙 파일(labeling_rules.json) 오류: %s" % e,
                                reason_code="LABELING_RULES_INVALID", detail=trace.safe_code(str(e)))
    prev_rules = rulesdiff.baseline(ws, con, p["prev_run"], tax, beat=lambda: axisupdate.touch_lock(ws, run_id))
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
    _save_rules_applied(con, run_id, prev_rules, own, axes=target | set(p["removed"]))
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


def _save_rules_applied(con, run_id, prev_rules, own, axes=(), keys=()):
    """부분 실행의 rules_applied:<run>: 이 실행이 다룬 범위(1차 축(삭제 축 포함), 3차 질문 ID·축=값)는 실행을 시작할 때
    잡은 승인 파일 기록(own)으로, 나머지는 기준 실행 기록(prev_rules = rulesdiff.baseline 결과)을 이어받는다.
    기준을 모르면 자기 범위만 partial로 남긴다(rulesdiff.baseline이 읽을 때 부모 기준을 다시 찾아 합친다)."""
    from labelbot import rulesdiff

    if prev_rules["code"]:
        rec = rulesdiff.merge(feedback.empty_record(), own, axes, keys)
        rec["partial"] = {"axes": sorted(axes), "keys": sorted(keys)}
    else:
        rec = rulesdiff.merge(prev_rules["record"], own, axes, keys)
    store.meta_set(con, "rules_applied:" + run_id, util.dumps(rec))
    return rec


def run_rules_update(ws, transport=None, dry_run=False):
    """라벨링 규칙 변경분만 다시 라벨링한다(rulesupdate). 축 규칙은 그 축만 1차 분류, 답 규칙은 그 질문만 3차 라벨링.

    반환: (plan, run_id 또는 None, ctx 또는 None). plan["code"]가 있으면(멈출 사유) 또는 dry_run이면 실행을 만들지 않는다.
    axis-update와 같은 잠금을 쓴다(AXIS_UPDATE_LOCKED). 잠금을 잡은 뒤 plan을 다시 계산해 그 결과로 실행한다.
    """
    from labelbot import axisupdate, rulesupdate, runchain

    con = store.connect(ws.work_db)
    try:
        tax, tax_sha = load_taxonomy(ws)
        cache = {}  # 기준 복원(git 이력 포함)은 잠금 밖·안 두 번의 plan에서 한 번만 한다
        try:
            p = rulesupdate.plan(ws, con, tax, cache=cache)
            if dry_run or p["code"]:
                return p, None, None
            owner = runchain.new_run_id(p["prev_run"])  # 잠금의 주인 = 만들 실행 ID
            if not axisupdate.acquire_lock(ws, owner, con):
                return dict(p, code=axisupdate.AXIS_UPDATE_LOCKED), None, None
            try:
                # 잠금 밖에서 본 상태가 그 사이 바뀌었을 수 있다. 오래 걸리면 잠금 mtime을 갱신한다
                p = rulesupdate.plan(ws, con, tax, own_lock=owner, cache=cache,
                                     beat=lambda: axisupdate.touch_lock(ws, owner))
                if p["code"]:
                    return p, None, None
                if owner <= p["prev_run"]:
                    new = runchain.new_run_id(p["prev_run"])
                    axisupdate.touch_lock(ws, owner, new)
                    owner = new
                try:
                    run_id, ctx = _rules_update(ws, con, tax, tax_sha, p, transport, owner)
                except LockLost:
                    return dict(p, code=axisupdate.AXIS_UPDATE_LOCK_LOST), None, None
            finally:
                axisupdate.release_lock(ws, owner)
        except feedback.FeedbackError as e:
            raise PipelineError("검수 피드백 규칙 파일(labeling_rules.json) 오류: %s" % e,
                                reason_code="LABELING_RULES_INVALID", detail=trace.safe_code(str(e)))
        return p, run_id, ctx
    finally:
        con.close()


def _rules_update(ws, con, tax, tax_sha, p, transport, run_id):
    """run_rules_update 본체(잠금 안). 반환: (run_id, ctx). 진행 줄은 실행 ID·건수만 낸다(규칙 문장·본문 없음)."""
    from labelbot import axisupdate, candidates, export, finals, report, rulesdiff, rulesupdate

    run_id = rulesupdate.start(ws, con, p, tax, run_id=run_id)
    log = Logger(ws)
    ctx = Ctx(ws, con, run_id, tax=tax, transport=transport, log=log)
    store.meta_set(con, "taxonomy_sha256", tax_sha)
    store.meta_set(con, "sent_params", util.dumps(ctx.chat.sent_params()))
    s = rulesupdate.summary(p)
    say("[rules-update] 기준 run_id=%s 바뀐 규칙 %d개(추가 %d, 수정 %d, 끔 %d, 기각 %d), 축 %d개 chunk %d개, 질문 %d개 답 %d건,"
        " 사람 값 건너뜀 %d건, 확인 chunk 건너뜀 %d건, 질문 없음 %d건, 축 없는 규칙 %d개" % (
            p["prev_run"], len(p["rules"]), len(p["added"]), len(p["edited"]), len(p["disabled"]), len(p["removed"]),
            len(s["classify_axes"]), len(p["axis_targets"]), s["answer_questions"], s["answer_targets"],
            p["skipped_human"], p["skipped_confirmed"], p["skipped_missing"], len(p["stage_wide"])))
    axis_t = {cid: set(v) for cid, v in p["axis_targets"].items()}
    all_axes = set().union(*axis_t.values()) if axis_t else set()
    rows = {c["chunk_id"]: c for c in rulesupdate.chunks(con, set(axis_t) | set(p["answer_targets"]))}
    ctx.feedback = feedback.load(ws, tax, ctx.chat, only_axes=all_axes)
    todo = [c for cid, c in rows.items() if cid in axis_t]
    ctx.feedback.prepare(ws, con, run_id, todo, log=log)
    if ctx.feedback.enabled:
        ctx.sheet_hashes["labeling_rules"] = ctx.feedback.digest()
    say(ctx.feedback.summary_line().replace("[feedback]", "[rules-update]", 1))
    active = {a.name for a in tax.active_axes()}
    prev_final = finals.final_labels(con, p["prev_run"], sorted(rows))
    workers = int(ctx.cfg["llm"].get("workers") or 4)
    beat = [0, time.time()]

    def keep_lock():
        with ctx.lock:  # 긴 실행: chunk 50개마다 또는 5분마다 잠금 mtime을 갱신한다
            beat[0] += 1
            if beat[0] % 50 == 0 or time.time() - beat[1] > 300:
                beat[1] = time.time()
                if not axisupdate.touch_lock(ws, run_id):
                    raise LockLost()

    st = {"relabeled": 0, "changed": 0, "failed": 0, "stale_answers": 0, "unasked_questions": 0}
    per_key, changes = {}, []

    def count(keys, field, item):
        for k in keys:  # 범위 키별 (chunk, 축·질문) 집합. 규칙별 건수는 자기 키의 합집합 크기다
            per_key.setdefault(k, {"relabeled": set(), "changed": set()})[field].add(item)

    def last_failure():
        return con.execute("SELECT COALESCE(MAX(id), 0) FROM failures").fetchone()[0]

    def clear_inherited(cid, stages, upto):
        """호출이 성공한 (chunk, 단계)의 이어받은 실패 기록(id ≤ upto)을 지운다. 이번 호출의 기록은 남는다."""
        con.execute("DELETE FROM failures WHERE run_id=? AND target_id=? AND id<=? AND stage IN (%s)"
                    % ",".join("?" * len(stages)), [run_id, cid, upto] + list(stages))

    def mark_failed(cid, stage, since):
        """이번 호출 실패(id > since): 이어받은 값이 유효하므로 분류·라벨 실패 chunk로 세지 않게 stage를 relabel로 바꾼다."""
        con.execute("UPDATE failures SET stage=?, reason_code=? WHERE run_id=? AND target_id=? AND stage=? AND id>?",
                    (rulesupdate.RELABEL_STAGE, rulesupdate.RELABEL_FAILED, run_id, cid, stage, since))

    # 1차: 대상 축만 부분 분류. 비대상 축의 확정 값은 참고 블록으로 준다. 호출이 성공한 축 행만 바꾼다.
    cur = finals.final_labels(con, run_id, [c["chunk_id"] for c in todo])
    # axis-update 대상 축을 아직 못 채운 chunk는 이어받은 분류 실패 기록을 남긴다(적재·내보내기 제외 기준과 같다)
    unfilled = finals.incomplete(con, run_id, cur)
    mark = last_failure()
    refs = {cid: {k: a["values"] for k, a in d["axes"].items() if k in active and k not in axis_t.get(cid, ())}
            for cid, d in cur.items()}

    def classify_one(c):
        res = classify.classify_chunk(ctx, c, axis_t[c["chunk_id"]], refs.get(c["chunk_id"]))
        keep_lock()
        return res
    with _threaded_con(ctx):
        results = _parallel(classify_one, todo, workers)
    for c, res in zip(todo, results):
        cid, target = c["chunk_id"], sorted(axis_t[c["chunk_id"]])
        if res is None:
            st["failed"] += len(target)  # 이어받은 값이 남는다
            mark_failed(cid, "classify", mark)
            continue
        if cid not in unfilled:
            clear_inherited(cid, ("classify",), mark)
        old = {k: cur[cid]["axes"].get(k, {}).get("values") or [] for k in target}
        con.execute("DELETE FROM labels WHERE run_id=? AND chunk_id=? AND kind='axis' AND key IN (%s)"
                    % ",".join("?" * len(target)), [run_id, cid] + target)
        classify.store_result(ctx, cid, res, set(target))
        candidates.collect_from_classify(ctx, cid, res)
        for ax in target:
            new = res["axes"][ax]["values"]
            st["relabeled"] += 1
            count([ax], "relabeled", (cid, ax))
            if set(old[ax]) == set(new):  # 다중값은 집합으로 비교
                continue
            st["changed"] += 1
            count([ax], "changed", (cid, ax))
            changes.append({"chunk_id": cid, "kind": "axis", "key": ax, "before": old[ax], "after": new, "stale": False})
            # 옛 값에 묶인 답은 버린다(사람이 손댄 답은 남긴다)
            for kind, key in rulesupdate.stale_keys(con, tax, run_id, cid, ax, old[ax], new):
                item = prev_final.get(cid, {}).get("answers", {}).get(key, {})
                if kind == "answer" and item.get("review", finals.UNREVIEWED) != finals.UNREVIEWED:
                    continue
                con.execute("DELETE FROM labels WHERE run_id=? AND chunk_id=? AND kind=? AND key=?",
                            (run_id, cid, kind, key))
                st["stale_answers"] += 1
                if kind == "answer":
                    changes.append({"chunk_id": cid, "kind": "answer", "key": key, "before": item.get("answer"),
                                    "after": None, "stale": True})
            # 새 값에 걸리는데 답이 없는 승인 질문은 다시 묻지 않고 센다
            answered = [r[0] for r in con.execute(
                "SELECT key FROM labels WHERE run_id=? AND chunk_id=? AND kind='answer'", (run_id, cid))]
            st["unasked_questions"] += rulesupdate.unasked(tax, ax, old[ax], new, answered)
    con.commit()
    say("[rules-update] 1차 분류 chunk %d개 중 실패 %d, 버린 답 %d건" % (
        len(todo), sum(1 for r in results if r is None), st["stale_answers"]))
    # 3차: 대상 질문만 다시 답한다. 축 값은 지금 확정 값(사람 교정 포함)을 준다. 버린 답은 다시 묻지 않는다.
    approved, gens = rulesupdate.question_index(con, tax)
    have = {(r[0], r[1]) for r in con.execute("SELECT chunk_id, key FROM labels WHERE run_id=? AND kind='answer'",
                                               (run_id,))}
    jobs = []
    for cid in sorted(p["answer_targets"]):
        qs = [gens.get(k) or approved.get(k) for k in p["answer_targets"][cid] if (cid, k) in have]
        qs = [q for q in qs if q is not None]
        if cid in rows and qs:
            jobs.append((rows[cid], qs))
    cur = finals.final_labels(con, run_id, [c["chunk_id"] for c, _ in jobs])
    mark = last_failure()

    def label_one(job):
        c, qs = job
        cls_res = {"axes": {k: {"values": a["values"]} for k, a in cur[c["chunk_id"]]["axes"].items() if k in active}}
        res = label.label_chunk(ctx, c, cls_res, qs)
        keep_lock()
        return res
    with _threaded_con(ctx):
        lab_results = _parallel(label_one, jobs, workers)
    base = ctx.label_base()("label")
    for (c, qs), res in zip(jobs, lab_results):
        cid = c["chunk_id"]
        if res is None:
            st["failed"] += len(qs)
            mark_failed(cid, "label", mark)
            continue
        clear_inherited(cid, ("label", "extract"), mark)
        candidates.collect_from_label(ctx, cid, res)
        for q in qs:
            a, keys = res["answers"][q.qid], p["answer_keys"][cid][q.qid]
            old = cur[cid]["answers"].get(q.qid, {}).get("answer")
            # extract 행은 다시 넣지 않는다(이어받은 행 그대로)
            con.execute("DELETE FROM labels WHERE run_id=? AND chunk_id=? AND kind='answer' AND key=?",
                        (run_id, cid, q.qid))
            con.execute("INSERT INTO labels(run_id, chunk_id, kind, key, value, status, evidence, confidence,"
                        " sheet_hashes, prompt_version, model, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (run_id, cid, "answer", q.qid, a["answer"], None, a["quote"], a["confidence"]) + base)
            st["relabeled"] += 1
            count(keys, "relabeled", (cid, q.qid))
            if old != a["answer"]:
                st["changed"] += 1
                count(keys, "changed", (cid, q.qid))
                changes.append({"chunk_id": cid, "kind": "answer", "key": q.qid, "before": old, "after": a["answer"],
                                "stale": False})
    con.commit()
    say("[rules-update] 3차 라벨 chunk %d개 중 실패 %d" % (len(jobs), sum(1 for r in lab_results if r is None)))
    cfg = ws.config.get("rules_update") or {}
    # 변경 비율: 다시 라벨한 (chunk, 축·질문) 중 값이 바뀐 비율. 버린 낡은 답(stale_answers)은 분모·분자에 넣지 않는다
    info = dict(s, **st)
    info.update(target=[], removed=[], values_added_only=[], axes=sorted(active), rules=_rule_stats(p, per_key),
                change_ratio=round(st["changed"] / float(st["relabeled"]), 4) if st["relabeled"] else 0.0,
                max_change_ratio=float(cfg.get("max_change_ratio", 0.3)), min_relabels=int(cfg.get("min_relabels", 10)))
    info["blocked"] = rulesupdate.blocked(ws, info)[0]
    store.meta_set(con, rulesupdate.META + run_id, util.dumps(info))
    store.meta_set(con, rulesupdate.CHANGES_META + run_id, util.dumps(changes))
    store.meta_set(con, "feedback_applied:" + run_id, util.dumps(ctx.feedback.applied()))
    export.export(ws, con, run_id, tax)
    report.write_report(ws, con, run_id, tax, stats={"chunks": len(rows), "classify_failed": st["failed"]})
    if not axisupdate.touch_lock(ws, run_id):  # 끝내기 전에 잠금이 아직 내 것인지 본다
        raise LockLost()
    # rules_applied: plan(잠금 안)에서 잡은 기준·지금 기록으로 남긴다. 실행 중 더해진 규칙은 다음 diff에 나온다
    sc = p["scope"]
    gone = [a for a in p["prev_record"]["classify"] if a not in active]  # 지금 비활성·삭제된 축의 옛 기록은 비운다
    _save_rules_applied(con, run_id, {"code": None, "record": p["prev_record"]}, p["cur_record"],
                        axes=sc["classify"]["axes"] + gone, keys=rulesdiff.label_keys(sc))
    finish_run(con, run_id, ctx.sheet_hashes, ctx.chat.sent_params())
    say("[rules-update] 완료 run_id=%s 다시 라벨 %d건, 값 바뀜 %d건, 실패 %d건, 변경 비율 %.2f(상한 %.2f)%s LLM 호출 %d회"
        " (캐시 %d회)" % (run_id, st["relabeled"], st["changed"], st["failed"], info["change_ratio"],
                         info["max_change_ratio"], ", 적재 보류 %s" % rulesupdate.RULES_CHANGE_RATIO_HIGH
                         if info["blocked"] else "", ctx.chat.calls, ctx.chat.cache_hits))
    return run_id, ctx


def _rule_stats(p, per_key):
    """규칙별 내역: 그 규칙의 범위 키(축 이름, 질문 ID·축=값)만 센다. 한 (chunk, 축·질문)이 규칙의 여러 키에 걸려도 한 번이다."""
    out = []
    for r in p["rules"]:
        row = dict(r, skipped_human=0, skipped_missing=0)
        for f in ("relabeled", "changed"):
            row[f] = len(set().union(*[per_key.get(k, {}).get(f, set()) for k in r["axes"] + r["keys"]]))
        for k in r["axes"] + r["keys"]:
            for f in ("skipped_human", "skipped_missing"):
                row[f] += p["scope_stats"].get(k, {}).get(f, 0)
        out.append(row)
    return out


def run_ingest(ws, input_root):
    con = store.connect(ws.work_db)
    try:
        run_id = start_run(con, ws, "ingest", input_root)
        trace.set_run(run_id)
        do_ingest(ws, con, run_id, input_root, Logger(ws))
        finish_run(con, run_id)
        return run_id
    finally:
        con.close()
