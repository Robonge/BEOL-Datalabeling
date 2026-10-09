#!/usr/bin/env python3
"""사이트 설정 폴더(workspaces/_site/)를 예시(config/site.example/)에서 만든다(M00 ENV/CLI, 배포판 python3 3.8+).

- 없는 파일만 복사한다. 이미 있는 파일은 절대 덮어쓰지 않는다(여러 번 실행해도 같다).
- 값이 들어갈 파일(beol.env, profile.json, doctor_targets.json, scan_denylist.json)은 chmod 600.
- workspaces/는 git에 올라가지 않는다. 실제 호스트·키 값은 만든 사본에만 적는다(예시는 placeholder만).
- 표준 라이브러리만, Python 3.8 문법. 출력은 파일 이름·상태만(값은 읽지도 출력하지도 않는다).

사용: python3 tools/site_init.py [--site workspaces/_site]
출력: 파일별 한 줄(만듦/있음) + 다음 할 일, 마지막 줄 JSON {site, created, kept}. 예시가 없으면 사유=SITE_TEMPLATE_MISSING, 종료 코드 1.
"""
import argparse
import json
import os
import shutil
import sys

CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIR = os.path.join("config", "site.example")
# (예시 이름, 사본 이름, 비밀값이 들어갈 수 있어 chmod 600)
FILES = (
    ("beol.env.example", "beol.env", True),
    ("profile.example.json", "profile.json", True),
    ("doctor_targets.example.json", "doctor_targets.json", True),
    ("scan_denylist.example.json", "scan_denylist.json", True),
    ("crontab.example", "crontab.example", False),
)
NEXT_STEPS = (
    "1) workspaces/_site/doctor_targets.json의 host를 실제 사내 호스트로 고친다 → python3 tools/beol_doctor.py",
    "2) workspaces/_site/beol.env를 편집기로 채우고 셸 rc에 넣는다: "
    "echo 'set -a; . <릴리스 폴더>/workspaces/_site/beol.env; set +a' >> ~/.bashrc",
    "3) bash tools/cloud_setup.sh --dry-run 으로 단계 목록을 본 뒤 bash tools/cloud_setup.sh",
    "4) crontab -e 에 workspaces/_site/crontab.example 내용을 붙이고 B=를 이 릴리스 폴더로 바꾼다",
)


def _fail(code, root):
    try:
        if root not in sys.path:
            sys.path.insert(0, root)
        from labelbot import trace
        trace.fail_code(code)
        if trace.current() is None:
            trace.fail_block("M00", code)
    except (ImportError, SyntaxError):
        sys.stderr.write("[M00 ENV/CLI] 실패  사유=%s\n" % code)


def init_site(root, site):
    """반환: (created 목록, kept 목록) 또는 예시가 없으면 None."""
    tdir = os.path.join(root, TEMPLATE_DIR)
    if not all(os.path.isfile(os.path.join(tdir, src)) for src, _, _ in FILES):
        return None
    os.makedirs(site, exist_ok=True)
    created, kept = [], []
    for src, dst, secret in FILES:
        path = os.path.join(site, dst)
        if os.path.lexists(path):
            kept.append(dst)
            continue
        shutil.copyfile(os.path.join(tdir, src), path)
        if secret:
            os.chmod(path, 0o600)
        created.append(dst)
    return created, kept


def main(argv=None):
    ap = argparse.ArgumentParser(prog="site_init", description="workspaces/_site/를 config/site.example/에서 만든다(M00)")
    ap.add_argument("--site", help="사이트 폴더(기본 <저장소>/workspaces/_site)")
    ap.add_argument("--root", default=CODE_ROOT, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    root = os.path.abspath(a.root)
    site = os.path.abspath(a.site) if a.site else os.path.join(root, "workspaces", "_site")
    res = init_site(root, site)
    if res is None:
        _fail("SITE_TEMPLATE_MISSING", root)
        return 1
    created, kept = res
    for name in created:
        print("[site_init] 만듦  %s" % name)
    for name in kept:
        print("[site_init] 있음(그대로 둠)  %s" % name)
    print("다음 할 일:")
    for line in NEXT_STEPS:
        print("  " + line)
    try:
        shown = os.path.relpath(site, root).replace(os.sep, "/")
    except ValueError:
        shown = ".."
    if shown.startswith(".."):
        shown = site.replace(os.sep, "/")
    print(json.dumps({"site": shown, "created": created, "kept": kept}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    if CODE_ROOT not in sys.path:
        sys.path.insert(0, CODE_ROOT)
    try:  # 마일스톤 M00(stderr 줄). labelbot.trace를 못 읽는 python이면 그대로 돈다
        from labelbot import trace
    except (ImportError, SyntaxError):
        sys.exit(main())
    sys.exit(trace.run_main("M00", main))
