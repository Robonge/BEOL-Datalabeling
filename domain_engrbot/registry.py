"""check 등록(@register)과 층·범위별 조회. L4·L5도 같은 방식으로 붙는다(11절)."""
import importlib

from domain_engrbot import model

BUILTIN_MODULES = (
    "domain_engrbot.checks.l0_parse",
    "domain_engrbot.checks.l1_schema",
    "domain_engrbot.checks.l2_taxonomy",
    "domain_engrbot.checks.l3a_span",
    "domain_engrbot.checks.l3b_judge",
    "domain_engrbot.checks.l4_domain",
    "domain_engrbot.checks.l5_crossdoc",
    "domain_engrbot.checks.l6_batch",
)

_REGISTRY = []
_loaded = []


class Check(object):
    """모든 검사의 기반. run(target, ctx) → list[Issue].

    scope=file이면 target은 FileTarget, record면 RecordTarget, batch면 BatchTarget이다.
    parallel=True인 record 검사는 엔진이 judge.workers 스레드로 돌린다.
    """

    id = None
    layer = None
    scope = "record"
    parallel = False

    def run(self, target, ctx):
        raise NotImplementedError


def register(cls):
    inst = cls()
    if not inst.id or inst.layer not in model.LAYERS or inst.scope not in model.SCOPES:
        raise ValueError("CHECK_INVALID:%s" % getattr(cls, "__name__", cls))
    if any(c.id == inst.id for c in _REGISTRY):
        raise ValueError("CHECK_DUPLICATE:%s" % inst.id)
    _REGISTRY.append(inst)
    return cls


def unregister(check_id):
    _REGISTRY[:] = [c for c in _REGISTRY if c.id != check_id]


def load_builtin():
    if not _loaded:
        for name in BUILTIN_MODULES:
            importlib.import_module(name)
        _loaded.append(True)


def checks(layer=None, scope=None):
    load_builtin()
    return [c for c in _REGISTRY if (layer is None or c.layer == layer) and (scope is None or c.scope == scope)]
