"""Roo Code skill·rules(L4) 검사: tools/gen_roo_skills.py 생성물 12개 + 수작성 7개 = 19개.

- 모든 .roo/skills/*/SKILL.md: frontmatter name·description, name == 폴더 이름, 이름 규칙(소문자·숫자·하이픈, 1–64자,
  앞뒤·연속 하이픈 없음), description 1–1024자
- 생성 12개 == .generated.json, 수작성 7개는 .generated.json에 없음, 합계 19
- 참조 경로(.claude/skills/…/scripts·assets, tools/*.py, config/…, 런북 문서)가 있음(아직 없는 도구는 milestones에 계획된 것만)
- Claude 전용 구문 0건(.roo 아래 모든 파일). "/BEOL-"는 슬래시 명령꼴만 센다 — 경로 .claude/skills/BEOL-…는 원본
  스크립트를 가리키는 참조라 허용한다.
- skill마다 "## 마일스톤"(등록부의 Mxx ≥1)과 고정 "## 실패하면"
- gen_roo_skills.py --check 종료 0, 공개 저장소 검사(사용자 홈 경로 없음)
"""
import glob
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from labelbot import milestones  # noqa: E402

GEN = os.path.join(ROOT, "tools", "gen_roo_skills.py")
SKILLS_DIR = os.path.join(ROOT, ".roo", "skills")
RULES = os.path.join(ROOT, ".roo", "rules", "00-beol-governing.md")
MANIFEST = os.path.join(SKILLS_DIR, ".generated.json")

GENERATED = {
    "beol-labeling", "beol-labeling-run-labeling", "beol-labeling-feedback", "beol-labeling-axis-update",
    "beol-labeling-rules-update", "beol-labeling-code-engr-bot", "beol-labeling-domain-engr-bot",
    "beol-taxonomy-dashboard", "beol-labeling-daily-report", "beol-labeling-project-html",
    "beol-labeling-workflow", "beol-labeling-rag-html",
}
HANDWRITTEN = {
    "beol-import-verify", "beol-upgrade-carry", "beol-env-setup", "beol-drm-probe",
    "beol-proxy-measure", "beol-release-accept", "beol-backup-ops",
}
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
FORBIDDEN = {
    "AskUserQuestion": r"AskUserQuestion", "preview_start": r"preview_start", "/BEOL-": r"(?<![\w.-])/BEOL-",
    "run_in_background": r"run_in_background", "7200000": r"7200000", "Monitor": r"Monitor",
    "get_page_text": r"get_page_text", "read_page": r"read_page", "mcp__": r"mcp__", "Skill(": r"Skill\(",
}
FAILURE_TEXT = (
    "터미널의 `[Mxx …] 실패` 블록을 먼저 읽는다 → `python -m labelbot status --workspace <작업 폴더>`"
    "(Python 3.14가 없으면 `python3 tools/beol_status.py status --workspace <작업 폴더>`) 출력을 복사해 알려 달라. "
    "환경 문제면 `python3 tools/beol_doctor.py`. `BEOL_TRACE=1`은 Roo 명령으로 실행하지 말고 일반 터미널에서만.")
_P = r"[A-Za-z0-9_.-]*[A-Za-z0-9_]"
PATH_RE = re.compile(r"(\.claude/skills/[A-Za-z0-9_-]+/(?:scripts|assets)/" + _P + r"|(?<![\w/.])tools/[A-Za-z0-9_]+\.py"
                     r"|(?<![\w/.])config/" + _P + r"|CLOUD_SETUP\.md|CLOSED_NETWORK_RUNBOOK\.md)")


def _read(path):
    with open(path, "rb") as f:
        return f.read().decode("utf-8").replace("\r\n", "\n")


def _load_gen():
    spec = importlib.util.spec_from_file_location("gen_roo_skills", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _frontmatter(text):
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None
    meta = {}
    for line in text[4:end].split("\n"):
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] == "'":
                v = v[1:-1].replace("''", "'")
            elif len(v) >= 2 and v[0] == v[-1] == '"':
                v = json.loads(v)
            meta[k.strip()] = v
    return meta


def _skills():
    return sorted(os.path.basename(os.path.dirname(p)) for p in glob.glob(os.path.join(SKILLS_DIR, "*", "SKILL.md")))


def _skill_text(name):
    return _read(os.path.join(SKILLS_DIR, name, "SKILL.md"))


def _roo_files():
    out = []
    for dirpath, _, names in os.walk(os.path.join(ROOT, ".roo")):
        out.extend(os.path.join(dirpath, n) for n in names)
    return sorted(out)


def _section(text, heading):
    i = text.find("\n" + heading + "\n")
    if i < 0:
        return None
    rest = text[i + len(heading) + 2:]
    m = re.search(r"^## ", rest, re.M)
    return rest[:m.start()] if m else rest


class SkillSetTest(unittest.TestCase):
    def test_frontmatter_and_name_rules(self):
        names = _skills()
        self.assertTrue(names)
        for name in names:
            with self.subTest(skill=name):
                meta = _frontmatter(_skill_text(name))
                self.assertIsNotNone(meta, "frontmatter 없음")
                self.assertEqual(name, meta.get("name"))
                self.assertTrue(1 <= len(name) <= 64)
                self.assertRegex(name, NAME_RE)
                desc = (meta.get("description") or "").strip()
                self.assertTrue(1 <= len(desc) <= 1024, len(desc))

    def test_generated_handwritten_total(self):
        with open(MANIFEST, encoding="utf-8") as f:
            manifest = json.load(f)
        gen = set(manifest["skills"])
        self.assertEqual(GENERATED, gen)
        names = set(_skills())
        self.assertEqual(HANDWRITTEN, names - gen)
        self.assertEqual(19, len(names))
        self.assertFalse(HANDWRITTEN & gen)

    def test_manifest_sources_match(self):
        with open(MANIFEST, encoding="utf-8") as f:
            manifest = json.load(f)
        gen = _load_gen()
        self.assertEqual(gen.GENERATOR_VERSION, manifest["generator_version"])
        entries = list(manifest["skills"].items()) + list(manifest["rules"].items())
        self.assertEqual(13, len(entries))
        for key, e in entries:
            with self.subTest(target=key):
                src = _read(os.path.join(ROOT, e["source"]))
                self.assertEqual(hashlib.sha256(src.encode("utf-8")).hexdigest(), e["source_sha256"])
                self.assertEqual(gen.GENERATOR_VERSION, e["generator_version"])
        self.assertIn("BEOL-labeling-change-dashboard", manifest["excluded"])


class ContentTest(unittest.TestCase):
    def test_no_claude_only_tokens(self):
        hits = []
        for path in _roo_files():
            text = _read(path)
            for tok, pat in FORBIDDEN.items():
                for m in re.finditer(pat, text):
                    hits.append("%s:%d %s" % (os.path.relpath(path, ROOT), text.count("\n", 0, m.start()) + 1, tok))
        self.assertEqual([], hits)

    def test_referenced_paths_exist(self):
        missing = []
        for path in _roo_files():
            for m in PATH_RE.finditer(_read(path)):
                rel = m.group(1)
                if os.path.exists(os.path.join(ROOT, rel)):
                    continue
                if rel in milestones.ENTRYPOINTS:  # 계획된 도구(예: B7 백업 도구)
                    continue
                missing.append("%s → %s" % (os.path.relpath(path, ROOT), rel))
        self.assertEqual([], missing)

    def test_generated_skills_reference_original_scripts(self):
        for name in ("beol-labeling", "beol-labeling-feedback", "beol-labeling-project-html", "beol-labeling-workflow"):
            text = _skill_text(name)
            with self.subTest(skill=name):
                self.assertRegex(text, r"\.claude/skills/BEOL-[A-Za-z-]+/(?:scripts|assets)/")
                self.assertNotRegex(text, r"(?<![\w./-])(?:scripts|assets)/[A-Za-z_]")  # skill 폴더 기준 상대 경로 없음
        self.assertEqual([], glob.glob(os.path.join(SKILLS_DIR, "*", "scripts")))

    def test_milestone_and_failure_sections(self):
        for name in _skills():
            text = _skill_text(name)
            with self.subTest(skill=name):
                sec = _section(text, "## 마일스톤")
                self.assertIsNotNone(sec, "## 마일스톤 없음")
                ids = set(re.findall(r"\bM\d\d\b", sec))
                self.assertTrue(ids, "마일스톤 ID 없음")
                self.assertLessEqual(ids, set(milestones.IDS))
                fail = _section(text, "## 실패하면")
                self.assertIsNotNone(fail, "## 실패하면 없음")
                self.assertIn(FAILURE_TEXT, fail)

    def test_generated_header_and_rules_file(self):
        for name in GENERATED:
            self.assertIn("python tools/gen_roo_skills.py`를 다시 실행한다", _skill_text(name))
        rules = _read(RULES)
        self.assertIn("DRM 규칙", rules)
        self.assertIn("`CLAUDE.md`에서 생성됐다", rules)
        self.assertIn("## 폐쇄망 운영 규칙 (Roo)", rules)

    def test_rag_html_before_b6(self):
        text = _skill_text("beol-labeling-rag-html")
        self.assertIn("답변 서버(ragsrv) 준비 전: 화면 디자인 수정만 가능", text)
        self.assertNotIn("deploy_edge_function", text)
        self.assertNotRegex(text, r"Supabase")

    def test_public_repo_safe(self):
        home = ("C:" + "\\" + "Users", "C:" + "/" + "Users")
        for path in _roo_files() + [GEN, os.path.abspath(__file__)]:
            text = _read(path)
            for h in home:
                self.assertNotIn(h, text, os.path.relpath(path, ROOT))


class GeneratorTest(unittest.TestCase):
    def test_check_mode_clean(self):
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        p = subprocess.run([sys.executable, GEN, "--check"], cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", env=env)
        self.assertEqual(0, p.returncode, p.stdout + p.stderr)
        self.assertIn('"check": "ok"', p.stdout)

    def test_skill_ref_particles(self):
        gen = _load_gen()
        rx = re.compile(r"(?<![\w.-])/" + gen._SKILL_REF + gen._PART)
        conv = lambda s: rx.sub(lambda m: gen._skill_ref(m, tick=False), s)  # noqa: E731
        self.assertEqual("beol-labeling-feedback 스킬로 검수", conv("/BEOL-labeling-feedback으로 검수"))
        self.assertEqual("beol-labeling 스킬을 부른다", conv("/BEOL-labeling을 부른다"))
        self.assertEqual("beol-labeling-axis-update 스킬이나", conv("/BEOL-labeling-axis-update나"))
        self.assertEqual("beol-taxonomy-dashboard 스킬이", conv("/BEOL-taxonomy-dashboard 스킬이"))
        self.assertEqual(".claude/skills/BEOL-labeling/scripts", conv(".claude/skills/BEOL-labeling/scripts"))

    def test_rule_anchor_missing_fails(self):
        gen = _load_gen()
        with self.assertRaises(gen.GenError):
            gen.apply_rules("BEOL-labeling", "설명", "원문에 없는 본문")

    def test_name_validation(self):
        gen = _load_gen()
        for bad in ("Beol", "beol--x", "-beol", "beol-", "", "a" * 65):
            with self.assertRaises(gen.GenError):
                gen.validate_name(bad, bad)
        with self.assertRaises(gen.GenError):
            gen.validate_name("beol-x", "beol-y")


if __name__ == "__main__":
    unittest.main()
