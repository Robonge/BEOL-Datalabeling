"""마일스톤 추적 shim: domain_engrbot이 labelbot.trace를 쓰는 유일한 통로(import 경계 — code_engrbot policy
labelbot_import_allowed). API는 labelbot/trace.py 머리말을 본다."""
from labelbot import milestones  # noqa: F401  진입점 → 마일스톤 표
from labelbot.trace import (  # noqa: F401
    aborted, fail_code, port_fail, port_in_use, post_failed, run, safe_code, serving,
)
