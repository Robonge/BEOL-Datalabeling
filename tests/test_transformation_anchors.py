"""transformation.md의 앵커가 실제 파일에 남아 있는지 본다.

사내 로컬 PC에서 에이전트(Claude Code·Roo Code)가 줄 번호 대신 앵커 문자열로 고칠 곳을 찾는다.
코드가 바뀌어 앵커가 사라지거나 두 번 이상 나오면 가이드가 틀린 곳을 가리키므로 여기서 잡는다.
"""
import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUIDE = os.path.join(REPO, "transformation.md")
ANCHOR = re.compile(r"앵커: `([^`]+)` :: `(.+)`$")


def anchors():
    with open(GUIDE, encoding="utf-8") as f:
        return [m.groups() for m in (ANCHOR.search(line.rstrip()) for line in f) if m]


class TransformationAnchorTest(unittest.TestCase):
    def test_has_anchors(self):
        self.assertGreaterEqual(len(anchors()), 15)

    def test_each_anchor_appears_once(self):
        for path, text in anchors():
            with self.subTest(path=path, anchor=text):
                full = os.path.join(REPO, *path.split("/"))
                self.assertTrue(os.path.isfile(full), path)
                with open(full, encoding="utf-8") as f:
                    self.assertEqual(f.read().count(text), 1, "앵커가 정확히 한 번 나와야 한다")

    def test_user_input_slots_present(self):
        with open(GUIDE, encoding="utf-8") as f:
            s = f.read()
        for tag in ("USER_INPUT:LLM BEGIN", "USER_INPUT:LLM END", "USER_INPUT:S3 BEGIN", "USER_INPUT:S3 END"):
            self.assertIn(tag, s)


if __name__ == "__main__":
    unittest.main()
