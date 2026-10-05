"""BEOL-labeling 작업 폴더 준비: pipeline.json 작성과 화면 서버(.claude/launch.json) 등록.

입력 파일은 열지 않는다(확장자별 개수만 센다). 원본은 labelbot의 read_input만 연다(CLAUDE.md).

작업 폴더는 실행마다 workspaces/261004_BEOL_<slug>_YYYYMMDD-HHMMSS로 새로 만든다.
injested-file-list/*.json(이전 실행에서 처리를 마친 파일명)과 입력 파일명을 비교해 중복 건수를 알린다.

사용:
  python init_workspace.py --input "<입력 폴더>" [--workspace "<작업 폴더>"] [--force]
  python init_workspace.py --input "<입력 폴더>" --workspace "<작업 폴더>" --skip-duplicates
출력: JSON 한 줄(workspace, launch_name, port, 파일 수, pipeline.json 작성 여부, duplicates).
duplicates에는 건수와 출처 목록 파일만 담는다(파일명은 출력하지 않는다).
"""
import argparse
import datetime
import glob
import json
import os
import re
import sys
import unicodedata

CODE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, CODE_ROOT)
from labelbot.ingest import iter_inputs  # noqa: E402
from labelbot.workspace import DEFAULT_CONFIG  # noqa: E402

PREFIX = "261004_BEOL_"
BASE_PORT = 8770
LIST_DIR = os.path.join(CODE_ROOT, "injested-file-list")

# pipeline.json에 쓰는 값. 기본값과 같은 항목은 DEFAULT_CONFIG에서 가져오고, 이 스킬이 바꾸는 값만 직접 적는다.
_D = DEFAULT_CONFIG
PIPELINE = {
    "taxonomy_path": os.path.join(CODE_ROOT, "taxonomy", "taxonomy.xlsx").replace("\\", "/"),
    "input_root": _D["input_root"],
    "llm": {
        "base_url": _D["llm"]["base_url"],
        "model": "gpt-6-sol",
        "temperature": None,
        "max_tokens": _D["llm"]["max_tokens"],
        "max_tokens_param": "max_completion_tokens",
        "response_format_json": True,
        "timeout": 180,
        "workers": 6,
    },
    "embedding": {"model": _D["embedding"]["model"]},
    # storage_enabled: 슬라이드 JPG를 Storage에 올린다(push-slides). 빠지면 workspace 기본값 False로 적재가 꺼진다.
    "supabase": {"enabled": True, "table": "beol_chunk_embeddings",
                 "storage_enabled": True, "storage_bucket": _D["supabase"]["storage_bucket"]},
}


def slug(name):
    s = re.sub(r"[^0-9A-Za-z가-힣]+", "-", name).strip("-").lower()
    return s or "input"


def nfc(s):
    return unicodedata.normalize("NFC", s)


def input_names(inp):
    """labelbot ingest.iter_inputs로 입력 파일명(NFC)을 모은다. 파일은 열지 않는다."""
    return {fname for _, _, fname in iter_inputs(inp)}


def find_duplicates(names):
    """injested-file-list/*.json과 겹치는 파일명과 그 출처 목록 파일."""
    dup, sources = set(), []
    for path in sorted(glob.glob(os.path.join(LIST_DIR, "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                done = {nfc(n) for n in json.load(f).get("files", [])}
        except (OSError, ValueError, AttributeError):
            continue
        hit = names & done
        if hit:
            dup |= hit
            sources.append(os.path.basename(path))
    return dup, sources


def inside(child, parent):
    child, parent = os.path.normcase(os.path.realpath(child)), os.path.normcase(os.path.realpath(parent))
    try:
        return os.path.commonpath([child, parent]) == parent
    except ValueError:
        return False


def serve_args(ws, port):
    """labelbot serve: screens/를 보여 주고 검수·대조 JSON을 inbox/에 바로 쓴다."""
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "serve_screens.py").replace("\\", "/")
    return [script, "--workspace", ws, "--port", str(port)]


def upsert_launch(name, port, ws):
    path = os.path.join(CODE_ROOT, ".claude", "launch.json")
    data = {"version": "0.0.1", "configurations": []}
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    confs = data.setdefault("configurations", [])
    conf = next((c for c in confs if c.get("name") == name), None)
    if conf is None:
        used = {c.get("port") for c in confs}
        while port in used:
            port += 1
        conf = {"name": name, "runtimeExecutable": "python", "runtimeArgs": [], "port": port}
        confs.append(conf)
    port = conf.get("port", port)
    args = serve_args(ws, port)
    # 예전 http.server 등록도 serve로 바꾼다(포트는 유지).
    if conf.get("runtimeArgs") != args or conf.get("runtimeExecutable") != "python":
        conf["runtimeExecutable"], conf["runtimeArgs"] = "python", args
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
    return port


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--workspace")
    ap.add_argument("--force", action="store_true", help="pipeline.json이 있어도 다시 쓴다")
    ap.add_argument("--skip-duplicates", action="store_true",
                    help="injested-file-list와 겹치는 파일명을 pipeline.json skip_file_names에 넣는다")
    a = ap.parse_args()
    inp = os.path.abspath(a.input if os.path.isabs(a.input) else os.path.join(CODE_ROOT, a.input))
    if not os.path.isdir(inp):
        print(json.dumps({"error": "INPUT_NOT_FOUND"}, ensure_ascii=False))
        return 2
    s = slug(os.path.basename(inp.rstrip("\\/")))
    wsroot = os.path.join(CODE_ROOT, "workspaces")
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    ws = os.path.abspath(a.workspace or os.path.join(wsroot, "%s%s_%s" % (PREFIX, s, stamp)))
    if inside(ws, CODE_ROOT) and not inside(ws, wsroot):
        print(json.dumps({"error": "WORKSPACE_INSIDE_CODE"}, ensure_ascii=False))
        return 2
    os.makedirs(ws, exist_ok=True)
    cfg_path = os.path.join(ws, "pipeline.json")
    wrote = False
    if a.force or not os.path.isfile(cfg_path):
        cfg = json.loads(json.dumps(PIPELINE))
        cfg["input_root"] = inp.replace("\\", "/")
        with open(cfg_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
            f.write("\n")
        wrote = True
    dup, sources = find_duplicates(input_names(inp))
    skipped = 0
    if a.skip_duplicates:
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        cfg["skip_file_names"] = sorted(dup)
        with open(cfg_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
            f.write("\n")
        skipped = len(dup)
    counts = {}
    for _, _, files in os.walk(inp):
        for fn in files:
            ext = os.path.splitext(fn)[1].lower() or "(없음)"
            counts[ext] = counts.get(ext, 0) + 1
    screens = os.path.join(ws, "screens").replace("\\", "/")
    os.makedirs(screens, exist_ok=True)
    name = "screens-" + s
    port = upsert_launch(name, BASE_PORT, ws.replace("\\", "/"))
    print(json.dumps({"workspace": ws.replace("\\", "/"), "input": inp.replace("\\", "/"), "pipeline_written": wrote,
                      "file_counts": counts, "launch_name": name, "port": port,
                      "duplicates": {"count": len(dup), "sources": sources}, "skipped": skipped},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
