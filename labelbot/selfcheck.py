"""환경 self-check. 항목별 PASS/FAIL. 키 값과 본문은 출력하지 않는다."""
import hashlib
import os
import shutil
import sqlite3
import sys
import urllib.parse

from labelbot import util
from labelbot.llm import CallFailed, get_json, read_key

EXTS = (".b64", ".sqlite", ".json", ".jsonl", ".html", ".md", ".log")
PROBE_SENTENCE = "Reply with JSON {\"ok\": true}"


def write_roundtrip(root, writer=None):
    """허용 확장자마다 알려진 바이트를 쓰고 다시 읽어 sha256 비교 후 지운다. 원본 경로를 열지 않는다(read_input 예외)."""
    tmp = os.path.join(root, "_roundtrip_tmp")
    os.makedirs(tmp, exist_ok=True)
    results = {}
    try:
        for ext in EXTS:
            p = os.path.join(tmp, "probe" + ext)
            try:
                if ext == ".sqlite":
                    con = sqlite3.connect(p)
                    con.execute("PRAGMA journal_mode=DELETE")
                    con.execute("CREATE TABLE t(x TEXT)")
                    con.execute("INSERT INTO t VALUES('roundtrip')")
                    con.commit()
                    con.close()
                    con = sqlite3.connect(p)
                    ok = con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                    ok = ok and con.execute("SELECT x FROM t").fetchone()[0] == "roundtrip"
                    con.close()
                else:
                    data = ("labelbot roundtrip %s 한글\n" % ext).encode("utf-8")
                    (writer or _write)(p, data)
                    with open(p, "rb") as f:
                        ok = hashlib.sha256(f.read()).hexdigest() == hashlib.sha256(data).hexdigest()
            except (OSError, sqlite3.DatabaseError):
                ok = False
            results[ext] = ok
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return results


def _write(path, data):
    with open(path, "wb") as f:
        f.write(data)


def run(ws, probe_llm=False, out=print):
    items = []

    def item(name, ok, detail=""):
        items.append((name, ok))
        out("%-28s %s %s" % (name, "PASS" if ok else "FAIL", detail))

    item("python", sys.version_info >= (3, 8), sys.version.split()[0])
    item("sqlite3", True, sqlite3.sqlite_version)
    try:
        util.write_text(ws.path("logs", "_selfcheck.log"), "ok\n")
        os.remove(ws.path("logs", "_selfcheck.log"))
        item("workspace_writable", True)
    except OSError:
        item("workspace_writable", False)
    _check_taxonomy(ws, item)
    llm = ws.config["llm"]
    item("llm_config", bool(llm.get("base_url") and llm.get("model")), "model=%s" % (llm.get("model") or "(없음)"))
    item("llm_key_env", llm.get("transport") == "mock" or bool(read_key(llm.get("api_key_env"))), llm.get("api_key_env") or "")
    rt = write_roundtrip(ws.root)
    for ext in EXTS:
        item("write_roundtrip %s" % ext, rt[ext])
    out("  write_roundtrip은 필요조건일 뿐이며 M7 게이트의 수동 확인이 필요하다.")
    if probe_llm and llm.get("transport") != "mock":
        _probe_llm(ws, llm, item)
    if ws.config["supabase"].get("enabled"):
        _check_supabase(ws, item, out)
    failed = [n for n, ok in items if not ok]
    out("결과: %s" % ("전 항목 PASS" if not failed else "FAIL %d개" % len(failed)))
    return not failed, items


def _check_taxonomy(ws, item):
    tax_ok = os.path.isfile(ws.taxonomy_path) and not ws.taxonomy_path.lower().endswith(".xlsx")
    detail, tax, d = "", None, {}
    if tax_ok:
        try:
            from labelbot import taxdiff
            from labelbot.pipeline import load_taxonomy

            tax, _ = load_taxonomy(ws)
            detail = "축 %d (활성 %d)" % (len(tax.axes), len(tax.active_axes()))
        except Exception as e:  # 시트 오류 내용은 load_taxonomy가 시트·행으로만 낸다
            tax_ok, detail = False, type(e).__name__
        if tax_ok:
            try:
                d, _ = taxdiff.compare_workspace(ws, tax)
                detail += " " + taxdiff.summary_line(d)
            except Exception:  # work.sqlite 오류는 taxonomy 자체의 실패가 아니다
                d = {}
                detail += " diff 알 수 없음"
            legacy = os.path.splitext(ws.taxonomy_path)[0] + ".xlsx"
            if os.path.isfile(legacy) and os.path.getmtime(legacy) > os.path.getmtime(ws.taxonomy_path):
                # 원본은 JSON이다. 예전 xlsx를 고쳐도 반영되지 않는다(실패로 치지 않는다)
                detail += " WARN TAXONOMY_XLSX_NEWER: 예전 taxonomy.xlsx가 더 최근에 저장됐다(편집은 보드·편집기로)"
    else:
        detail = ("TAXONOMY_XLSX_NEEDS_MIGRATION: python -m labelbot taxonomy-migrate --xlsx \"%s\"" % ws.taxonomy_path
                  if ws.taxonomy_path.lower().endswith(".xlsx") else "pipeline.json taxonomy_path의 taxonomy.json이 없습니다")
    item("taxonomy.json", tax_ok, detail)
    if tax_ok and tax is not None:
        warns = axis_quality(tax, d)
        # WARN은 실패로 치지 않는다(ok=True). 축 이름과 건수만 낸다.
        item("taxonomy_axes", True, "; ".join(warns) if warns else "점검 통과")


def axis_quality(tax, d=None):
    """축 품질 WARN 문구 목록. 축 이름과 건수만 쓴다."""
    new_axes = set((d or {}).get("added") or [])
    targeted = {q.target[0] for q in tax.questions if isinstance(q.target, tuple)}
    no_def = [a.name for a in tax.active_axes() if not a.definition.strip()]
    # 질문 시트는 대개 "공통" 대상이라 기존 축에 축별 질문이 없는 것은 정상이다. 새 축만 알린다.
    no_question = [a.name for a in tax.active_axes() if a.name in new_axes and a.name not in targeted]
    no_values = [a.name for a in tax.axes if a.enabled and not a.values]
    warns = []
    if no_def:
        warns.append("WARN 정의·판정 규칙 없는 활성 축 %d(%s)" % (len(no_def), ", ".join(no_def)))
    if no_question:
        warns.append("WARN 질문 적용 대상에 없는 새 축 %d(%s)" % (len(no_question), ", ".join(no_question)))
    if no_values:
        warns.append("WARN 값 행이 없어 비활성인 축 %d(%s)" % (len(no_values), ", ".join(no_values)))
    return warns


def _probe_llm(ws, llm, item):
    from labelbot import store
    from labelbot.llm import ChatClient

    con = store.connect(ws.work_db)
    try:
        client = ChatClient(llm, con)
        obj = client.chat_json([{"role": "user", "content": PROBE_SENTENCE}], [], lambda o: (o.get("ok") is True, "PROBE"), probe=True)
        item("llm_probe", bool(obj))
    except CallFailed as e:
        item("llm_probe", False, e.reason_code)
    finally:
        con.close()


def _check_supabase(ws, item, out):
    """supabase.enabled일 때만 부른다. 키, 표, slide_image_* 열, Storage 버킷을 확인한다."""
    sb = ws.config["supabase"]
    key = read_key(sb.get("key_env"))
    item("supabase_key_env", bool(key), sb.get("key_env") or "")
    if key and ws.supabase_url():
        base = ws.supabase_url().rstrip("/")
        hdrs = {"apikey": key, "Authorization": "Bearer " + key}
        timeout = sb.get("timeout") or 60
        try:
            get_json("%s/rest/v1/%s?select=chunk_id&limit=1" % (base, sb["table"]), hdrs, timeout, sb.get("ca_file"))
            item("supabase_table", True, sb["table"])
        except CallFailed as e:
            item("supabase_table", False, e.reason_code)
        # push-slides가 쓰는 slide_image_* 열과 Storage 버킷을 미리 확인한다(docs/supabase_schema.md).
        if sb.get("storage_enabled"):
            bucket = sb.get("storage_bucket") or "BEOL-labeling"
            try:
                get_json("%s/rest/v1/%s?select=slide_image_path&limit=1" % (base, sb["table"]), hdrs, timeout,
                         sb.get("ca_file"))
                item("supabase_slide_columns", True, "slide_image_*")
            except CallFailed as e:
                item("supabase_slide_columns", False, e.reason_code)
            try:
                get_json("%s/storage/v1/bucket/%s" % (base, urllib.parse.quote(bucket, safe="")), hdrs, timeout,
                         sb.get("ca_file"))
                item("supabase_storage_bucket", True, bucket)
            except CallFailed as e:
                item("supabase_storage_bucket", False, e.reason_code)
    if not sb.get("storage_enabled"):
        out("%-28s -    supabase.storage_enabled=false(슬라이드 JPG 적재 꺼짐)" % "supabase_storage")
