"""labelbot.raglib(옛 lib.ts의 Python 판) 순수 함수 시험.

사례는 tests/test_rag_ui.py의 RagLibRunTest(LIB_CASES_JS)와 같은 입력·같은 기대값이다(18개).
"""
import json
import unittest

from labelbot import raglib as lib


def ok(body):
    """lib.ts validateInput처럼 결과 dict를 돌려준다(실패면 {ok: False, code})."""
    try:
        return dict(ok=True, **lib.validate_input(body))
    except lib.RagInputError as e:
        return {"ok": False, "code": e.code}


def long(n):
    return "가" * n


def build_cases():
    msgs = [{"role": "assistant" if i % 2 else "user", "content": "m%d" % i} for i in range(29)]
    msgs.append({"role": "user", "content": "last"})
    out = {
        "fix_basic": lib.fix_citations("가[1, 3]", 5),
        "fix_out_of_range": lib.fix_citations("가[9]", 5),
        "fix_after_alnum": lib.fix_citations("저항은 TaN[1], 두께는 10nm[2][9].", 5),
        "fix_range": lib.fix_citations("가[1-3]", 5),
        "q1001": ok({"messages": [{"role": "user", "content": long(1001)}]}),
        "q1000": ok({"messages": [{"role": "user", "content": long(1000)}]}),
        "msgs30": ok({"messages": msgs}),
        "long_assistant": ok({"messages": [{"role": "user", "content": "a"}, {"role": "assistant", "content": long(5000)},
                                           {"role": "user", "content": "b"}]}),
        "k50": ok({"messages": [{"role": "user", "content": "a"}], "k": 50}),
        "proto": ok(json.loads('{"messages":[{"role":"user","content":"a"}],"filters":{"__proto__":["x"]}}')),
        "title": lib.title_of("\n\n# 제목\n본문"),
        "guide": lib.NO_ANSWER_GUIDE,
        "noans_missing_guide": lib.finalize_answer("자료에 없음 — 근거에 Ru etch passivation 이력이 없습니다[2].", 5),
        "noans_with_guide": lib.finalize_answer("자료에 없음 — 가격 정보가 없습니다. " + lib.NO_ANSWER_GUIDE, 5),
        "noans_with_reference": lib.finalize_answer(
            "자료에 없음 — SF1.0 평가에 Ru 이력이 없습니다[1]. " + lib.NO_ANSWER_GUIDE
            + " 참고로 [2]는 Ru depo 평가입니다[2][9].", 5),
        "normal_answer": lib.finalize_answer("Via 저항이 기준 안에 들었다[1].", 5),
        "siblings": lib.attach_siblings(
            lib.build_evidence([
                {"chunk_id": "h1", "file_id": "aaaa", "seq": 2, "content": "# A2"},
                {"chunk_id": "h2", "file_id": "bbbb", "seq": 1, "content": "# B1"},
                {"chunk_id": "h3", "file_id": "aaaa", "seq": 4, "content": "# A4"},
            ], {}),
            [
                {"chunk_id": "h1", "file_id": "aaaa", "seq": 2, "content": "# A2"},
                {"chunk_id": "a3", "file_id": "aaaa", "seq": 3, "content": "# A3"},
                {"chunk_id": "a1", "file_id": "aaaa", "seq": 1, "content": "# A1"},
                {"chunk_id": "h3", "file_id": "aaaa", "seq": 4, "content": "# A4"},
                {"chunk_id": "b2", "file_id": "bbbb", "seq": 2, "content": "# B2"},
                {"chunk_id": "zz", "file_id": "cccc", "seq": 1, "content": "# 다른 파일"},
            ], {}),
        "q_trailing": lib.finalize_answer("저항이 기준 안에 들었습니다[1]. 원하신 답이 맞을까요? 😊[1][2]", 5),
        "q_only_cite": lib.finalize_answer("저항이 기준 안에 들었습니다[1]. 맞나요?[2]", 5),
        "confirm_on": lib.build_answer_messages([{"role": "user", "content": "q"}], [], "q", None, True)[0]["content"],
        "confirm_off": lib.build_answer_messages([{"role": "user", "content": "q"}], [], "q")[0]["content"],
        "confirm_rate": lib.CONFIRM_QUESTION_RATE,
    }
    out["sib_prompt"] = lib.build_answer_messages([{"role": "user", "content": "q"}], out["siblings"], "q")[1]["content"]
    return out


class RagLibTest(unittest.TestCase):
    """RagLibRunTest와 같은 18개 사례."""

    @classmethod
    def setUpClass(cls):
        cls.res = build_cases()

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


if __name__ == "__main__":
    unittest.main()
