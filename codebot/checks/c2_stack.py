"""C2 스택 규칙: 구문, 전송 우회, 비밀 리터럴, requirements 비움."""
import ast
import re

from codebot.registry import Check, register
from codebot.scan import match_any

_BYPASS_MODULES = ("http.client", "socket", "ftplib", "smtplib")
_BYPASS_CALLS = ("urlopen", "build_opener")
_SECRET_RES = (
    # 앞이 영숫자이면 disk-, task- 같은 ID의 일부이므로 맞추지 않는다. sk-ant-, sk-proj- 접두 형식도 잡는다.
    re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?<![A-Za-z0-9])eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"(?<![A-Za-z0-9])AKIA[A-Z0-9]{16}"),
    re.compile(r"(?<![A-Za-z0-9])ghp_[A-Za-z0-9]{30,}"),
)


def _is_bypass_module(name):
    return any(name == m or name.startswith(m + ".") for m in _BYPASS_MODULES)


@register
class C2Stack(Check):
    layer = "C2"
    scope = "file"
    rules = {
        "C2_PY314_SYNTAX": {"severity": "critical", "desc": "Python 3.14 구문으로 파싱되지 않는다."},
        "C2_TRANSPORT_BYPASS": {"severity": "major", "desc": "전송 공용 모듈 밖에서 네트워크 호출을 직접 쓴다."},
        "C2_SECRET_LITERAL": {"severity": "critical", "desc": "키·토큰 꼴 문자열 리터럴이 있다."},
    }

    def run(self, sf, ctx):
        out = []
        if sf.syntax_error:
            line, msg = sf.syntax_error
            out.append(self.finding(
                "C2_PY314_SYNTAX", sf.path, line, f"구문 오류가 있다: {msg}",
                "Python 3.14 구문에 맞게 고친다."))
        if sf.tree is None:
            return out
        c2 = ctx.policy.get("c2", {})
        skip = list(c2.get("transport_modules", [])) + list(ctx.policy.get("c1", {}).get("test_globs", []))
        if not match_any(sf.path, skip):
            out.extend(self._bypass(sf))
        out.extend(self._secrets(sf))
        return out

    def _bypass(self, sf):
        out = []
        fix = "labelbot/llm.py의 전송 공용 함수를 거친다."
        for node in ast.walk(sf.tree):
            hit = None
            if isinstance(node, ast.Call):
                f = node.func
                name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
                if name in _BYPASS_CALLS:
                    hit = f"{name}() 직접 호출"
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if _is_bypass_module(a.name):
                        hit = f"{a.name} import"
            elif isinstance(node, ast.ImportFrom) and node.module:
                if _is_bypass_module(node.module):
                    hit = f"{node.module} import"
                elif node.module == "http" and any(a.name == "client" for a in node.names):
                    hit = "http.client import"
            if hit:
                out.append(self.finding(
                    "C2_TRANSPORT_BYPASS", sf.path, node.lineno,
                    f"전송 공용 모듈 밖에서 {hit}를 쓴다.", fix))
        return out

    def _secrets(self, sf):
        out = []
        for node in ast.walk(sf.tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for rx in _SECRET_RES:
                    m = rx.search(node.value)
                    if m:
                        s = m.group(0)
                        out.append(self.finding(
                            "C2_SECRET_LITERAL", sf.path, node.lineno,
                            f"키·토큰 꼴 문자열 리터럴이 있다(접두 {s[:3]}, 길이 {len(s)}).",
                            "환경 변수나 설정 파일에서 읽고 소스에서 지운다."))
                        break
        return out


@register
class C2Requirements(Check):
    layer = "C2"
    scope = "repo"
    rules = {
        "C2_REQUIREMENTS_NOT_EMPTY": {
            "severity": "major", "desc": "requirements.txt에 패키지 줄이 있다."},
    }

    def run(self, index, ctx):
        text = index.read_text("requirements.txt")
        if text is None:
            return []
        out = []
        for i, line in enumerate(text.splitlines(), 1):
            s = line.strip()
            if s and not s.startswith("#"):
                out.append(self.finding(
                    "C2_REQUIREMENTS_NOT_EMPTY", "requirements.txt", i,
                    "requirements.txt에 패키지 줄이 있다. 본체는 표준 라이브러리만 쓴다.",
                    "사외 PoC SDK는 requirements-poc.txt로 옮긴다."))
        return out
