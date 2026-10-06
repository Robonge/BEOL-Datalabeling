"""C3 규칙 테스트: 예시 소스는 문자열로 둔다."""
import unittest

from code_engrbot.checks.c3_workflow import WorkflowCheck
from code_engrbot.model import Ctx
from code_engrbot.scan import RepoIndex, SourceFile

LB_CLI = '''
def _parser():
    def add(name, help_text):
        return sub.add_parser(name, help=help_text)
    sc = add("selfcheck", "환경 점검")
    for name, h in (("ingest", "수집"), ("run", "전체")):
        add(name, h)
'''
QA_CLI = '''
r = sub.add_parser("run", help="x")
b = sub.add_parser("baseline", help="y")
'''
DOC = "설명\n`python -m labelbot ingest --workspace W`\n`python -m labelbot bogus`\n`python -m domain_engrbot run`\n`python -m unittest discover`\n"

STORE = '''
TABLES = {
    "runs": "run_id TEXT PRIMARY KEY, command TEXT",
    "files": (
        "file_id TEXT PRIMARY KEY, file_name TEXT NOT NULL CHECK(file_name <> '', file_id), "
        "UNIQUE(file_id, file_name)"
    ),
}
'''
REQ_OK = 'REQUIRED = {\n    "runs": ("run_id", "command"),\n    "files": ("file_id", "file_name"),\n}\n'
REQ_BAD = 'REQUIRED = {\n    "runs": ("run_id", "command", "extra_col"),\n    "files": ("file_id", "file_name"),\n}\n'
REQ_TABLE = 'REQUIRED = {\n    "runs": ("run_id",),\n    "ghost": ("a",),\n}\n'


def _ctx():
    ctx = Ctx(root=".")
    ctx.policy["c3"] = {
        "cli_modules": {"labelbot": "labelbot/cli.py", "domain_engrbot": "domain_engrbot/cli.py", "code_engrbot": "code_engrbot/cli.py"},
        "doc_globs": [".claude/skills/*/SKILL.md", "README.md"],
        "contract": {"required": "domain_engrbot/adapters/labelbot_ws.py", "tables": "labelbot/store.py"},
        "labelbot_import_allowed": ["domain_engrbot/adapters/labelbot_ws.py", "domain_engrbot/io.py", "domain_engrbot/llm_http.py"],
    }
    return ctx


def _run(files, texts=None):
    index = RepoIndex("__no_such_root__", [SourceFile(p, s) for p, s in files.items()], texts=texts or {})
    return WorkflowCheck().run(index, _ctx())


class CliRefTest(unittest.TestCase):
    def test_missing_command_flagged(self):
        fs = _run({"labelbot/cli.py": LB_CLI, "domain_engrbot/cli.py": QA_CLI}, {"README.md": DOC})
        hits = [f for f in fs if f["rule"] == "C3_CLI_REF_MISSING"]
        self.assertEqual(len(hits), 1)
        self.assertEqual((hits[0]["path"], hits[0]["line"]), ("README.md", 3))

    def test_declared_commands_clean(self):
        doc = "`python -m labelbot selfcheck`\n`python -m labelbot run`\n`python -m domain_engrbot baseline`\n"
        fs = _run({"labelbot/cli.py": LB_CLI, "domain_engrbot/cli.py": QA_CLI}, {"README.md": doc})
        self.assertEqual([f for f in fs if f["rule"] == "C3_CLI_REF_MISSING"], [])

    def test_package_without_cli_skipped(self):
        fs = _run({"domain_engrbot/cli.py": QA_CLI}, {"README.md": "`python -m labelbot nothing`\n"})
        self.assertEqual([f for f in fs if f["rule"] == "C3_CLI_REF_MISSING"], [])

    def test_python3_and_py_launchers(self):
        doc = "`python3 -m labelbot nope`\n`py -m domain_engrbot nope2`\n`python3.14 -m domain_engrbot run`\n"
        fs = _run({"labelbot/cli.py": LB_CLI, "domain_engrbot/cli.py": QA_CLI}, {"README.md": doc})
        self.assertEqual([f["line"] for f in fs if f["rule"] == "C3_CLI_REF_MISSING"], [1, 2])

    def test_attribute_add_not_command(self):
        cli = LB_CLI + 'seen = set()\nseen.add("ghost")\n'
        fs = _run({"labelbot/cli.py": cli}, {"README.md": "`python -m labelbot ghost`\n"})
        self.assertEqual(len([f for f in fs if f["rule"] == "C3_CLI_REF_MISSING"]), 1)

    def test_loop_not_passed_to_add_not_command(self):
        cli = LB_CLI + 'for k, v in (("other", 1),):\n    print(k)\n'
        fs = _run({"labelbot/cli.py": cli}, {"README.md": "`python -m labelbot other`\n"})
        self.assertEqual(len([f for f in fs if f["rule"] == "C3_CLI_REF_MISSING"]), 1)

    def test_domain_engrbot_add_parser_missing(self):
        fs = _run({"domain_engrbot/cli.py": QA_CLI}, {"README.md": "`python -m domain_engrbot nope`\n"})
        self.assertEqual(len([f for f in fs if f["rule"] == "C3_CLI_REF_MISSING"]), 1)


class ImportBoundaryTest(unittest.TestCase):
    def test_violation_including_local_import(self):
        src = "import labelbot.store\n\ndef f():\n    from labelbot import ingest\n"
        fs = _run({"domain_engrbot/engine.py": src})
        hits = [f for f in fs if f["rule"] == "C3_IMPORT_BOUNDARY"]
        self.assertEqual([h["line"] for h in hits], [1, 4])

    def test_allowed_and_tests_clean(self):
        src = "from labelbot import ingest\n"
        fs = _run({"domain_engrbot/adapters/labelbot_ws.py": src, "domain_engrbot/tests/test_x.py": src, "code_engrbot/x.py": src})
        self.assertEqual([f for f in fs if f["rule"] == "C3_IMPORT_BOUNDARY"], [])


class TableContractTest(unittest.TestCase):
    PATH = "domain_engrbot/adapters/labelbot_ws.py"

    def _drift(self, req, store=STORE):
        fs = _run({self.PATH: req, "labelbot/store.py": store})
        return [f for f in fs if f["rule"] == "C3_TABLE_CONTRACT_DRIFT"]

    def test_clean(self):
        self.assertEqual(self._drift(REQ_OK), [])

    def test_extra_required_column(self):
        hits = self._drift(REQ_BAD)
        self.assertEqual(len(hits), 1)
        self.assertEqual((hits[0]["path"], hits[0]["line"], hits[0]["severity"]), (self.PATH, 2, "critical"))
        self.assertIn("extra_col", hits[0]["message"])

    def test_missing_table(self):
        hits = self._drift(REQ_TABLE)
        self.assertEqual(len(hits), 1)
        self.assertIn("ghost", hits[0]["message"])

    def test_alter_add_column_counts(self):
        store = STORE + 'MIG = "ALTER TABLE runs ADD COLUMN extra_col TEXT"\n'
        self.assertEqual(self._drift(REQ_BAD, store), [])

    def test_constraint_pieces_not_columns(self):
        self.assertEqual(len(self._drift('REQUIRED = {"files": ("UNIQUE",)}\n')), 1)

    def test_quoted_column_names(self):
        store = 'TABLES = {"t": \'"key" TEXT PRIMARY KEY, `b` TEXT, [c] TEXT\'}\n'
        req = 'REQUIRED = {"t": ("key", "b", "c")}\n'
        self.assertEqual(self._drift(req, store), [])

    def test_missing_file_no_finding(self):
        fs = _run({self.PATH: REQ_BAD})
        self.assertEqual([f for f in fs if f["rule"] == "C3_TABLE_CONTRACT_DRIFT"], [])


if __name__ == "__main__":
    unittest.main()
