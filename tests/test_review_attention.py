"""검수 화면 DATA의 chunk별 attention(확인 필요) 판정. 모든 값은 가짜다. 사내 파일·작업 폴더를 읽지 않는다."""
import json
import os
import re
import shutil
import tempfile
import unittest

from labelbot import review, store, taxonomy
from labelbot.questions import GEN_PREFIX

ALL = {"A", "B", "C"}


def _chunk(axes=None, answers=None, controls=None):
    return {"axes": axes or {}, "answers": answers or {}, "controls": controls or []}


def _ax(conf=0.9, values=("v",)):
    return {"values": list(values), "evidence": "", "confidence": conf}


class AttentionForTest(unittest.TestCase):
    def att(self, chunk, gen_map=None, editable=ALL):
        return review.attention_for(chunk, gen_map or {}, 0.7, editable, sample_rate=0)  # 표본은 따로 본다

    def test_low_conf_and_boundary(self):
        got = self.att(_chunk({"A": _ax(0.69), "B": _ax(0.7), "C": _ax(0.9)}))
        self.assertEqual(got, {"axes": {"A": ["LOW_CONF"]}, "questions": {}})

    def test_none_confidence_not_low(self):
        self.assertEqual(self.att(_chunk({"A": _ax(None)}))["axes"], {})

    def test_unknown(self):
        got = self.att(_chunk({"A": _ax(0.9, ("unknown",)), "B": _ax(0.9, ("값",))}))
        self.assertEqual(got["axes"], {"A": ["UNKNOWN"]})

    def test_unknown_with_low_conf_has_both(self):
        self.assertEqual(self.att(_chunk({"A": _ax(0.1, ("unknown",))}))["axes"], {"A": ["LOW_CONF", "UNKNOWN"]})

    def test_verify_x_only_target_axis(self):
        q = GEN_PREFIX + "x1"
        ans = {q: {"answer": "X", "quote": "", "confidence": 0.9},
               GEN_PREFIX + "o1": {"answer": "O", "quote": "", "confidence": 0.9},
               "Q-COM-001": {"answer": "X", "quote": "", "confidence": 0.9}}
        got = self.att(_chunk({"A": _ax(), "B": _ax()}, ans),
                       {q: "A", GEN_PREFIX + "o1": "B", "Q-COM-001": "B"})
        self.assertEqual(got["axes"], {"A": ["VERIFY_X"]})
        self.assertEqual(got["questions"], {})

    def test_control_o(self):
        ctl = [{"qid": "Q-CTL-1", "axis": "B", "answer": "O"}, {"qid": "Q-CTL-2", "axis": "C", "answer": "X"},
               {"qid": "Q-CTL-3", "axis": None, "answer": "O"}]
        self.assertEqual(self.att(_chunk(controls=ctl))["axes"], {"B": ["CONTROL_O"]})

    def test_question_low_conf(self):
        ans = {"Q-COM-001": {"answer": "O", "quote": "", "confidence": 0.5},
               "Q-COM-002": {"answer": "O", "quote": "", "confidence": 0.7},
               "Q-COM-003": {"answer": "O", "quote": "", "confidence": None}}
        self.assertEqual(self.att(_chunk(answers=ans))["questions"], {"Q-COM-001": ["LOW_CONF"]})

    def test_ox_sample_deterministic_and_rate(self):
        ids = ["c%d" % i for i in range(2000)]
        picked = [i for i in ids if review.ox_sampled(i, "Q-COM-001")]
        self.assertTrue(150 <= len(picked) <= 250, len(picked))  # 10% 안팎
        self.assertEqual(picked, [i for i in ids if review.ox_sampled(i, "Q-COM-001")])
        self.assertFalse(any(review.ox_sampled(i, "Q-COM-001", 0) for i in ids))

    def test_ox_sample_only_confident_o_x(self):
        ans = {"Q-COM-001": {"answer": "O", "quote": "", "confidence": 0.99},
               "Q-COM-002": {"answer": "N/A", "quote": "", "confidence": 0.99},
               "Q-COM-003": {"answer": "X", "quote": "", "confidence": 0.5}}
        got = review.attention_for(dict(_chunk(answers=ans), chunk_id="c1"), {}, 0.7, ALL, sample_rate=1.0)
        self.assertEqual(got["questions"], {"Q-COM-001": ["OX_SAMPLE"], "Q-COM-003": ["LOW_CONF"]})

    def test_excluded_axes_not_flagged(self):
        ctl = [{"qid": "Q-CTL-1", "axis": "C", "answer": "O"}]
        ans = {GEN_PREFIX + "x1": {"answer": "X", "quote": "", "confidence": 0.9}}
        got = self.att(_chunk({"A": _ax(0.1, ("unknown",)), "B": _ax(0.1)}, ans, ctl),
                       {GEN_PREFIX + "x1": "A"}, editable={"B"})
        self.assertEqual(got["axes"], {"B": ["LOW_CONF"]})


RUN = "20261007T010203-at01"
SHA_F = "fa" * 8


def _tax():
    tax = taxonomy.Taxonomy()
    axes = []
    for name in ("예시축A", "예시축B", "예시축C"):
        a = taxonomy.Axis(name, "분류", True, False, False, "", "", "")
        a.values = [taxonomy.Value("값-1", None, "", "", "", 2), taxonomy.Value("값-2", None, "", "", "", 3)]
        axes.append(a)
    tax.axes = axes
    tax.questions = []
    tax.sheet_hashes = {"taxonomy": "t" * 16, "questions": "q" * 16}
    return tax


class _FakeWs:
    def __init__(self, root):
        self.root = root
        self.config = {"limits": {"images_per_chunk": 0, "questions_per_chunk": 5},
                       "flag": {"unknown_ratio_min": 0.5, "confidence_min": 0.7}}

    def path(self, *parts):
        return os.path.join(self.root, *parts)


class BuildReviewAttentionTest(unittest.TestCase):
    def test_data_has_attention(self):
        d = tempfile.mkdtemp(prefix="labelbot_attn_")
        self.addCleanup(shutil.rmtree, d, True)
        con = store.connect(":memory:")
        self.addCleanup(con.close)
        con.execute("INSERT INTO runs(run_id, command) VALUES(?, 'run')", (RUN,))
        con.execute("INSERT INTO files(file_id, file_name, rel_path, title) VALUES(?,?,?,?)",
                    (SHA_F, "가짜.txt", "폴더/가짜.txt", "제목"))
        con.execute("INSERT INTO chunks(chunk_id, file_id, seq, title, text, text_hash, images, warnings)"
                    " VALUES('c1',?,1,'제목','본문 한 줄','h1','[]','[]')", (SHA_F,))
        con.execute("INSERT INTO flagged_chunks(run_id, chunk_id, reason_codes, text_hash) VALUES(?,?,?,?)",
                    (RUN, "c1", '["LOW_CONFIDENCE"]', "h1"))
        L = "INSERT INTO labels(run_id, chunk_id, kind, key, value, status, confidence) VALUES(?,?,?,?,?,?,?)"
        con.execute(L, (RUN, "c1", "chunk_type", "", "내용", "value", None))
        con.execute(L, (RUN, "c1", "axis", "예시축A", '["값-1"]', "value", 0.69))
        con.execute(L, (RUN, "c1", "axis", "예시축B", '["unknown"]', "unknown", 0.9))
        con.execute(L, (RUN, "c1", "axis", "예시축C", '["값-2"]', "value", 0.7))
        qid = GEN_PREFIX + "t1"
        con.execute("INSERT INTO gen_questions(qid, chunk_id, axis, value, text) VALUES(?,?,?,?,?)",
                    (qid, "c1", "예시축C", "값-2", "가짜 질문"))
        con.execute(L, (RUN, "c1", "answer", qid, "X", "value", 0.9))
        con.commit()
        path, n = review.build_review(_FakeWs(d), con, RUN, _tax())
        with open(path, encoding="utf-8") as f:
            data = json.loads(re.search(r"const DATA = (.*);\n", f.read()).group(1))
        self.assertEqual(n, 1)
        self.assertEqual(data["chunks"][0]["attention"], {
            "axes": {"예시축A": ["LOW_CONF"], "예시축B": ["UNKNOWN"], "예시축C": ["VERIFY_X"]}, "questions": {}})


if __name__ == "__main__":
    unittest.main()
