"""RAG 화면(rag/)의 정적 검사: 키가 저장소에 없는지, 외부 자원이 없는지, 상한 상수와 SQL 문서·설정이 계획대로인지 본다.

네트워크·DB·Deno 없이 파일 글자만 읽는다. 키처럼 보이는 리터럴은 쓰지 않고 패턴만 정규식으로 둔다.
"""
import base64
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAG = ROOT / "rag"
PAGE = RAG / "beol_rag.html"
MOCKUPS = [RAG / "mockups" / ("layout-%s.html" % x) for x in "abc"]
INDEX_TS = RAG / "functions" / "beol-rag-ask" / "index.ts"
LIB_TS = RAG / "functions" / "beol-rag-ask" / "lib.ts"
LAUNCH = ROOT / ".claude" / "launch.json"
SCHEMA_MD = ROOT / "docs" / "supabase_schema.md"
POLICY = ROOT / "code_engrbot" / "defaults" / "policy.json"
README = ROOT / "README.md"

OPENAI_KEY = re.compile(r"sk-[A-Za-z0-9_-]{20,}")
JWT = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
SECRET_KEY_SHAPE = re.compile(r"sb_" + "secret_")
SUPABASE_HOST = "akvsabzuwjenxepxybpe.supabase.co"
PROJECT_REF = "akvsabzuwjenxepxybpe"
EXTERNAL_RES = [
    re.compile(r"""(?:src|href)\s*=\s*["']?(?:https?:)?//""", re.I),
    re.compile(r"""url\(\s*["']?(?:https?:)?//""", re.I),
    re.compile(r"@import", re.I),
]
TABLE_GRANT = re.compile(
    r"grant\s+(select|insert)(\s*\([^)]*\))?\s+on\s+public\.(beol_rag_\w+)\s+to\s+([^;]+);", re.I)
BAD_GRANT = re.compile(r"grant\s+(?:update|delete|all|truncate)\b[^;]*?\bon\s+public\.beol_rag_", re.I)
# 옛 봇 이름: 낱말을 쪼개 써서 이 파일 자신이 걸리지 않게 한다.
OLD_BOT = re.compile("code" + r"[-_ ]?" + "bot", re.I)


def read(path):
    return Path(path).read_text(encoding="utf-8")


def rag_sources():
    return sorted(p for p in RAG.rglob("*") if p.is_file() and p.suffix in (".html", ".ts"))


def section(text, heading):
    """heading으로 시작하는 줄부터 끝까지."""
    i = text.index(heading)
    return text[i:]


def readme_rag_section():
    text = read(README)
    m = re.search(r"^## RAG 화면.*?(?=^## |\Z)", text, re.S | re.M)
    return m.group(0) if m else ""


class RagKeyTest(unittest.TestCase):
    def test_sources_exist(self):
        names = [p.name for p in rag_sources()]
        self.assertIn("beol_rag.html", names)
        self.assertIn("index.ts", names)
        self.assertIn("lib.ts", names)

    def test_no_openai_key_shape(self):
        for p in rag_sources():
            self.assertIsNone(OPENAI_KEY.search(read(p)), p.name)

    def test_jwt_payload_role_is_anon(self):
        for p in rag_sources():
            for tok in JWT.findall(read(p)):
                payload = tok.split(".")[1]
                data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
                self.assertEqual(data.get("role"), "anon", p.name)

    def test_openai_key_name_only_in_env_get(self):
        total = 0
        for p in rag_sources():
            text = read(p)
            n_all = text.count("OPENAI_API_KEY")
            n_env = text.count('Deno.env.get("OPENAI_API_KEY")')
            self.assertEqual(n_all, n_env, p.name)
            if n_all:
                self.assertEqual(p.name, "index.ts")
            total += n_all
        self.assertGreaterEqual(total, 1)

    def test_no_service_role_key_name(self):
        for p in rag_sources():
            self.assertNotIn("SUPABASE_SERVICE_ROLE_KEY", read(p), p.name)


class RagHtmlTest(unittest.TestCase):
    def test_no_external_resources(self):
        for p in [PAGE] + MOCKUPS:
            text = read(p).replace(SUPABASE_HOST, "")
            for pat in EXTERNAL_RES:
                m = pat.search(text)
                self.assertIsNone(m, "%s: %s" % (p.name, m and m.group(0)))

    def test_page_has_no_web_url_except_backend(self):
        # 사내 리눅스 환경은 웹에 나가지 못한다. 데이터 서버(Supabase) 주소 말고는 http(s) 주소를 두지 않는다.
        text = read(PAGE).replace("https://" + SUPABASE_HOST, "")
        m = re.search(r"https?://", text)
        self.assertIsNone(m, m and text[m.start():m.start() + 60])

    def test_page_has_exactly_one_jwt_anon_for_project(self):
        toks = JWT.findall(read(PAGE))
        self.assertEqual(len(toks), 1)
        payload = toks[0].split(".")[1]
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        self.assertEqual(data.get("role"), "anon")
        self.assertEqual(data.get("ref"), PROJECT_REF)

    def test_no_new_style_secret_key_anywhere_in_rag(self):
        for p in RAG.rglob("*"):
            if p.is_file():
                self.assertIsNone(SECRET_KEY_SHAPE.search(p.read_text(encoding="utf-8", errors="ignore")), p.name)

    def test_page_has_csp_meta_with_supabase_connect_src(self):
        text = read(PAGE)
        m = re.search(r"""<meta[^>]+http-equiv\s*=\s*["']Content-Security-Policy["'][^>]*>""", text, re.I)
        self.assertIsNotNone(m)
        cs = re.search(r"""connect-src([^;"']*)""", m.group(0))
        self.assertIsNotNone(cs)
        self.assertIn(SUPABASE_HOST, cs.group(1))

    def test_page_has_config_constants(self):
        text = read(PAGE)
        for name in ("const SUPABASE_URL", "const ANON_KEY", "const FUNCTION_URL"):
            self.assertIn(name, text)

    def test_page_has_no_inner_html(self):
        self.assertNotIn("innerHTML", read(PAGE))

    def test_mockups_do_not_fetch(self):
        for p in MOCKUPS:
            self.assertNotIn("fetch(", read(p), p.name)


class RagFunctionTest(unittest.TestCase):
    def test_lib_limits(self):
        text = read(LIB_TS)
        for pat in (r"MAX_K\s*=\s*8\b", r"DEFAULT_K\s*=\s*5\b", r"MAX_MESSAGES\s*=\s*12\b",
                    r"MAX_QUESTION_CHARS\s*=\s*1000\b", r"MAX_BODY_BYTES\s*=\s*204800\b",
                    r"""["']text-embedding-3-small["']""", r"EMBED_DIM\s*=\s*1536\b"):
            self.assertRegex(text, pat)

    def test_no_temperature(self):
        for p in (INDEX_TS, LIB_TS):
            self.assertNotIn("temperature", read(p).lower(), p.name)

    def test_max_completion_tokens(self):
        self.assertIn("max_completion_tokens", read(INDEX_TS))

    def test_single_console_call(self):
        self.assertEqual(len(re.findall(r"console\.", read(INDEX_TS))), 1)


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


class RagSchemaDocTest(unittest.TestCase):
    def setUp(self):
        self.text = read(SCHEMA_MD)
        self.rag = section(self.text, "## RAG 화면용")

    def test_required_names(self):
        for name in ("beol_rag_is_complete", "beol_rag_chunks", "beol_rag_facets", "beol_rag_search",
                     "beol_rag_feedback", "content_tsv", "security definer", "search_path",
                     "beol_rag_anon_read_slides"):
            self.assertIn(name, self.text)

    def test_no_other_app_tables_in_rag_section(self):
        for name in ("summaries", "sources", "source_tags", "public.tags"):
            self.assertNotIn(name, self.rag)

    def grants(self, name):
        return [m for m in TABLE_GRANT.finditer(self.rag) if m.group(3) == name]

    def test_revoke_before_grant(self):
        for name in ("beol_rag_chunks", "beol_rag_facets", "beol_rag_feedback"):
            rev = re.search(r"revoke\s+all\s+on\s+public\.%s\b" % name, self.rag)
            gr = self.grants(name)
            self.assertIsNotNone(rev, name)
            self.assertTrue(gr, name)
            self.assertLess(rev.start(), gr[0].start(), name)

    def test_table_grants_only_to_anon_and_authenticated(self):
        found = TABLE_GRANT.findall(self.rag)
        self.assertTrue(found)
        for _verb, _cols, name, to in found:
            self.assertEqual([x.strip() for x in to.split(",")], ["anon", "authenticated"], name)

    def test_rag_section_has_no_write_grants_beyond_insert(self):
        self.assertIsNone(BAD_GRANT.search(self.rag))

    def test_feedback_insert_grant_excludes_id_and_created_at(self):
        gr = [m for m in self.grants("beol_rag_feedback") if m.group(1).lower() == "insert"]
        self.assertEqual(len(gr), 1)
        cols = [c.strip() for c in (gr[0].group(2) or "").strip("() \n").split(",") if c.strip()]
        self.assertTrue(cols)
        self.assertNotIn("id", cols)
        self.assertNotIn("created_at", cols)


NODE = shutil.which("node")
LIB_CASES_JS = r"""
import * as lib from %(url)s;
const long = (n) => "가".repeat(n);
const msgs = [];
for (let i = 0; i < 29; i++) msgs.push({ role: i %% 2 ? "assistant" : "user", content: "m" + i });
msgs.push({ role: "user", content: "last" });
const ok = (b) => lib.validateInput(b);
const out = {
  fix_basic: lib.fixCitations("가[1, 3]", 5),
  fix_out_of_range: lib.fixCitations("가[9]", 5),
  fix_after_alnum: lib.fixCitations("저항은 TaN[1], 두께는 10nm[2][9].", 5),
  fix_range: lib.fixCitations("가[1-3]", 5),
  q1001: ok({ messages: [{ role: "user", content: long(1001) }] }),
  q1000: ok({ messages: [{ role: "user", content: long(1000) }] }),
  msgs30: ok({ messages: msgs }),
  long_assistant: ok({ messages: [{ role: "user", content: "a" }, { role: "assistant", content: long(5000) },
                                  { role: "user", content: "b" }] }),
  k50: ok({ messages: [{ role: "user", content: "a" }], k: 50 }),
  proto: ok(JSON.parse('{"messages":[{"role":"user","content":"a"}],"filters":{"__proto__":["x"]}}')),
  title: lib.titleOf("\n\n# 제목\n본문"),
  guide: lib.NO_ANSWER_GUIDE,
  noans_missing_guide: lib.finalizeAnswer("자료에 없음 — 근거에 Ru etch passivation 이력이 없습니다[2].", 5),
  noans_with_guide: lib.finalizeAnswer("자료에 없음 — 가격 정보가 없습니다. " + lib.NO_ANSWER_GUIDE, 5),
  noans_with_reference: lib.finalizeAnswer(
    "자료에 없음 — SF1.0 평가에 Ru 이력이 없습니다[1]. " + lib.NO_ANSWER_GUIDE + " 참고로 [2]는 Ru depo 평가입니다[2][9].", 5),
  normal_answer: lib.finalizeAnswer("Via 저항이 기준 안에 들었다[1].", 5),
  siblings: lib.attachSiblings(
    lib.buildEvidence([
      { chunk_id: "h1", file_id: "aaaa", seq: 2, content: "# A2" },
      { chunk_id: "h2", file_id: "bbbb", seq: 1, content: "# B1" },
      { chunk_id: "h3", file_id: "aaaa", seq: 4, content: "# A4" },
    ], {}),
    [
      { chunk_id: "h1", file_id: "aaaa", seq: 2, content: "# A2" },
      { chunk_id: "a3", file_id: "aaaa", seq: 3, content: "# A3" },
      { chunk_id: "a1", file_id: "aaaa", seq: 1, content: "# A1" },
      { chunk_id: "h3", file_id: "aaaa", seq: 4, content: "# A4" },
      { chunk_id: "b2", file_id: "bbbb", seq: 2, content: "# B2" },
      { chunk_id: "zz", file_id: "cccc", seq: 1, content: "# 다른 파일" },
    ], {}),
  sib_prompt: "",
  q_trailing: lib.finalizeAnswer("저항이 기준 안에 들었습니다[1]. 원하신 답이 맞을까요? 😊[1][2]", 5),
  q_only_cite: lib.finalizeAnswer("저항이 기준 안에 들었습니다[1]. 맞나요?[2]", 5),
  confirm_on: lib.buildAnswerMessages([{ role: "user", content: "q" }], [], "q", undefined, true)[0].content,
  confirm_off: lib.buildAnswerMessages([{ role: "user", content: "q" }], [], "q")[0].content,
  confirm_rate: lib.CONFIRM_QUESTION_RATE,
};
out.sib_prompt = lib.buildAnswerMessages([{ role: "user", content: "q" }], out.siblings, "q")[1].content;
console.log(JSON.stringify(out));
"""


class RagLibRunTest(unittest.TestCase):
    """node로 lib.ts를 실제 실행해 순수 함수 동작을 본다(node 22.6+ 필요)."""

    @classmethod
    def setUpClass(cls):
        if not NODE:
            raise AssertionError("node가 없다: lib.ts 실행 시험에는 node 22.6+가 필요하다")
        with tempfile.TemporaryDirectory() as td:
            mjs = Path(td) / "run_lib_cases.mjs"
            mjs.write_text(LIB_CASES_JS % {"url": json.dumps(LIB_TS.as_uri())}, encoding="utf-8")
            r = subprocess.run([NODE, "--experimental-strip-types", str(mjs)],
                               capture_output=True, text=True, encoding="utf-8", timeout=60)
        if r.returncode != 0:
            raise AssertionError("node 실행 실패: " + r.stderr[-800:])
        cls.res = json.loads(r.stdout.strip().splitlines()[-1])

    def test_fix_citations_expands_comma_list(self):
        self.assertEqual(self.res["fix_basic"], {"text": "가[1][3]", "cited": [1, 3]})

    def test_fix_citations_removes_out_of_range(self):
        self.assertEqual(self.res["fix_out_of_range"]["cited"], [])
        self.assertNotIn("[9]", self.res["fix_out_of_range"]["text"])

    def test_no_answer_appends_guide_once_without_citations(self):
        guide = self.res["guide"]
        a = self.res["noans_missing_guide"]
        self.assertEqual(a["cited"], [])
        self.assertEqual(a["text"], "자료에 없음 — 근거에 Ru etch passivation 이력이 없습니다. " + guide)
        b = self.res["noans_with_guide"]
        self.assertEqual(b["text"].count(guide), 1)
        self.assertTrue(b["text"].endswith(guide))
        # 첫 문장의 번호는 지우고, 뒤의 참고 설명은 번호를 남긴다(범위 밖 [9]는 지운다).
        c = self.res["noans_with_reference"]
        self.assertEqual(c["text"], "자료에 없음 — SF1.0 평가에 Ru 이력이 없습니다. " + guide
                         + " 참고로 [2]는 Ru depo 평가입니다[2].")
        self.assertEqual(c["cited"], [2])

    def test_trailing_confirm_question_has_no_citations(self):
        self.assertEqual(self.res["q_trailing"],
                         {"text": "저항이 기준 안에 들었습니다[1]. 원하신 답이 맞을까요? 😊", "cited": [1]})
        # 질문에만 붙은 번호는 cited에서도 빠진다.
        self.assertEqual(self.res["q_only_cite"]["cited"], [1])

    def test_confirm_question_toggle_and_rate(self):
        # 문구는 사용자가 고쳐 쓰므로 뜻만 본다: 켜면 확인 질문을 하되 번호 없이, 끄면 하지 않는다
        on, off = self.res["confirm_on"], self.res["confirm_off"]
        self.assertNotEqual(on, off)
        self.assertIn("확인 질문", on)
        self.assertIn("근거 번호", on)
        self.assertIn("확인 질문", off)
        self.assertRegex(off, r"확인 질문[^\n]*(않|마라|말라)")
        self.assertEqual(self.res["confirm_rate"], 0.3)

    def test_prompt_asks_for_html_table(self):
        p = self.res["confirm_off"]
        self.assertIn('<table class="border-collapse border">', p)
        for tag in ("<thead>", "<tbody>", "<tr>", "<th", "<td"):
            self.assertIn(tag, p)

    def test_attach_siblings_order_and_numbering(self):
        ev = self.res["siblings"]
        self.assertEqual([(e["chunk_id"], e["n"], e["kind"], e["sibling_of"]) for e in ev], [
            ("h1", 1, "hit", None), ("h2", 2, "hit", None), ("h3", 3, "hit", None),
            ("a1", 4, "sibling", 1), ("a3", 5, "sibling", 1), ("b2", 6, "sibling", 2),
        ])

    def test_answer_prompt_marks_sibling_blocks(self):
        p = self.res["sib_prompt"]
        self.assertIn("[4] (같은 파일 — [1]과 같은 파일의 다른 슬라이드) 제목: A1", p)
        self.assertIn("[1] 제목: A2", p)

    def test_normal_answer_has_no_guide(self):
        n = self.res["normal_answer"]
        self.assertEqual(n, {"text": "Via 저항이 기준 안에 들었다[1].", "cited": [1]})

    def test_fix_citations_after_alnum_token(self):
        self.assertEqual(self.res["fix_after_alnum"],
                         {"text": "저항은 TaN[1], 두께는 10nm[2].", "cited": [1, 2]})

    def test_fix_citations_expands_dash_range(self):
        self.assertEqual(self.res["fix_range"]["text"], "가[1][2][3]")
        self.assertEqual(self.res["fix_range"]["cited"], [1, 2, 3])

    def test_validate_rejects_1001_char_question(self):
        self.assertEqual(self.res["q1001"].get("code"), "BAD_INPUT")

    def test_validate_accepts_1000_char_question(self):
        self.assertTrue(self.res["q1000"]["ok"])

    def test_validate_keeps_last_12_messages(self):
        self.assertEqual(len(self.res["msgs30"]["messages"]), 12)

    def test_validate_truncates_assistant_to_4000_chars(self):
        self.assertEqual(len(self.res["long_assistant"]["messages"][1]["content"]), 4000)

    def test_validate_clamps_k_to_8(self):
        self.assertEqual(self.res["k50"]["k"], 8)

    def test_validate_rejects_proto_filter_key(self):
        self.assertEqual(self.res["proto"].get("code"), "BAD_INPUT")

    def test_title_of_skips_leading_blank_lines(self):
        self.assertEqual(self.res["title"], "제목")


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
