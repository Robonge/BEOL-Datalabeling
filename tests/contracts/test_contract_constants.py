"""모듈 수준 상수 계약 동결: 사유 코드, 실패 단계, 표 목록, 허용 확장자, 작업 폴더 하위 폴더, 기본 설정,
domain_engrbot issue code 카탈로그. 실제로 모듈에 정의된 데이터만 읽는다.
"""
import importlib
import unittest

from tests.contracts import _support

# (모듈, 속성). 속성 'A.B'는 클래스 속성이다.
CONSTANTS = [
    ("labelbot.review", "REASONS"),
    ("labelbot.review", "REASON_LABELS"),
    ("labelbot.revisit", "REASONS"),
    ("labelbot.revisit", "REASON_LABELS"),
    ("labelbot.revisit", "TARGET_REASONS"),
    ("labelbot.revisit", "TARGETS"),
    ("labelbot.revisit", "MEMO_REQUIRED"),
    ("labelbot.revisit", "MEMO_MAX"),
    ("labelbot.revisit", "DROP_CODES"),
    ("labelbot.store", "SCHEMA_VERSION"),
    ("labelbot.store", "INDEXES"),
    ("labelbot.util", "ALLOWED_EXT"),
    ("labelbot.workspace", "Workspace.SUBDIRS"),
    ("labelbot.workspace", "DEFAULT_CONFIG"),
    ("labelbot.ingest", "OOXML_SIG"),
    ("labelbot.ingest", "OLE_SIG"),
    ("labelbot.ingest", "OOXML_EXT"),
    ("labelbot.ingest", "OLE_EXT"),
    ("labelbot.ingest", "PARSED_EXT"),
    ("labelbot.ingest", "TEXT_EXT"),
    ("labelbot.slideimg", "STAGE"),
    ("labelbot.slidepush", "STAGE"),
    ("labelbot.finals", "UNREVIEWED"),
    ("labelbot.finals", "CONFIRMED"),
    ("labelbot.finals", "CORRECTED"),
    ("labelbot.finals", "RECHECK"),
    ("labelbot.label", "ANSWERS"),
    ("labelbot.classify", "NA"),
    ("labelbot.classify", "UNKNOWN"),
    ("labelbot.classify", "CHUNK_TYPES"),
    ("labelbot.dashboard", "ALERT_LABELS"),
    ("labelbot.feedback", "RULES_FILENAME"),
    ("labelbot.feedback", "AXIS_KINDS"),
    ("labelbot.feedback", "ANSWER_KINDS"),
    ("labelbot.questions", "GEN_PREFIX"),
    ("domain_engrbot.adapters.labelbot_ws", "REQUIRED"),
    ("domain_engrbot.adapters.labelbot_ws", "LABEL_STAGE"),
    ("domain_engrbot.adapters.labelbot_ws", "RECORD_STAGES"),
    ("domain_engrbot.adapters.labelbot_ws", "SOURCE_FAIL_STAGES"),
]


def _get(mod, attr):
    obj = importlib.import_module(mod)
    for part in attr.split("."):
        obj = getattr(obj, part)
    return obj


class ConstantsContract(unittest.TestCase):
    def test_labelbot_constants(self):
        data = {}
        for mod, attr in CONSTANTS:
            with self.subTest(constant="%s.%s" % (mod, attr)):
                data["%s.%s" % (mod, attr)] = _get(mod, attr)
        store = importlib.import_module("labelbot.store")
        data["labelbot.store.TABLES:order"] = list(store.TABLES)
        chunker = importlib.import_module("labelbot.chunker")
        data["labelbot.chunker.METHODS:shape"] = {
            m: {ext: "%s.%s" % (fn.__module__, fn.__qualname__) for ext, fn in exts.items()}
            for m, exts in chunker.METHODS.items()
        }
        _support.check(self, "constants", data)

    def test_domain_engrbot_issue_codes(self):
        codes = importlib.import_module("domain_engrbot.codes")
        cat = codes.catalog()
        data = {
            code: {k: v for k, v in entry.items() if k != "desc"}
            for code, entry in cat.items()
        }
        data["__order__"] = list(cat)
        _support.check(self, "domain_engrbot_issue_codes", data)


if __name__ == "__main__":
    unittest.main()
