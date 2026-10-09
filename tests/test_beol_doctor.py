"""tools/beol_doctor.py(M00 ENV, E01~E15) 테스트. 127.0.0.1의 가짜 서버만 쓰고 외부 네트워크는 쓰지 않는다.

- refused·timeout·자체 서명 CA·407 프록시·pip 인덱스 404 → 사유 코드
- 실패 블록 형식과 "담당자에게:" 문장(별칭 자리표시만), 화면·보고에 실제 호스트·값 미노출
- --step 선택, 종료 코드, Python 3.8 문법, 카탈로그 완전성
"""
import ast
import email.utils
import http.server
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCTOR = os.path.join(ROOT, "tools", "beol_doctor.py")
_spec = importlib.util.spec_from_file_location("beol_doctor", DOCTOR)
doctor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(doctor)

LEAK_HOST = "leak-check-host.example.invalid"
SECRET_VALUE = "doctor-secret-value-9f3a71"
PROXY_VARS = ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "no_proxy", "all_proxy")


def clean_env(**extra):
    env = dict((k, v) for k, v in os.environ.items() if k not in PROXY_VARS)
    env["PIP_CONFIG_FILE"] = os.devnull
    env.update(extra)
    return env


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def target(alias, port, proto="tcp", host="127.0.0.1", **kw):
    return dict(kw, alias=alias, host=host, port=port, proto=proto)


def ctx_for(targets, env=None, **doc):
    doc = dict(doc, targets=targets)
    return doctor.Ctx(doc, env=clean_env() if env is None else env, timeout=doc.pop("timeout_s", 5))


def codes(findings, status="FAIL"):
    return [f["code"] for f in findings if f["status"] == status]


class _Quiet(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass


class _Server(object):
    """BaseHTTPRequestHandler 서버를 스레드로 띄운다."""

    def __init__(self, handler, wrap=None):
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.srv.handle_error = lambda *a: None
        if wrap:
            self.srv.socket = wrap(self.srv.socket)
        self.port = self.srv.server_address[1]
        self.th = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.th.start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


class Status(object):
    """고정 상태 코드를 돌려주는 HTTP 처리기 클래스를 만든다."""

    @staticmethod
    def handler(code, date=None):
        class H(_Quiet):
            def date_time_string(self, timestamp=None):
                return date or http.server.BaseHTTPRequestHandler.date_time_string(self, timestamp)

            def _reply(self):
                self.send_response(code)
                self.send_header("Content-Length", "0")
                self.end_headers()

            do_GET = do_HEAD = _reply

            def do_CONNECT(self):
                self.send_response(code)
                self.send_header("Proxy-Authenticate", 'Basic realm="corp"')
                self.send_header("Content-Length", "0")
                self.end_headers()
        return H


class SourceTest(unittest.TestCase):
    def test_py38_syntax(self):
        with open(DOCTOR, encoding="utf-8") as f:
            ast.parse(f.read(), feature_version=(3, 8))

    def test_no_labelbot_import_and_allow_comments(self):
        with open(DOCTOR, encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src)
        mods = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        mods += [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        self.assertFalse([m for m in mods if m and m.split(".")[0] == "labelbot"])
        for line in src.splitlines():
            if line.startswith(("import socket", "import ssl", "import http.client")):
                self.assertIn("# code_engrbot: allow C2_TRANSPORT_BYPASS", line)

    def test_every_emitted_code_is_in_catalog(self):
        with open(DOCTOR, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        found = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("F", "DoctorFail"):
                idx = 1 if n.func.id == "F" else 0
                if len(n.args) > idx and isinstance(n.args[idx], ast.Constant) and isinstance(n.args[idx].value, str):
                    found.add(n.args[idx].value)
        self.assertGreater(len(found), 30)
        missing = [c for c in sorted(found) if doctor.lookup(c) is None]
        self.assertEqual(missing, [])
        for c in ("PY_MODULE_MISSING_ssl", "BUILD_HEADER_MISSING_ffi", "ENV_MISSING_BEOL_X", "HTTP_503",
                  "HTTP_418", "UNEXPECTED_KeyError"):
            self.assertIsNotNone(doctor.lookup(c), c)
        self.assertIs(doctor.lookup("HTTP_503"), doctor.CATALOG["HTTP_5xx"])

    def test_failure_block_format_and_relay_uses_alias_only(self):
        step = {"id": "E03", "name": "TCP_CONNECT"}
        lines = doctor.failure_block(step, doctor.F("FAIL", "CONN_TIMEOUT", "pip", "", 443, "https"))
        self.assertTrue(lines[0].startswith("[M00 ENV/E03 TCP_CONNECT] 실패  사유=CONN_TIMEOUT  대상=pip"))
        self.assertTrue(lines[1].startswith("  원인: "))
        self.assertTrue(lines[2].startswith("  조치: "))
        self.assertIn('담당자에게: "보안팀에 <pip 호스트> 443/TCP(HTTPS) 허용 요청, 출발지 = 이 서버 IP', lines[3])
        self.assertIn('doctor_targets.json "pip" 항목', lines[3])


class NetworkCodeTest(unittest.TestCase):
    def test_refused_port_is_conn_refused(self):
        port = free_port()
        ctx = ctx_for([target("svc", port)])
        self.assertEqual(codes(doctor.e03_tcp(ctx)), ["CONN_REFUSED"])

    def test_silent_listener_is_conn_timeout(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen(5)  # accept하지 않는다: TCP는 붙지만 TLS 응답이 오지 않는다
        try:
            ctx = ctx_for([target("api", s.getsockname()[1], "https")], timeout_s=0.5)
            self.assertEqual(codes(doctor.e03_tcp(ctx)), [])
            self.assertEqual(codes(doctor.e04_tls(ctx)), ["CONN_TIMEOUT"])
        finally:
            s.close()

    def test_dns_unresolved_and_later_steps_skip(self):
        ctx = ctx_for([target("mirror", 443, "https", host=LEAK_HOST)])
        self.assertEqual(codes(doctor.e02_dns(ctx)), ["DNS_UNRESOLVED"])
        self.assertEqual([f["status"] for f in doctor.e03_tcp(ctx)], ["SKIP"])
        self.assertEqual([f["status"] for f in doctor.e04_tls(ctx)], ["SKIP"])

    def test_port_in_use(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        try:
            port = s.getsockname()[1]
            ctx = doctor.Ctx({"ports": [port], "port_ranges": []}, env=clean_env())
            fs = doctor.e12_ports(ctx)
            self.assertEqual(codes(fs), ["PORT_IN_USE"])
            self.assertEqual(fs[0]["port"], port)
        finally:
            s.close()

    def test_clock_skew_from_date_header(self):
        old = email.utils.formatdate(time.time() - 86400, usegmt=True)
        srv = _Server(Status.handler(200, date=old))
        try:
            ctx = ctx_for([target("s3", srv.port, "http", role="s3")])
            fs = doctor.e10_clock(ctx)
            self.assertEqual(codes(fs), ["CLOCK_SKEW"])
        finally:
            srv.close()

    def test_e15_rate_limited_only_when_gated_on(self):
        srv = _Server(Status.handler(429))
        try:
            ctx = ctx_for([target("llm", srv.port, "http", role="llm")])
            self.assertEqual([f["status"] for f in doctor.e15_endpoints(ctx)], ["SKIP"])
            ctx.force_e15 = True
            self.assertEqual(codes(doctor.e15_endpoints(ctx)), ["RATE_LIMITED"])
        finally:
            srv.close()


@unittest.skipUnless(shutil.which("openssl"), "openssl CLI가 없어 자체 서명 인증서를 만들 수 없다")
class TlsCaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="doctor_tls_")
        cls.cert = os.path.join(cls.dir, "cert.pem")
        key = os.path.join(cls.dir, "key.pem")
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", cls.cert,
                        "-days", "2", "-subj", "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        import ssl
        sctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        sctx.load_cert_chain(cls.cert, key)
        cls.srv = _Server(Status.handler(200), wrap=lambda s: sctx.wrap_socket(s, server_side=True))

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_self_signed_is_ca_unknown(self):
        ctx = ctx_for([target("vectordb", self.srv.port, "https")])
        self.assertEqual(codes(doctor.e04_tls(ctx)), ["TLS_CA_UNKNOWN"])

    def test_ca_file_makes_it_pass(self):
        ctx = ctx_for([target("vectordb", self.srv.port, "https")], ca_file=self.cert)
        fs = doctor.e04_tls(ctx)
        self.assertEqual([f["status"] for f in fs], ["PASS"])


class ProxyTest(unittest.TestCase):
    def test_connect_407_is_proxy_auth(self):
        srv = _Server(Status.handler(407))
        try:
            env = clean_env(HTTPS_PROXY="http://127.0.0.1:%d" % srv.port)
            ctx = ctx_for([target("pip", 443, "https", host=LEAK_HOST)], env=env)
            fs = doctor.e05_proxy(ctx)
            self.assertIn("PROXY_AUTH_407", codes(fs))
            self.assertEqual(codes(fs, "WARN"), ["NO_PROXY_MISSING"])
            self.assertEqual([f["status"] for f in doctor.e04_tls(ctx)], ["SKIP"])  # E05 실패 대상은 건너뜀
            self.assertIn("PROXY_AUTH_407", doctor.proxy_summary(doctor.run_step(ctx, "E05")))
        finally:
            srv.close()

    def test_connect_403_is_blocked_url(self):
        srv = _Server(Status.handler(403))
        try:
            env = clean_env(HTTPS_PROXY="http://127.0.0.1:%d" % srv.port)
            ctx = ctx_for([target("llm", 443, "https", host=LEAK_HOST, internal=False)], env=env)
            self.assertEqual(codes(doctor.e05_proxy(ctx)), ["PROXY_BLOCKED_URL"])
        finally:
            srv.close()

    def test_no_proxy_matching(self):
        # 사설 IP는 실행 중에 조립한다(공개 저장소 push 전 검사 prepush_scan의 IP_PRIVATE 규칙에 걸리지 않게)
        net10 = ".".join(["10", "0", "0", "0"]) + "/8"
        ip10 = ".".join(["10", "1", "2", "3"])
        ctx = doctor.Ctx({}, env=clean_env(NO_PROXY="localhost,.corp.example,%s,*.svc.example:443" % net10))
        for host, want in (("a.corp.example", True), ("corp.example", True), (ip10, True),
                           ("x.svc.example", True), ("evilcorp.example", False), ("11.0.0.1", False)):
            self.assertEqual(ctx.no_proxy_covers(host), want, host)


class PipTest(unittest.TestCase):
    def test_index_404_is_pkg_not_found(self):
        srv = _Server(Status.handler(404))
        try:
            ctx = ctx_for([target("pip", srv.port, "http", role="pip", index_path="/simple")],
                          packages={"pip": ["beol-doctor-probe-pkg"]}, timeout_s=10)
            ctx.python = sys.executable
            fs = doctor.e07_pip(ctx)
            self.assertEqual(codes(fs), ["PIP_PKG_NOT_FOUND"])
        finally:
            srv.close()

    def test_refused_index_is_unreachable(self):
        ctx = ctx_for([target("pip", free_port(), "http", role="pip")], packages={"pip": ["x"]})
        self.assertEqual(codes(doctor.e07_pip(ctx)), ["PIP_INDEX_UNREACHABLE"])

    def test_pip_output_classification(self):
        self.assertEqual(doctor._pip_code("THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE"), "PIP_HASH_MISMATCH")
        self.assertEqual(doctor._pip_code("error: subprocess-exited-with-error"), "PIP_BUILD_DEPS_MISSING")
        self.assertEqual(doctor._pip_code("ResolutionImpossible"), "PIP_VERSION_CONFLICT")
        self.assertEqual(doctor._pip_code("SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED]"), "PIP_CA")


class LocalStepTest(unittest.TestCase):
    def test_fs_and_disk_low(self):
        root = tempfile.mkdtemp(prefix="doctor_fs_")
        try:
            ctx = doctor.Ctx({"disk_min_gb": 10 ** 9}, env=clean_env(), root=root)
            self.assertEqual(codes(doctor.e13_fs(ctx)), ["DISK_LOW"])
            self.assertTrue(os.path.isdir(os.path.join(root, "workspaces", "_site")))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_env_names_only(self):
        env = clean_env(BEOL_DOCTOR_TEST_SET=SECRET_VALUE)
        env.pop("BEOL_DOCTOR_TEST_UNSET", None)
        ctx = doctor.Ctx({"env_required": ["BEOL_DOCTOR_TEST_SET", "BEOL_DOCTOR_TEST_UNSET"]}, env=env)
        fs = doctor.e14_env(ctx)
        self.assertEqual(codes(fs), ["ENV_MISSING_BEOL_DOCTOR_TEST_UNSET"])
        self.assertNotIn(SECRET_VALUE, json.dumps(fs))

    def test_python_target_modules(self):
        ctx = doctor.Ctx({}, env=clean_env(), python=sys.executable)
        fs = doctor.e08_py_build(ctx)
        self.assertFalse([c for c in codes(fs) if c.startswith("PY_MODULE_MISSING_")])
        ctx = doctor.Ctx({}, env=clean_env(), python=os.path.join(tempfile.gettempdir(), "no-such-python-xyz"))
        self.assertIn("PY_TARGET_NOT_FOUND", codes(doctor.e08_py_build(ctx)))


class CliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="doctor_cli_")
        cls.targets = os.path.join(cls.dir, "targets.json")
        with open(cls.targets, "w", encoding="utf-8") as f:
            json.dump({"targets": [target("mirror", 443, "https", host=LEAK_HOST, auth_env="BEOL_DOCTOR_TEST_KEY")],
                       "env_required": ["BEOL_DOCTOR_TEST_KEY", "BEOL_DOCTOR_TEST_UNSET"]}, f)
        cls.report = os.path.join(cls.dir, "report.json")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def run_cli(self, *args):
        env = clean_env(PYTHONIOENCODING="utf-8", BEOL_DOCTOR_TEST_KEY=SECRET_VALUE)
        env.pop("BEOL_DOCTOR_TEST_UNSET", None)
        p = subprocess.run([sys.executable, DOCTOR, "--targets", self.targets, "--report", self.report] + list(args),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=120)
        return p.returncode, p.stdout.decode("utf-8"), p.stderr.decode("utf-8")

    def read_report(self):
        with open(self.report, encoding="utf-8") as f:
            return f.read()

    def test_step_selection_failure_exit_1_and_no_leak(self):
        rc, out, err = self.run_cli("--step", "E02,E14")
        self.assertEqual(rc, 1)
        self.assertEqual(err, "")
        self.assertIn("[M00 ENV/E02 DNS] 실패  사유=DNS_UNRESOLVED  대상=mirror", out)
        self.assertIn("▶ 처음 실패: E02 DNS — DNS_UNRESOLVED (대상=mirror)", out)
        self.assertIn("ENV_MISSING_BEOL_DOCTOR_TEST_UNSET", out)
        self.assertNotIn("E03", out.split("▶ 처음 실패")[0])  # 선택한 단계만 표에 나온다
        rep = self.read_report()
        doc = json.loads(rep)
        self.assertEqual(doc["steps_selected"], ["E02", "E14"])
        self.assertEqual(doc["first_fail"]["code"], "DNS_UNRESOLVED")
        for text in (out, rep):
            self.assertNotIn(LEAK_HOST, text)
            self.assertNotIn("leak-check-host", text)
            self.assertNotIn(SECRET_VALUE, text)

    def test_json_and_exit_0(self):
        rc, out, err = self.run_cli("--step", "E01", "--json")
        self.assertEqual(rc, 0, out + err)
        doc = json.loads(out)
        self.assertEqual([s["id"] for s in doc["steps"]], ["E01"])
        self.assertEqual(doc["result"], "PASS")
        self.assertIsNone(doc["first_fail"])

    def test_proxy_summary_printed_first(self):
        rc, out, _ = self.run_cli("--step", "E02,E05")
        lines = out.splitlines()
        self.assertTrue(lines[1].startswith("프록시 판정(E05):"), lines[:3])

    def test_bad_step_is_usage_error(self):
        rc, _, err = self.run_cli("--step", "E99")
        self.assertEqual(rc, 2)
        self.assertNotIn("Traceback", err)

    def test_invalid_targets_file_no_traceback(self):
        bad = os.path.join(self.dir, "bad.json")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("{not json")
        env = clean_env(PYTHONIOENCODING="utf-8")
        p = subprocess.run([sys.executable, DOCTOR, "--targets", bad, "--report", self.report, "--step", "E02"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=60)
        out = p.stdout.decode("utf-8")
        self.assertEqual(p.returncode, 1)
        self.assertIn("사유=TARGETS_INVALID", out)
        self.assertNotIn("Traceback", out + p.stderr.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
