"""glob 매칭 구현은 scan.match 하나다. 정책과 검사가 실제로 쓰는 패턴의 결과를 고정한다.

옛 구현(fnmatch)에서는 '*'가 '/'를 넘었다. 쓰는 패턴이 모두 '접두/**' 꼴이거나 '/' 없는 리터럴이라
두 구현의 결과가 같음을 fnmatchcase와 대조해 확인한다.
"""
import fnmatch
import unittest

from codebot import model, scan

# 정책 test_globs(c1)와 c2의 건너뛰기 목록에서 오는 접두 패턴
_PREFIX = {
    "tests/**": {
        "tests/test_slides.py": True,
        "tests/contracts/test_contract_cli.py": True,
        "engrbot/tests/test_judge.py": False,
        "codebot/tests/test_c1.py": False,
        "labelbot/tests.py": False,
        "mytests/a.py": False,
    },
    "engrbot/tests/**": {
        "engrbot/tests/test_judge.py": True,
        "engrbot/tests/sub/test_x.py": True,
        "engrbot/cli.py": False,
        "tests/test_slides.py": False,
    },
    "codebot/tests/**": {
        "codebot/tests/test_c1.py": True,
        "codebot/tests/sub/x.py": True,
        "codebot/scan.py": False,
        "engrbot/tests/test_judge.py": False,
    },
    "codebot/out/**": {
        "codebot/out/CR-1/findings.jsonl": True,
        "codebot/out/a.py": True,
        "codebot/scan.py": False,
        "codebot/outer/a.py": False,
    },
    "**/__pycache__/**": {
        "labelbot/__pycache__/x.pyc": True,
        "a/b/__pycache__/c/d.py": True,
        "__pycache__/x.py": True,
        "labelbot/x.py": False,
    },
}
# 정책 path 리터럴(allow, ingest_modules, transport_modules, cli_modules, contract)
_LITERAL = {
    "labelbot/llm.py": {"labelbot/llm.py": True, "labelbot/llm_x.py": False, "labelbot/llmXpy": False},
    "labelbot/ingest.py": {"labelbot/ingest.py": True, "engrbot/ingest.py": False},
    "labelbot/selfcheck.py": {"labelbot/selfcheck.py": True, "labelbot/selfcheck.pyc": False},
    "engrbot/tests/test_judge.py": {"engrbot/tests/test_judge.py": True, "engrbot/tests/test_judge2.py": False},
    "engrbot/adapters/labelbot_ws.py": {"engrbot/adapters/labelbot_ws.py": True},
    "README.md": {"README.md": True, "docs/README.md": False, "README.mdx": False},
}
# index.glob이 쓰던 패턴(원래부터 scan.match였다). 한 단계 폴더만 허용하는 '*'
_DOC = {
    ".claude/skills/*/SKILL.md": {
        ".claude/skills/labeling-codebot/SKILL.md": True,
        ".claude/skills/a/b/SKILL.md": False,
        ".claude/skills/SKILL.md": False,
    },
}


class GlobPinTest(unittest.TestCase):
    def _check(self, table):
        for pat, cases in table.items():
            for path, want in cases.items():
                self.assertEqual(scan.match(path, pat), want, (pat, path))

    def test_prefix_patterns(self):
        self._check(_PREFIX)

    def test_literals(self):
        self._check(_LITERAL)

    def test_single_star_stops_at_slash(self):
        self._check(_DOC)

    def test_same_as_fnmatchcase_for_prefix_and_literal_patterns(self):
        """옛 fnmatch 대상이던 패턴은 fnmatchcase와 같은 결과를 낸다('**/' 접두 패턴 제외)."""
        for table in (_PREFIX, _LITERAL):
            for pat, cases in table.items():
                if pat.startswith("**/"):
                    continue
                for path in cases:
                    self.assertEqual(scan.match(path, pat), fnmatch.fnmatchcase(path, pat), (pat, path))

    def test_match_any(self):
        self.assertTrue(scan.match_any("tests/a.py", ["x/**", "tests/**"]))
        self.assertFalse(scan.match_any("src/a.py", ["x/**", "tests/**"]))
        self.assertFalse(scan.match_any("tests/a.py", []))

    def test_policy_globs_are_all_pinned(self):
        """정책의 glob이 늘어나면 이 표에 결과를 고정하도록 실패시킨다."""
        pol = model.default_policy()
        used = set(pol["c1"]["test_globs"]) | set(pol["exclude"])
        used |= set(pol["c3"]["doc_globs"]) | set(pol["c2"]["transport_modules"])
        pinned = set(_PREFIX) | set(_LITERAL) | set(_DOC)
        self.assertEqual(sorted(used - pinned), [])


if __name__ == "__main__":
    unittest.main()
