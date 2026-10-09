#!/usr/bin/env python3
"""마일스톤 상태·사유 코드(M00 CLI, 읽기 전용). 배포판 python3(3.8+)용 — python -m labelbot status|codes와 같은 출력.

labelbot/cli.py는 3.8 안전이 아니므로 거치지 않고 3.8 안전 모듈(labelbot.status·milestones·reason_codes·trace)만 읽는다.

사용: python3 tools/beol_status.py status --workspace <작업 폴더> | --all-workspaces
      python3 tools/beol_status.py codes [--milestone Mxx] [--entrypoints]
      python3 tools/beol_status.py test-modules [--unittest] [--manifest PATH]
        폐쇄망 테스트 목록(transfer/import_manifest.json의 test_modules, UTF-8로 읽음)을 공백으로 이어 한 줄로 낸다.
        --unittest면 python -m unittest용 점 이름. 목록이 비었거나 manifest를 못 읽으면 아무것도 출력하지 않고
        실패 블록(사유=TEST_LIST_EMPTY)과 종료 코드 1 — 전체 테스트로 넘어가지 않게
        `T=$(python3 tools/beol_status.py test-modules) && python -m pytest -q $T`처럼 쓴다.
"""
import argparse
import json
import os
import sys

CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if CODE_ROOT not in sys.path:
    sys.path.insert(0, CODE_ROOT)

from labelbot import status, trace  # noqa: E402

MANIFEST = os.path.join(CODE_ROOT, "transfer", "import_manifest.json")


def test_modules(argv):
    ap = argparse.ArgumentParser(prog="beol_status test-modules", description="폐쇄망 테스트 목록(manifest test_modules)")
    ap.add_argument("--unittest", action="store_true", help="python -m unittest용 점 이름으로 낸다")
    ap.add_argument("--manifest", default=MANIFEST, help="기본 transfer/import_manifest.json")
    a = ap.parse_args(argv)
    try:
        with open(a.manifest, encoding="utf-8") as f:
            mods = json.load(f).get("test_modules")
    except (OSError, ValueError, AttributeError):
        mods = None
    mods = [m for m in (mods if isinstance(mods, list) else []) if isinstance(m, str) and m.endswith(".py")]
    if not mods:
        trace.fail_code("TEST_LIST_EMPTY")
        return 1
    print(" ".join(m[:-3].replace("/", ".") if a.unittest else m for m in mods))
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0] == "test-modules":
        return test_modules(argv[1:])
    return status.main(argv)


if __name__ == "__main__":
    sys.exit(trace.run_main("M00", main, quiet=True))
