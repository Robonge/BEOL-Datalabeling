"""검사 등록(@register)과 층·범위별 조회, 규칙 카탈로그."""
import importlib
import pkgutil

from codebot import model

_REGISTRY = []
_loaded = []


class Check(object):
    """모든 검사의 기반. run(target, ctx) → list[finding].

    scope가 file이면 target은 SourceFile, repo면 RepoIndex다.
    """

    layer = None
    scope = "file"
    rules = {}

    def run(self, target, ctx):
        raise NotImplementedError  # codebot: allow C4_PLACEHOLDER 기반 클래스

    def finding(self, rule, path, line, message, suggested_fix=None, symbol=None):
        if rule not in self.rules:
            raise KeyError("RULE_UNKNOWN:%s" % rule)
        return {
            "rule": rule,
            "layer": self.layer,
            "severity": self.rules[rule]["severity"],
            "path": path,
            "line": line,
            "symbol": symbol,
            "message": message,
            "suggested_fix": suggested_fix,
            "source": "static",
            "suppressed": False,
        }


def register(cls):
    inst = cls()
    if inst.layer not in model.LAYERS or inst.scope not in ("file", "repo"):
        raise ValueError("CHECK_INVALID:%s" % cls.__name__)
    for rule, meta in inst.rules.items():
        if meta.get("severity") not in model.SEVERITIES:
            raise ValueError("RULE_SEVERITY_INVALID:%s" % rule)
        if any(rule in c.rules for c in _REGISTRY):
            raise ValueError("RULE_DUPLICATE:%s" % rule)
    _REGISTRY.append(inst)
    return cls


def unregister(cls):
    """테스트용. 클래스로 등록된 검사를 뺀다."""
    _REGISTRY[:] = [c for c in _REGISTRY if type(c) is not cls]


def load_builtin():
    if _loaded:
        return
    import codebot.checks as pkg
    for info in pkgutil.iter_modules(pkg.__path__):
        importlib.import_module("codebot.checks." + info.name)
    _loaded.append(True)


def checks(layer=None, scope=None):
    load_builtin()
    return [c for c in _REGISTRY if (layer is None or c.layer == layer) and (scope is None or c.scope == scope)]


def all_rules():
    out = {}
    for c in checks():
        for rule, meta in c.rules.items():
            out[rule] = {"layer": c.layer, "severity": meta["severity"], "desc": meta.get("desc", "")}
    return out
