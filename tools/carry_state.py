#!/usr/bin/env python3
"""업그레이드 상태 이어받기(CU, 마일스톤 M19 IMPORT): 이전 릴리스 폴더(폐쇄망 운영 사본)의 state를 새 릴리스 폴더로 옮긴다.

배포판 python3(3.8+)에서 돈다. Python 3.8 문법·표준 라이브러리만 쓴다.

3방향 비교(추적 state): base = 이전 폴더 transfer/import_manifest.json의 state 해시, release = 새 폴더 파일,
closed = 이전 폴더 파일(폐쇄망에서 바뀐 사본).
- KEEP_CLOSED   릴리스가 base 그대로 → 폐쇄망 사본 유지(복사, 폐쇄망에서 지웠으면 새 폴더에서도 지움)
- TAKE_RELEASE  릴리스만 바뀜(또는 둘이 같게 바뀜) → 새 릴리스 것
- CONFLICT      둘 다 다르게 바뀜 → 행 단위 차이 보고. --resolve path=closed|release 없으면 멈춤(종료 1)
- ADDED_CLOSED  폐쇄망에만 있음 → 복사
- FLAG_RELEASE_DELETED  릴리스에서 삭제 → 아무것도 안 함, 사람이 확인
- FLAG          폐쇄망에서 삭제했는데 릴리스도 바꿈 → 아무것도 안 함, 사람이 확인
- COPIED_UNTRACKED 비추적(workspaces/ 등) → 비교 없이 폐쇄망 사본 복사(새 릴리스의 추적 파일은 덮지 않음)

dry-run이 기본이고 --apply를 줘야 쓴다. 보고서 carry_report.json(기본 <new>/carry_report.json)에는 경로·판정·사유 코드만.
사용: python3 tools/carry_state.py --old DIR --new DIR [--apply] [--resolve path=closed|release ...] [--report PATH]
종료 코드: 0 정상, 1 NO_BASE_MANIFEST·미해결 CONFLICT 등.
"""
import argparse
import difflib
import fnmatch
import hashlib
import json
import os
import shutil
import sys
import time

MILESTONE = "M19 IMPORT"
CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST_REL = "transfer/import_manifest.json"
# JSON 목록 행을 식별하는 키(taxonomy.json 섹션, labeling_rules.json 섹션). 없으면 순번.
ROW_KEYS = {
    "taxonomy": ("축", "값", "상위값"),
    "questions": ("질문 ID",),
    "synonyms": ("동의어",),
    "rejected": ("종류", "내용"),
    "rules": ("rule_id",),
    "examples": ("example_id",),
    "rejected_examples": ("example_id",),
}
MAX_DIFF_ROWS = 50


class ToolError(Exception):
    def __init__(self, code, cause, action):
        Exception.__init__(self, code)
        self.code, self.cause, self.action = code, cause, action


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


def sha_of(path):
    if not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(folder):
    try:
        with open(os.path.join(folder, *MANIFEST_REL.split("/")), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def list_files(folder, pattern):
    """folder 안에서 pattern에 맞는 파일의 상대경로 목록."""
    if pattern.endswith("/"):
        top = os.path.join(folder, *pattern.rstrip("/").split("/"))
        out = []
        for dirpath, dirnames, filenames in os.walk(top):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for name in filenames:
                out.append(os.path.relpath(os.path.join(dirpath, name), folder).replace(os.sep, "/"))
        return out
    parent = pattern.rsplit("/", 1)[0] if "/" in pattern else ""
    top = os.path.join(folder, *parent.split("/")) if parent else folder
    if not os.path.isdir(top):
        return []
    out = []
    for name in os.listdir(top):
        rel = (parent + "/" if parent else "") + name
        if os.path.isfile(os.path.join(top, name)) and glob_match(pattern, rel):
            out.append(rel)
    return out


def decide(b, r, c):
    """(판정, 동작). b=base, r=release, c=closed sha(없으면 None)."""
    if b is None:
        if c is None:
            return ("TAKE_RELEASE", "none") if r else (None, None)
        if r is None:
            return "ADDED_CLOSED", "copy"
        return ("TAKE_RELEASE", "none") if r == c else ("CONFLICT", "none")
    if r is None:
        return ("FLAG_RELEASE_DELETED", "none") if c else (None, None)
    if r == b:
        if c is None:
            return "KEEP_CLOSED", "delete"
        return "KEEP_CLOSED", ("copy" if c != r else "none")
    if c is None:
        return "FLAG", "none"
    if c == b or c == r:
        return "TAKE_RELEASE", "none"
    return "CONFLICT", "none"


def _rows(value, section):
    keys = ROW_KEYS.get(section)
    out = {}
    for i, row in enumerate(value):
        if keys and isinstance(row, dict) and all(k in row for k in keys):
            k = "[%s]" % "|".join(str(row[k]) for k in keys)
        else:
            k = "[%d]" % i
        while k in out:
            k += "'"
        out[k] = row
    return out


def json_diff(a, b, path="", section=None, out=None):
    """키 경로 단위 차이 [{op, key}]. 목록은 ROW_KEYS로 행을 맞추고, 없으면 순번으로 맞춘다."""
    out = [] if out is None else out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            p = "%s.%s" % (path, k) if path else str(k)
            if k not in a:
                out.append({"op": "added", "key": p})
            elif k not in b:
                out.append({"op": "removed", "key": p})
            elif a[k] != b[k]:
                json_diff(a[k], b[k], p, k, out)
        return out
    if isinstance(a, list) and isinstance(b, list):
        ra, rb = _rows(a, section), _rows(b, section)
        for k in list(ra) + [k for k in rb if k not in ra]:
            p = path + k
            if k not in ra:
                out.append({"op": "row_added", "key": p})
            elif k not in rb:
                out.append({"op": "row_removed", "key": p})
            elif ra[k] != rb[k]:
                if isinstance(ra[k], dict) and isinstance(rb[k], dict):
                    json_diff(ra[k], rb[k], p, None, out)
                else:
                    out.append({"op": "row_changed", "key": p})
        return out
    out.append({"op": "changed", "key": path or "$"})
    return out


def conflict_diff(closed_path, release_path):
    """폐쇄망 사본 → 릴리스 차이. JSON은 키 경로·행, 그 밖은 바뀐 줄 범위."""
    with open(closed_path, "rb") as f:
        ca = f.read()
    with open(release_path, "rb") as f:
        rb = f.read()
    if closed_path.lower().endswith(".json"):
        try:
            return {"kind": "json", "changes": json_diff(json.loads(ca.decode("utf-8")), json.loads(rb.decode("utf-8")))}
        except ValueError:
            pass
    la = ca.decode("utf-8", "replace").splitlines()
    lb = rb.decode("utf-8", "replace").splitlines()
    hunks = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, la, lb, autojunk=False).get_opcodes():
        if tag != "equal":
            hunks.append({"op": tag, "closed_lines": [i1 + 1, i2], "release_lines": [j1 + 1, j2]})
    return {"kind": "lines", "changes": hunks}


def plan(old, new):
    base_manifest = load_manifest(old)
    if base_manifest is None:
        raise ToolError("NO_BASE_MANIFEST", "이전 릴리스 폴더에 transfer/import_manifest.json이 없다(기준 해시 없음)",
                        "수동 비교 후 반출 보고. 이전 폴더 경로(--old)가 맞는지 확인한다")
    new_manifest = load_manifest(new) or {}
    state_paths = new_manifest.get("state_paths") or base_manifest.get("state_paths") or []
    base = dict((f["path"], f["sha256"]) for f in base_manifest.get("files", []) if f.get("class") == "state")
    new_tracked = set(f["path"] for f in new_manifest.get("files", []))
    rows, handled = [], set()
    for entry in state_paths:
        pattern = entry["glob"]
        if entry.get("tracked"):
            paths = set(p for p in base if glob_match(pattern, p))
            paths.update(list_files(old, pattern))
            paths.update(list_files(new, pattern))
            for p in sorted(paths - handled):
                handled.add(p)
                parts = p.split("/")
                b = base.get(p)
                r = sha_of(os.path.join(new, *parts))
                c = sha_of(os.path.join(old, *parts))
                decision, action = decide(b, r, c)
                if decision is None:
                    continue
                row = {"path": p, "decision": decision, "action": action}
                if decision == "CONFLICT":
                    row["diff"] = conflict_diff(os.path.join(old, *parts), os.path.join(new, *parts))
                rows.append(row)
        else:
            files = [p for p in list_files(old, pattern) if p not in handled]
            handled.update(files)
            copy, same, kept = [], 0, 0
            for p in files:
                parts = p.split("/")
                if p in new_tracked:
                    kept += 1
                elif sha_of(os.path.join(new, *parts)) == sha_of(os.path.join(old, *parts)):
                    same += 1
                else:
                    copy.append(p)
            rows.append({"glob": pattern, "decision": "COPIED_UNTRACKED", "action": "copy",
                         "files": len(files), "to_copy": len(copy), "same": same, "kept_release_tracked": kept,
                         "_copy": copy})
    return rows, new_manifest.get("release_label"), base_manifest.get("release_label")


def copy_file(src, dst):
    parent = os.path.dirname(dst)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    tmp = dst + ".carrytmp"
    shutil.copy2(src, tmp)
    os.replace(tmp, dst)


def apply(rows, old, new, resolve):
    done = 0
    for row in rows:
        if row["decision"] == "COPIED_UNTRACKED":
            for p in row["_copy"]:
                copy_file(os.path.join(old, *p.split("/")), os.path.join(new, *p.split("/")))
                done += 1
            continue
        parts = row["path"].split("/")
        action = row["action"]
        if row["decision"] == "CONFLICT":
            action = "copy" if resolve.get(row["path"]) == "closed" else "none"
        if action == "copy":
            copy_file(os.path.join(old, *parts), os.path.join(new, *parts))
            done += 1
        elif action == "delete" and os.path.isfile(os.path.join(new, *parts)):
            os.remove(os.path.join(new, *parts))
            done += 1
    return done


def parse_resolve(items):
    out = {}
    for item in items or []:
        path, sep, side = item.rpartition("=")
        if not sep or side not in ("closed", "release") or not path:
            raise ToolError("RESOLVE_INVALID", "--resolve는 path=closed|release 형식이어야 한다",
                            "예: --resolve taxonomy/taxonomy.json=closed")
        out[path] = side
    return out


def print_rows(rows, resolve):
    for row in rows:
        if row["decision"] == "COPIED_UNTRACKED":
            print("  %-20s %s files=%d to_copy=%d same=%d kept_release_tracked=%d" % (
                row["decision"], row["glob"], row["files"], row["to_copy"], row["same"], row["kept_release_tracked"]))
            continue
        extra = (" resolve=" + resolve[row["path"]]) if row["path"] in resolve else ""
        print("  %-20s %s (%s)%s" % (row["decision"], row["path"], row["action"], extra))
        if row["decision"] == "CONFLICT":
            changes = row["diff"]["changes"]
            for ch in changes[:MAX_DIFF_ROWS]:
                if row["diff"]["kind"] == "json":
                    print("      %-11s %s" % (ch["op"], ch["key"]))
                else:
                    print("      %-7s 폐쇄망 %d-%d줄 / 릴리스 %d-%d줄" % (
                        ch["op"], ch["closed_lines"][0], ch["closed_lines"][1], ch["release_lines"][0], ch["release_lines"][1]))
            if len(changes) > MAX_DIFF_ROWS:
                print("      … 외 %d건(carry_report.json)" % (len(changes) - MAX_DIFF_ROWS))


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
    ap = argparse.ArgumentParser(prog="carry_state", description="업그레이드 상태 이어받기(M19 IMPORT, CU)")
    ap.add_argument("--old", required=True, help="이전 릴리스 폴더(폐쇄망 운영 사본)")
    ap.add_argument("--new", required=True, help="새 릴리스 폴더(C0 통과)")
    ap.add_argument("--apply", action="store_true", help="실제로 복사·삭제한다(없으면 dry-run)")
    ap.add_argument("--resolve", action="append", metavar="PATH=closed|release", help="CONFLICT 선택(반복)")
    ap.add_argument("--report", help="보고서 경로(기본 <new>/carry_report.json)")
    args = ap.parse_args(argv)
    old, new = os.path.abspath(args.old), os.path.abspath(args.new)
    report_path = args.report or os.path.join(new, "carry_report.json")
    sys.stderr.write("[%s] 시작 carry %s\n" % (MILESTONE, "apply" if args.apply else "dry-run"))
    try:
        resolve = parse_resolve(args.resolve)
        rows, new_label, old_label = plan(old, new)
    except ToolError as e:
        fail_block(e.code, e.cause, e.action)
        return 1
    except (OSError, ValueError, KeyError, TypeError):
        fail_block("CARRY_READ_FAILED", "폴더나 manifest를 읽는 중 오류가 났다", "--old·--new 경로와 권한을 확인한다")
        return 1
    unresolved = [r["path"] for r in rows if r["decision"] == "CONFLICT" and r["path"] not in resolve]
    applied = 0
    if args.apply and not unresolved:
        try:
            applied = apply(rows, old, new, resolve)
        except OSError:
            fail_block("CARRY_WRITE_FAILED", "새 폴더에 쓰는 중 오류가 났다", "디스크 여유·권한 확인 후 --apply를 다시 실행한다")
            return 1
    counts = {}
    for r in rows:
        counts[r["decision"]] = counts.get(r["decision"], 0) + 1
    report = {
        "old_release_label": old_label,
        "new_release_label": new_label,
        "mode": "apply" if args.apply and not unresolved else "dry-run",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "counts": counts,
        "unresolved_conflicts": unresolved,
        "resolve": resolve,
        "applied_actions": applied,
        "rows": [dict((k, v) for k, v in r.items() if k != "_copy") for r in rows],
    }
    try:
        write_json(report_path, report)
    except OSError:
        fail_block("REPORT_NOT_WRITABLE", "carry_report.json을 쓸 수 없다", "--report 경로의 폴더 권한을 확인한다")
        return 1
    print("carry %s: %s -> %s" % (report["mode"], old_label, new_label))
    print_rows(rows, resolve)
    print("report: %s" % report_path)
    if unresolved:
        fail_block("CONFLICT", "릴리스와 폐쇄망이 둘 다 바꾼 state 파일 %d개" % len(unresolved),
                   "위 차이를 보고 --resolve <path>=closed|release를 붙여 다시 실행한다")
        return 1
    if not args.apply:
        print("다음: 확인 후 같은 명령에 --apply")
    print("그다음: python tools/cloud_migrate_paths.py --old-root %s   (dry-run 확인 후)" % old)
    print("        python tools/cloud_migrate_paths.py --old-root %s --apply" % old)
    sys.stdout.flush()
    sys.stderr.write("[%s] 완료 n=%d\n" % (MILESTONE, len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
