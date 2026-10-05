"""소스 색인. 소스는 import하지 않고 텍스트로만 읽는다."""
import ast
import os
import re

_ALLOW_RE = re.compile(r"#\s*codebot:\s*allow\s+([A-Za-z0-9_]+)")
_SKIP_DIRS = (".git", "__pycache__", "node_modules")


class SourceFile(object):
    """.py 한 개. tree의 모든 노드에 parent 속성을 단다(루트는 None)."""

    def __init__(self, path, text, read_error=None):
        self.path = path.replace("\\", "/")
        self.text = text
        self.lines = text.splitlines()
        self.tree = None
        self.syntax_error = None
        if read_error is not None:
            self.syntax_error = (0, read_error)
            return
        try:
            tree = ast.parse(text, filename=self.path)
        except SyntaxError as e:
            self.syntax_error = (e.lineno or 0, e.msg or "SyntaxError")
            return
        except (ValueError, RecursionError) as e:
            self.syntax_error = (0, "%s" % e)
            return
        tree.parent = None
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                child.parent = node
        self.tree = tree

    def _span(self, line):
        """finding 줄에서 시작하는 문장들의 줄 범위를 (시작, 끝)으로 합친다. 복합문과 정의는 머리부터 본문 첫 문장 줄까지만 본다."""
        lo = hi = line
        if self.tree is None:
            return lo, hi
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.stmt):
                continue
            start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
            if line not in (start, node.lineno):
                continue
            body = getattr(node, "body", None)
            if isinstance(body, list) and body:
                end = body[0].lineno
            else:
                end = getattr(node, "end_lineno", None) or node.lineno
            lo, hi = min(lo, start), max(hi, end)
        return lo, hi

    def allowed(self, rule, line):
        if not line or line < 1 or line > len(self.lines):
            return False
        lo, hi = self._span(line)
        for i in range(lo, min(hi, len(self.lines)) + 1):
            if any(m.group(1) == rule for m in _ALLOW_RE.finditer(self.lines[i - 1])):
                return True
        return False


def dotted(node):
    """Name·Attribute 체인을 'a.b.c' 문자열로 바꾼다. 아니면 빈 문자열이다."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


def leaf_name(node):
    """Call이면 호출 대상을 보고, Name은 id를, Attribute는 마지막 attr을 낸다(밑동이 Name이 아니어도 된다). 아니면 None이다."""
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def match(rel, pattern):
    """glob 한 개를 저장소 상대 경로(구분자 '/')에 맞춘다. '*'·'?'는 '/'를 넘지 않고, '**'는 넘는다.

    정책·검사의 모든 glob이 이 함수 하나를 쓴다. fnmatch와 달리 대소문자를 구분하고 '[...]'를 문자 집합으로 보지 않는다.
    """
    regex = ""
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            regex += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            regex += ".*"
            i += 2
        elif pattern[i] == "*":
            regex += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            regex += "[^/]"
            i += 1
        else:
            regex += re.escape(pattern[i])
            i += 1
    return re.fullmatch(regex, rel) is not None


def match_any(rel, patterns):
    return any(match(rel, p) for p in patterns)


def read_file(full):
    """파일 하나를 utf-8-sig로 읽는다. 실패하면 (빈 문자열, 사유 코드)를 낸다."""
    try:
        with open(full, "r", encoding="utf-8-sig") as fh:
            return fh.read(), None
    except UnicodeDecodeError:
        return "", "READ_DECODE_FAILED"
    except OSError:
        return "", "READ_FAILED"


class RepoIndex(object):
    def __init__(self, root, files, texts=None):
        self.root = root
        self.files = list(files)
        self.texts = dict(texts or {})
        self._by_path = {f.path: f for f in self.files}

    def get(self, path):
        return self._by_path.get(path.replace("\\", "/"))

    def read_text(self, rel_path):
        rel = rel_path.replace("\\", "/")
        if rel in self.texts:
            return self.texts[rel]
        src = self._by_path.get(rel)
        if src is not None:
            return src.text
        full = os.path.join(self.root, rel)
        if not os.path.isfile(full):
            return None
        text, err = read_file(full)
        return None if err else text

    def glob(self, pattern):
        found = set(p for p in self.texts if match(p, pattern))
        found.update(p for p in self._by_path if match(p, pattern))
        if os.path.isdir(self.root):
            for dirpath, dirs, names in os.walk(self.root):
                dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
                for n in names:
                    rel = os.path.relpath(os.path.join(dirpath, n), self.root).replace(os.sep, "/")
                    if match(rel, pattern):
                        found.add(rel)
        return sorted(found)


def build(root, targets, exclude):
    """targets(폴더 또는 .py 파일)에서 .py를 모아 RepoIndex를 만든다. 읽지 못한 파일도 syntax_error로 남긴다."""
    exclude = list(exclude or [])
    rels = set()
    for t in targets:
        full = os.path.join(root, t)
        if os.path.isfile(full) and t.endswith(".py"):
            rels.add(t.replace("\\", "/"))
        elif os.path.isdir(full):
            for dirpath, dirs, names in os.walk(full):
                dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
                for n in names:
                    if n.endswith(".py"):
                        rels.add(os.path.relpath(os.path.join(dirpath, n), root).replace(os.sep, "/"))
    files = []
    for rel in sorted(rels):
        if match_any(rel, exclude):
            continue
        text, err = read_file(os.path.join(root, rel))
        files.append(SourceFile(rel, text, read_error=err))
    return RepoIndex(root, files)
