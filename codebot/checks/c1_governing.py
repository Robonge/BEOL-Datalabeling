"""C1 최상위 규칙(DRM, 표준 라이브러리, 쓰기 확장자, ingest 한 곳) 검사."""
import ast
import posixpath
import sys
from pathlib import Path

from codebot.registry import Check, register
from codebot.scan import dotted, match_any

SELF_EXTS = (".b64", ".json", ".jsonl", ".sqlite", ".md", ".html", ".log")
MEMORY_CTORS = ("BytesIO", "StringIO")
PATH_CALLS = ("os.path.join", "path", "pathlib.path", "purepath", "pathlib.purepath")
PATH_TOKENS = ("path", "file", "fname", "filename", "filepath")


def is_memory_call(node):
    return isinstance(node, ast.Call) and dotted(node.func).split(".")[-1] in MEMORY_CTORS


def enclosing_scope(node):
    cur = getattr(node, "parent", None)
    while cur is not None:
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
            return cur
        cur = getattr(cur, "parent", None)
    return None


def memory_names(scope):
    """같은 함수 안에서 BytesIO·StringIO로 대입된 이름을 모은다."""
    names = set()
    if scope is None:
        return names
    for n in ast.walk(scope):
        if isinstance(n, ast.Assign) and is_memory_call(n.value):
            names.update(t.id for t in n.targets if isinstance(t, ast.Name))
        elif isinstance(n, ast.AnnAssign) and n.value is not None and is_memory_call(n.value):
            if isinstance(n.target, ast.Name):
                names.add(n.target.id)
        elif isinstance(n, ast.withitem) and is_memory_call(n.context_expr):
            if isinstance(n.optional_vars, ast.Name):
                names.add(n.optional_vars.id)
    return names


def is_memory_arg(arg, call):
    if is_memory_call(arg):
        return True
    return isinstance(arg, ast.Name) and arg.id in memory_names(enclosing_scope(call))


def is_path_name(name):
    """이름을 '_' 토큰으로 나눠 경로 이름인지 본다(profile, fileobj는 아니다)."""
    return any(t in PATH_TOKENS or t.endswith("path") for t in name.lower().split("_"))


def surely_path(arg, call):
    """인자가 확실히 경로일 때만 참이다(불확실하면 거짓)."""
    if is_memory_arg(arg, call):
        return False
    if isinstance(arg, ast.Constant):
        return isinstance(arg.value, str)
    if isinstance(arg, ast.JoinedStr):
        return True
    if isinstance(arg, ast.Call):
        return dotted(arg.func).lower() in PATH_CALLS
    if isinstance(arg, ast.Name):
        return is_path_name(arg.id)
    return False


def first_arg(call):
    return call.args[0] if call.args else None


def open_mode(call):
    node = call.args[1] if len(call.args) > 1 else None
    for kw in call.keywords:
        if kw.arg == "mode":
            node = kw.value
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def assigned_value(name, call):
    """같은 함수, 없으면 모듈 최상위에서 이름의 마지막 대입 값을 찾는다. 없으면 None이다."""
    scope = enclosing_scope(call)
    scopes = [scope] if scope is not None else []
    top = scope
    while top is not None and getattr(top, "parent", None) is not None:
        top = top.parent
    if top is not None and top is not scope:
        scopes.append(top)
    for sc in scopes:
        found = None
        for n in ast.walk(sc):
            if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets):
                if found is None or n.lineno >= found.lineno:
                    found = n
            elif isinstance(n, ast.AnnAssign) and n.value is not None and isinstance(n.target, ast.Name) and n.target.id == name:
                if found is None or n.lineno >= found.lineno:
                    found = n
        if found is not None:
            return found.value
    return None


def tail_literal(arg, call=None, depth=0):
    """경로 인자에서 끝에 오는 문자열 리터럴을 꺼낸다. 없으면 None이다."""
    if depth > 5:
        return None
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    if isinstance(arg, ast.JoinedStr) and arg.values:
        last = arg.values[-1]
        if isinstance(last, ast.Constant) and isinstance(last.value, str):
            return last.value
    if isinstance(arg, ast.BinOp) and isinstance(arg.op, (ast.Div, ast.Add)):
        return tail_literal(arg.right, call, depth + 1)
    if isinstance(arg, ast.Call) and dotted(arg.func).lower() in PATH_CALLS and arg.args:
        return tail_literal(arg.args[-1], call, depth + 1)
    if isinstance(arg, ast.Name) and call is not None:
        val = assigned_value(arg.id, call)
        if val is not None:
            return tail_literal(val, call, depth + 1)
    return None


def is_open_call(node):
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open"


@register
class GoverningCheck(Check):
    layer = "C1"
    scope = "file"
    rules = {
        "C1_PATH_PARSER": {
            "severity": "critical",
            "desc": "경로를 받는 파서(Presentation, load_workbook, pd.read_*, csv.reader(open), ZipFile)를 쓴다.",
        },
        "C1_NONSTDLIB_IMPORT": {
            "severity": "critical",
            "desc": "표준 라이브러리도 로컬 패키지도 아닌 모듈을 import한다.",
        },
        "C1_WRITE_EXT_FORBIDDEN": {
            "severity": "critical",
            "desc": "office·텍스트 확장자 경로로 쓰기 모드 open을 한다.",
        },
        "C1_OPEN_OUTSIDE_INGEST": {
            "severity": "major",
            "desc": "ingest 모듈 밖에서 open(..., 'rb')로 원본을 연다(휴리스틱).",
        },
    }

    def run(self, sf, ctx):
        if sf.tree is None:
            return []
        pol = ctx.policy.get("c1", {})
        in_test = match_any(sf.path, pol.get("test_globs", []))
        out = []
        for node in ast.walk(sf.tree):
            if isinstance(node, ast.Call):
                self.check_path_parser(sf, node, out)
                if not in_test:
                    self.check_write_ext(sf, node, pol, out)
                    self.check_open_outside(sf, node, pol, out)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                self.check_import(sf, node, ctx, pol, out)
        return out

    def check_path_parser(self, sf, call, out):
        name = dotted(call.func)
        last = name.split(".")[-1]
        arg = first_arg(call)
        hit = None
        if last in ("Presentation", "load_workbook"):
            hit = last
        elif name.split(".")[0] in ("pd", "pandas") and "." in name and last.startswith("read_"):
            hit = name
        elif name == "csv.reader" and is_open_call(arg):
            hit = "csv.reader(open(...))"
        elif last == "ZipFile" and arg is not None and surely_path(arg, call):
            hit = "ZipFile"
        if hit is None:
            return
        if last != "ZipFile" and name != "csv.reader" and arg is not None and is_memory_arg(arg, call):
            return
        out.append(self.finding(
            "C1_PATH_PARSER", sf.path, call.lineno,
            f"{hit}는 경로를 받는 파서여서 DRM이 걸린 사내 파일을 열지 못한다.",
            "base64를 디코딩한 bytes를 io.BytesIO로 감싸 표준 라이브러리로 연다.",
        ))

    def check_import(self, sf, node, ctx, pol, out):
        if isinstance(node, ast.ImportFrom):
            if node.level > 0 or not node.module:
                return
            mods = [node.module]
        else:
            mods = [a.name for a in node.names]
        local = set(pol.get("local_packages", []))
        for mod in mods:
            top = mod.split(".")[0]
            if top in sys.stdlib_module_names or top in local or self.is_sibling(sf, top, ctx):
                continue
            out.append(self.finding(
                "C1_NONSTDLIB_IMPORT", sf.path, node.lineno,
                f"{top}는 표준 라이브러리도 로컬 패키지도 아니어서 본체가 표준 라이브러리만 쓴다는 규칙을 어긴다.",
                "표준 라이브러리로 바꾸거나 사외 PoC 전용이면 requirements-poc.txt로 옮기고 본체에서는 import하지 않는다.",
            ))

    def is_sibling(self, sf, top, ctx):
        base = Path(ctx.root) / posixpath.dirname(sf.path)
        return (base / f"{top}.py").is_file() or (base / top / "__init__.py").is_file()

    def check_write_ext(self, sf, call, pol, out):
        if is_open_call(call):
            mode = open_mode(call)
            arg = first_arg(call)
            if mode is None or arg is None or not any(c in mode for c in "wax+"):
                return
        elif isinstance(call.func, ast.Attribute) and call.func.attr in ("write_text", "write_bytes"):
            arg = call.func.value
        else:
            return
        lit = tail_literal(arg, call)
        exts = tuple(pol.get("forbidden_write_exts", []))
        if lit is None or not exts or not lit.lower().endswith(exts):
            return
        out.append(self.finding(
            "C1_WRITE_EXT_FORBIDDEN", sf.path, call.lineno,
            "office·텍스트 확장자로 파일을 쓰면 DRM이 다시 걸린다.",
            "결과는 .json, .jsonl, .md, .html, .log, .sqlite, .b64 중 허용 형식으로 쓴다.",
        ))

    def check_open_outside(self, sf, call, pol, out):
        if not is_open_call(call) or open_mode(call) != "rb":
            return
        if sf.path in pol.get("ingest_modules", []):
            return
        lit = tail_literal(first_arg(call), call)
        if lit is not None and lit.lower().endswith(SELF_EXTS):
            return
        out.append(self.finding(
            "C1_OPEN_OUTSIDE_INGEST", sf.path, call.lineno,
            "원본 경로를 여는 코드는 ingest 한 곳뿐이어야 하는데 그 밖에서 open(..., 'rb')를 한다.",
            "ingest가 만든 .b64를 읽어 디코딩한 bytes를 쓴다.",
        ))
