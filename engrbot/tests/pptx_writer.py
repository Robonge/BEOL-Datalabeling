"""engrbot.pptx_writer로 옮겼다. 테스트의 `from engrbot.tests import pptx_writer`가 같은 모듈 객체를 받게 한다(mock.patch 포함)."""
import sys

from engrbot import pptx_writer

sys.modules[__name__] = pptx_writer
