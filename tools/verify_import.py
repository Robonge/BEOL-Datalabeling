#!/usr/bin/env python3
"""반입 확인(C0, 마일스톤 M19 IMPORT): 압축 해제한 릴리스 폴더를 transfer/import_manifest.json과 대조한다.

배포판 python3(3.8+)에서 돈다. Python 3.8 문법·표준 라이브러리만 쓴다(removeprefix·zoneinfo·match 금지).

- 파일별 상태: OK / MISSING / EXTRA / CHANGED, office MISSING + 같은 크기·sha256 EXTRA = RENAMED_OK(이름 인코딩 깨짐)
- OOXML(.pptx .docx .xlsx) 시그니처: PK\\x03\\x04 정상, D0 CF 11 E0 = DRM_ENCRYPTED, 그 밖 NOT_OOXML
- 줄 끝만 바뀐 텍스트는 사유 EOL_CRLF
- code class가 CHANGED·MISSING이면 종료 코드 2(이 릴리스 사용 중지). state·office·media·text-other는 차단하지 않는다
- 보고서(--report, 기본 <root>/../_import/<release_label>.json): 경로·순번·사유 코드만. office 파일은 manifest 순번으로만 적는다

사용: python3 tools/verify_import.py --manifest transfer/import_manifest.json --root . [--report PATH]
종료 코드: 0 통과, 2 code 변경·누락, 1 manifest 오류 등.
"""
import argparse
import fnmatch
import hashlib
import json
import os
import sys
import time
import unicodedata

MILESTONE = "M19 IMPORT"
CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST_REL = "transfer/import_manifest.json"
OOXML_EXT = (".pptx", ".docx", ".xlsx")
NAMED_EXT = (".py", ".js", ".mjs", ".ts", ".html", ".htm", ".css", ".json", ".jsonl", ".md", ".sh", ".toml",
             ".ini", ".cfg", ".yml", ".yaml", ".sql", ".txt")
SKIP_DIRS = ("__pycache__", ".pytest_cache")
BLOCKING = ("CHANGED", "MISSING")


def fail_block(code, cause, action):
    """L3c labelbot.trace가 있으면 그 출력기를, 없으면(3.8·ImportError·SyntaxError) 같은 형식의 내장 출력기를 쓴다."""
    sys.stdout.flush()
    try:
        if CODE_ROOT not in sys.path:
            sys.path.insert(0, CODE_ROOT)
        from labelbot import trace
        fn = getattr(trace, "fail_block", None)
    except (ImportError, SyntaxError):
        fn = None
    if fn is not None:
        fn(MILESTONE, code, cause, action)
        return
    sys.stderr.write("[%s] 실패  사유=%s\n  원인: %s\n  조치: %s\n" % (MILESTONE, code, cause, action))
    sys.stderr.flush()


def glob_match(pattern, path):
    if pattern.endswith("/"):
        return path.startswith(pattern)
    pp, sp = pattern.split("/"), path.split("/")
    return len(pp) == len(sp) and all(fnmatch.fnmatchcase(s, p) for p, s in zip(pp, sp))


def nfc(s):
    return unicodedata.normalize("NFC", s)


def file_digest(path):
    h = hashlib.sha256()
    size = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            size += len(chunk)
            h.update(chunk)
    return size, h.hexdigest()


def ooxml_reason(path):
    with open(path, "rb") as f:
        head = f.read(4)
    if head == b"PK\x03\x04":
        return None
    if head == b"\xd0\xcf\x11\xe0":
        return "DRM_ENCRYPTED"
    return "NOT_OOXML"


def eol_only(path, sha):
    with open(path, "rb") as f:
        data = f.read()
    return b"\r\n" in data and hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest() == sha


def walk(root):
    """{nfc 상대경로: 실제 경로}. __pycache__는 건너뛴다."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            full = os.path.join(dirpath, name)
            out[nfc(os.path.relpath(full, root).replace(os.sep, "/"))] = full
    return out


def entry_ref(entry, index_of):
    """보고서용 식별자: office는 manifest 순번, 그 밖은 경로."""
    if entry["class"] == "office":
        return {"index": index_of[entry["path"]]}
    return {"path": entry["path"]}


def verify(manifest, root, manifest_path=None):
    files = manifest.get("files")
    if not isinstance(files, list):
        raise ValueError("files")
    index_of = dict((f["path"], i) for i, f in enumerate(files))
    expected = dict((nfc(f["path"]), f) for f in files)
    skip = [e["glob"] for e in manifest.get("state_paths", []) if not e.get("tracked")]
    found = walk(root)
    found.pop(MANIFEST_REL, None)
    if manifest_path:
        rel = nfc(os.path.relpath(os.path.abspath(manifest_path), os.path.abspath(root)).replace(os.sep, "/"))
        found.pop(rel, None)
    results = []  # (status, class, entry or None, actual path or None, reason)
    missing_office, extra = [], {}
    for rel, entry in expected.items():
        full = found.pop(rel, None)
        if full is None:
            if entry["class"] == "office":
                missing_office.append(entry)
            else:
                results.append(("MISSING", entry["class"], entry, None, None))
            continue
        size, sha = file_digest(full)
        if size == entry["size"] and sha == entry["sha256"]:
            results.append(("OK", entry["class"], entry, full, None))
            continue
        reason = None
        if entry["path"].lower().endswith(OOXML_EXT):
            reason = ooxml_reason(full)
        if reason is None and eol_only(full, entry["sha256"]):
            reason = "EOL_CRLF"
        results.append(("CHANGED", entry["class"], entry, full, reason))
    ignored = 0
    for rel, full in found.items():
        if any(glob_match(g, rel) for g in skip):  # 비추적 state(workspaces/ 등)는 EXTRA가 아니다
            ignored += 1
            continue
        extra[rel] = (full,) + file_digest(full)
    for entry in missing_office:
        hit = None
        for rel, (full, size, sha) in extra.items():
            if size == entry["size"] and sha == entry["sha256"]:
                hit = rel
                break
        if hit is None:
            results.append(("MISSING", "office", entry, None, None))
        else:
            results.append(("RENAMED_OK", "office", entry, extra.pop(hit)[0], None))
    for n, rel in enumerate(sorted(extra)):
        full = extra[rel][0]
        reason = ooxml_reason(full) if rel.lower().endswith(OOXML_EXT) else None
        results.append(("EXTRA", None, {"path": rel, "n": n + 1}, full, reason))
    return results, ignored


def build_report(manifest, root, results, ignored, elapsed):
    index_of = dict((f["path"], i) for i, f in enumerate(manifest["files"]))
    counts, entries = {}, []
    blocked = False
    for status, cls, entry, _full, reason in results:
        key = cls or "unknown"
        counts.setdefault(status, {})
        counts[status][key] = counts[status].get(key, 0) + 1
        if status == "OK":
            continue
        if cls == "code" and status in BLOCKING:
            blocked = True
        if status == "EXTRA":
            path = entry["path"]
            ext = os.path.splitext(path)[1].lower()
            row = {"path": path} if ext in NAMED_EXT else {"extra_id": "extra-%d" % entry["n"], "ext": ext}
        else:
            row = entry_ref(entry, index_of)
        row.update({"status": status, "class": cls})
        if reason:
            row["reason"] = reason
        entries.append(row)
    label = manifest.get("release_label")
    return {
        "release_label": label,
        "source_commit": manifest.get("source_commit"),
        "verified_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "root_name_matches_label": os.path.basename(os.path.abspath(root)) == label,
        "verdict": "BLOCKED" if blocked else "OK",
        "counts": counts,
        "ignored_untracked": ignored,
        "elapsed_s": round(elapsed, 2),
        "entries": entries,
    }


def print_summary(report):
    print("release_label=%s commit=%s verdict=%s" % (report["release_label"], (report["source_commit"] or "")[:7], report["verdict"]))
    for status in ("OK", "CHANGED", "MISSING", "EXTRA", "RENAMED_OK"):
        by = report["counts"].get(status)
        if by:
            print("  %-10s %s" % (status, " ".join("%s=%d" % kv for kv in sorted(by.items()))))
    for row in report["entries"]:
        ref = row.get("path") or ("#%d" % row["index"] if "index" in row else row.get("extra_id"))
        print("  %s %s %s%s" % (row["status"], row["class"] or "-", ref, (" " + row["reason"]) if row.get("reason") else ""))
    if not report["root_name_matches_label"]:
        print("  [알림] 폴더 이름이 release_label과 다르다(CLOSED_NETWORK_RUNBOOK C0의 mv 단계 확인)")


def write_json(path, obj):
    parent = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(parent):
        os.makedirs(parent)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, path)


def main(argv=None):
    for _s in (sys.stdout, sys.stderr):  # Windows 콘솔(cp949)에서도 한글·기호 출력이 죽지 않게
        try:
            _s.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    ap = argparse.ArgumentParser(prog="verify_import", description="반입 확인(M19 IMPORT, C0)")
    ap.add_argument("--root", default=".", help="압축 해제한 릴리스 폴더(기본 현재 폴더)")
    ap.add_argument("--manifest", help="manifest 경로(기본 <root>/transfer/import_manifest.json)")
    ap.add_argument("--report", "--out", dest="report", help="보고서 경로(기본 <root>/../_import/<release_label>.json)")
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root)
    manifest_path = args.manifest or os.path.join(root, *MANIFEST_REL.split("/"))
    sys.stderr.write("[%s] 시작\n" % MILESTONE)
    started = time.time()
    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        results, ignored = verify(manifest, root, manifest_path)
    except (OSError, ValueError, KeyError, TypeError):
        fail_block("MANIFEST_INVALID", "manifest를 읽을 수 없거나 형식이 다르다",
                   "--manifest 경로(transfer/import_manifest.json)와 압축 해제 상태를 확인한다")
        return 1
    report = build_report(manifest, root, results, ignored, time.time() - started)
    out = args.report or os.path.join(os.path.dirname(root), "_import", "%s.json" % report["release_label"])
    try:
        write_json(out, report)
    except OSError:
        fail_block("REPORT_NOT_WRITABLE", "반입 보고서를 쓸 수 없다", "--report 경로의 폴더 권한을 확인한다")
        return 1
    print_summary(report)
    print("report: %s" % out)
    if report["verdict"] == "BLOCKED":
        fail_block("CODE_CHANGED", "code 파일이 바뀌었거나 빠졌다(압축 해제·DRM 변형 또는 직접 수정)",
                   "이 릴리스를 쓰지 않는다. 보고서를 반출해 로컬에 알리고, 사내 PC에서 7-Zip으로 다시 압축 해제해 본다")
        return 2
    sys.stdout.flush()
    sys.stderr.write("[%s] 완료 n=%d\n" % (MILESTONE, len(results)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
