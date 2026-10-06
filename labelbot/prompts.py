"""prompts/*.md 템플릿 렌더링. 프롬프트 버전은 템플릿 내용 해시다.

'<!-- INCLUDE _조각 -->' 한 줄은 prompts/_조각.md 내용으로 바꾼다(여러 프롬프트가 같은 규칙 문장을 쓴다).
버전 해시는 조각을 펼친 뒤의 내용으로 계산한다.
"""
import os
import re

from labelbot import util
from labelbot.workspace import CODE_ROOT

PROMPT_DIR = os.path.join(CODE_ROOT, "prompts")
_INCLUDE = re.compile(r"^<!-- INCLUDE (_\w+) -->$", re.M)
_cache = {}


def _read(name):
    with open(os.path.join(PROMPT_DIR, name + ".md"), encoding="utf-8") as f:
        return f.read()


def load(name):
    if name not in _cache:
        text = _INCLUDE.sub(lambda m: _read(m.group(1)).rstrip("\n"), _read(name))
        _cache[name] = (text, util.sha256_text(text)[:12])
    return _cache[name]


def version(name):
    return load(name)[1]


def render(name, values):
    """system/user 두 메시지. 템플릿의 '<!-- USER -->' 줄로 나눈다."""
    text, _ = load(name)
    for k, v in values.items():
        text = text.replace("{{%s}}" % k, v if isinstance(v, str) else str(v))
    system, user = text.split("<!-- USER -->", 1)
    return [{"role": "system", "content": system.strip()}, {"role": "user", "content": user.strip()}]
