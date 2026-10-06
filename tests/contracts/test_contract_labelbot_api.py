"""domain_engrbot(테스트 제외)이 쓰는 labelbot 심볼 동결.

domain_engrbot 소스를 ast로 훑어 `from labelbot... import X`와 `from labelbot import mod as alias` 뒤의 `alias.attr`를 모은다.
각 심볼을 실제로 import해 종류(class/exception/function/module/constant)와 함수 시그니처를 스냅샷과 비교한다.
"""
import ast
import importlib
import inspect
import os
import types
import unittest

from tests.contracts import _support

DOMAIN_ENGRBOT_DIR = os.path.join(_support.REPO_ROOT, "domain_engrbot")


def _sources():
    for base, dirs, files in os.walk(DOMAIN_ENGRBOT_DIR):
        dirs[:] = sorted(d for d in dirs if d not in ("tests", "__pycache__"))
        for name in sorted(files):
            if name.endswith(".py"):
                path = os.path.join(base, name)
                yield os.path.relpath(path, _support.REPO_ROOT).replace("\\", "/"), path


def used_symbols():
    """{'labelbot.mod.attr': [사용 파일, ...]}"""
    used = {}

    def add(sym, rel):
        used.setdefault(sym, set()).add(rel)

    for rel, path in _sources():
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), rel)
        aliases = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").split(".")[0] == "labelbot":
                for a in node.names:
                    full = "%s.%s" % (node.module, a.name)
                    try:
                        is_mod = isinstance(importlib.import_module(full), types.ModuleType)
                    except ImportError:
                        is_mod = False
                    if is_mod:
                        aliases[a.asname or a.name] = full
                    else:
                        add(full, rel)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.split(".")[0] == "labelbot":
                        aliases[a.asname or a.name] = a.name
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases:
                add("%s.%s" % (aliases[node.value.id], node.attr), rel)
    return {k: sorted(v) for k, v in sorted(used.items())}


def _resolve(sym):
    mod, _, attr = sym.rpartition(".")
    return getattr(importlib.import_module(mod), attr)


def describe(obj):
    if inspect.isclass(obj):
        kind = "exception" if issubclass(obj, BaseException) else "class"
        try:
            sig = str(inspect.signature(obj))
        except (TypeError, ValueError):
            sig = None
        return {"kind": kind, "signature": sig}
    if inspect.ismodule(obj):
        return {"kind": "module"}
    if callable(obj):
        return {"kind": "function", "signature": str(inspect.signature(obj))}
    return {"kind": "constant", "type": type(obj).__name__}


class LabelbotSymbolsUsedByEngrbot(unittest.TestCase):
    def test_symbols(self):
        used = used_symbols()
        self.assertTrue(used, "domain_engrbot에서 labelbot 사용처를 하나도 찾지 못했다")
        data = {}
        for sym, files in used.items():
            with self.subTest(symbol=sym):
                try:
                    obj = _resolve(sym)
                except (ImportError, AttributeError) as e:
                    self.fail("SYMBOL_MISSING %s (%s)" % (sym, type(e).__name__))
                data[sym] = dict(describe(obj), used_in=files)
        _support.check(self, "labelbot_symbols_used_by_domain_engrbot", data)


if __name__ == "__main__":
    unittest.main()
