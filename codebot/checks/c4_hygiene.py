"""C4 위생 규칙: 테스트 건너뛰기, 미완 표식과 빈 구현."""
import ast
import io
import re
import tokenize

from codebot.registry import Check, register
from codebot.scan import leaf_name

_SKIP_DECORATORS = ("skip", "skipif", "skipunless", "expectedfailure")
_MARK_RE = re.compile(r"\b(TODO|FIXME|XXX)\b")


def _is_empty_stmt(st):
    if isinstance(st, ast.Pass):
        return True
    if isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant) and st.value.value is Ellipsis:
        return True
    if isinstance(st, ast.Raise) and st.exc is not None:
        return leaf_name(st.exc) == "NotImplementedError"
    return False


@register
class C4Hygiene(Check):
    layer = "C4"
    scope = "file"
    rules = {
        "C4_TEST_SKIP": {"severity": "major", "desc": "테스트를 건너뛰거나 실패를 기대 처리한다."},
        "C4_PLACEHOLDER": {"severity": "minor", "desc": "미완 표식 주석이나 빈 구현이 있다."},
    }

    def run(self, sf, ctx):
        out = []
        if sf.tree is not None:
            out.extend(self._skips(sf))
            out.extend(self._empty_bodies(sf))
        out.extend(self._comments(sf))
        return out

    def _skips(self, sf):
        out = []
        fix = "건너뛰지 말고 테스트를 통과시키거나 지운다."
        for node in ast.walk(sf.tree):
            line = None
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                for d in node.decorator_list:
                    name = leaf_name(d)
                    if name is not None and name.lower() in _SKIP_DECORATORS:
                        line = d.lineno
                        break
            elif isinstance(node, ast.Call) and leaf_name(node) == "skipTest":
                line = node.lineno
            elif isinstance(node, ast.Raise) and node.exc is not None and leaf_name(node.exc) == "SkipTest":
                line = node.lineno
            if line is not None:
                out.append(self.finding(
                    "C4_TEST_SKIP", sf.path, line, "테스트 건너뛰기가 있다.", fix))
        return out

    def _comments(self, sf):
        out = []
        try:
            for tok in tokenize.generate_tokens(io.StringIO(sf.text).readline):
                if tok.type == tokenize.COMMENT:
                    m = _MARK_RE.search(tok.string)
                    if m:
                        out.append(self.finding(
                            "C4_PLACEHOLDER", sf.path, tok.start[0],
                            f"{m.group(1)} 표식 주석이 남아 있다.", "구현하거나 표식을 지운다."))
        except (tokenize.TokenError, IndentationError, SyntaxError):
            pass
        return out

    def _empty_bodies(self, sf):
        out = []
        for node in ast.walk(sf.tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if any(leaf_name(d) == "abstractmethod" for d in node.decorator_list):
                continue
            body = node.body
            if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                body = body[1:]
            # 클래스 안 메서드의 본문이 raise NotImplementedError뿐이면 추상 메서드 관례로 보고 면제한다
            if (isinstance(getattr(node, "parent", None), ast.ClassDef) and len(body) == 1
                    and isinstance(body[0], ast.Raise) and body[0].exc is not None
                    and leaf_name(body[0].exc) == "NotImplementedError"):
                continue
            if body and all(_is_empty_stmt(s) for s in body):
                out.append(self.finding(
                    "C4_PLACEHOLDER", sf.path, node.lineno,
                    f"함수 {node.name}의 본문이 비어 있다.", "구현하거나 함수를 지운다.",
                    symbol=node.name))
        return out
