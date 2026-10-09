"""tools/prepush_scan.py(공개 저장소 push 전 검사, G-PUB) 테스트.

- 지금 저장소(추적 파일 전체)는 허용 목록으로 통과
- 임시 파일에 넣은 가짜 키·사설 IP·PEM·UNC·실값 접미사·denylist 호스트는 실패, 값은 출력 안 함
- placeholder·loopback·CSS 선택자(.sk-…)는 통과, 허용 목록의 줄 해시로 통과
가짜 키는 실행 중에 조립한다(키 꼴 리터럴을 두지 않는다).
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN = os.path.join(ROOT, "tools", "prepush_scan.py")

FAKE_SK = "sk-" + "x" * 24
FAKE_AWS = "AK" + "IA" + "Q" * 16
FAKE_GHP = "gh" + "p_" + "a" * 36
FAKE_JWT = "ey" + "J" + "h" * 12 + "." + "p" * 12 + ".sig"
PEM = "-----BEGIN " + "RSA PRIVATE KEY-----"
PRIVATE_IPS = [".".join(p) for p in (("10", "20", "30", "40"), ("172", "16", "5", "9"), ("192", "168", "0", "77"))]
PUBLIC_IPS = [".".join(p) for p in (("127", "0", "0", "1"), ("172", "32", "0", "1"), ("8", "8", "4", "4"))]
DENY_HOST = "corp-intranet-" + "zz.example.invalid"
REAL_SUFFIX = "." + "corp-zz" + ".co.kr"
UNC = "\\\\" + "fileserver01\\share$\\dir"


def run(*args):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    p = subprocess.run([sys.executable, SCAN] + list(args), cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    return p.returncode, p.stdout.decode("utf-8", "replace") + p.stderr.decode("utf-8", "replace")


class PrepushScanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prepush_")
        self.deny = os.path.join(self.tmp, "scan_denylist.json")
        with open(self.deny, "w", encoding="utf-8") as f:
            json.dump({"hosts": [DENY_HOST], "domains": [], "paths": []}, f)
        self.no_allow = os.path.join(self.tmp, "none.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def scan_text(self, text, *extra):
        path = os.path.join(self.tmp, "sample.txt")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        args = ["--paths", path, "--denylist", self.deny, "--allow", self.no_allow] + list(extra)
        rc, out = run(*args)
        shown = path.replace(os.sep, "/")  # 출력 경로는 / 구분자
        hits = [ln.rsplit(":", 2) for ln in out.splitlines() if ln.startswith(shown)]
        return rc, [(int(h[1]), h[2]) for h in hits], out, path

    def test_current_tree_passes(self):
        rc, out = run()
        self.assertEqual(rc, 0, out)
        self.assertIn("hits=0", out)

    def test_injected_secrets_fail_and_values_hidden(self):
        lines = ["key = '%s'" % FAKE_SK, "aws=%s" % FAKE_AWS, "tok %s" % FAKE_GHP, "jwt: %s" % FAKE_JWT, PEM,
                 "host %s:8080" % PRIVATE_IPS[0], "a %s b" % PRIVATE_IPS[1], "url http://%s/x" % PRIVATE_IPS[2],
                 "export BEOL_ALLOWED_HOST_SUFFIXES=%s" % REAL_SUFFIX, "share %s" % UNC,
                 "see https://%s/path" % DENY_HOST.upper()]
        rc, hits, out, _ = self.scan_text("\n".join(lines) + "\n")
        self.assertEqual(rc, 1)
        self.assertEqual(hits, [(1, "KEY_SK"), (2, "KEY_AWS"), (3, "KEY_GHP"), (4, "KEY_JWT"), (5, "KEY_PEM"),
                                (6, "IP_PRIVATE"), (7, "IP_PRIVATE"), (8, "IP_PRIVATE"), (9, "ENV_HOST_SUFFIXES"),
                                (10, "UNC_PATH"), (11, "DENYLIST")])
        for value in [FAKE_SK, FAKE_AWS, FAKE_GHP, FAKE_JWT, REAL_SUFFIX, DENY_HOST, "fileserver01"] + PRIVATE_IPS:
            self.assertNotIn(value, out)

    def test_placeholders_and_safe_values_pass(self):
        lines = ["." + "sk-" + "bridge-connector-label-wrapper { color: red }",
                 "var(--sk-" + "bridge-connector-label-width)",
                 "task-" + "sk-" + "x" * 24,
                 "BEOL_ALLOWED_HOST_SUFFIXES=<사내 도메인 접미사>",
                 "BEOL_ALLOWED_HOST_SUFFIXES=.example.invalid,.corp.test",
                 "BEOL_ALLOWED_HOST_SUFFIXES=$SUFFIXES",
                 "C:\\\\Users\\\\someone\\\\repo", r"pattern = '\\d+\\.\\d+'",
                 "version 1.2.3.4 and 300.1.1.1"] + ["ip %s" % ip for ip in PUBLIC_IPS]
        rc, hits, out, _ = self.scan_text("\n".join(lines) + "\n")
        self.assertEqual((rc, hits), (0, []), out)

    def test_allowlist_by_line_hash(self):
        line = "key = '%s'" % FAKE_SK
        rc, hits, _, path = self.scan_text(line + "\n")
        self.assertEqual((rc, hits), (1, [(1, "KEY_SK")]))
        allow = os.path.join(self.tmp, "allow.json")
        with open(allow, "w", encoding="utf-8") as f:
            json.dump([{"path": path.replace(os.sep, "/"), "pattern_id": "KEY_SK",
                        "line_sha256": hashlib.sha256(line.encode("utf-8")).hexdigest()}], f)
        rc, out = run("--paths", path, "--denylist", self.deny, "--allow", allow)
        self.assertEqual(rc, 0, out)
        self.assertIn("allowed=1", out)

    def test_missing_denylist_skips_rule_with_notice(self):
        path = os.path.join(self.tmp, "s.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("see https://%s/\n" % DENY_HOST)
        rc, out = run("--paths", path, "--denylist", os.path.join(self.tmp, "absent.json"), "--allow", self.no_allow)
        self.assertEqual(rc, 0, out)
        self.assertIn("scan_denylist.json 없음", out)

    def test_suggest_allow_prints_hashes_only(self):
        rc, _, out, _ = self.scan_text("k=%s\n" % FAKE_SK, "--suggest-allow")
        self.assertEqual(rc, 1)
        self.assertIn('"line_sha256"', out)
        self.assertNotIn(FAKE_SK, out)


if __name__ == "__main__":
    unittest.main()
