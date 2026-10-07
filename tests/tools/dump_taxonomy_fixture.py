"""taxonomy/taxonomy.json에서 tests/fixtures/default_taxonomy_rows.jsonl을 다시 만든다.

사용: python tests/tools/dump_taxonomy_fixture.py          fixture를 덮어쓴다
      python tests/tools/dump_taxonomy_fixture.py --check  최신인지 건수만 알린다(쓰지 않음, 다르면 종료 코드 1)
json은 labelbot.ingest.read_input(DRM 규칙의 유일한 원본 열기 경로)으로 읽는다. 셀 내용은 출력하지 않는다.
행 구성은 tests/test_defaults_taxonomy.doc_rows와 같다.
"""
import argparse
import collections
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from labelbot import taxonomy  # noqa: E402
from labelbot.ingest import read_input  # noqa: E402
from tests.test_defaults_taxonomy import JSON_PATH, ROWS_PATH, doc_rows  # noqa: E402


def build_lines():
    doc = taxonomy.decode_doc(read_input(JSON_PATH, None))
    return [json.dumps(r, ensure_ascii=False) for r in doc_rows(doc)]


def current_lines():
    try:
        with open(ROWS_PATH, "r", encoding="utf-8") as f:
            return [line.rstrip("\n") for line in f if line.strip()]
    except FileNotFoundError:
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fixture가 최신인지 건수만 보고하고 쓰지 않는다")
    a = ap.parse_args()
    new, old = build_lines(), current_lines()
    if a.check:
        diff = sum(((collections.Counter(new) - collections.Counter(old)) + (collections.Counter(old) - collections.Counter(new))).values())
        print("[dump] json 행 %d, fixture 행 %d, 다른 행 %d(추가·삭제 합, %s)" % (
            len(new), len(old), diff, "최신" if not diff else "갱신 필요"))
        return 1 if diff else 0
    with open(ROWS_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(line + "\n" for line in new))
    print("[dump] fixture %d행 기록" % len(new))
    return 0


if __name__ == "__main__":
    sys.exit(main())
