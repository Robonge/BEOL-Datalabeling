"""RAG 화면(rag/)의 정적 검사: 키·외부 주소가 페이지에 없는지, 같은 출처 API(labelbot.ragsrv)만 부르는지, 설정이 계획대로인지 본다.

네트워크·DB 없이 파일 글자만 읽는다. 키처럼 보이는 리터럴은 쓰지 않고 패턴만 정규식으로 둔다.
서버 동작(API·요청 검사)은 tests/test_ragsrv.py, 답변 순수 함수는 tests/test_raglib.py가 본다.
"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAG = ROOT / "rag"
PAGE = RAG / "beol_rag.html"
MOCKUPS = [RAG / "mockups" / ("layout-%s.html" % x) for x in "abc"]
LAUNCH = ROOT / ".claude" / "launch.json"
POLICY = ROOT / "code_engrbot" / "defaults" / "policy.json"
README = ROOT / "README.md"

OPENAI_KEY = re.compile(r"sk-[A-Za-z0-9_-]{20,}")
JWT = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
SECRET_KEY_SHAPE = re.compile(r"sb_" + "secret_")
# 옛 데이터 서버 이름: 낱말을 쪼개 써서 저장소 전체 grep에 걸리지 않게 한다.
OLD_BACKEND = re.compile("supa" + "base", re.I)
EXTERNAL_RES = [
    re.compile(r"""(?:src|href)\s*=\s*["']?(?:https?:)?//""", re.I),
    re.compile(r"""url\(\s*["']?(?:https?:)?//""", re.I),
    re.compile(r"@import", re.I),
]
# 옛 봇 이름: 낱말을 쪼개 써서 이 파일 자신이 걸리지 않게 한다.
OLD_BOT = re.compile("code" + r"[-_ ]?" + "bot", re.I)
NODE = shutil.which("node")


def read(path):
    return Path(path).read_text(encoding="utf-8")


def rag_sources():
    return sorted(p for p in RAG.rglob("*") if p.is_file() and p.suffix == ".html")


def readme_rag_section():
    text = read(README)
    m = re.search(r"^## RAG 화면.*?(?=^## |\Z)", text, re.S | re.M)
    return m.group(0) if m else ""


class RagKeyTest(unittest.TestCase):
    def test_sources_exist(self):
        names = [p.name for p in rag_sources()]
        self.assertIn("beol_rag.html", names)

    def test_no_openai_key_shape(self):
        for p in rag_sources():
            self.assertIsNone(OPENAI_KEY.search(read(p)), p.name)


class RagHtmlTest(unittest.TestCase):
    def test_no_external_resources(self):
        for p in [PAGE] + MOCKUPS:
            text = read(p)
            for pat in EXTERNAL_RES:
                m = pat.search(text)
                self.assertIsNone(m, "%s: %s" % (p.name, m and m.group(0)))

    def test_page_has_no_web_url_except_backend(self):
        # 사내 리눅스 환경은 웹에 나가지 못한다. 데이터 서버도 같은 출처(labelbot.ragsrv)라 http(s) 주소를 하나도 두지 않는다.
        text = read(PAGE)
        m = re.search(r"https?://", text)
        self.assertIsNone(m, m and text[m.start():m.start() + 60])

    def test_no_new_style_secret_key_anywhere_in_rag(self):
        for p in RAG.rglob("*"):
            if p.is_file():
                self.assertIsNone(SECRET_KEY_SHAPE.search(p.read_text(encoding="utf-8", errors="ignore")), p.name)

    def test_page_has_csp_meta_with_self_connect_src(self):
        text = read(PAGE)
        m = re.search(r"""<meta[^>]+http-equiv\s*=\s*["']Content-Security-Policy["'][^>]*>""", text, re.I)
        self.assertIsNotNone(m)
        cs = re.search(r"""connect-src([^;"]*)""", m.group(0))
        self.assertIsNotNone(cs)
        self.assertEqual(cs.group(1).split(), ["'self'"])
        img = re.search(r"""img-src([^;"]*)""", m.group(0))
        self.assertIsNotNone(img)
        self.assertEqual(img.group(1).split(), ["'self'", "blob:", "data:"])
        self.assertIsNone(OLD_BACKEND.search(m.group(0)))

    def test_page_has_config_constants(self):
        text = read(PAGE)
        self.assertIn('const API_BASE = "";', text)
        self.assertIn('const FUNCTION_URL = API_BASE + "/api/ask";', text)
        for path in ("/api/facets", "/api/stats", "/api/feedback", "/slides/"):
            self.assertIn('API_BASE + "%s"' % path, text)

    def test_page_has_no_jwt_apikey_or_old_backend(self):
        text = read(PAGE)
        self.assertIsNone(JWT.search(text))
        self.assertNotIn("eyJ", text)
        self.assertIsNone(re.search(r"""["']apikey["']""", text, re.I))
        self.assertIsNone(OLD_BACKEND.search(text))
        self.assertNotIn("ANON_KEY", text)
        for old in ("/rest" + "/v1", "/storage" + "/v1", "/functions" + "/v1", '"Prefer"'):
            self.assertNotIn(old, text)

    def test_page_posts_send_json_content_type(self):
        text = read(PAGE)
        posts = [m.start() for m in re.finditer(r'method:\s*"POST"', text)]
        self.assertTrue(posts)
        for i in posts:
            self.assertIn('"Content-Type": "application/json"', text[i:i + 200])

    def test_page_has_no_inner_html(self):
        self.assertNotIn("innerHTML", read(PAGE))

    def test_mockups_do_not_fetch(self):
        for p in MOCKUPS:
            self.assertNotIn("fetch(", read(p), p.name)


class RagConfigTest(unittest.TestCase):
    def test_launch_json_rag_ui(self):
        data = json.loads(read(LAUNCH))
        entries = [c for c in data["configurations"] if c.get("name") == "rag-ui"]
        self.assertEqual(len(entries), 1)
        args = entries[0]["runtimeArgs"]
        for a in ("--bind", "127.0.0.1", "--directory"):
            self.assertIn(a, args)
        self.assertEqual(entries[0]["port"], 8795)

    def test_policy_excludes_rag(self):
        self.assertIn("rag/**", json.loads(read(POLICY))["exclude"])

    def test_readme_has_rag_section(self):
        self.assertTrue(readme_rag_section())


class RagOldNameTest(unittest.TestCase):
    def test_this_file_has_no_old_name(self):
        self.assertIsNone(OLD_BOT.search(read(__file__)))

    def test_readme_rag_section_has_no_old_name(self):
        self.assertIsNone(OLD_BOT.search(readme_rag_section()))


class PageRenumberTest(unittest.TestCase):
    """화면의 renumber(): 인용된 슬라이드가 1번부터, 그다음 후보, 마지막에 같은 파일 슬라이드."""

    def test_cited_first_then_candidates_then_siblings(self):
        if not NODE:
            raise AssertionError("node가 없다")
        m = re.search(r"  function renumber\(.*?\n  }\n", read(PAGE), re.S)
        self.assertIsNotNone(m)
        js = m.group(0) + """
const ev = [{n:1,kind:"hit"},{n:2,kind:"hit"},{n:3,kind:"hit"},{n:4,kind:"sibling",sibling_of:1},{n:5,kind:"sibling",sibling_of:3}];
const r = renumber("A[3] B[5] C[1] D[9]", ev, [1, 3, 5]);
console.log(JSON.stringify({answer: r.answer, cited: r.cited, order: r.evidence.map(e => [e.n, e.kind, e.sibling_of || 0])}));
"""
        out = subprocess.run([NODE, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr[-500:])
        res = json.loads(out.stdout.strip().splitlines()[-1])
        self.assertEqual(res["answer"], "A[1] B[2] C[3] D[9]")
        self.assertEqual(res["cited"], [1, 2, 3])
        # 옛 3→1, 5→2, 1→3, 2→4(후보), 4→5(같은 파일, 옛 1번 곧 새 3번의 형제)
        self.assertEqual(res["order"], [[1, "hit", 0], [2, "sibling", 1], [3, "hit", 0], [4, "hit", 0], [5, "sibling", 3]])


if __name__ == "__main__":
    unittest.main()
