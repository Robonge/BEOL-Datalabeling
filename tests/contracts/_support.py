"""계약 테스트 공용: 스냅샷 비교·갱신, 하위 프로세스 실행, 출력 정규화.

CONTRACT_UPDATE=1이면 snapshots/<name>.json을 다시 쓰고 비교하지 않는다.
스냅샷은 .json으로만 쓴다(루트 CLAUDE.md 쓰기 규칙).
"""
import json
import os
import re
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SNAP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshots")

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# argparse 3.14는 -m 실행 시 prog를 "<인터프리터> -m <모듈>"로 만든다. 인터프리터 이름 차이를 지운다.
_PY_PROG = re.compile(r"\bpython(?:\d+(?:\.\d+)*)?(?:\.exe)?(?= -m )", re.I)


def updating():
    return os.environ.get("CONTRACT_UPDATE") == "1"


def _jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, bytes):
        return "hex:" + obj.hex()
    return obj


def check(case, name, data):
    """data를 snapshots/<name>.json과 비교한다. dict이면 키 집합과 키별 값을 따로 비교해 차이를 좁혀 보인다."""
    data = json.loads(json.dumps(_jsonable(data), ensure_ascii=False))
    path = os.path.join(SNAP_DIR, name + ".json")
    if updating():
        os.makedirs(SNAP_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        return
    if not os.path.isfile(path):
        case.fail("SNAPSHOT_MISSING %s (CONTRACT_UPDATE=1로 만든다)" % name)
    with open(path, encoding="utf-8") as f:
        expected = json.load(f)
    case.maxDiff = None
    if isinstance(expected, dict) and isinstance(data, dict):
        case.assertEqual(sorted(expected), sorted(data), "%s: 키 목록이 다르다" % name)
        for key in expected:
            with case.subTest(snapshot=name, key=key):
                case.assertEqual(expected[key], data[key])
    else:
        case.assertEqual(expected, data)


def normalize(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _ANSI.sub("", text)
    text = _PY_PROG.sub("python", text)
    for root in {REPO_ROOT, REPO_ROOT.replace("\\", "/")}:
        text = text.replace(root, "<REPO>")
    tmp = tempfile.gettempdir()
    for t in {tmp, tmp.replace("\\", "/")}:
        text = text.replace(t, "<TMP>")
    return "\n".join(line.rstrip() for line in text.split("\n")).strip("\n") + "\n"


def subprocess_env():
    env = dict(os.environ)
    env.update({
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "COLUMNS": "200",
        "LINES": "50",
        "NO_COLOR": "1",
        "PYTHON_COLORS": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    env.pop("FORCE_COLOR", None)
    return env


def run_help(args, timeout=60):
    """sys.executable로 args를 실행하고 (returncode, 정규화한 stdout, stderr)를 돌려준다."""
    p = subprocess.run(
        [sys.executable] + list(args), cwd=REPO_ROOT, env=subprocess_env(),
        stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout,
    )
    return p.returncode, normalize(p.stdout.decode("utf-8", "replace")), p.stderr.decode("utf-8", "replace")
