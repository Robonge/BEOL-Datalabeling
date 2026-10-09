"""브라우저가 내려받은 검수·대조 JSON을 작업 폴더 inbox/로 옮긴다(JSON 출력).

파일 내용은 열지 않는다. 같은 드라이브 안에서 이름만 바꾸는 os.replace로 옮기므로
내용을 읽는 곳은 여전히 `labelbot apply`의 read_input 한 곳뿐이다. 드라이브가 달라
이름 바꾸기가 안 되면 복사하지 않고 CROSS_DEVICE로 남긴다.

이번 실행 ID의 파일만 옮긴다: review_<RUN>.json, compare_<RUN>.json과
브라우저가 붙이는 사본 이름(review_<RUN> (1).json 등). 수정 시각은 그대로 유지되어
apply가 같은 실행의 최신 검수 파일을 고르는 기준이 바뀌지 않는다.

사용: python collect_inbox.py --workspace "<작업 폴더>" --run <실행 ID> [--downloads "<폴더>"]
"""
import argparse
import json
import os
import re
import sys

# Windows '다운로드' 폴더의 Known Folder ID
_DOWNLOADS_GUID = "{374DE290-123F-4565-9164-39C4925E467B}"


def downloads_dir():
    try:
        import winreg
        key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            path = os.path.expandvars(winreg.QueryValueEx(k, _DOWNLOADS_GUID)[0])
        if os.path.isdir(path):
            return path
    except (ImportError, OSError):
        pass
    return os.path.join(os.path.expanduser("~"), "Downloads")


def free_name(folder, name):
    """inbox에 같은 이름이 있으면 덮어쓰지 않도록 번호를 붙인다."""
    if not os.path.exists(os.path.join(folder, name)):
        return name
    stem, ext = os.path.splitext(name)
    n = 2
    while os.path.exists(os.path.join(folder, "%s_%d%s" % (stem, n, ext))):
        n += 1
    return "%s_%d%s" % (stem, n, ext)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--downloads")
    a = ap.parse_args()
    src = a.downloads or downloads_dir()
    inbox = os.path.join(a.workspace, "inbox")
    os.makedirs(inbox, exist_ok=True)
    pat = re.compile(r"^(review|compare)_%s( \(\d+\))?\.json$" % re.escape(a.run), re.IGNORECASE)
    out = {"run_id": a.run, "downloads_found": os.path.isdir(src),
           "moved": {"review": 0, "compare": 0}, "skipped": {}}
    if out["downloads_found"]:
        names = [fn for fn in os.listdir(src) if pat.match(fn) and os.path.isfile(os.path.join(src, fn))]
        # 오래된 것부터 옮겨 inbox의 이름 순서도 내려받은 순서를 따르게 한다.
        names.sort(key=lambda fn: os.path.getmtime(os.path.join(src, fn)))
        for fn in names:
            kind = pat.match(fn).group(1).lower()
            try:
                os.replace(os.path.join(src, fn), os.path.join(inbox, free_name(inbox, fn)))
                out["moved"][kind] += 1
            except OSError as e:
                code = "CROSS_DEVICE" if getattr(e, "winerror", None) == 17 or e.errno == 18 else "MOVE_FAILED"
                out["skipped"][code] = out["skipped"].get(code, 0) + 1
    names = os.listdir(inbox)
    out["inbox"] = {k: sum(1 for n in names if n.lower().startswith(k + "_") and n.lower().endswith(".json"))
                    for k in ("review", "compare")}
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")))
    from labelbot import trace  # noqa: E402  마일스톤 M06(stderr 줄, stdout JSON 불변)

    sys.exit(trace.run_main("M06", main))
