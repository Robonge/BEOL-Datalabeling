"""engrbot.synthetic로 옮겼다. 테스트의 `from engrbot.tests import fixturegen`가 같은 모듈 객체를 받게 한다(mock.patch 포함)."""
import sys

from engrbot import synthetic

sys.modules[__name__] = synthetic
