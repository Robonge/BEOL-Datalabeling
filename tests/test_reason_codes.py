"""사유 코드 카탈로그(labelbot/reason_codes.py) 완전성·doctor 사본 일치.

labelbot·domain_engrbot·code_engrbot CLI가 내는 사유 코드 문자열을 ast로 모아 카탈로그(패턴 포함)에 있는지 본다:
`raise …Error("CODE")`(목록 인자 포함), `reason_code="CODE"`, `add_failure(…, "CODE")`·`ctx.fail(…)`,
`"…_%d" %`(동적 코드 — 숫자를 넣어 패턴으로 확인), `return False, "CODE"`(LLM 응답 검증),
`fail_code`·`skip_code`·`note_partial("CODE")`, "[오류] CODE" 줄, 화면 서버 응답 {"code": "CODE"}(labelbot/serve.py).
핵심 범주(네트워크·인증·DRM·경로·sqlite·설정·포트 등)와 PipelineError는 누락 0.
"""
import ast
import importlib.util
import os
import re
import unittest

from labelbot import reason_codes
from labelbot.workspace import CODE_ROOT

CODE = re.compile(r"^(?=.{4,})[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$")  # ENCRYPTED·TIMEOUT 같은 한 단어 코드 포함
ERR_LINE = re.compile(r"^\[오류\] ([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)")
CALL_NAMES = ("add_failure", "fail", "fail_code", "_fail_code", "skip_code", "note_partial", "port_fail")
CRITICAL = re.compile(r"^(HTTP_.*|.*AUTH.*|ENCRYPTED|NOT_OOXML|.*NOT_FOUND|.*PATH.*|SQLITE.*|CONFIG.*|.*MISSING|"
                      r"EXTERNAL_BLOCKED|CLOCK_SKEW|SSE_UNAVAILABLE|PORT_IN_USE|DUMMY_DIR_NOT_FOUND|KEY_MISSING|"
                      r"TIMEOUT|NETWORK_ERROR|.*TAXONOMY.*|WORKSPACE.*)$")
# 카탈로그에 아직 넣지 않은 비핵심 코드(작게 유지 — 늘리지 말고 카탈로그에 넣는다).
TODO = frozenset()


def _name(f):
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""


def _str(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _files():
    for pkg in ("labelbot", "domain_engrbot"):
        for base, dirs, files in os.walk(os.path.join(CODE_ROOT, pkg)):
            dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__")]
            for fn in files:
                if fn.endswith(".py"):
                    yield os.path.join(base, fn)
    yield os.path.join(CODE_ROOT, "code_engrbot", "cli.py")


def scan():
    """{코드 또는 '%d' 패턴: {파일}}."""
    found = {}

    def add(code, path):
        found.setdefault(code, set()).add(os.path.relpath(path, CODE_ROOT).replace("\\", "/"))

    for path in _files():
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), path)
        serve_mod = path.replace("\\", "/").endswith("labelbot/serve.py")
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                n = _name(node.func)
                if re.search(r"(Error|Failed|Refused)$", n) and node.args:
                    a = node.args[0]
                    items = a.elts if isinstance(a, ast.List) else [a]
                    for it in items:
                        s = _str(it)
                        if s and CODE.match(s):
                            add(s, path)
                if n in CALL_NAMES and node.args:
                    s = _str(node.args[-1] if n in ("add_failure", "fail") else node.args[0])
                    if s and CODE.match(s):
                        add(s, path)
                for kw in node.keywords:
                    s = _str(kw.value)
                    if kw.arg == "reason_code" and s:
                        add(s, path)
                for a in node.args:
                    s = _str(a)
                    m = ERR_LINE.match(s or "")
                    if m:
                        add(m.group(1), path)
            elif serve_mod and isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values):
                    if k is not None and _str(k) == "code" and _str(v):
                        add(_str(v), path)
            elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
                s = _str(node.left)
                if s and re.match(r"^[A-Z][A-Z0-9_]*_%d$", s):
                    add(s, path)
            elif isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple) and len(node.value.elts) == 2:
                first, second = node.value.elts
                if isinstance(first, ast.Constant) and first.value is False and _str(second) and CODE.match(_str(second)):
                    add(_str(second), path)
    return found


def _doctor():
    path = os.path.join(CODE_ROOT, "tools", "beol_doctor.py")
    spec = importlib.util.spec_from_file_location("beol_doctor_parity", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.CATALOG


class CatalogCompletenessTest(unittest.TestCase):
    def test_every_raised_code_is_in_catalog(self):
        found = scan()
        self.assertGreater(len(found), 100, "스캔이 너무 적다(패턴이 깨졌다)")
        missing = {}
        for code, files in found.items():
            sample = code.replace("%d", "401")
            if not reason_codes.known(sample) and code not in TODO:
                missing[code] = sorted(files)
        self.assertEqual({}, missing, "카탈로그에 없는 사유 코드(labelbot/reason_codes.py에 원인·조치를 넣는다)")

    def test_critical_categories_have_no_allowlist(self):
        self.assertEqual(set(), {c for c in TODO if CRITICAL.match(c)})

    def test_pipeline_error_sites_all_have_codes(self):
        """raise PipelineError(...)마다 reason_code=가 있고 카탈로그에 있다."""
        sites = []
        for path in _files():
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read(), path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and _name(node.exc.func) == "PipelineError":
                    kw = dict((k.arg, k.value) for k in node.exc.keywords)
                    code = _str(kw.get("reason_code"))
                    sites.append((os.path.basename(path), node.lineno, code))
        self.assertGreaterEqual(len(sites), 12)
        self.assertEqual([], [s for s in sites if not s[2] or not reason_codes.known(s[2])])

    def test_dynamic_patterns(self):
        for code, key in (("HTTP_401", "HTTP_401"), ("HTTP_418", "HTTP_\\d+"), ("HTTP_503", "HTTP_5xx"),
                          ("CDP_HTTP_500", "CDP_HTTP_\\d+"), ("RC_2", "RC_\\d+"), ("UPLOAD_HTTP_500", "UPLOAD_*")):
            self.assertEqual(key, reason_codes.lookup(code, "M07" if code.startswith("HTTP") else None)["key"], code)
        self.assertEqual("UNEXPECTED_.*", reason_codes.lookup("UNEXPECTED_ValueError", "M07")["key"])
        self.assertEqual("UNEXPECTED_*", reason_codes.lookup("UNEXPECTED_ValueError", "M00")["key"])
        self.assertIsNone(reason_codes.lookup("NOT_A_REAL_CODE_XYZ"))
        self.assertEqual("카탈로그에 없는 사유 코드", reason_codes.describe("NOT_A_REAL_CODE_XYZ")["원인"])

    def test_same_code_differs_by_milestone(self):
        m07, m02, m08 = (reason_codes.lookup("HTTP_401", m)["조치"] for m in ("M07", "M02", "M08"))
        self.assertIn("임베딩", reason_codes.lookup("HTTP_401", "M07")["원인"])
        self.assertIn("LLM", reason_codes.lookup("HTTP_401", "M02")["원인"])
        self.assertEqual(3, len({m07, m02, m08}))

    def test_every_entry_has_cause_action_and_valid_milestones(self):
        from labelbot import milestones
        for key, e in reason_codes.CODES.items():
            self.assertTrue(e["원인"] and e["조치"], key)
            for m in e["milestones"]:
                self.assertTrue(m == reason_codes.ANY or m in milestones.NAMES, (key, m))
            for m in e["by_milestone"]:
                self.assertIn(m, milestones.NAMES, key)


class DoctorParityTest(unittest.TestCase):
    def test_doctor_catalog_is_a_subset_with_same_text(self):
        """tools/beol_doctor.py CATALOG(3.8 사본) ⊆ reason_codes, 원인·조치·담당자 문장이 같다."""
        doctor = _doctor()
        self.assertGreater(len(doctor), 30)
        for code, (cause, action, contact) in doctor.items():
            with self.subTest(code=code):
                self.assertIn(code, reason_codes.CODES)
                e = reason_codes.CODES[code]
                self.assertEqual((cause, action, contact), (e["원인"], e["조치"], e["담당자"]))
                d = reason_codes.lookup(code if not code.endswith("*") else code[:-1] + "X", "M00")
                self.assertEqual((cause, action), (d["원인"], d["조치"]))


if __name__ == "__main__":
    unittest.main()
