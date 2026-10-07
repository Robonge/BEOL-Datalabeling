"""테스트용 더미 pptx 폴더 위치(한 곳에서 정한다).

더미 폴더는 저장소 밖 <저장소>/../dummy pptx files에 고정한다(2026-10-08 사용자 결정, 더 옮기지 않는다).
폴더가 없으면 건너뛰지 않고 오류를 낸다(skip은 핵심 파이프라인 커버리지를 숨긴다, C4_TEST_SKIP).
파일은 labelbot.ingest.read_input으로만 읽고, 여기서는 폴더 존재만 본다.
"""
import os

from labelbot.workspace import CODE_ROOT

DUMMY_DIR = os.path.join(os.path.dirname(CODE_ROOT), "dummy pptx files")

if not os.path.isdir(DUMMY_DIR):
    raise RuntimeError("DUMMY_DIR_NOT_FOUND: 더미 pptx 폴더가 없다: " + DUMMY_DIR)
