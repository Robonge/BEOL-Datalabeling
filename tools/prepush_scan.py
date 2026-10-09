#!/usr/bin/env python3
"""공개 저장소 push 전 검사(G-PUB, 마일스톤 M25 RELEASE_TOOLS, 로컬 전용).

추적 파일(git ls-files, 작업 트리 내용) 또는 --paths 파일에서 비밀·사내 정보 패턴을 찾는다.
--range A..B를 주면 그 범위 커밋들이 더한 줄도 검사한다(뒤 커밋에서 지운 비밀도 push되므로).

패턴 ID: KEY_SK·KEY_JWT·KEY_AWS·KEY_GHP(code_engrbot C2 _SECRET_RES 재사용), KEY_PEM, IP_PRIVATE(10/8·172.16/12·
192.168/16, loopback 제외), ENV_HOST_SUFFIXES(BEOL_ALLOWED_HOST_SUFFIXES=<실값>), UNC_PATH, DENYLIST(비추적
workspaces/_site/scan_denylist.json의 호스트·도메인·경로 — 없으면 이 규칙만 건너뜀).
CSS 선택자·변수(.sk-… / --sk-…)는 키로 보지 않는다.

출력은 path:line:pattern_id만이다. 맞은 값은 절대 출력하지 않는다.
허용 목록 transfer/prepush_allow.json [{path, pattern_id, line_sha256}] — 줄 내용이 바뀌면 다시 검토해야 한다.

사용: python tools/prepush_scan.py [--all-tracked] [--range origin/LLM-added..HEAD] [--paths F ...]
      [--denylist PATH] [--allow PATH] [--suggest-allow]
종료 코드: 0 통과, 1 허용 목록 밖 검출.
"""
import argparse
import hashlib
import ipaddress
import json
import os
import re
import subprocess
import sys

CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if CODE_ROOT not in sys.path:
    sys.path.insert(0, CODE_ROOT)
from code_engrbot.checks.c2_stack import _SECRET_RES  # noqa: E402  C2와 같은 키 정규식을 쓴다

MILESTONE = "M25 RELEASE_TOOLS"
DEFAULT_ALLOW = os.path.join(CODE_ROOT, "transfer", "prepush_allow.json")
DEFAULT_DENYLIST = os.path.join(CODE_ROOT, "workspaces", "_site", "scan_denylist.json")
BINARY_EXT = (".pptx", ".docx", ".xlsx", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".mp4", ".mov",
              ".webm", ".woff", ".woff2", ".ttf", ".otf", ".zip", ".sqlite", ".b64")
_KEY_IDS = (("sk-", "KEY_SK"), ("eyJ", "KEY_JWT"), ("AKIA", "KEY_AWS"), ("ghp_", "KEY_GHP"))
KEY_RES = [(next((pid for mark, pid in _KEY_IDS if mark in rx.pattern), "KEY_OTHER"), rx) for rx in _SECRET_RES]
PEM_RE = re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")
IPV4_RE = re.compile(r"(?<![\d.])(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?!\.?\d)")
# 아래 두 정규식은 이 파일 자신이 걸리지 않게 조각을 이어 붙여 만든다
SUFFIX_RE = re.compile("BEOL_ALLOWED_HOST_SUFFIXES" + r"=([^\s'\"`#;,)]*(?:,[^\s'\"`#;)]*)*)")
_BS = re.escape("\\")  # 정규식에서 백슬래시 하나
UNC_RES = (
    re.compile(r"(?<![\\:\w])" + _BS * 2 + r"[A-Za-z][\w.-]+" + _BS + r"[\w$.-]+"),      # UNC 경로(서버\공유)
    re.compile(r"(?<![\\:\w])" + _BS * 4 + r"[A-Za-z][\w.-]+" + _BS * 2 + r"[\w$.-]+"),  # 문자열 안 이스케이프 꼴
)
# 10/8, 172.16/12, 192.168/16 (점 네 개 리터럴은 이 검사 자신에 걸리므로 정수로 만든다)
PRIVATE_NETS = [ipaddress.IPv4Network(n) for n in ((10 << 24, 8), (172 << 24 | 16 << 16, 12), (192 << 24 | 168 << 16, 16))]
PLACEHOLDER_HINTS = ("example", ".test", ".invalid", "localhost")


def _placeholder_suffix(value):
    v = value.strip()
    if not v or v[0] in "<$%{[" or v.startswith(("...", "…")):
        return True
    items = [s.strip().lower() for s in v.split(",") if s.strip()]
    return all(any(h in s for h in PLACEHOLDER_HINTS) or s.startswith("<") for s in items)


def scan_line(line, deny):
    """한 줄에서 맞은 패턴 ID 목록(중복 없이, 순서 유지). 값은 돌려주지 않는다."""
    hits = []
    for pid, rx in KEY_RES:
        for m in rx.finditer(line):
            prev = line[m.start() - 1] if m.start() else ""
            if pid == "KEY_SK" and prev in ".-":  # CSS 선택자 .sk-bridge, 변수 --sk-…
                continue
            hits.append(pid)
            break
    if PEM_RE.search(line):
        hits.append("KEY_PEM")
    for m in IPV4_RE.finditer(line):
        octets = [int(g) for g in m.groups()]
        if all(o <= 255 for o in octets):
            ip = ipaddress.ip_address(".".join(str(o) for o in octets))
            if any(ip in net for net in PRIVATE_NETS):
                hits.append("IP_PRIVATE")
                break
    for m in SUFFIX_RE.finditer(line):
        if not _placeholder_suffix(m.group(1)):
            hits.append("ENV_HOST_SUFFIXES")
            break
    if any(rx.search(line) for rx in UNC_RES):
        hits.append("UNC_PATH")
    if deny:
        low = line.lower()
        if any(d in low for d in deny):
            hits.append("DENYLIST")
    seen = []
    for h in hits:
        if h not in seen:
            seen.append(h)
    return seen


def line_sha(line):
    return hashlib.sha256(line.rstrip("\r\n").encode("utf-8", "surrogateescape")).hexdigest()


def load_denylist(path):
    """None이면 파일 없음(규칙 건너뜀). 형식: {"hosts":[…], "domains":[…], "paths":[…]} 또는 문자열 목록."""
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    items = doc if isinstance(doc, list) else [v for key in ("hosts", "domains", "paths", "patterns")
                                               for v in (doc.get(key) or [])]
    return [str(s).strip().lower() for s in items if str(s).strip()]


def load_allow(path):
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _git(*args):
    return subprocess.run(["git", "-C", CODE_ROOT] + list(args), stdout=subprocess.PIPE, check=True).stdout


def tracked_files():
    return [p.decode("utf-8", "surrogateescape") for p in _git("ls-files", "-z").split(b"\0") if p]


def read_text(full):
    with open(full, "rb") as f:
        data = f.read()
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", "replace")


def scan_files(paths, deny, root=CODE_ROOT):
    """[(path, line_no, pattern_id, line_sha256)]"""
    out = []
    for rel in paths:
        if rel.lower().endswith(BINARY_EXT):
            continue
        full = rel if os.path.isabs(rel) else os.path.join(root, rel)
        if not os.path.isfile(full):
            continue
        text = read_text(full)
        if text is None:
            continue
        shown = rel.replace(os.sep, "/")
        for no, line in enumerate(text.splitlines(), 1):
            for pid in scan_line(line, deny):
                out.append((shown, no, pid, line_sha(line)))
    return out


def scan_range(rng, deny):
    """범위 커밋들이 더한 줄. 줄 번호는 그 커밋 기준, 경로 뒤에 @sha7."""
    raw = _git("log", "-p", "-U0", "--no-color", "--no-ext-diff", "--format=@@COMMIT %H", rng)
    out, commit, path, no = [], "", None, 0
    for bline in raw.split(b"\n"):
        line = bline.decode("utf-8", "replace")
        if line.startswith("@@COMMIT "):
            commit, path = line.split()[1][:7], None
        elif line.startswith("+++ "):
            target = line[4:]
            path = target[2:] if target.startswith("b/") else None
        elif line.startswith("@@ ") and path:
            m = re.search(r"\+(\d+)", line)
            no = int(m.group(1)) if m else 0
        elif line.startswith("+") and path and not line.startswith("+++"):
            if not path.lower().endswith(BINARY_EXT):
                for pid in scan_line(line[1:], deny):
                    out.append(("%s@%s" % (path, commit), no, pid, line_sha(line[1:])))
            no += 1
    return out


def main(argv=None):
    for _s in (sys.stdout, sys.stderr):  # Windows 콘솔(cp949)에서도 한글·기호 출력이 죽지 않게
        try:
            _s.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    ap = argparse.ArgumentParser(prog="prepush_scan", description="공개 저장소 push 전 비밀·사내 정보 검사(M25)")
    ap.add_argument("--all-tracked", action="store_true", help="추적 파일 전체(--paths·--range가 없으면 기본)")
    ap.add_argument("--range", help="push할 커밋 범위(예 origin/LLM-added..HEAD)의 추가 줄도 검사")
    ap.add_argument("--paths", nargs="+", help="이 파일들만 검사")
    ap.add_argument("--denylist", default=DEFAULT_DENYLIST, help="사내 호스트 목록(기본 workspaces/_site/scan_denylist.json)")
    ap.add_argument("--allow", default=DEFAULT_ALLOW, help="허용 목록(기본 transfer/prepush_allow.json)")
    ap.add_argument("--suggest-allow", action="store_true", help="허용 목록 밖 검출을 허용 목록 항목(JSON)으로 출력")
    args = ap.parse_args(argv)
    try:
        deny = load_denylist(args.denylist)
    except (OSError, ValueError):
        sys.stderr.write("[%s] 실패  사유=DENYLIST_INVALID\n  원인: scan_denylist.json을 읽을 수 없다\n"
                         "  조치: JSON 형식({\"hosts\": [...], \"domains\": [...], \"paths\": [...]})을 확인한다\n" % MILESTONE)
        return 1
    if deny is None:
        print("[알림] scan_denylist.json 없음 — 사내 호스트(DENYLIST) 검사는 건너뜀")
    hits = []
    if args.paths:
        hits += scan_files(args.paths, deny, root=os.getcwd())
    if args.all_tracked or not (args.paths or args.range):
        hits += scan_files(tracked_files(), deny)
    if args.range:
        hits += scan_range(args.range, deny)
    allow = set((a["path"], a["pattern_id"], a["line_sha256"]) for a in load_allow(args.allow))
    bad, used = [], set()
    for path, no, pid, sha in hits:
        key = (path.split("@")[0], pid, sha)
        if key in allow:
            used.add(key)
        else:
            bad.append((path, no, pid, sha))
    for path, no, pid, _sha in bad:
        print("%s:%d:%s" % (path, no, pid))
    if args.suggest_allow and bad:
        seen = []
        for path, _no, pid, sha in bad:
            item = {"path": path.split("@")[0], "pattern_id": pid, "line_sha256": sha}
            if item not in seen:
                seen.append(item)
        print(json.dumps(seen, ensure_ascii=False, indent=1))
    stale = len(allow - used)
    print("prepush_scan: hits=%d allowed=%d stale_allow=%d" % (len(bad), len(hits) - len(bad), stale))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
