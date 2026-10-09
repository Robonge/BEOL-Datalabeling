#!/usr/bin/env python3
"""반입 manifest(transfer/import_manifest.json)를 git blob 기준으로 만든다(마일스톤 M25 RELEASE_TOOLS, 로컬 전용).

GitHub 브랜치 ZIP에는 .git이 없고 파일 내용은 blob(LF) 그대로다. 그래서 작업 트리가 아니라
`git ls-tree -r <rev>` + `git cat-file --batch`로 blob을 읽어 sha256·크기를 싣는다.

- class: state(이어받는 상태, 우선) > office(.pptx .docx .xlsx .csv .pdf) > media > code > text-other
- state_paths: 업그레이드(carry_state.py)가 이어받는 목록. tracked=True는 3방향 비교, False는 폐쇄망 사본 복사
- test_modules: 폐쇄망 테스트 목록. tests._dummy를 직접·간접 import하는 모듈은 import 그래프로 빼낸다.
  모듈 맨 위에 `CLOSED_NETWORK_EXCLUDE = "<이유>"`가 있는 테스트 모듈(예: git 체크아웃이 필요한 테스트)도 뺀다.
  뺀 모듈과 이유는 test_modules_excluded[{path, excluded_reason}]에 싣는다(DUMMY_IMPORT 또는 그 이유 문장)
- 상태 동결: --base-manifest를 주면 state blob이 바뀌었는데 --override path=reason이 없을 때 STATE_FROZEN으로 실패

사용: python tools/make_import_manifest.py --label beol-import-YYYYMMDD-<sha7> [--rev HEAD] [--out PATH]
      [--base-manifest PATH] [--override path=reason ...]
종료 코드: 0 성공, 1 실패(STATE_FROZEN·LABEL_*·GIT_*), 2 인자 오류.
"""
import argparse
import ast
import datetime
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys

MILESTONE = "M25 RELEASE_TOOLS"
CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST_REL = "transfer/import_manifest.json"
DOWNLOAD_LIST_REL = "transfer/download_list.json"

STATE_PATHS = [
    {"glob": "taxonomy/taxonomy.json", "tracked": True},
    {"glob": "taxonomy/labeling_rules.json", "tracked": True},
    {"glob": "taxonomy/taxonomy_revisit_requests/*", "tracked": True},
    {"glob": "injested-file-list/*.json", "tracked": True},
    {"glob": "docs/project_intro.html", "tracked": True},
    {"glob": "docs/user_flow.html", "tracked": True},
    {"glob": "docs/workflow.html", "tracked": True},
    {"glob": "rag/beol_rag.html", "tracked": True},
    {"glob": "taxonomy/taxonomy_history.jsonl", "tracked": False},
    {"glob": "workspaces/", "tracked": False},
    {"glob": "workspaces/_site/", "tracked": False},
    {"glob": "docs/snapshots/*", "tracked": False},
]
OFFICE_EXT = (".pptx", ".docx", ".xlsx", ".csv", ".pdf")
MEDIA_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".svg", ".mp4", ".mov", ".webm",
             ".mp3", ".wav", ".woff", ".woff2", ".ttf", ".otf")
CODE_EXT = (".py", ".js", ".mjs", ".ts", ".html", ".htm", ".css", ".json", ".jsonl", ".md", ".sh", ".toml",
            ".ini", ".cfg", ".yml", ".yaml", ".sql", ".gitignore", ".gitattributes", ".example")
TEST_RE = re.compile(r"^(tests|domain_engrbot/tests|code_engrbot/tests)/(.+/)?test_[^/]*\.py$")
DUMMY_MODULE = "tests._dummy"
LABEL_RE = re.compile(r"^beol-import-[a-z0-9][a-z0-9-]*$")
DATED_LABEL_RE = re.compile(r"^beol-import-\d{8}-([0-9a-f]{7})$")


class ToolError(Exception):
    def __init__(self, code, cause, action):
        Exception.__init__(self, code)
        self.code, self.cause, self.action = code, cause, action


def fail_block(code, cause, action):
    """L3c labelbot.trace가 있으면 그 출력기를, 없으면 같은 형식의 내장 출력기를 쓴다(stderr)."""
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
    """'dir/'는 그 폴더 아래 전부, 그 밖은 경로 조각별 fnmatch('*'가 '/'를 넘지 않는다)."""
    if pattern.endswith("/"):
        return path.startswith(pattern)
    pp, sp = pattern.split("/"), path.split("/")
    return len(pp) == len(sp) and all(fnmatch.fnmatchcase(s, p) for p, s in zip(pp, sp))


def classify(path):
    if any(e["tracked"] and glob_match(e["glob"], path) for e in STATE_PATHS):
        return "state"
    low = path.lower()
    base = low.rsplit("/", 1)[-1]
    ext = os.path.splitext(base)[1] or (base if base.startswith(".") else "")
    if ext in OFFICE_EXT:
        return "office"
    if ext in MEDIA_EXT:
        return "media"
    if ext in CODE_EXT:
        return "code"
    return "text-other"


def _git(root, *args):
    try:
        p = subprocess.run(["git", "-C", root] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError:
        raise ToolError("GIT_NOT_FOUND", "git 실행 파일을 찾지 못했다", "git을 설치하거나 PATH를 확인한다")
    if p.returncode != 0:
        raise ToolError("GIT_FAILED", "git %s 실패(rc=%d)" % (args[0], p.returncode),
                        "저장소 루트·--rev 값을 확인한다")
    return p.stdout


def read_blobs(root, rev):
    """{path: bytes} — rev 트리의 모든 blob. 경로는 -z로 받아 한글 이름도 그대로다."""
    entries = []
    for rec in _git(root, "ls-tree", "-r", "-z", "--full-tree", rev).split(b"\0"):
        if not rec:
            continue
        meta, path = rec.split(b"\t", 1)
        _mode, kind, sha = meta.split(b" ")
        if kind == b"blob":
            entries.append((path.decode("utf-8", "surrogateescape"), sha.decode("ascii")))
    proc = subprocess.Popen(["git", "-C", root, "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    out = {}
    try:
        for path, sha in entries:
            proc.stdin.write(sha.encode("ascii") + b"\n")
            proc.stdin.flush()
            header = proc.stdout.readline().split()
            if len(header) != 3 or header[1] != b"blob":
                raise ToolError("GIT_FAILED", "git cat-file 응답이 blob이 아니다", "저장소 상태를 확인한다")
            size = int(header[2])
            data = proc.stdout.read(size)
            proc.stdout.read(1)
            out[path] = data
    finally:
        proc.stdin.close()
        proc.wait()
    return out


def module_name(path):
    if not path.endswith(".py"):
        return None
    mod = path[:-3].replace("/", ".")
    return mod[:-len(".__init__")] if mod.endswith(".__init__") else mod


def _imports(mod, is_pkg, src, known):
    """mod가 import하는 저장소 모듈 이름 집합(부모 패키지 포함, 함수 안 import도 포함)."""
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return set()
    found = set()

    def add(name):
        parts = name.split(".")
        for i in range(1, len(parts) + 1):
            cand = ".".join(parts[:i])
            if cand in known:
                found.add(cand)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                pkg = mod.split(".") if is_pkg else mod.split(".")[:-1]
                pkg = pkg[:len(pkg) - (node.level - 1)] if node.level > 1 else pkg
                base = ".".join(pkg + ([node.module] if node.module else []))
            else:
                base = node.module or ""
            if base:
                add(base)
            for a in node.names:
                add((base + "." if base else "") + a.name)
    found.discard(mod)
    return found


MARKER = "CLOSED_NETWORK_EXCLUDE"
DUMMY_REASON = "DUMMY_IMPORT"


def marker_reason(src):
    """모듈 최상위 `CLOSED_NETWORK_EXCLUDE = "<이유>"`의 이유 문장. 없으면 None."""
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        named = any(isinstance(t, ast.Name) and t.id == MARKER for t in node.targets)
        val = node.value.value if isinstance(node.value, ast.Constant) else None
        if named and isinstance(val, str) and val.strip():
            return val.strip()
    return None


def excluded_reasons(blobs, excluded):
    """[{path, excluded_reason}] — 표시가 있으면 그 이유, 아니면 DUMMY_IMPORT."""
    return [{"path": p, "excluded_reason": marker_reason(blobs[p]) or DUMMY_REASON} for p in excluded]


def compute_test_modules(blobs):
    mods = {}
    for path, data in blobs.items():
        name = module_name(path)
        if name:
            mods[name] = path
    known = set(mods)
    graph = {}
    for name, path in mods.items():
        graph[name] = _imports(name, path.endswith("/__init__.py"), blobs[path], known)
    tests, excluded = [], []
    for name, path in sorted(mods.items(), key=lambda kv: kv[1]):
        if not TEST_RE.match(path):
            continue
        seen, stack = set(), [name]
        while stack:
            cur = stack.pop()
            for dep in graph.get(cur, ()):
                if dep not in seen:
                    seen.add(dep)
                    stack.append(dep)
        (excluded if DUMMY_MODULE in seen or marker_reason(blobs[path]) else tests).append(path)
    return tests, excluded


def check_label(label, commit):
    if not LABEL_RE.match(label):
        raise ToolError("LABEL_INVALID", "release_label 형식이 아니다(beol-import-YYYYMMDD-<sha7>)",
                        "--label beol-import-<YYYYMMDD>-<커밋 sha 앞 7자>로 다시 실행")
    m = DATED_LABEL_RE.match(label)
    if m and m.group(1) != commit[:7]:
        raise ToolError("LABEL_SHA_MISMATCH", "label의 sha7이 --rev 커밋과 다르다",
                        "--label의 sha7을 %s로 맞춘다" % commit[:7])


def parse_overrides(items):
    out = []
    for item in items or []:
        path, sep, reason = item.partition("=")
        if not sep or not path.strip() or not reason.strip():
            raise ToolError("OVERRIDE_INVALID", "--override는 path=reason 형식이어야 한다", "예: --override rag/beol_rag.html=B6 ragsrv 연결")
        out.append({"path": path.strip(), "reason": reason.strip()})
    return out


def check_state_freeze(files, base_path, overrides):
    try:
        with open(base_path, encoding="utf-8") as f:
            base = json.load(f)
    except (OSError, ValueError):
        raise ToolError("BASE_MANIFEST_INVALID", "--base-manifest를 읽을 수 없다", "직전 릴리스의 transfer/import_manifest.json 경로를 확인한다")
    old = dict((f["path"], f["sha256"]) for f in base.get("files", []) if f.get("class") == "state")
    new = dict((f["path"], f["sha256"]) for f in files if f["class"] == "state")
    allowed = set(o["path"] for o in overrides)
    changed = sorted(p for p in set(old) | set(new) if old.get(p) != new.get(p))
    frozen = [p for p in changed if p not in allowed]
    if frozen:
        for p in frozen:
            sys.stderr.write("  state 변경: %s\n" % p)
        raise ToolError("STATE_FROZEN", "직전 릴리스 이후 state 파일 %d개가 override 없이 바뀌었다" % len(frozen),
                        "되돌리거나 --override <path>=<이유>로 바꾼 이유를 manifest에 싣는다")
    return changed


def build_manifest(root, rev, label, overrides, base_manifest=None):
    commit = _git(root, "rev-parse", "--verify", rev + "^{commit}").decode("ascii").strip()
    check_label(label, commit)
    blobs = read_blobs(root, commit)
    files = []
    for path in sorted(blobs):
        if path == MANIFEST_REL:
            continue
        data = blobs[path]
        files.append({"path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "class": classify(path)})
    state_files = set(f["path"] for f in files if f["class"] == "state")
    for o in overrides:
        if o["path"] not in state_files and not any(glob_match(e["glob"], o["path"]) for e in STATE_PATHS):
            raise ToolError("OVERRIDE_NOT_STATE", "--override 경로가 state 목록에 없다", "state_paths의 경로만 override한다")
    if base_manifest:
        check_state_freeze(files, base_manifest, overrides)
    tests, excluded = compute_test_modules(blobs)
    dl = blobs.get(DOWNLOAD_LIST_REL)
    manifest = {
        "release_label": label,
        "source_commit": commit,
        "created_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "files": files,
        "state_paths": STATE_PATHS,
        "state_overrides": overrides,
        "test_modules": tests,
        "test_modules_excluded": excluded_reasons(blobs, excluded),
        "download_list_sha256": hashlib.sha256(dl).hexdigest() if dl is not None else None,
    }
    return manifest, excluded


def write_json(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
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
    ap = argparse.ArgumentParser(prog="make_import_manifest", description="git blob 기준 반입 manifest 생성(M25)")
    ap.add_argument("--label", required=True, help="release_label (beol-import-YYYYMMDD-<sha7>)")
    ap.add_argument("--rev", default="HEAD", help="manifest를 만들 커밋(기본 HEAD)")
    ap.add_argument("--root", default=CODE_ROOT, help="git 저장소 루트(기본 이 저장소)")
    ap.add_argument("--out", help="출력 경로(기본 <root>/transfer/import_manifest.json)")
    ap.add_argument("--base-manifest", help="직전 릴리스 manifest(상태 동결 검사)")
    ap.add_argument("--override", action="append", metavar="PATH=REASON", help="바꾼 state 파일과 이유(반복)")
    args = ap.parse_args(argv)
    out = args.out or os.path.join(args.root, *MANIFEST_REL.split("/"))
    sys.stderr.write("[%s] 시작 label=%s\n" % (MILESTONE, args.label))
    try:
        overrides = parse_overrides(args.override)
        manifest, excluded = build_manifest(args.root, args.rev, args.label, overrides, args.base_manifest)
        write_json(out, manifest)
    except ToolError as e:
        fail_block(e.code, e.cause, e.action)
        return 1
    counts = {}
    for f in manifest["files"]:
        counts[f["class"]] = counts.get(f["class"], 0) + 1
    print("manifest: %s" % out)
    print("commit=%s files=%d %s" % (manifest["source_commit"][:7], len(manifest["files"]),
                                     " ".join("%s=%d" % kv for kv in sorted(counts.items()))))
    rows = manifest["test_modules_excluded"]
    n_dummy = len([r for r in rows if r["excluded_reason"] == DUMMY_REASON])
    print("test_modules=%d excluded_dummy=%d excluded_marked=%d" % (len(manifest["test_modules"]), n_dummy,
                                                                   len(rows) - n_dummy))
    sys.stdout.flush()
    sys.stderr.write("[%s] 완료 n=%d\n" % (MILESTONE, len(manifest["files"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
