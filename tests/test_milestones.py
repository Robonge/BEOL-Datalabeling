"""마일스톤 등록부·진입점 표(labelbot/milestones.py)와 Python 3.8 경계.

- ENTRYPOINTS가 모든 argparse 하위 명령(labelbot·domain_engrbot·code_engrbot)·skill 스크립트·tools·nightly·
  daily_report의 main을 덮는다(parser를 직접 훑는다).
- 감싸기 확인: 스크립트 main이 표의 마일스톤으로 trace.run/run_main을 부른다(스스로 블록을 내는 도구 제외).
- 3.8 경계: trace·milestones·reason_codes·status·labelbot/__init__과 tools/{beol_status,verify_import,carry_state}
  는 ast feature_version=(3,8)로 읽히고, 3.8 모듈은 서로 말고는 다른 labelbot 모듈을 import하지 않는다.
"""
import argparse
import ast
import glob
import os
import unittest

from labelbot import milestones
from labelbot.workspace import CODE_ROOT

PY38 = ["labelbot/trace.py", "labelbot/milestones.py", "labelbot/reason_codes.py", "labelbot/status.py",
        "labelbot/__init__.py", "tools/beol_status.py", "tools/verify_import.py", "tools/carry_state.py"]
SAFE_SET = {"labelbot", "labelbot.trace", "labelbot.milestones", "labelbot.reason_codes", "labelbot.status"}


def _subcommands(parser, prefix):
    """parser의 하위 명령 경로들. 하위 명령에 또 하위 명령이 있으면 그 잎까지 내려간다(부모도 함께 낸다)."""
    out = []
    for act in parser._actions:
        if isinstance(act, argparse._SubParsersAction):
            for name, sp in act.choices.items():
                path = prefix + " " + name
                out.append(path)
                out.extend(_subcommands(sp, path))
    return out


def _rel(path):
    return os.path.relpath(path, CODE_ROOT).replace("\\", "/")


def _has_main(path):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), path)
    return any(isinstance(n, ast.FunctionDef) and n.name == "main" for n in tree.body)


def _scripts():
    paths = glob.glob(os.path.join(CODE_ROOT, ".claude", "skills", "*", "scripts", "*.py"))
    paths += glob.glob(os.path.join(CODE_ROOT, "tools", "*.py"))
    paths += [os.path.join(CODE_ROOT, "nightly_run.py"), os.path.join(CODE_ROOT, "daily_report.py")]
    # skill 스크립트는 main이 없어도(serve_screens.py는 labelbot.cli.main을 부른다) 진입점이다
    return sorted(_rel(p) for p in paths if _has_main(p) or os.sep + "skills" + os.sep in p or "/skills/" in p)


class RegistryTest(unittest.TestCase):
    def test_ids_and_names(self):
        self.assertEqual(28, len(milestones.MILESTONES))
        self.assertEqual("M07 EMBED", milestones.label("M07"))
        for mid, name, desc in milestones.MILESTONES:
            self.assertRegex(mid, r"^M\d\d$")
            self.assertRegex(name, r"^[A-Z_/]+$")
            self.assertTrue(desc)

    def test_entrypoint_values_are_registered(self):
        for key, ms in milestones.ENTRYPOINTS.items():
            self.assertTrue(ms, key)
            for m in ms:
                self.assertIn(m, milestones.NAMES, key)
        self.assertLessEqual(milestones.QUIET, set(milestones.ENTRYPOINTS))
        self.assertLessEqual(set(milestones.STAGE_MILESTONE.values()), set(milestones.NAMES))


class EntrypointCoverageTest(unittest.TestCase):
    def test_labelbot_subcommands(self):
        from labelbot import cli
        cmds = _subcommands(cli._parser(), "labelbot")
        self.assertEqual(23, len(cmds))  # 21 + status, codes
        for c in cmds:
            self.assertIn(c, milestones.ENTRYPOINTS, c)
        self.assertEqual(("M01", "M02", "M03", "M04"), milestones.lookup("labelbot", "run"))

    def test_domain_engrbot_subcommands(self):
        from domain_engrbot import cli
        cmds = _subcommands(cli._parser(), "domain_engrbot")
        self.assertEqual(18, len(cmds))  # 하위 parser 18개(baseline·golden 부모 포함), 실행 명령 16개
        leaves = [c for c in cmds if not any(o.startswith(c + " ") for o in cmds)]
        self.assertEqual(16, len(leaves))
        for c in cmds:
            self.assertTrue(milestones.lookup(*c.split(" ")), c)
        for c in leaves:
            self.assertIn(c, milestones.ENTRYPOINTS, c)

    def test_code_engrbot_subcommands(self):
        with open(os.path.join(CODE_ROOT, "code_engrbot", "cli.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        names = [n.args[0].value for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and getattr(n.func, "attr", "") == "add_parser" and n.args and isinstance(n.args[0], ast.Constant)]
        self.assertEqual(["review", "rules"], sorted(names))
        for n in names:
            self.assertEqual(("M20",), milestones.lookup("code_engrbot", n))

    def test_every_script_main(self):
        scripts = _scripts()
        self.assertGreaterEqual(len([s for s in scripts if s.startswith(".claude/")]), 9)
        missing = [s for s in scripts if s not in milestones.ENTRYPOINTS]
        self.assertEqual([], missing)

    def test_scripts_are_wrapped_with_their_milestone(self):
        """표의 스크립트가 실제로 그 마일스톤으로 감싼다(스스로 블록을 내는 도구·labelbot serve 위임 제외)."""
        for rel in _scripts():
            if rel in milestones.SELF_REPORTING or rel.endswith("serve_screens.py"):
                continue
            with open(os.path.join(CODE_ROOT, rel), encoding="utf-8") as f:
                src = f.read()
            mid = milestones.ENTRYPOINTS[rel][0]
            with self.subTest(script=rel):
                self.assertTrue("trace.run_main(" in src or "trace.run(" in src, rel)
                self.assertIn('"%s"' % mid, src, rel)
                if rel in milestones.QUIET:
                    self.assertIn("quiet=True", src)


class Py38BoundaryTest(unittest.TestCase):
    def test_py38_syntax(self):
        for rel in PY38:
            path = os.path.join(CODE_ROOT, rel)
            if not os.path.isfile(path):
                continue  # 아직 없는 도구(다른 단계)
            with open(path, encoding="utf-8") as f:
                with self.subTest(file=rel):
                    ast.parse(f.read(), rel, feature_version=(3, 8))

    def test_py38_modules_import_only_safe_labelbot_modules(self):
        for rel in PY38[:4]:
            with open(os.path.join(CODE_ROOT, rel), encoding="utf-8") as f:
                tree = ast.parse(f.read(), rel)
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    mods = [node.module] + ["%s.%s" % (node.module, a.name) for a in node.names] \
                        if node.module == "labelbot" else [node.module]
                for m in mods:
                    if m and m.split(".")[0] == "labelbot":
                        if node.__class__ is ast.ImportFrom and m == "labelbot":
                            continue
                        with self.subTest(file=rel, module=m):
                            self.assertIn(m, SAFE_SET)


if __name__ == "__main__":
    unittest.main()
