#!/usr/bin/env python3
"""마일스톤 상태·사유 코드(M00 CLI, 읽기 전용). 배포판 python3(3.8+)용 — python -m labelbot status|codes와 같은 출력.

labelbot/cli.py는 3.8 안전이 아니므로 거치지 않고 3.8 안전 모듈(labelbot.status·milestones·reason_codes·trace)만 읽는다.

사용: python3 tools/beol_status.py status --workspace <작업 폴더> | --all-workspaces
      python3 tools/beol_status.py codes [--milestone Mxx] [--entrypoints]
"""
import os
import sys

CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if CODE_ROOT not in sys.path:
    sys.path.insert(0, CODE_ROOT)

from labelbot import status, trace  # noqa: E402


def main(argv=None):
    return status.main(argv)


if __name__ == "__main__":
    sys.exit(trace.run_main("M00", main, quiet=True))
