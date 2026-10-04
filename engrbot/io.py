"""읽기·쓰기 단일 경로.

- 쓰기는 labelbot.util.write_text를 거쳐 허용 확장자(.b64 .sqlite .json .jsonl .html .md .log)만 쓴다.
- 사람이 고치는 입력(policy.json, schema.json, 결정 파일)은 labelbot.ingest.read_input으로 읽고 inputs/에 보관한다.
- 검수봇이 직접 쓴 파일(verdicts, 캐시, 이력)은 그대로 읽는다.
"""
import base64
import json
import os
import threading

from labelbot import ingest as lb_ingest
from labelbot import util as lb_util
from labelbot.workspace import CODE_ROOT, is_forbidden_inside_code

from engrbot import model

ALLOWED_EXT = lb_util.ALLOWED_EXT


class QaPathError(Exception):
    def __init__(self, reason_code):
        Exception.__init__(self, reason_code)
        self.reason_code = reason_code


def _is_inside(child, parent):
    child = os.path.normcase(os.path.realpath(child))
    parent = os.path.normcase(os.path.realpath(parent))
    try:
        return os.path.commonpath([child, parent]) == parent
    except ValueError:
        return False


class QaPaths(object):
    """작업 폴더(labelbot과 같은 폴더) 안의 qa/ 경로. 코드 폴더 안은 거부한다(PRD 9.2절)."""

    def __init__(self, root, create=True):
        if not root:
            raise QaPathError("WORKSPACE_REQUIRED")
        root = os.path.abspath(root)
        if is_forbidden_inside_code(root):
            raise QaPathError("WORKSPACE_INSIDE_CODE")
        self.root = root
        self.qa = os.path.join(root, "qa")
        if create:
            for d in (self.qa, self.inbox, self.cache_dir, self.runs_dir, self.golden_dir, self.inputs_dir, self.logs_dir):
                os.makedirs(d, exist_ok=True)

    def ws(self, *parts):
        return os.path.join(self.root, *parts)

    def q(self, *parts):
        return os.path.join(self.qa, *parts)

    policy = property(lambda self: self.q("policy.json"))
    schema = property(lambda self: self.q("schema.json"))
    baseline = property(lambda self: self.q("baseline.json"))
    history = property(lambda self: self.q("history.jsonl"))
    feedback_rejected = property(lambda self: self.q("feedback_rejected.jsonl"))
    golden_dir = property(lambda self: self.q("golden"))
    golden = property(lambda self: self.q("golden", "golden.jsonl"))
    inbox = property(lambda self: self.q("inbox"))
    cache_dir = property(lambda self: self.q("cache"))
    judge_cache = property(lambda self: self.q("cache", "judge_cache.jsonl"))
    runs_dir = property(lambda self: self.q("runs"))
    inputs_dir = property(lambda self: self.ws("inputs"))
    logs_dir = property(lambda self: self.ws("logs"))
    log_path = property(lambda self: self.ws("logs", "engrbot.log"))

    def run_dir(self, qa_run_id, create=False):
        p = self.q("runs", qa_run_id)
        if create:
            os.makedirs(p, exist_ok=True)
        return p

    def list_runs(self):
        if not os.path.isdir(self.runs_dir):
            return []
        return sorted(d for d in os.listdir(self.runs_dir) if d.startswith("QA-"))


# ---- 쓰기 ------------------------------------------------------------------

def check_ext(path):
    lb_util.check_ext(path)


def dumps(obj, indent=None):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=indent)


def write_text(path, text):
    lb_util.write_text(path, text)


def write_json(path, obj, indent=2):
    write_text(path, dumps(obj, indent=indent) + "\n")


def write_jsonl(path, rows):
    write_text(path, "".join(dumps(r) + "\n" for r in rows))


_append_lock = threading.Lock()


def append_jsonl(path, row):
    check_ext(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with _append_lock:
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(dumps(row) + "\n")


# ---- 읽기 ------------------------------------------------------------------

def read_input(path, snapshot_dir=None, expect=None):
    """사람 입력은 이 함수로만 읽는다(labelbot.ingest.read_input)."""
    return lb_ingest.read_input(path, snapshot_dir, expect=expect)


def read_json_input(path, snapshot_dir=None):
    return json.loads(read_input(path, snapshot_dir, expect="text"))


def read_own_json(path, default=None):
    if not os.path.isfile(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read_own_jsonl(path):
    if not os.path.isfile(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def load_b64_file(path):
    """작업 폴더의 .b64(원본, 이미지)를 bytes로. 실패하면 model.LoaderError."""
    if not path.lower().endswith(".b64"):
        raise model.LoaderError("NOT_B64")
    if not os.path.isfile(path):
        raise model.LoaderError("B64_MISSING")
    try:
        with open(path, "r", encoding="ascii") as f:
            return base64.b64decode(f.read(), validate=False)
    except (ValueError, UnicodeDecodeError, OSError):
        raise model.LoaderError("B64_DECODE_FAILED")


# ---- 로그 ------------------------------------------------------------------

class Logger(object):
    """logs/engrbot.log. 단계, 파일 ID·chunk ID, 사유 코드만 남긴다."""

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()

    def __call__(self, stage, target_id, reason):
        line = "%s\t%s\t%s\t%s\n" % (model.now_iso(), stage, target_id, reason)
        check_ext(self.path)
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with self.lock:
            with open(self.path, "a", encoding="utf-8", newline="\n") as f:
                f.write(line)


def null_log(stage, target_id, reason):
    return None


# ---- 본문 없음 부류 정리 ----------------------------------------------------

JUDGE_REASON_CODES = ("L3_NOT_SUPPORTED", "L3_PARTIALLY_SUPPORTED")


def strip_text(obj):
    """작업 폴더 전용 파일에서 발췌를 뺄 때(output.include_text=false) 쓴다.
    judge가 쓴 reason에는 본문 조각이 섞일 수 있으므로 카탈로그 설명으로 바꾼다."""
    if isinstance(obj, dict):
        out = {k: strip_text(v) for k, v in obj.items() if k not in ("text", "quote", "judge_reason")}
        if out.get("code") in JUDGE_REASON_CODES and "reason" in out:
            from engrbot import codes

            out["reason"] = codes.get(out["code"])["desc"]
        return out
    if isinstance(obj, list):
        return [strip_text(v) for v in obj]
    return obj
