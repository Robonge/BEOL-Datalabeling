"""화면 서버 실행기: 어느 폴더에서 띄워도 `python -m labelbot serve`와 같게 동작한다.

.claude/launch.json이 이 파일을 부른다(작업 디렉터리와 무관하게 코드 폴더의 labelbot을 쓰기 위해).

사용: python serve_screens.py --workspace "<작업 폴더>" --port <포트>
"""
import os
import sys

CODE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

if __name__ == "__main__":
    # 미리보기 패널은 PYTHONIOENCODING 없이 띄우므로 출력 인코딩을 직접 맞춘다.
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    sys.path.insert(0, CODE_ROOT)
    from labelbot.cli import main

    sys.exit(main(["serve"] + sys.argv[1:]))
