"""실행 산출물 골든 테스트(US-001B). report.render_md, feedback.build, harness.evaluate, cli.main을 나누기 전에
CLI 실행 결과를 바이트 단위로 묶어 둔다. 리팩터링 뒤에도 같은 입력이면 같은 바이트가 나와야 한다.

시나리오(모두 tempfile.mkdtemp() 임시 작업 폴더, judge는 기본 policy의 transport=mock):
- clean   : synthetic seed=7, n_files=4. `run`(기본 층) → `feedback`(결정 없음).
- defects : reviewfix.scenario(seed=7, n_files=12)로 결함을 심은 번들. `run --layers L0..L6(L4·L5 포함)`
            → qa/inbox에 검토 결정(확인·교정·판단 불가, rework·false_positive, 자동 수정 규칙 승인·거절) → `feedback`.
- eval    : `eval --golden synthetic:7 --per-mutator 2`(하네스 mock judge).

정규화(_normalize). 이것 말고는 모두 바이트 그대로 비교한다:
1. 이번 실행의 qa_run_id 문자열(예: QA-20261005T045227-8a9d) → "<QA_RUN_ID>". 실제 ID만 글자 그대로 바꾼다.
2. ISO-8601 UTC 시각(YYYY-MM-DDTHH:MM:SS[.ffffff]Z, manifest의 started_at·finished_at) → "<TS>".
   날짜만 있는 값(예: 2024-03-05)은 바꾸지 않는다.
3. 임시 폴더 경로(그대로, "/" 구분, JSON 이스케이프 "\\\\") → "<TMP>". 지금 산출물에는 없지만 새면 고정 값으로 드러난다.
4. defects가 inbox에 넣은 결정 파일의 sha256(golden.decisions_sha256). 결정 파일에 qa_run_id가 들어가 실행마다
   바뀐다. 그 실제 해시(64자)와 feedback.md에 찍히는 앞 16자만 글자 그대로 "<DECISIONS_SHA256>"으로 바꾼다.
5. eval 파일명의 시각(eval_<YYYYMMDDTHHMMSS>.json)은 비교 대상 이름에서 빠진다(eval.json, eval.md로 저장).
골든 파일 쪽만 CRLF를 LF로 읽는다(core.autocrlf=true 체크아웃 대비). 산출물은 LF로 쓰이므로 바이트 비교와 같다.

골든 다시 만들기: GOLDEN_UPDATE=1 python -m unittest engrbot.tests.test_golden_outputs
골든 파일 형식은 .json, .jsonl, .md, .html만 쓴다(CLAUDE.md 쓰기 규칙). 콘솔 출력은 console.md에 둔다.
"""
import contextlib
import difflib
import glob
import io as stdio
import os
import re
import shutil
import tempfile
import unittest

from engrbot import cli, golden, io
from engrbot.adapters import bundle_files
from engrbot import synthetic
from engrbot.tests import reviewfix as rf

GOLDEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden_outputs")
UPDATE = os.environ.get("GOLDEN_UPDATE") == "1"
ALL_LAYERS = "L0,L1,L2,L3A,L3B,L4,L5,L6"

# 실행 폴더 안 산출물 → 골든 파일 이름
RUN_ARTIFACTS = (
    ("report.md", "report.md"),
    ("report.json", "report.json"),
    ("manifest.json", "manifest.json"),
    ("verdicts.jsonl", "verdicts.jsonl"),
    ("review_queue.jsonl", "review_queue.jsonl"),
    ("taxonomy_candidates.md", "taxonomy_candidates.md"),
    ("review.html", "review.html"),
    (os.path.join("feedback", "feedback.json"), "feedback.json"),
    (os.path.join("feedback", "feedback.md"), "feedback.md"),
)

TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z")


def _normalize(text, qa_run_id=None, tmp=None, decisions_sha=None):
    """모듈 docstring의 정규화 규칙 1~4."""
    if decisions_sha:
        text = text.replace(decisions_sha, "<DECISIONS_SHA256>").replace(decisions_sha[:16], "<DECISIONS_SHA256>")
    if qa_run_id:
        text = text.replace(qa_run_id, "<QA_RUN_ID>")
    if tmp:
        for form in (tmp.replace("\\", "\\\\"), tmp.replace("\\", "/"), tmp):
            text = text.replace(form, "<TMP>")
    return TS_RE.sub("<TS>", text)


def _read(path):
    with open(path, "rb") as f:
        return f.read().decode("utf-8")


def _cli(argv, out):
    with contextlib.redirect_stdout(out):
        rc = cli.main(argv)
    if rc != 0:
        raise AssertionError("cli %s rc=%s: %s" % (argv[0], rc, out.getvalue()))


class _GoldenCase(unittest.TestCase):
    scenario = None  # golden_outputs/<scenario>/

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="engrbot_golden_")
        cls.qa_run_id = None
        cls.decisions_sha = None
        cls.outputs = {}  # 골든 이름 → 정규화한 본문
        try:
            cls.produce()
        except Exception:
            shutil.rmtree(cls.tmp, True)
            raise

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    @classmethod
    def norm(cls, text):
        return _normalize(text, cls.qa_run_id, cls.tmp, cls.decisions_sha)

    @classmethod
    def collect_run(cls, ws):
        run_dir = io.QaPaths(ws).run_dir(cls.qa_run_id)
        for rel, name in RUN_ARTIFACTS:
            cls.outputs[name] = cls.norm(_read(os.path.join(run_dir, rel)))

    @classmethod
    def run_cli(cls, ws, bdir, extra=(), decisions=None):
        """run → (decisions가 있으면 inbox에 넣고) feedback. 콘솔 전체를 console.md로 남긴다."""
        out = stdio.StringIO()
        _cli(["run", "--workspace", ws, "--bundle", bdir] + list(extra), out)
        paths = io.QaPaths(ws)
        cls.qa_run_id = paths.list_runs()[-1]
        if decisions is not None:
            doc = decisions(cls.qa_run_id)
            cls.decisions_sha = golden.decisions_sha256(doc)
            io.write_json(os.path.join(paths.inbox, "qa_decisions.json"), doc)
        _cli(["feedback", "--workspace", ws, "--qa-run", cls.qa_run_id, "--bundle", bdir], out)
        cls.outputs["console.md"] = cls.norm(out.getvalue())
        cls.collect_run(ws)

    def test_outputs_match_golden(self):
        sdir = os.path.join(GOLDEN_DIR, self.scenario)
        if UPDATE:
            os.makedirs(sdir, exist_ok=True)
            for name in os.listdir(sdir):
                if name not in self.outputs:
                    os.remove(os.path.join(sdir, name))
            for name, text in self.outputs.items():
                with open(os.path.join(sdir, name), "wb") as f:
                    f.write(text.encode("utf-8"))
        self.assertTrue(os.path.isdir(sdir), "골든 없음: GOLDEN_UPDATE=1로 만든다 (%s)" % self.scenario)
        self.assertEqual(sorted(os.listdir(sdir)), sorted(self.outputs), "골든 파일 목록이 산출물과 다르다")
        for name, got in sorted(self.outputs.items()):
            with self.subTest(file=name):
                want = _read(os.path.join(sdir, name)).replace("\r\n", "\n")
                if got != want:
                    diff = "\n".join(list(difflib.unified_diff(want.splitlines(), got.splitlines(), "golden", "actual",
                                                               lineterm="", n=1))[:40])
                    self.fail("%s/%s 가 골든과 다르다(GOLDEN_UPDATE=1로 갱신):\n%s" % (self.scenario, name, diff))

    def test_no_unnormalized_volatile_values(self):
        """정규화 뒤에 실행 ID·시각·임시 경로가 남아 있지 않다."""
        for name, text in self.outputs.items():
            with self.subTest(file=name):
                self.assertNotRegex(text, r"QA-\d{8}T\d{6}-[0-9a-f]{4}")
                self.assertNotIn("engrbot_golden_", text)
                self.assertIsNone(TS_RE.search(text))


class CleanRunGoldenTest(_GoldenCase):
    scenario = "clean"

    @classmethod
    def produce(cls):
        fx = synthetic.generate(seed=7, n_files=4)
        bdir = os.path.join(cls.tmp, "bundle")
        bundle_files.save(fx.bundle, bdir, blobs=fx.blobs, images=fx.images)
        cls.run_cli(os.path.join(cls.tmp, "ws"), bdir)


class DefectRunGoldenTest(_GoldenCase):
    scenario = "defects"

    @classmethod
    def produce(cls):
        # reviewfix가 fx.bundle에 결함을 심는다(판정은 아래 CLI run이 처음부터 다시 한다)
        _res, fx, roles = rf.scenario(seed=7, n_files=12, root=os.path.join(cls.tmp, "seed_ws"))
        bdir = os.path.join(cls.tmp, "bundle")
        bundle_files.save(fx.bundle, bdir, blobs=fx.blobs, images=fx.images)
        recs = {r["record_id"]: r for r in fx.bundle.records}

        def field(rid):
            return "axis:%s" % rf._value_axis(recs[rid])

        def decisions(qa_run_id):
            a, b, c = roles["review"]
            r1, r2 = roles["reject"]
            va, qa = golden.bot_value(recs[a], field(a))
            return rf.decisions_doc(
                qa_run_id,
                decisions=[
                    {"record_id": a, "field": field(a), "decision": "confirm", "value": va, "quote": qa},
                    {"record_id": b, "field": field(b), "decision": "correct", "value": ["unknown"], "quote": None},
                    {"record_id": c, "field": field(c), "decision": "cannot_judge", "value": None, "quote": None},
                ],
                rejects=[
                    {"record_id": r1, "decision": "rework", "corrections": []},
                    {"record_id": r2, "decision": "false_positive", "corrections": []},
                ],
                autofix=[
                    {"rule": "date_iso", "decision": "approve", "except": [roles["autofix_date"][0]]},
                    {"rule": "taxonomy_case", "decision": "reject", "except": []},
                ])

        cls.run_cli(os.path.join(cls.tmp, "ws"), bdir, extra=["--layers", ALL_LAYERS], decisions=decisions)


class EvalGoldenTest(_GoldenCase):
    scenario = "eval"

    @classmethod
    def produce(cls):
        ws = os.path.join(cls.tmp, "ws")
        out = stdio.StringIO()
        _cli(["eval", "--workspace", ws, "--golden", "synthetic:7", "--per-mutator", "2"], out)
        cls.outputs["console.md"] = cls.norm(out.getvalue())
        qa = io.QaPaths(ws).qa
        for ext in ("json", "md"):
            found = glob.glob(os.path.join(qa, "eval_*.%s" % ext))
            if len(found) != 1:
                raise AssertionError("eval_*.%s %d개" % (ext, len(found)))
            cls.outputs["eval.%s" % ext] = cls.norm(_read(found[0]))


class NormalizerTest(unittest.TestCase):
    def test_rules(self):
        tmp = r"C:\Temp\engrbot_golden_x"
        src = ('{"qa_run_id": "QA-20261005T045227-8a9d", "started_at": "2026-10-05T04:52:27Z", '
               '"t2": "2026-10-05T04:52:27.123456Z", "date": "2024-03-05", "p": "C:\\\\Temp\\\\engrbot_golden_x\\\\a", '
               '"q": "C:/Temp/engrbot_golden_x/b", "other": "QA-20261004T010203-0a0b"}')
        got = _normalize(src, "QA-20261005T045227-8a9d", tmp)
        self.assertEqual(got, '{"qa_run_id": "<QA_RUN_ID>", "started_at": "<TS>", "t2": "<TS>", "date": "2024-03-05", '
                              '"p": "<TMP>\\\\a", "q": "<TMP>/b", "other": "QA-20261004T010203-0a0b"}')

    def test_decisions_sha_exact_only(self):
        sha = "c09c52c8c01ceed07b70ccf93df058e65d9f385d548d2d70bc2d0fff68b2d3d6"
        other = "b8afea6fb2894b8e54e8445b126dfc039c273ba97b1e06ec915905a678e53352"
        got = _normalize("%s|%s|%s|%s" % (sha, sha[:16], sha[:15], other), decisions_sha=sha)
        self.assertEqual(got, "<DECISIONS_SHA256>|<DECISIONS_SHA256>|%s|%s" % (sha[:15], other))


del _GoldenCase  # 기반 클래스 자체는 돌리지 않는다

if __name__ == "__main__":
    unittest.main()
