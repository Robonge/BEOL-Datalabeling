"""prompts/*.md 템플릿 렌더링. 프롬프트 버전은 템플릿 내용 해시다."""
import os

from labelbot import util
from labelbot.workspace import CODE_ROOT

PROMPT_DIR = os.path.join(CODE_ROOT, "prompts")
_cache = {}


def load(name):
    if name not in _cache:
        with open(os.path.join(PROMPT_DIR, name + ".md"), encoding="utf-8") as f:
            text = f.read()
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
