"""작업 폴더 pipeline.json의 옛 절대경로를 현재 저장소 기준으로 바꾼다(저장소를 옮긴 뒤 1회 실행).

대상: workspaces/*/pipeline.json의 taxonomy_path·input_root
      (--include-ingested-list면 injested-file-list/*.json의 workspace·input도).
값마다 판정한다(os.path.isabs는 쓰지 않는다 — Linux에서 C:/… 를 상대로 보기 때문):
  `\\`를 `/`로 바꾼 뒤
  1) --old-root 접두어와 맞으면(대소문자 무시) 변환 → CONVERTED
  2) 아니고 드라이브 문자(`X:/`)나 `/`로 시작하지 않으면 → ALREADY_OK(이미 상대경로)
  3) 그 밖의 절대경로 → OUTSIDE_REPO(그대로 둔다)
변환 값:
  --mode relative(기본): relpath(<현재 저장소 루트>/<접미사>, <작업 폴더>)(`/` 구분).
      injested-file-list의 workspace는 저장소 루트 기준, input은 그 작업 폴더 기준(record_ingested.py와 같은 기준).
  --new-root PATH: PATH/<접미사>(절대경로).
--apply가 없으면 dry-run(아무것도 쓰지 않는다). --apply면 바꿀 파일을 먼저
workspaces/_migrate_backup_<YYYYMMDD-HHMMSS>/<저장소 기준 경로>로 복사하고, 원자적으로 쓴 뒤
같은 폴더의 migrate.jsonl에 대상 종류·순번·필드·사유 코드만 남긴다(경로 값·파일명은 남기지 않는다).
--restore BACKUP_DIR: 백업 폴더의 파일을 원래 자리로 되돌린다.

사용:
  python tools/cloud_migrate_paths.py --old-root "<옛 저장소 루트>" [--old-root ...] [--apply]
  python tools/cloud_migrate_paths.py --old-root "<옛 루트>" --new-root "<새 루트>" --apply
  python tools/cloud_migrate_paths.py --restore workspaces/_migrate_backup_<stamp>
출력: JSON 한 줄 {files_scanned, files_converted, fields_converted, fields_already_ok,
      fields_outside_repo, errors, backup}. --old-root가 없으면 종료 코드 2.
"""
import argparse
import datetime
import glob
import json
import os
import re
import shutil
import sys
import tempfile

CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPELINE_FIELDS = ("taxonomy_path", "input_root")
LIST_FIELDS = ("workspace", "input")
BACKUP_PREFIX = "_migrate_backup_"
LOG_NAME = "migrate.jsonl"
_DRIVE = re.compile(r"^[A-Za-z]:/")


def _slash(p):
    return p.replace("\\", "/")


def _root(p):
    p = _slash(p)
    return p if p == "/" else p.rstrip("/")


def classify(value, old_roots, new_root=None):
    """값 판정. 반환 (사유 코드, 접미사). 사유 코드: CONVERT | ALREADY_OK | OUTSIDE_REPO."""
    v = _slash(value)
    low = v.lower()
    for r in old_roots:
        rl = r.lower()
        if low == rl:
            return "CONVERT", ""
        if low.startswith(rl if rl.endswith("/") else rl + "/"):
            return "CONVERT", v[len(r) if r.endswith("/") else len(r) + 1:]
    if new_root and (low == new_root.lower() or low.startswith(new_root.lower().rstrip("/") + "/")):
        return "ALREADY_OK", None
    if not _DRIVE.match(v) and not v.startswith("/"):
        return "ALREADY_OK", None
    return "OUTSIDE_REPO", None


def _target(suffix, base_dir, repo_root, new_root):
    if new_root:
        return new_root.rstrip("/") + ("/" + suffix if suffix else "")
    full = os.path.join(repo_root, *suffix.split("/")) if suffix else repo_root
    return _slash(os.path.relpath(full, base_dir))


def _read(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("NOT_OBJECT")
    return data


def _write_atomic(path, data):
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".", suffix=".tmp.json",
                               dir=os.path.dirname(os.path.abspath(path)))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _backup_dir(repo_root):
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    base = os.path.join(repo_root, "workspaces", BACKUP_PREFIX + stamp)
    path, n = base, 1
    while os.path.exists(path):
        path, n = "%s-%d" % (base, n), n + 1
    return path


def _targets(repo_root, include_list):
    """(종류, 파일 경로) 목록. 백업 폴더(_migrate_backup_*)는 한 단계 더 깊어서 glob에 걸리지 않는다."""
    out = [("pipeline", p) for p in sorted(glob.glob(os.path.join(repo_root, "workspaces", "*", "pipeline.json")))]
    if include_list:
        out += [("ingested_list", p) for p in sorted(glob.glob(os.path.join(repo_root, "injested-file-list", "*.json")))]
    return out


def _plan_file(kind, path, data, old_roots, repo_root, new_root):
    """바꿀 값 {필드: 새 값}과 필드별 사유 [(필드, 사유)]."""
    changes, reasons = {}, []
    if kind == "pipeline":
        ws_dir = os.path.dirname(os.path.abspath(path))
        for key in PIPELINE_FIELDS:
            v = data.get(key)
            if not isinstance(v, str) or not v:
                continue
            code, suffix = classify(v, old_roots, new_root)
            if code == "CONVERT":
                changes[key] = _target(suffix, ws_dir, repo_root, new_root)
                code = "CONVERTED"
            reasons.append((key, code))
        return changes, reasons
    # injested-file-list: workspace는 저장소 루트 기준, input은 그 작업 폴더 기준
    ws_dir = os.path.join(repo_root, "workspaces", os.path.splitext(os.path.basename(path))[0])
    v = data.get("workspace")
    if isinstance(v, str) and v:
        code, suffix = classify(v, old_roots, new_root)
        if code == "CONVERT":
            changes["workspace"] = _target(suffix, repo_root, repo_root, new_root)
            ws_dir = os.path.join(repo_root, *suffix.split("/")) if suffix else repo_root
            code = "CONVERTED"
        elif code == "ALREADY_OK":
            ws_dir = os.path.join(repo_root, *_slash(v).split("/"))
        reasons.append(("workspace", code))
    v = data.get("input")
    if isinstance(v, str) and v:
        code, suffix = classify(v, old_roots, new_root)
        if code == "CONVERT":
            changes["input"] = _target(suffix, ws_dir, repo_root, new_root)
            code = "CONVERTED"
        reasons.append(("input", code))
    return changes, reasons


def migrate(old_roots, repo_root, new_root=None, include_list=False, apply=False):
    repo_root = os.path.abspath(repo_root)
    old_roots = [_root(r) for r in old_roots]
    new_root = _root(new_root) if new_root else None
    res = {"files_scanned": 0, "files_converted": 0, "fields_converted": 0, "fields_already_ok": 0,
           "fields_outside_repo": 0, "errors": 0, "backup": None}
    log, todo = [], []
    for idx, (kind, path) in enumerate(_targets(repo_root, include_list)):
        res["files_scanned"] += 1
        try:
            data = _read(path)
        except (OSError, ValueError):
            res["errors"] += 1
            log.append({"kind": kind, "index": idx, "reason": "CONFIG_UNREADABLE"})
            continue
        changes, reasons = _plan_file(kind, path, data, old_roots, repo_root, new_root)
        for key, code in reasons:
            res[{"CONVERTED": "fields_converted", "ALREADY_OK": "fields_already_ok",
                 "OUTSIDE_REPO": "fields_outside_repo"}[code]] += 1
            log.append({"kind": kind, "index": idx, "field": key, "reason": code})
        if changes:
            res["files_converted"] += 1
            data.update(changes)
            todo.append((kind, idx, path, data))
    if not apply or not todo:
        return res
    bdir = _backup_dir(repo_root)
    res["backup"] = _slash(os.path.relpath(bdir, repo_root))
    for kind, idx, path, data in todo:
        dst = os.path.join(bdir, os.path.relpath(path, repo_root))
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(path, dst)
            _write_atomic(path, data)
        except OSError:
            res["errors"] += 1
            res["files_converted"] -= 1
            log.append({"kind": kind, "index": idx, "reason": "WRITE_FAILED"})
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    with open(os.path.join(bdir, LOG_NAME), "a", encoding="utf-8", newline="\n") as f:
        for rec in log:
            f.write(json.dumps(dict(ts=ts, **rec), ensure_ascii=False) + "\n")
    return res


def restore(backup_dir, repo_root):
    """백업 폴더의 *.json을 저장소의 같은 상대 위치로 원자적으로 되돌린다."""
    repo_root = os.path.abspath(repo_root)
    bdir = backup_dir if os.path.isabs(backup_dir) else os.path.join(repo_root, backup_dir)
    res = {"restored": 0, "errors": 0, "backup": _slash(os.path.relpath(os.path.abspath(bdir), repo_root))}
    if not os.path.isdir(bdir):
        res["errors"] = 1
        res["reason"] = "BACKUP_NOT_FOUND"
        return res
    for cur, _dirs, files in os.walk(bdir):
        for fn in sorted(files):
            if not fn.endswith(".json"):
                continue
            src = os.path.join(cur, fn)
            dst = os.path.join(repo_root, os.path.relpath(src, bdir))
            try:
                _write_atomic(dst, _read(src))
                res["restored"] += 1
            except (OSError, ValueError):
                res["errors"] += 1
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description="pipeline.json 옛 절대경로를 현재 저장소 기준으로 변환")
    ap.add_argument("--old-root", action="append", default=[], help="옛 저장소 루트(반복 가능, Windows·POSIX)")
    ap.add_argument("--mode", choices=["relative"], default="relative")
    ap.add_argument("--new-root", help="상대경로 대신 이 루트 아래 절대경로로 쓴다")
    ap.add_argument("--include-ingested-list", action="store_true")
    ap.add_argument("--apply", action="store_true", help="없으면 dry-run")
    ap.add_argument("--restore", metavar="BACKUP_DIR")
    ap.add_argument("--root", default=CODE_ROOT, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.restore:
        res = restore(a.restore, a.root)
        print(json.dumps(res, ensure_ascii=False))
        return 1 if res["errors"] else 0
    if not a.old_root:
        ap.error("--old-root is required")
    res = migrate(a.old_root, a.root, a.new_root, a.include_ingested_list, a.apply)
    print(json.dumps(res, ensure_ascii=False))
    return 1 if res["errors"] else 0


if __name__ == "__main__":
    if CODE_ROOT not in sys.path:
        sys.path.insert(0, CODE_ROOT)
    try:  # 마일스톤 M19 IMPORT(stderr 줄). labelbot.trace를 못 읽는 python이면 그대로 돈다
        from labelbot import trace
    except (ImportError, SyntaxError):
        sys.exit(main())
    sys.exit(trace.run_main("M19", main))
