"""공용 데이터 폴더(workspaces/_domain_engrbot)의 위치.

2026-10-06 이름 변경 전 폴더(workspaces/_engrbot)가 남아 있으면 새 폴더를 조용히 비어 있는 채로 읽지 않도록
호출한 쪽이 LEGACY_DATA_DIR로 멈춘다. 옮기는 방법은 SKILL.md 오류 표에 있다.
"""
import os

DATA_DIRNAME = "_domain_engrbot"
LEGACY_DIRNAME = "_engrbot"


def data_path(workspaces_dir, kind):
    """<workspaces>/_domain_engrbot/<kind>. 검사하지 않는 순수 경로(모듈 상수용)."""
    return os.path.join(workspaces_dir, DATA_DIRNAME, kind)


def legacy_exists(workspaces_dir):
    """옛 데이터 폴더가 남아 있는가(새 폴더가 함께 있어도 True)."""
    return os.path.isdir(os.path.join(workspaces_dir, LEGACY_DIRNAME))
