"""severity·층 상수, 판정, 정책 로드, 실행 문맥."""
import json
import os

SEVERITIES = ("critical", "major", "minor", "info")
# C5·C6은 아직 구현된 검사가 없는 예약 층이다. registry가 등록 시 이 목록으로 layer를 검증하고,
# 테스트와 CLI가 C5·C6을 가짜 검사의 층으로 쓰므로 지우지 않는다. 정책 기본값(policy.json)은 C1~C4만 켠다.
LAYERS = ("C1", "C2", "C3", "C4", "C5", "C6")
POLICY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "defaults", "policy.json")


def decide(findings):
    """억제되지 않은 finding으로 판정한다. critical이면 REQUEST_CHANGES, major면 COMMENT, 그 밖은 APPROVE다."""
    live = [f for f in findings if not f.get("suppressed")]
    if any(f.get("severity") == "critical" for f in live):
        return "REQUEST_CHANGES"
    if any(f.get("severity") == "major" for f in live):
        return "COMMENT"
    return "APPROVE"


def default_policy():
    with open(POLICY_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


class Ctx(object):
    """검사에 넘기는 문맥. policy가 None이면 기본 정책을 쓴다."""

    def __init__(self, policy=None, root="."):
        self.policy = default_policy() if policy is None else policy
        self.root = root
