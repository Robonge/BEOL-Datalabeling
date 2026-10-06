"""C3 워크플로 약속 검사: 문서의 명령 참조, import 경계, 표 계약."""
import ast
import re

from code_engrbot.registry import Check, register

_CMD_RE = re.compile(r"(?:python[\d.]*|py)\s+-m\s+([A-Za-z_][\w.]*)\s+([A-Za-z][\w-]*)")
_SKIP_PREFIX = ("PRIMARY", "UNIQUE", "CHECK", "FOREIGN", "CONSTRAINT")


def _is_cmd_call(node):
    """명령 선언 호출인지 본다: 이름 호출 add(...)와 속성 호출 .add_parser(...)만 해당한다."""
    if not isinstance(node, ast.Call) or not node.args:
        return False
    fn = node.func
    return (isinstance(fn, ast.Name) and fn.id in ("add", "add_parser")) or (
        isinstance(fn, ast.Attribute) and fn.attr == "add_parser")


def _declared_commands(tree):
    """cli 모듈 AST에서 선언된 명령 이름을 모은다(add(이름)·.add_parser(이름) 호출, 인자로 넘기는 튜플 반복문)."""
    names = set()
    for node in ast.walk(tree):
        if _is_cmd_call(node):
            a = node.args[0]
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                names.add(a.value)
        elif isinstance(node, ast.For) and isinstance(node.iter, (ast.Tuple, ast.List)):
            tgt = node.target
            if isinstance(tgt, (ast.Tuple, ast.List)) and tgt.elts:
                tgt = tgt.elts[0]
            if not isinstance(tgt, ast.Name):
                continue
            used = any(_is_cmd_call(n) and isinstance(n.args[0], ast.Name) and n.args[0].id == tgt.id
                       for stmt in node.body for n in ast.walk(stmt))
            if not used:
                continue
            for elt in node.iter.elts:
                if isinstance(elt, (ast.Tuple, ast.List)) and elt.elts:
                    elt = elt.elts[0]
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    names.add(elt.value)
    return names


def _find_dict(tree, name):
    """모듈 최상위 name = {...} 대입에서 (ast.Dict, 값 dict)를 돌려준다. 없거나 리터럴이 아니면 None."""
    if tree is None:
        return None
    for node in tree.body:
        targets = []
        value = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        if any(isinstance(t, ast.Name) and t.id == name for t in targets) and isinstance(value, ast.Dict):
            try:
                return value, ast.literal_eval(value)
            except (ValueError, SyntaxError):
                return None
    return None


def _split_top(spec):
    """괄호 깊이 0의 쉼표로 spec을 나눈다. 따옴표 안의 쉼표는 무시한다."""
    parts, depth, quote, cur = [], 0, None, []
    for ch in spec:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    parts.append("".join(cur))
    return parts


def _table_columns(spec):
    cols = set()
    for part in _split_top(spec):
        # 열 이름을 따옴표·백틱·대괄호로 감싼 경우도 벗겨서 받는다
        m = re.match(r"\s*(?:\"([^\"]+)\"|`([^`]+)`|\[([^\]]+)\]|([A-Za-z_]\w*))", part)
        if m:
            name = next(g for g in m.groups() if g)
            if name.upper() not in _SKIP_PREFIX or m.group(4) is None:
                cols.add(name)
    return cols


def _extra_columns(tree):
    """TABLES 밖에서 더해지는 열: 'ALTER TABLE <표> ADD COLUMN <열>' 문자열."""
    extra = {}
    pat = re.compile(r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)", re.I)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for t, c in pat.findall(node.value):
                extra.setdefault(t, set()).add(c)
    return extra


@register
class WorkflowCheck(Check):
    layer = "C3"
    scope = "repo"
    rules = {
        "C3_CLI_REF_MISSING": {"severity": "major", "desc": "문서의 `python -m <패키지> <명령>`이 그 패키지 cli에 선언돼 있지 않다"},
        "C3_IMPORT_BOUNDARY": {"severity": "major", "desc": "domain_engrbot이 허용 모듈 밖에서 labelbot을 import한다"},
        "C3_TABLE_CONTRACT_DRIFT": {"severity": "critical", "desc": "REQUIRED의 표·열이 store.TABLES에 없다"},
    }

    def run(self, index, ctx):
        pol = ctx.policy.get("c3", {})
        out = self._cli_refs(index, pol)
        out += self._imports(index, pol)
        out += self._contract(index, pol)
        return out

    def _cli_refs(self, index, pol):
        cli_modules = pol.get("cli_modules", {})
        declared = {}
        for pkg, path in cli_modules.items():
            sf = index.get(path)
            if sf is not None and sf.tree is not None:
                declared[pkg] = _declared_commands(sf.tree)
        findings = []
        for pattern in pol.get("doc_globs", []):
            for doc in index.glob(pattern):
                text = index.read_text(doc)
                if text is None:
                    continue
                for lineno, line in enumerate(text.splitlines(), 1):
                    for pkg, cmd in _CMD_RE.findall(line):
                        if pkg in declared and cmd not in declared[pkg]:
                            findings.append(self.finding(
                                "C3_CLI_REF_MISSING", doc, lineno,
                                "문서가 `python -m %s %s`를 안내하지만 %s에 그 명령이 없다" % (pkg, cmd, cli_modules[pkg]),
                                "문서의 명령 이름을 cli 선언에 맞추거나 cli에 명령을 추가한다"))
        return findings

    def _imports(self, index, pol):
        allowed = set(pol.get("labelbot_import_allowed", []))
        findings = []
        for sf in index.files:
            p = sf.path
            if not p.startswith("domain_engrbot/") or p.startswith("domain_engrbot/tests/") or p in allowed or sf.tree is None:
                continue
            for node in ast.walk(sf.tree):
                bad = False
                if isinstance(node, ast.Import):
                    bad = any(a.name == "labelbot" or a.name.startswith("labelbot.") for a in node.names)
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    bad = node.level == 0 and (mod == "labelbot" or mod.startswith("labelbot."))
                if bad:
                    findings.append(self.finding(
                        "C3_IMPORT_BOUNDARY", p, node.lineno,
                        "domain_engrbot의 허용 모듈 밖에서 labelbot을 import한다",
                        "labelbot 접근은 domain_engrbot/adapters/labelbot_ws.py 등 허용 모듈로 모은다"))
        return findings

    def _contract(self, index, pol):
        contract = pol.get("contract", {})
        req_sf = index.get(contract.get("required", ""))
        tab_sf = index.get(contract.get("tables", ""))
        if req_sf is None or tab_sf is None:
            return []
        req = _find_dict(req_sf.tree, "REQUIRED")
        tab = _find_dict(tab_sf.tree, "TABLES")
        if req is None or tab is None:
            return []
        req_node, req_val = req
        _, tab_val = tab
        have = {t: _table_columns(spec) for t, spec in tab_val.items() if isinstance(spec, str)}
        for t, cols in _extra_columns(tab_sf.tree).items():
            have.setdefault(t, set()).update(cols)
        key_lines = {}
        for k in req_node.keys:
            if isinstance(k, ast.Constant):
                key_lines[k.value] = k.lineno
        findings = []
        for t, cols in req_val.items():
            line = key_lines.get(t, req_node.lineno)
            if t not in have:
                findings.append(self.finding(
                    "C3_TABLE_CONTRACT_DRIFT", req_sf.path, line,
                    "REQUIRED의 표 %s가 TABLES에 없다" % t,
                    "TABLES에 표를 추가하거나 REQUIRED에서 뺀다"))
                continue
            missing = [c for c in cols if c not in have[t]]
            if missing:
                findings.append(self.finding(
                    "C3_TABLE_CONTRACT_DRIFT", req_sf.path, line,
                    "REQUIRED의 %s 열 %s가 TABLES에 없다" % (t, ", ".join(missing)),
                    "TABLES에 열을 추가하거나 REQUIRED에서 뺀다"))
        return findings
