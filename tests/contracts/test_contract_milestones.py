"""마일스톤 ID 동결(추가만): snapshots/milestone_ids.json의 목록이 지금 등록부의 앞부분과 같아야 한다.

ID는 Roo skill 문구·런북·반출 status가 참조하는 계약이다. 재번호·재사용·이름 변경은 실패, 끝에 덧붙이는 것만
허용한다(덧붙였으면 CONTRACT_UPDATE=1로 스냅샷을 늘린다 — 늘리기 전에도 이 테스트는 통과한다).
"""
import json
import os
import unittest

from labelbot import milestones
from tests.contracts import _support

NAME = "milestone_ids"


class MilestoneIdsContract(unittest.TestCase):
    def test_ids_append_only(self):
        current = ["%s %s" % (mid, name) for mid, name, _ in milestones.MILESTONES]
        self.assertEqual(["M%02d" % i for i in range(len(current))], [c.split()[0] for c in current], "ID는 M00부터 빈틈없이")
        path = os.path.join(_support.SNAP_DIR, NAME + ".json")
        if _support.updating():
            snap = json.load(open(path, encoding="utf-8")) if os.path.isfile(path) else []
            self.assertEqual(snap, current[:len(snap)], "스냅샷을 늘리기만 한다(앞부분이 바뀌면 안 된다)")
            _support.check(self, NAME, current)
            return
        self.assertTrue(os.path.isfile(path), "SNAPSHOT_MISSING %s" % NAME)
        with open(path, encoding="utf-8") as f:
            snap = json.load(f)
        self.assertLessEqual(len(snap), len(current), "등록부에서 마일스톤이 사라졌다")
        self.assertEqual(snap, current[:len(snap)], "마일스톤 ID·이름은 추가만 한다(재번호·재사용·이름 변경 금지)")


if __name__ == "__main__":
    unittest.main()
