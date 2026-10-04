"""환경 self-check. 항목별 PASS/FAIL. 키 값과 본문은 출력하지 않는다."""
import hashlib
import os
import shutil
import sqlite3
import sys

from labelbot import util
from labelbot.llm import CallFailed, SendBlocked, get_json, host_class, read_key

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
    tax_ok, detail = os.path.isfile(ws.taxonomy_path), ""
    if tax_ok:
        try:
            from labelbot.pipeline import load_taxonomy

            tax, _ = load_taxonomy(ws)
            detail = "축 %d (활성 %d)" % (len(tax.axes), len(tax.active_axes()))
        except Exception as e:  # 시트 오류 내용은 load_taxonomy가 시트·행으로만 낸다
            tax_ok, detail = False, type(e).__name__
    else:
        detail = "defaults/taxonomy.xlsx를 작업 폴더로 복사하세요"
    item("taxonomy.xlsx", tax_ok, detail)
    llm = ws.config["llm"]
    suffixes = llm.get("internal_host_suffixes")
    llm_url = (llm.get("base_url") or "").rstrip("/") + llm.get("chat_path", "")
    item("llm_config", bool(llm.get("base_url") and llm.get("model")), "model=%s" % (llm.get("model") or "(없음)"))
    item("llm_key_env", llm.get("transport") == "mock" or bool(read_key(llm.get("api_key_env"))), llm.get("api_key_env") or "")
    for name, url in (("host_llm", llm_url),
                      ("host_embedding", (ws.config["embedding"].get("base_url") or "") + ws.config["embedding"].get("path", "")),
                      ("host_supabase", ws.supabase_url())):
        if name == "host_supabase" and not ws.config["supabase"].get("enabled"):
            out("%-28s -    supabase.enabled=false" % name)
            continue
        cls = host_class(url, suffixes)
        item(name, cls != "uncertain", {"internal": "사내", "external": "사외", "uncertain": "불확실"}[cls])
    rt = write_roundtrip(ws.root)
    for ext in EXTS:
        item("write_roundtrip %s" % ext, rt[ext])
    out("  write_roundtrip은 필요조건일 뿐이며 M7 게이트의 수동 확인이 필요하다.")
    if probe_llm and llm.get("transport") != "mock":
        from labelbot import store
        from labelbot.llm import ChatClient

        con = store.connect(ws.work_db)
        try:
            client = ChatClient(llm, con)
            obj = client.chat_json([{"role": "user", "content": PROBE_SENTENCE}], [], lambda o: (o.get("ok") is True, "PROBE"), probe=True)
            item("llm_probe", bool(obj))
        except (CallFailed, SendBlocked) as e:
            item("llm_probe", False, e.reason_code)
        finally:
            con.close()
    sb = ws.config["supabase"]
    if sb.get("enabled"):
        key = read_key(sb.get("key_env"))
        item("supabase_key_env", bool(key), sb.get("key_env") or "")
        if key and ws.supabase_url() and host_class(ws.supabase_url(), suffixes) != "uncertain":
            try:
                get_json("%s/rest/v1/%s?select=chunk_id&limit=1" % (ws.supabase_url().rstrip("/"), sb["table"]),
                         {"apikey": key, "Authorization": "Bearer " + key}, sb.get("timeout") or 60, sb.get("ca_file"))
                item("supabase_table", True, sb["table"])
            except CallFailed as e:
                item("supabase_table", False, e.reason_code)
    failed = [n for n, ok in items if not ok]
    out("결과: %s" % ("전 항목 PASS" if not failed else "FAIL %d개" % len(failed)))
    return not failed, items
