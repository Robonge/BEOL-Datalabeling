"""CLI 표면 동결: python -m labelbot|engrbot|codebot의 --help와 모든 하위 명령(중첩 포함)의 -h.

하위 명령은 usage의 '{a,b} ...'(subparsers)에서 찾아 재귀한다. '{a,b}'만 있는 위치 인자 선택지는
하위 명령이 아니므로 그 명령의 -h에 선택지로만 남는다(engrbot ledger, labeling-rules).
"""
import re
import unittest
from concurrent.futures import ThreadPoolExecutor

from tests.contracts import _support

PACKAGES = ("labelbot", "engrbot", "codebot")
_SUBPARSERS = re.compile(r"\{([^{}]+)\} \.\.\.")
MAX_DEPTH = 4


def _usage(text):
    return text.split("\n\n", 1)[0]


def collect(pkg):
    """{명령 경로: help 출력}. 경로는 'labelbot', 'engrbot baseline set'처럼 공백으로 잇는다."""
    out, level = {}, [()]
    with ThreadPoolExecutor(max_workers=8) as pool:
        for _ in range(MAX_DEPTH):
            if not level:
                break
            results = list(pool.map(
                lambda path: (path, _support.run_help(["-m", pkg] + list(path) + ["--help" if not path else "-h"])),
                level))
            nxt = []
            for path, (rc, stdout, stderr) in results:
                key = " ".join((pkg,) + path)
                if rc != 0:
                    raise AssertionError("HELP_FAILED %s rc=%d %s" % (key, rc, stderr[-500:]))
                out[key] = stdout
                m = _SUBPARSERS.search(_usage(stdout))
                if m:
                    nxt.extend(path + (name.strip(),) for name in m.group(1).split(","))
            level = nxt
    return out


class CliSurfaceContract(unittest.TestCase):
    def test_labelbot_cli(self):
        _support.check(self, "cli_labelbot", collect("labelbot"))

    def test_engrbot_cli(self):
        _support.check(self, "cli_engrbot", collect("engrbot"))

    def test_codebot_cli(self):
        _support.check(self, "cli_codebot", collect("codebot"))


if __name__ == "__main__":
    unittest.main()
