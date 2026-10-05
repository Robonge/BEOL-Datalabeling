"""skill 문서(.claude/skills/*/SKILL.md)가 부르는 CLI 명령이 동결된 CLI 스냅샷에 있는지 확인한다.

리팩토링으로 서브커맨드나 하위 동작 이름이 바뀌면 skill 절차가 깨지므로 여기서 먼저 잡는다.
"""
import glob
import json
import os
import re
import unittest

from tests.contracts import _support

SKILL_GLOB = os.path.join(_support.REPO_ROOT, ".claude", "skills", "*", "SKILL.md")
CMD = re.compile(r"python -m (labelbot|engrbot|codebot) ([a-z][a-z-]*)(?: ([a-z][a-z-]*))?")


def _snapshot(bot):
    with open(os.path.join(_support.SNAP_DIR, "cli_%s.json" % bot), encoding="utf-8") as f:
        return json.load(f)


def skill_commands():
    found = []
    for path in sorted(glob.glob(SKILL_GLOB)):
        with open(path, encoding="utf-8") as f:
            text = f.read()
        skill = os.path.basename(os.path.dirname(path))
        for m in CMD.finditer(text):
            found.append((skill, m.group(1), m.group(2), m.group(3)))
    return found


class SkillCommandContract(unittest.TestCase):
    def test_skill_docs_reference_commands(self):
        self.assertTrue(skill_commands(), "SKILL.md에서 명령을 하나도 찾지 못했다")

    def test_skill_commands_exist_in_cli(self):
        snaps = {b: _snapshot(b) for b in ("labelbot", "engrbot", "codebot")}
        for skill, bot, sub, action in skill_commands():
            with self.subTest(skill=skill, cmd="%s %s %s" % (bot, sub, action or "")):
                key = "%s %s" % (bot, sub)
                self.assertIn(key, snaps[bot], "%s가 부르는 '%s'가 CLI에 없다" % (skill, key))
                if action:
                    # 하위 서브커맨드이거나, 그 명령 도움말에 나오는 동작 이름(positional choice)이어야 한다
                    nested = "%s %s" % (key, action)
                    self.assertTrue(nested in snaps[bot] or action in json.dumps(snaps[bot][key], ensure_ascii=False),
                                    "%s가 부르는 '%s'를 CLI에서 찾지 못했다" % (skill, nested))


if __name__ == "__main__":
    unittest.main()
