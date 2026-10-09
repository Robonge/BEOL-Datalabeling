#!/usr/bin/env python3
"""BEOL 환경·설치 진단(doctor). 마일스톤 M00 ENV 아래 단계 E01~E15.

폐쇄망 서버에서 Python 3.14를 설치하기 전, 배포판 python3(3.8+)로 돌린다. 그래서 Python 3.8 문법과
표준 라이브러리만 쓰고 labelbot을 import하지 않는다(labelbot/llm.py 전송도 쓸 수 없다).

- 대상 호스트는 비추적 workspaces/_site/doctor_targets.json에만 둔다(예시: config/doctor_targets.example.json).
- 화면·--json·doctor_report.json에는 별칭(mirror, pip, llm, ...)·포트·사유 코드만 낸다. 실제 호스트·IP·값은
  내보내지 않는다(출력이 반출될 수 있다). "담당자에게:" 문장도 별칭 자리표시로 내고, 실제 호스트는 사람이
  doctor_targets.json에서 채워 전달한다.
- 실패 블록은 L3c와 같은 형식이다: [M00 ENV/E03 TCP_CONNECT] 실패  사유=CONN_TIMEOUT  대상=pip

사용: python3 tools/beol_doctor.py [--step E07[,E08]] [--json] [--targets PATH] [--python PATH] [--report PATH]
종료 코드: FAIL이 하나라도 있으면 1, 아니면 0(WARN·SKIP은 0). 잡히지 않은 예외도 traceback 대신 UNEXPECTED_<이름>.
"""
import argparse
import base64
import email.utils
import errno
import http.client  # code_engrbot: allow C2_TRANSPORT_BYPASS 진단 전용(대상은 doctor_targets.json의 사내 호스트만)
import ipaddress
import json
import os
import platform
import re
import shutil
import socket  # code_engrbot: allow C2_TRANSPORT_BYPASS 진단 전용(대상은 doctor_targets.json의 사내 호스트만)
import ssl  # code_engrbot: allow C2_TRANSPORT_BYPASS 진단 전용(대상은 doctor_targets.json의 사내 호스트만)
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

MILESTONE = "M00 ENV"
CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_TARGETS = os.path.join(CODE_ROOT, "workspaces", "_site", "doctor_targets.json")
DEFAULT_REPORT = os.path.join(CODE_ROOT, "workspaces", "_site", "doctor_report.json")

STEPS = [
    ("E01", "PYTHON"), ("E02", "DNS"), ("E03", "TCP_CONNECT"), ("E04", "TLS"), ("E05", "PROXY"),
    ("E06", "PKG_MIRROR"), ("E07", "PIP_INSTALL"), ("E08", "PY_BUILD"), ("E09", "CHROMIUM"),
    ("E10", "CLOCK"), ("E11", "TZ"), ("E12", "PORTS"), ("E13", "FILESYSTEM"), ("E14", "ENV_VARS"),
    ("E15", "ENDPOINTS"),
]
STEP_NAMES = dict(STEPS)

DEFAULT_PORTS = [8771, 8790, 8795, 8796]
DEFAULT_PORT_RANGES = [[8700, 8899], [8900, 9099]]
BUILD_LIBS = [  # (이름, pkg-config 이름, 헤더 후보)
    ("sqlite3", "sqlite3", ["sqlite3.h"]),
    ("ssl", "openssl", ["openssl/ssl.h"]),
    ("zlib", "zlib", ["zlib.h"]),
    ("lzma", "liblzma", ["lzma.h"]),
    ("bz2", "bzip2", ["bzlib.h"]),
    ("ffi", "libffi", ["ffi.h"]),
    ("readline", "readline", ["readline/readline.h"]),
]
INCLUDE_DIRS = ["/usr/include", "/usr/local/include", "/usr/include/x86_64-linux-gnu", "/usr/include/aarch64-linux-gnu"]
PY_MODULES = ["sqlite3", "ssl", "zlib", "lzma", "bz2"]
CHROME_NAMES = ["chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "microsoft-edge"]
E15_ROLES = ("llm", "embed", "vectordb", "s3")

# ===== CATALOG BEGIN =====
# 사유 코드 → (원인, 조치, 담당자 문장 템플릿 또는 None). L3c의 labelbot/reason_codes.py와 짝(사본 일치 테스트 대상).
# 템플릿 자리: {host}=별칭 자리표시("<pip 호스트>"), {port}, {proto}("TCP(HTTPS)" 등), {detail}.
# 키 끝의 *는 접두어 패턴이다(PY_MODULE_MISSING_ssl 등). HTTP_5xx는 HTTP_500~599에 쓴다.
CATALOG = {
    "PY3_TOO_OLD": ("python3이 3.8보다 낮다", "배포판 python3 3.8 이상을 설치하고 다시 실행", "서버 관리자에게 python3(3.8 이상) 설치 요청"),
    "TARGETS_MISSING": ("doctor_targets.json이 없어 네트워크 대상을 모른다",
                        "mkdir -p workspaces/_site 후 config/doctor_targets.example.json을 workspaces/_site/doctor_targets.json으로 복사해 사내 호스트를 채운다", None),
    "TARGETS_INVALID": ("doctor_targets.json을 읽을 수 없다(JSON 형식 오류)", "JSON 문법·필드(alias, host, port, proto)를 예시 파일과 대조해 고친다", None),
    "DNS_UNRESOLVED": ("이 서버의 DNS가 호스트 이름을 찾지 못했다(내부 DNS 미등록·오타·/etc/hosts 누락)",
                       "doctor_targets.json의 host 철자 확인 → 맞으면 DNS 등록 요청(임시로 /etc/hosts)", "{host} DNS 등록 요청(이 서버 DNS에서 조회 안 됨)"),
    "CONN_REFUSED": ("상대 호스트가 연결을 거부했다(서비스 중단 또는 호스트 방화벽 차단)",
                     "포트 번호 확인 → 서비스 담당에게 상태·호스트 방화벽 확인 요청", "{host} {port}/{proto} 서비스 상태와 호스트 방화벽 확인 요청"),
    "CONN_TIMEOUT": ("연결 또는 응답 시간 초과(네트워크 방화벽·ACL에서 패킷을 버림)",
                     "보안·인프라 담당에게 방화벽 허용 요청 후 같은 단계 재실행", "보안팀에 {host} {port}/{proto} 허용 요청, 출발지 = 이 서버 IP와 사용자 PC IP"),
    "CONN_RESET": ("연결이 중간에 끊겼다(방화벽·IPS가 RST를 보냄)", "보안 담당에게 차단 로그 확인 요청", "{host} {port}/{proto} 접속이 RST로 끊김 — 방화벽·IPS 차단 로그 확인 요청, 출발지 = 이 서버 IP"),
    "NET_UNREACHABLE": ("이 서버에서 대상 네트워크로 가는 경로가 없다(라우팅)", "인프라 담당에게 라우팅 확인 요청", "{host} {port}/{proto} 대역으로 가는 라우팅 확인 요청, 출발지 = 이 서버 IP"),
    "TLS_CA_UNKNOWN": ("대상 인증서를 발급한 CA를 이 서버가 모른다(사내 루트 CA 미설치 또는 TLS 검사 프록시)",
                       "사내 루트 CA를 시스템 저장소(update-ca-certificates)와 doctor_targets.json ca_file·pipeline.json ca_file에 넣는다",
                       "{host} 인증서를 발급한 사내 루트 CA 인증서 파일(PEM) 요청"),
    "TLS_HOSTNAME_MISMATCH": ("인증서의 이름이 접속한 호스트 이름과 다르다", "인증서에 있는 정식 호스트 이름으로 host를 바꾼다", "{host} 인증서의 SAN(정식 호스트 이름) 확인 요청"),
    "TLS_CERT_EXPIRED": ("대상 인증서가 만료됐다(또는 이 서버 시계가 틀림 — E10 확인)", "E10 시계 확인 후 서비스 담당에게 인증서 갱신 요청", "{host} TLS 인증서 만료 — 갱신 요청"),
    "TLS_CA_FILE_MISSING": ("ca_file에 적은 CA 파일이 없다", "doctor_targets.json ca_file 경로를 고친다(저장소 기준 상대경로 가능)", None),
    "TLS_HANDSHAKE_FAIL": ("TLS 협상 실패(프로토콜·암호 불일치 또는 TLS가 아닌 포트)", "proto(https/http)와 포트를 확인", "{host} {port}/{proto} TLS 설정(지원 버전·암호) 확인 요청"),
    "HTTP_BAD_RESPONSE": ("HTTP 응답 형식이 아니다(다른 서비스 포트 또는 중간 장비)", "proto·포트·probe_path 확인", None),
    "PROXY_UNREACHABLE": ("프록시 서버에 연결되지 않는다", "HTTPS_PROXY/HTTP_PROXY 값(호스트·포트) 확인", "{host} {port}/TCP(프록시) 접속 허용 요청, 출발지 = 이 서버 IP"),
    "PROXY_AUTH_407": ("프록시가 인증을 요구했다(407)", "프록시 계정을 HTTPS_PROXY=http://<id>:<pw>@<proxy>:<port> 형식으로 넣거나 IP 인증 예외를 받는다",
                       "프록시 인증 계정 또는 이 서버 IP의 인증 예외 요청 — {host} {port}/{proto} 접속용"),
    "PROXY_BLOCKED_URL": ("프록시가 이 대상 URL을 막았다(403)", "보안 담당에게 화이트리스트 등록 요청", "프록시에서 {host} URL 화이트리스트 등록 요청"),
    "PROXY_UPSTREAM_FAIL": ("프록시가 대상에 연결하지 못했다(5xx 등)", "프록시 쪽 방화벽·대상 상태 확인", "프록시에서 {host} {port}/{proto} 연결 실패({detail}) — 프록시·방화벽 확인 요청"),
    "NO_PROXY_MISSING": ("사내 호스트가 NO_PROXY에 없어 프록시로 나간다", "NO_PROXY(no_proxy)에 사내 호스트(또는 도메인 접미어)를 더한다", None),
    "PKG_MANAGER_MISSING": ("apt-get·dnf·yum을 찾지 못했다", "배포판 패키지 관리자 확인", None),
    "PKG_NOT_IN_MIRROR": ("사내 미러에 패키지가 없다", "패키지 이름·배포판 버전 확인 → 미러 동기화 요청", "사내 {host} 미러에 패키지 {detail} 추가(동기화) 요청"),
    "PKG_SIM_FAIL": ("패키지 모의 설치가 실패했다", "같은 명령을 직접 돌려 E: 줄 확인", None),
    "MIRROR_UNREACHABLE": ("패키지 관리자가 미러 메타데이터를 받지 못했다", "E02~E05 결과(DNS·방화벽·프록시)부터 확인", "{host} {port}/{proto}(패키지 미러) 접속 허용 요청, 출발지 = 이 서버 IP"),
    "APT_LOCK_HELD": ("다른 apt/dpkg 프로세스가 잠금을 잡고 있다(자동 업데이트 등)", "끝날 때까지 기다리거나 ps로 확인 후 재실행", None),
    "PKG_LOCK_HELD": ("다른 dnf/yum 프로세스가 잠금을 잡고 있다", "끝날 때까지 기다린 뒤 재실행", None),
    "NO_SUDO": ("sudo 권한이 없다(비밀번호 없는 sudo 불가)", "설치 단계는 sudo 가능한 계정으로 실행", "이 서버 계정의 sudo(패키지 설치) 권한 요청"),
    "PIP_MISSING": ("대상 python에 pip가 없다", "python3 -m ensurepip 또는 배포판 python3-pip 설치", None),
    "PIP_INDEX_UNREACHABLE": ("pip 인덱스에 연결되지 않는다(DNS·방화벽·시간 초과)", "프록시·NO_PROXY 확인 후 재시도",
                              "{host} {port}/{proto}(pip 인덱스) 접속 허용 요청, 출발지 = 이 서버 IP"),
    "PIP_PKG_NOT_FOUND": ("pip 인덱스에 패키지(또는 이 Python에 맞는 배포본)가 없다", "패키지 이름·버전·Python 버전 확인 → 인덱스 반입 요청",
                          "사내 pip 인덱스({host})에 패키지 {detail} 반입 요청"),
    "PIP_HASH_MISMATCH": ("받은 파일의 해시가 기대값과 다르다(미러 손상 또는 중간 변조)", "미러 담당에게 파일 재동기화 요청", "{host} pip 인덱스의 {detail} 파일 해시 불일치 — 재동기화 요청"),
    "PIP_BUILD_DEPS_MISSING": ("소스 배포본 빌드에 필요한 컴파일러·헤더가 없다", "wheel을 반입하거나 build-essential·*-dev 패키지 설치(E06·E08)", None),
    "PIP_VERSION_CONFLICT": ("요청한 버전 조건을 동시에 만족하는 배포본이 없다", "버전 고정 조건 확인", None),
    "PIP_PROXY": ("pip가 프록시를 통과하지 못했다", "HTTPS_PROXY·NO_PROXY 확인, 사내 인덱스는 NO_PROXY에", "pip용 프록시 경유 허용 요청 — {host} {port}/{proto}"),
    "PIP_CA": ("pip가 인덱스 인증서를 검증하지 못했다(사내 CA)", "pip.conf [global] cert = <사내 CA PEM> 또는 PIP_CERT", "{host} 인증서를 발급한 사내 루트 CA 인증서 파일(PEM) 요청"),
    "PIP_FAILED": ("pip가 알 수 없는 이유로 실패했다", "같은 pip download 명령을 직접 돌려 ERROR 줄 확인", None),
    "BUILD_HEADER_MISSING_*": ("Python 빌드에 필요한 개발 헤더가 없다", "배포판 *-dev(*-devel) 패키지 설치 후 Python 다시 빌드", "서버 관리자에게 개발 헤더 패키지 설치 요청({detail})"),
    "PY_MODULE_MISSING_*": ("대상 Python에서 표준 모듈을 import할 수 없다(빌드 때 헤더 없음)", "E08 헤더 설치 후 Python 3.14.2를 다시 빌드(make clean)", None),
    "PY_TARGET_NOT_FOUND": ("--python으로 준 실행 파일을 실행할 수 없다", "경로 확인(예: /opt/python3.14/bin/python3.14)", None),
    "CHROME_MISSING": ("chromium(또는 Chrome·Edge) 실행 파일이 없다", "chromium 설치 또는 doctor_targets.json chromium_path 지정", "서버 관리자에게 chromium 패키지 설치 요청"),
    "CHROME_MISSING_LIB": ("chromium이 필요한 공유 라이브러리가 없다", "ldd 결과의 라이브러리 패키지 설치", "서버 관리자에게 chromium 의존 라이브러리 설치 요청: {detail}"),
    "CHROME_START_FAIL": ("chromium --version이 실패했다", "같은 명령을 직접 실행해 오류 확인", None),
    "FONT_CJK_MISSING": ("한글(CJK) 글꼴이 없어 슬라이드 이미지 글자가 깨진다", "fonts-noto-cjk(google-noto-sans-cjk) 설치 후 fc-cache", "서버 관리자에게 CJK 글꼴 패키지(fonts-noto-cjk) 설치 요청"),
    "CLOCK_SKEW": ("이 서버 시계가 기준 서버와 크게 다르다(서명·인증서 검증 실패 원인)", "NTP(chrony) 설정 확인 후 시간 동기화", "이 서버에서 쓸 사내 NTP 서버 주소 안내 요청"),
    "TZ_NOT_SEOUL": ("시간대가 Asia/Seoul이 아니다(보고서·nightly 시각이 어긋남)", "export TZ=Asia/Seoul 또는 timedatectl set-timezone Asia/Seoul", None),
    "PORT_IN_USE": ("필요한 포트를 다른 프로세스가 쓰고 있다", "ss -ltnp로 프로세스 확인 후 종료하거나 다른 포트 사용", None),
    "FS_NOT_WRITABLE": ("저장소 또는 workspaces/에 쓸 수 없다", "소유자·권한(chown/chmod) 확인", None),
    "WORKSPACES_SYMLINK": ("workspaces/가 심볼릭 링크(또는 junction)다(경로 검사·백업이 어긋남)", "실제 폴더로 바꾸거나 저장소를 그 위치로 옮긴다", None),
    "DISK_LOW": ("디스크 여유 공간이 기준보다 적다", "불필요한 파일 정리 또는 디스크 증설", "서버 디스크 증설 요청(여유 {detail})"),
    "ENV_MISSING_*": ("필요한 환경 변수가 설정되지 않았다(값은 출력하지 않는다)", "workspaces/_site/beol.env 등에 이름=값을 넣고 셸에 export", None),
    "HTTP_401": ("API가 인증을 거부했다(키 없음·만료)", "키 환경 변수(auth_env) 값 확인", "{host} API 키 발급·만료 확인 요청(서비스 계정)"),
    "HTTP_403": ("API가 권한을 거부했다(키 권한 또는 IP 제한)", "키 권한·출발지 IP 허용 확인", "{host} API 권한 확인 요청 — 키 권한과 출발지 IP(이 서버) 허용"),
    "HTTP_404": ("요청한 경로가 없다(probe_path·API 버전 경로 확인)", "doctor_targets.json probe_path 확인", None),
    "HTTP_5xx": ("대상 서비스 내부 오류", "잠시 뒤 재시도, 계속되면 서비스 담당에게 문의", "{host} 서비스 상태 확인 요청(HTTP {detail})"),
    "HTTP_*": ("예상하지 못한 HTTP 상태 코드", "probe_path·proto 확인", None),
    "RATE_LIMITED": ("호출 한도 초과(429)", "잠시 뒤 재시도, 동시 호출 수 줄이기", "{host} 호출 한도(rate limit) 정보 또는 상향 요청"),
    "SKIPPED_NOT_LINUX": ("리눅스가 아니라 이 검사는 건너뛴다", "폐쇄망 리눅스 서버에서 다시 실행", None),
    "UNEXPECTED_*": ("doctor 내부 예외", "화면 출력과 doctor_report.json을 로컬 담당에게 전달", None),
}
# ===== CATALOG END =====


def lookup(code):
    """사유 코드의 카탈로그 항목. 없으면 None."""
    if code in CATALOG:
        return CATALOG[code]
    if re.match(r"HTTP_5\d\d$", code or ""):
        return CATALOG["HTTP_5xx"]
    best = None
    for key in CATALOG:
        if key.endswith("*") and (code or "").startswith(key[:-1]):
            if best is None or len(key) > len(best):
                best = key
    return CATALOG[best] if best else None


class DoctorFail(Exception):
    def __init__(self, code, detail=""):
        Exception.__init__(self, code)
        self.code = code
        self.detail = detail


def F(status, code=None, alias=None, detail="", port=None, proto=None):
    """한 검사 결과. detail에는 호스트·값을 넣지 않는다(코드·건수·버전만)."""
    return {"status": status, "code": code, "alias": alias, "detail": detail, "port": port, "proto": proto}


def exc_code(e):
    if isinstance(e, DoctorFail):
        return e.code
    if isinstance(e, socket.gaierror):
        return "DNS_UNRESOLVED"
    if isinstance(e, ssl.SSLCertVerificationError):
        vc = getattr(e, "verify_code", None)
        if vc in (2, 18, 19, 20, 21):
            return "TLS_CA_UNKNOWN"
        if vc == 10:
            return "TLS_CERT_EXPIRED"
        if vc == 62:
            return "TLS_HOSTNAME_MISMATCH"
        return "TLS_HANDSHAKE_FAIL"
    if isinstance(e, socket.timeout):
        return "CONN_TIMEOUT"
    if isinstance(e, ssl.SSLError):
        return "TLS_HANDSHAKE_FAIL"
    if isinstance(e, ConnectionRefusedError):
        return "CONN_REFUSED"
    if isinstance(e, (ConnectionResetError, ConnectionAbortedError)):
        return "CONN_RESET"
    if isinstance(e, http.client.HTTPException):
        return "HTTP_BAD_RESPONSE"
    if isinstance(e, OSError):
        en = getattr(e, "errno", None) or getattr(e, "winerror", None)
        if en in (errno.ENETUNREACH, errno.EHOSTUNREACH, 10051, 10065):
            return "NET_UNREACHABLE"
        if en in (errno.ETIMEDOUT, 10060):
            return "CONN_TIMEOUT"
        if en in (errno.ECONNREFUSED, 10061):
            return "CONN_REFUSED"
    return "UNEXPECTED_" + type(e).__name__


def proto_label(proto):
    return {"https": "TCP(HTTPS)", "http": "TCP(HTTP)"}.get(proto or "tcp", "TCP")


class Ctx(object):
    """실행 문맥: 대상·환경 변수·시간 제한. 출력 가림 목록(redact)도 여기서 모은다."""

    def __init__(self, doc=None, env=None, python=None, timeout=None, root=None, force_e15=False, targets_state="present"):
        self.doc = doc or {}
        self.env = dict(os.environ if env is None else env)
        self.python = python
        self.timeout = float(timeout or self.doc.get("timeout_s") or 5)
        self.root = root or CODE_ROOT
        self.force_e15 = force_e15
        self.targets_state = targets_state
        self.blocked = {}  # alias → (단계, 코드): 앞 단계에서 실패한 대상은 뒤 단계에서 건너뛴다
        self.targets = []
        for t in self.doc.get("targets") or []:
            if not isinstance(t, dict) or not t.get("alias") or not t.get("host"):
                continue
            proto = (t.get("proto") or "tcp").lower()
            port = int(t.get("port") or {"https": 443, "http": 80}.get(proto, 0))
            self.targets.append(dict(t, proto=proto, port=port, role=t.get("role") or t["alias"],
                                     internal=t.get("internal", True)))
        self._secrets = []
        for t in self.targets:
            self._add_secret(t["host"], "<%s>" % t["alias"])
            if t.get("auth_env"):
                self._add_secret(self.env.get(t["auth_env"], ""), "<값>")
        for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "NO_PROXY", "no_proxy"):
            raw = self.env.get(name, "")
            self._add_secret(raw, "<%s>" % name.upper())
            if name.upper() != "NO_PROXY" and raw:
                p = self._parse_proxy(raw)
                if p:
                    self._add_secret(p["host"], "<proxy>")
            elif raw:
                for part in raw.split(","):
                    self._add_secret(part.strip(), "<NO_PROXY 항목>")
        for name in self.doc.get("env_required") or []:
            self._add_secret(self.env.get(name, ""), "<값>")
        self._secrets.sort(key=lambda x: -len(x[0]))

    def _add_secret(self, s, rep):
        s = (s or "").strip()
        if len(s) >= 4:
            self._secrets.append((s, rep))

    def redact(self, text):
        for s, rep in self._secrets:
            if s in text:
                text = text.replace(s, rep)
        return text

    def ca_file(self):
        p = self.doc.get("ca_file") or ""
        if not p:
            return None
        return p if os.path.isabs(p) else os.path.join(self.root, p)

    def ssl_context(self):
        ca = self.ca_file()
        if ca and not os.path.isfile(ca):
            raise DoctorFail("TLS_CA_FILE_MISSING")
        return ssl.create_default_context(cafile=ca)

    @staticmethod
    def _parse_proxy(raw):
        raw = (raw or "").strip()
        if not raw:
            return None
        u = urllib.parse.urlsplit(raw if "://" in raw else "http://" + raw)
        if not u.hostname:
            return None
        auth = None
        if u.username:
            cred = "%s:%s" % (urllib.parse.unquote(u.username), urllib.parse.unquote(u.password or ""))
            auth = "Basic " + base64.b64encode(cred.encode("utf-8")).decode("ascii")
        try:
            port = u.port or 80
        except ValueError:
            port = 80
        return {"host": u.hostname, "port": port, "auth": auth}

    def _env(self, name):
        return self.env.get(name) or self.env.get(name.lower()) or ""

    def proxy_for(self, t):
        """대상이 실제로 거칠 프록시(없으면 None). tcp 대상과 NO_PROXY에 든 대상은 직접 연결."""
        if t["proto"] not in ("http", "https") or self.no_proxy_covers(t["host"]):
            return None
        return self._parse_proxy(self._env("HTTPS_PROXY" if t["proto"] == "https" else "HTTP_PROXY"))

    def no_proxy_covers(self, host):
        host = (host or "").lower().strip("[]")
        for e in self._env("NO_PROXY").split(","):
            e = e.strip().lower()
            if not e:
                continue
            if e == "*":
                return True
            if e.count(":") == 1:
                e = e.split(":")[0]
            try:
                if ipaddress.ip_address(host) in ipaddress.ip_network(e, strict=False):
                    return True
                continue
            except ValueError:
                pass
            e = e.lstrip("*").lstrip(".")
            if e and (host == e or host.endswith("." + e)):
                return True
        return False

    def open_tcp(self, t, timeout=None):
        """대상까지 TCP 소켓(프록시면 CONNECT 터널). 실패는 예외(DoctorFail 또는 OSError)."""
        timeout = timeout or self.timeout
        p = self.proxy_for(t)
        if not p:
            return socket.create_connection((t["host"], t["port"]), timeout=timeout)
        try:
            s = socket.create_connection((p["host"], p["port"]), timeout=timeout)
        except OSError as e:
            raise DoctorFail("PROXY_UNREACHABLE", exc_code(e))
        try:
            req = "CONNECT %s:%d HTTP/1.1\r\nHost: %s:%d\r\n" % (t["host"], t["port"], t["host"], t["port"])
            if p["auth"]:
                req += "Proxy-Authorization: %s\r\n" % p["auth"]
            s.sendall((req + "\r\n").encode("latin-1"))
            buf = b""
            while b"\r\n\r\n" not in buf and len(buf) < 16384:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
            m = re.match(rb"HTTP/\d(?:\.\d)?\s+(\d{3})", buf)
            status = int(m.group(1)) if m else 0
        except socket.timeout:
            s.close()
            raise DoctorFail("PROXY_UNREACHABLE", "응답 시간 초과")
        except OSError as e:
            s.close()
            raise DoctorFail("PROXY_UNREACHABLE", exc_code(e))
        if status == 200:
            return s
        s.close()
        if status == 407:
            raise DoctorFail("PROXY_AUTH_407")
        if status == 403:
            raise DoctorFail("PROXY_BLOCKED_URL")
        raise DoctorFail("PROXY_UPSTREAM_FAIL", "HTTP %d" % status if status else "응답 형식 오류")

    def http_request(self, t, method, path, headers=None):
        """최소 HTTP 요청. 반환 (상태 코드, 소문자 헤더 dict). 본문은 버린다."""
        hdrs = {"User-Agent": "beol-doctor/1", "Accept": "*/*"}
        hdrs.update(headers or {})
        path = path or "/"
        p = self.proxy_for(t)
        if t["proto"] == "https":
            raw = self.open_tcp(t)
            try:
                sock = self.ssl_context().wrap_socket(raw, server_hostname=t["host"])
            except Exception:
                raw.close()
                raise
            conn = http.client.HTTPConnection(t["host"], t["port"], timeout=self.timeout)
            conn.sock = sock
            url = path
        elif p:
            conn = http.client.HTTPConnection(p["host"], p["port"], timeout=self.timeout)
            url = "http://%s:%d%s" % (t["host"], t["port"], path)
            if p["auth"]:
                hdrs["Proxy-Authorization"] = p["auth"]
        else:
            conn = http.client.HTTPConnection(t["host"], t["port"], timeout=self.timeout)
            url = path
        try:
            conn.request(method, url, headers=hdrs)
            r = conn.getresponse()
            status = r.status
            out = dict((k.lower(), v) for k, v in r.getheaders())
            if method != "HEAD":
                r.read(65536)
        finally:
            conn.close()
        if p and t["proto"] == "http" and status == 407:
            raise DoctorFail("PROXY_AUTH_407")
        return status, out


def _resolve(host, port, timeout):
    """getaddrinfo에 시간 제한을 건다(스레드). 반환: 주소 수. 실패는 DoctorFail/gaierror."""
    box = {}

    def work():
        try:
            box["r"] = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
        except Exception as e:  # 스레드 밖으로 넘긴다
            box["e"] = e

    th = threading.Thread(target=work)
    th.daemon = True
    th.start()
    th.join(timeout)
    if th.is_alive():
        raise DoctorFail("DNS_UNRESOLVED", "시간 초과")
    if "e" in box:
        raise box["e"]
    return len(box.get("r") or [])


def _run(cmd, env=None, timeout=120):
    """하위 프로세스. 반환 (rc, 출력 합친 문자열). 실행 불가면 (None, 예외 이름)."""
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "TimeoutExpired"
    except OSError as e:
        return None, type(e).__name__
    return p.returncode, p.stdout.decode("utf-8", "replace")


def _is_linux():
    return sys.platform.startswith("linux")


def _direct_targets(ctx, protos=("tcp", "http", "https")):
    return [t for t in ctx.targets if t["proto"] in protos]


def _targets_missing(ctx):
    if ctx.targets_state == "missing":
        return [F("WARN", "TARGETS_MISSING", detail="네트워크 검사 대상 없음")]
    if ctx.targets_state == "invalid":
        return [F("FAIL", "TARGETS_INVALID")]
    if not ctx.targets:
        return [F("SKIP", None, detail="targets 목록이 비었다")]
    return None


# ---------------- 단계 ----------------

def e01_python(ctx):
    v = sys.version_info
    bits = 8 * struct.calcsize("P")
    detail = "%d.%d.%d %s %dbit" % (v[0], v[1], v[2], platform.machine() or "?", bits)
    if v < (3, 8):
        return [F("FAIL", "PY3_TOO_OLD", detail=detail)]
    return [F("PASS", detail=detail)]


def e02_dns(ctx):
    miss = _targets_missing(ctx)
    if miss:
        return miss
    out = []
    for t in ctx.targets:
        if ctx.proxy_for(t):
            out.append(F("SKIP", None, t["alias"], "프록시 경유 — E05에서 확인", t["port"], t["proto"]))
            continue
        try:
            ipaddress.ip_address(t["host"].strip("[]"))
            out.append(F("PASS", None, t["alias"], "IP 리터럴", t["port"], t["proto"]))
            continue
        except ValueError:
            pass
        try:
            n = _resolve(t["host"], t["port"], ctx.timeout)
            out.append(F("PASS", None, t["alias"], "주소 %d개" % n, t["port"], t["proto"]))
        except Exception as e:  # 코드로 분류해 남긴다
            code = exc_code(e)
            ctx.blocked[t["alias"]] = ("E02", code)
            out.append(F("FAIL", code, t["alias"], getattr(e, "detail", ""), t["port"], t["proto"]))
    return out


def _blocked_skip(ctx, t):
    b = ctx.blocked.get(t["alias"])
    if b:
        return F("SKIP", None, t["alias"], "%s 실패(%s)로 건너뜀" % b, t["port"], t["proto"])
    return None


def e03_tcp(ctx):
    miss = _targets_missing(ctx)
    if miss:
        return miss
    out = []
    for t in ctx.targets:
        if ctx.proxy_for(t):
            out.append(F("SKIP", None, t["alias"], "프록시 경유 — E05에서 확인", t["port"], t["proto"]))
            continue
        sk = _blocked_skip(ctx, t)
        if sk:
            out.append(sk)
            continue
        try:
            s = socket.create_connection((t["host"], t["port"]), timeout=ctx.timeout)
            s.close()
            out.append(F("PASS", None, t["alias"], "연결됨", t["port"], t["proto"]))
        except Exception as e:  # 코드로 분류해 남긴다
            code = exc_code(e)
            ctx.blocked[t["alias"]] = ("E03", code)
            out.append(F("FAIL", code, t["alias"], "", t["port"], t["proto"]))
    return out


def e04_tls(ctx):
    miss = _targets_missing(ctx)
    if miss:
        return miss
    out = []
    for t in ctx.targets:
        if t["proto"] != "https":
            continue
        sk = _blocked_skip(ctx, t)
        if sk:
            out.append(sk)
            continue
        raw = None
        try:
            sslctx = ctx.ssl_context()
            raw = ctx.open_tcp(t)
            s = sslctx.wrap_socket(raw, server_hostname=t["host"])
            ver = s.version() or "TLS"
            s.close()
            out.append(F("PASS", None, t["alias"], ver, t["port"], t["proto"]))
        except Exception as e:  # 코드로 분류해 남긴다
            if raw is not None:
                raw.close()
            code = exc_code(e)
            ctx.blocked[t["alias"]] = ("E04", code)
            out.append(F("FAIL", code, t["alias"], getattr(e, "detail", ""), t["port"], t["proto"]))
    if not out:
        out.append(F("SKIP", None, detail="https 대상 없음"))
    return out


def e05_proxy(ctx):
    raw = {k: ctx._env(k) for k in ("HTTPS_PROXY", "HTTP_PROXY")}
    if not any(raw.values()):
        return [F("PASS", None, "proxy", "프록시 환경 변수 없음(직접 연결)")]
    out = []
    down = set()
    for name, val in raw.items():
        p = ctx._parse_proxy(val)
        if val and not p:
            out.append(F("FAIL", "PROXY_UNREACHABLE", "proxy", "%s 형식 오류" % name))
            down.add(name)
            continue
        if not p:
            continue
        try:
            s = socket.create_connection((p["host"], p["port"]), timeout=ctx.timeout)
            s.close()
            out.append(F("PASS", None, "proxy", "%s 연결됨" % name, p["port"], "tcp"))
        except Exception as e:  # 코드로 분류해 남긴다
            out.append(F("FAIL", "PROXY_UNREACHABLE", "proxy", "%s %s" % (name, exc_code(e)), p["port"], "tcp"))
            down.add(name)
    for t in ctx.targets:
        if t["proto"] not in ("http", "https"):
            continue
        covered = ctx.no_proxy_covers(t["host"])
        if t["internal"] and not covered:
            out.append(F("WARN", "NO_PROXY_MISSING", t["alias"], "", t["port"], t["proto"]))
        if covered:
            continue
        pname = "HTTPS_PROXY" if t["proto"] == "https" else "HTTP_PROXY"
        if not raw.get(pname) or pname in down:
            if raw.get(pname):
                ctx.blocked[t["alias"]] = ("E05", "PROXY_UNREACHABLE")
            continue
        try:
            if t["proto"] == "https":
                ctx.open_tcp(t).close()
                out.append(F("PASS", None, t["alias"], "CONNECT 200", t["port"], t["proto"]))
            else:
                status, _ = ctx.http_request(t, "HEAD", t.get("probe_path") or "/")
                if status == 403:
                    raise DoctorFail("PROXY_BLOCKED_URL")
                out.append(F("PASS", None, t["alias"], "프록시 경유 HTTP %d" % status, t["port"], t["proto"]))
        except Exception as e:  # 코드로 분류해 남긴다
            code = exc_code(e)
            ctx.blocked[t["alias"]] = ("E05", code)
            out.append(F("FAIL", code, t["alias"], getattr(e, "detail", ""), t["port"], t["proto"]))
    return out


def _sudo_prefix(ctx, out):
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return []
    if not shutil.which("sudo"):
        out.append(F("WARN", "NO_SUDO", detail="sudo 없음"))
        return None
    rc, _ = _run(["sudo", "-n", "true"], timeout=15)
    if rc != 0:
        out.append(F("WARN", "NO_SUDO"))
        return None
    return ["sudo", "-n"]


def e06_pkg_mirror(ctx):
    if not _is_linux():
        return [F("SKIP", "SKIPPED_NOT_LINUX")]
    out = []
    mirrors = [t for t in ctx.targets if t["role"] == "mirror" and t["proto"] in ("http", "https")]
    for t in mirrors:
        sk = _blocked_skip(ctx, t)
        if sk:
            out.append(sk)
            continue
        try:
            status, _ = ctx.http_request(t, "GET", t.get("probe_path") or "/")
            if status >= 400:
                out.append(F("FAIL", "HTTP_%d" % status, t["alias"], str(status), t["port"], t["proto"]))
            else:
                out.append(F("PASS", None, t["alias"], "HTTP %d" % status, t["port"], t["proto"]))
        except Exception as e:  # 코드로 분류해 남긴다
            out.append(F("FAIL", exc_code(e), t["alias"], "", t["port"], t["proto"]))
    mgr = next((m for m in ("apt-get", "dnf", "yum") if shutil.which(m)), None)
    if not mgr:
        out.append(F("FAIL", "PKG_MANAGER_MISSING"))
        return out
    pkgs = (ctx.doc.get("packages") or {}).get("apt" if mgr == "apt-get" else "dnf") or []
    if not pkgs:
        out.append(F("SKIP", None, detail="모의 설치할 패키지 목록 없음"))
        return out
    alias = mirrors[0]["alias"] if mirrors else "mirror"
    env = dict(ctx.env, LC_ALL="C", LANG="C")
    if mgr == "apt-get":
        _sudo_prefix(ctx, out)  # 모의 설치는 sudo 없이 되지만 실제 설치에는 필요하다
        rc, text = _run(["apt-get", "install", "-s", "--no-install-recommends"] + pkgs, env=env, timeout=180)
        if rc is None:
            out.append(F("FAIL", "PKG_SIM_FAIL", detail=text))
            return out
        if re.search(r"Could not get lock|Unable to acquire the dpkg frontend lock|is another process using it", text):
            out.append(F("FAIL", "APT_LOCK_HELD"))
            return out
        missing = re.findall(r"Unable to locate package (\S+)", text)
        missing += re.findall(r"Package '?([^'\s]+)'? has no installation candidate", text)
    else:
        prefix = _sudo_prefix(ctx, out) or []
        rc, text = _run(prefix + [mgr, "install", "--assumeno"] + pkgs, env=env, timeout=300)
        if rc is None:
            out.append(F("FAIL", "PKG_SIM_FAIL", detail=text))
            return out
        if re.search(r"Waiting for process with pid|Existing lock", text):
            out.append(F("FAIL", "PKG_LOCK_HELD"))
            return out
        if re.search(r"Failed to download metadata|Cannot download repomd|Curl error", text):
            out.append(F("FAIL", "MIRROR_UNREACHABLE", alias))
            return out
        missing = re.findall(r"No match for argument:\s*(\S+)", text)
    for name in missing:
        out.append(F("FAIL", "PKG_NOT_IN_MIRROR", alias, name))
    if not missing:
        if rc != 0 and mgr == "apt-get":
            out.append(F("FAIL", "PKG_SIM_FAIL", detail="rc=%d" % rc))
        else:
            out.append(F("PASS", None, alias, "%s 모의 설치 %d개 확인" % (mgr, len(pkgs))))
    return out


def _pip_code(text):
    checks = [
        (r"CERTIFICATE_VERIFY_FAILED|problem confirming the ssl certificate", "PIP_CA"),
        (r"ProxyError|Cannot connect to proxy|407 Proxy Authentication", "PIP_PROXY"),
        (r"NewConnectionError|ConnectTimeoutError|Failed to establish a new connection|Read timed out|"
         r"Max retries exceeded|Name or service not known|getaddrinfo failed|Temporary failure in name resolution", "PIP_INDEX_UNREACHABLE"),
        (r"DO NOT MATCH THE HASHES", "PIP_HASH_MISMATCH"),
        (r"ResolutionImpossible|conflicting dependencies", "PIP_VERSION_CONFLICT"),
        (r"Failed building wheel|subprocess-exited-with-error|metadata-generation-failed", "PIP_BUILD_DEPS_MISSING"),
        (r"No matching distribution found|Could not find a version that satisfies", "PIP_PKG_NOT_FOUND"),
    ]
    for rx, code in checks:
        if re.search(rx, text):
            return code
    return "PIP_FAILED"


def e07_pip(ctx):
    pkgs = (ctx.doc.get("packages") or {}).get("pip") or []
    if not pkgs:
        return [F("SKIP", None, "pip", "확인할 pip 패키지 없음(본체는 의존성 0)")]
    py = ctx.python or sys.executable
    env = dict(ctx.env, PIP_NO_INPUT="1", PIP_DISABLE_PIP_VERSION_CHECK="1")
    rc, _ = _run([py, "-m", "pip", "--version"], env=env, timeout=60)
    if rc != 0:
        return [F("FAIL", "PIP_MISSING", "pip")]
    idx = []
    t = next((x for x in ctx.targets if x["role"] == "pip"), None)
    alias, port, proto = ("pip", None, None)
    if t:
        alias, port, proto = t["alias"], t["port"], t["proto"]
        default_port = {"https": 443, "http": 80}.get(t["proto"])
        hostport = t["host"] if t["port"] == default_port else "%s:%d" % (t["host"], t["port"])
        idx = ["--index-url", "%s://%s%s" % (t["proto"], hostport, t.get("index_path") or "/simple")]
        if t["proto"] == "http":
            idx += ["--trusted-host", t["host"]]
    ca = ctx.ca_file()
    if ca:
        idx += ["--cert", ca]
    if t:
        # pip는 연결 실패도 "No matching distribution"으로 끝낼 수 있어, 인덱스 루트를 먼저 직접 확인한다
        sk = _blocked_skip(ctx, t)
        if sk:
            return [sk]
        try:
            status, _ = ctx.http_request(t, "GET", (t.get("index_path") or "/simple").rstrip("/") + "/")
        except Exception as e:  # 코드로 분류해 남긴다
            code = exc_code(e)
            pcode = ("PIP_CA" if code.startswith("TLS_") else "PIP_PROXY" if code.startswith("PROXY_")
                     else "PIP_INDEX_UNREACHABLE")
            return [F("FAIL", pcode, alias, code, port, proto)]
        if status >= 500:
            return [F("FAIL", "PIP_INDEX_UNREACHABLE", alias, "HTTP %d" % status, port, proto)]
    out = []
    tmo = max(60, int(ctx.timeout * 8))
    for pkg in pkgs:
        tmp = tempfile.mkdtemp(prefix="beol_doctor_pip_")
        try:
            cmd = [py, "-m", "pip", "download", "--no-deps", "--no-cache-dir", "--dest", tmp,
                   "--timeout", str(int(ctx.timeout)), "--retries", "1"] + idx + [pkg]
            rc, text = _run(cmd, env=env, timeout=tmo)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if rc is None:
            out.append(F("FAIL", "PIP_INDEX_UNREACHABLE", alias, "시간 초과", port, proto))
        elif rc == 0:
            out.append(F("PASS", None, alias, "%s 받기 확인" % pkg, port, proto))
        else:
            out.append(F("FAIL", _pip_code(text), alias, pkg, port, proto))
    return out


def e08_py_build(ctx):
    out = []
    linux = _is_linux()
    target = ctx.python or shutil.which("python3.14")
    if linux:
        pkgconf = shutil.which("pkg-config")
        for name, pc, headers in BUILD_LIBS:
            ok = False
            if pkgconf:
                rc, _ = _run([pkgconf, "--exists", pc], timeout=20)
                ok = rc == 0
            if not ok:
                ok = any(os.path.isfile(os.path.join(d, h)) for d in INCLUDE_DIRS for h in headers)
            if not ok:
                out.append(F("FAIL", "BUILD_HEADER_MISSING_" + name, detail=name))
    elif not target:
        return [F("SKIP", "SKIPPED_NOT_LINUX", detail="헤더 검사는 리눅스만, --python 없음")]
    if target:
        code = ("import importlib,sys\nprint('VER %d.%d.%d' % sys.version_info[:3])\n"
                "for m in " + repr(PY_MODULES) + ":\n    try:\n        importlib.import_module(m)\n"
                "    except Exception:\n        print('MISSING', m)\n")
        rc, text = _run([target, "-c", code], timeout=60)
        if rc is None or "VER " not in (text or ""):
            out.append(F("FAIL", "PY_TARGET_NOT_FOUND"))
        else:
            missing = re.findall(r"^MISSING (\w+)", text, re.M)
            for m in missing:
                out.append(F("FAIL", "PY_MODULE_MISSING_" + m, detail=m))
            ver = re.search(r"VER (\S+)", text).group(1)
            if not missing:
                # 이미 빌드한 Python이 다 import하면 헤더 없음은 경고로 낮춘다(다시 빌드할 때만 필요)
                for f in out:
                    if f["status"] == "FAIL" and (f["code"] or "").startswith("BUILD_HEADER_MISSING_"):
                        f["status"] = "WARN"
                out.append(F("PASS", None, detail="대상 Python %s import %s 정상" % (ver, ",".join(PY_MODULES))))
    if not out:
        out.append(F("PASS", None, detail="빌드 헤더 %d종 있음" % len(BUILD_LIBS)))
    return out


def _find_chrome(ctx):
    p = ctx.doc.get("chromium_path")
    if p:
        return p if os.path.isfile(p) else None
    env_p = os.path.expanduser((ctx.env.get("BEOL_CHROME") or "").strip())  # labelbot/cdp.py와 같은 env
    if env_p:
        cands = [env_p]
        if os.path.isdir(env_p):
            cands = [os.path.join(env_p, "chrome-linux64", "chrome"), os.path.join(env_p, "chrome")]
        return next((c for c in cands if os.path.isfile(c)), None)
    for name in CHROME_NAMES:
        w = shutil.which(name)
        if w:
            return w
    pf = [ctx.env.get(k) or ctx.env.get(k.upper()) for k in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
    cands = []
    for base in [b for b in pf if b]:
        cands.append(os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"))
        cands.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
    cands += ["/usr/bin/microsoft-edge", "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
              "/usr/bin/google-chrome-stable", "/snap/bin/chromium",
              os.path.join(os.path.expanduser("~"), ".local", "opt", "chrome-linux64", "chrome"),
              "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    return next((c for c in cands if os.path.isfile(c)), None)


def e09_chromium(ctx):
    out = []
    path = _find_chrome(ctx)
    if not path:
        out.append(F("FAIL", "CHROME_MISSING"))
    elif not _is_linux():
        out.append(F("PASS", None, detail="실행 파일 있음(--version은 리눅스에서만)"))
    else:
        rc, text = _run([path, "--version"], timeout=30)
        libs = []
        if shutil.which("ldd"):
            _, ltxt = _run(["ldd", path], timeout=30)
            libs = re.findall(r"^\s*(\S+)\s+=>\s+not found", ltxt or "", re.M)
        if libs:
            out.append(F("FAIL", "CHROME_MISSING_LIB", detail=" ".join(sorted(set(libs)))))
        elif rc != 0:
            out.append(F("FAIL", "CHROME_START_FAIL", detail="rc=%s" % rc))
        else:
            m = re.search(r"(\d+\.\d+[\d.]*)", text or "")
            out.append(F("PASS", None, detail="버전 %s" % (m.group(1) if m else "?")))
    if _is_linux():
        if not shutil.which("fc-list"):
            out.append(F("FAIL", "FONT_CJK_MISSING", detail="fc-list 없음(fontconfig)"))
        else:
            _, ftxt = _run(["fc-list", ":lang=ko", "family"], timeout=30)
            n = len([x for x in (ftxt or "").splitlines() if x.strip()])
            out.append(F("PASS", None, detail="한글 글꼴 %d종" % n) if n else F("FAIL", "FONT_CJK_MISSING"))
    return out


def e10_clock(ctx):
    ref = ctx.doc.get("clock_ref")
    web = [t for t in ctx.targets if t["proto"] in ("http", "https")]
    t = next((x for x in web if x["alias"] == ref), None) if ref else None
    if t is None:
        t = next((x for x in web if x["role"] in ("s3", "mirror", "pip")), None) or (web[0] if web else None)
    if t is None:
        return [F("SKIP", None, detail="기준 HTTP 대상 없음")]
    sk = _blocked_skip(ctx, t)
    if sk:
        return [sk]
    try:
        _, hdrs = ctx.http_request(t, "HEAD", t.get("probe_path") or "/")
    except Exception as e:  # 연결 문제는 E02~E05가 낸다
        return [F("SKIP", None, t["alias"], "기준 대상 응답 없음(%s)" % exc_code(e), t["port"], t["proto"])]
    date = hdrs.get("date")
    if not date:
        return [F("SKIP", None, t["alias"], "Date 헤더 없음", t["port"], t["proto"])]
    try:
        server = email.utils.parsedate_to_datetime(date).timestamp()
    except (TypeError, ValueError):
        return [F("SKIP", None, t["alias"], "Date 헤더 형식 오류", t["port"], t["proto"])]
    skew = time.time() - server
    limit = float(ctx.doc.get("clock_max_skew_s") or 120)
    detail = "%+ds" % int(round(skew))
    if abs(skew) > limit:
        return [F("FAIL", "CLOCK_SKEW", t["alias"], detail, t["port"], t["proto"])]
    return [F("PASS", None, t["alias"], "오차 " + detail, t["port"], t["proto"])]


def e11_tz(ctx):
    name = ctx.env.get("TZ") or ""
    if not name and _is_linux():
        try:
            with open("/etc/timezone") as f:
                name = f.read().strip()
        except OSError:
            link = os.path.realpath("/etc/localtime")
            if "zoneinfo/" in link:
                name = link.split("zoneinfo/", 1)[1]
    offset = -(time.altzone if time.daylight and time.localtime().tm_isdst else time.timezone)
    off = "%+03d:%02d" % (offset // 3600, (abs(offset) % 3600) // 60)
    if name:
        ok = name.lstrip(":") in ("Asia/Seoul", "ROK")
    else:
        ok = offset == 9 * 3600
    if ok:
        return [F("PASS", None, detail="%s UTC%s" % (name or "로컬", off))]
    return [F("WARN", "TZ_NOT_SEOUL", detail="UTC%s" % off)]


def _port_free(port):
    for addr in ("127.0.0.1", "0.0.0.0"):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            s.bind((addr, port))
        except OSError:
            return False
        finally:
            s.close()
    return True


def e12_ports(ctx):
    ports = ctx.doc.get("ports", DEFAULT_PORTS)
    ranges = ctx.doc.get("port_ranges", DEFAULT_PORT_RANGES)
    out = []
    for p in ports:
        if not _port_free(int(p)):
            out.append(F("FAIL", "PORT_IN_USE", None, "", int(p), "tcp"))
    for lo, hi in ranges:
        cand = [p for p in range(int(lo), int(hi) + 1) if p not in ports]
        busy = [p for p in cand if not _port_free(p)]
        if cand and len(busy) == len(cand):
            out.append(F("FAIL", "PORT_IN_USE", None, "%d-%d 빈 포트 없음" % (lo, hi)))
        elif busy:
            out.append(F("WARN", "PORT_IN_USE", None, "%d-%d 중 %d개 사용 중" % (lo, hi, len(busy))))
    if not out:
        out.append(F("PASS", None, detail="고정 %d개·범위 %d개 사용 가능" % (len(ports), len(ranges))))
    return out


def e13_fs(ctx):
    out = []
    ws = os.path.join(ctx.root, "workspaces")
    if os.path.lexists(ws):
        real = os.path.normcase(os.path.realpath(ws))
        expect = os.path.normcase(os.path.join(os.path.realpath(ctx.root), "workspaces"))
        if os.path.islink(ws) or real != expect:
            out.append(F("FAIL", "WORKSPACES_SYMLINK"))
    for label, d in (("저장소", ctx.root), ("workspaces/_site", os.path.join(ws, "_site"))):
        try:
            os.makedirs(d, exist_ok=True)
            fd, p = tempfile.mkstemp(prefix=".doctor_", suffix=".log", dir=d)
            os.close(fd)
            os.remove(p)
        except OSError:
            out.append(F("FAIL", "FS_NOT_WRITABLE", detail=label))
    try:
        free_gb = shutil.disk_usage(ctx.root).free / float(1 << 30)
        need = float(ctx.doc.get("disk_min_gb") or 10)
        if free_gb < need:
            out.append(F("FAIL", "DISK_LOW", detail="%.1fGB < %.0fGB" % (free_gb, need)))
        else:
            out.append(F("PASS", None, detail="여유 %.0fGB" % free_gb))
    except OSError:
        out.append(F("FAIL", "FS_NOT_WRITABLE", detail="disk_usage"))
    return out


def e14_env(ctx):
    names = ctx.doc.get("env_required") or []
    if not names:
        return [F("SKIP", None, detail="env_required 목록 없음")]
    out = []
    for n in names:
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", n or ""):
            continue
        if not ctx.env.get(n):
            out.append(F("FAIL", "ENV_MISSING_" + n, detail=n))
    if not out:
        out.append(F("PASS", None, detail="%d개 설정됨(값 미출력)" % len(names)))
    return out


def e15_endpoints(ctx):
    if not (ctx.force_e15 or ctx.doc.get("e15_enabled")):
        return [F("SKIP", None, detail="게이트 후 실행: --step E15 또는 doctor_targets.json e15_enabled=true")]
    out = []
    for t in ctx.targets:
        if t["role"] not in E15_ROLES or t["proto"] not in ("http", "https"):
            continue
        sk = _blocked_skip(ctx, t)
        if sk:
            out.append(sk)
            continue
        hdrs = {}
        key = ctx.env.get(t.get("auth_env") or "", "")
        if key:
            hdrs["Authorization"] = "Bearer " + key
        try:
            status, _ = ctx.http_request(t, "GET", t.get("probe_path") or "/", hdrs)
        except Exception as e:  # 코드로 분류해 남긴다
            out.append(F("FAIL", exc_code(e), t["alias"], "", t["port"], t["proto"]))
            continue
        if status < 400:
            out.append(F("PASS", None, t["alias"], "HTTP %d" % status, t["port"], t["proto"]))
        elif status in (401, 403) and not key:
            out.append(F("PASS", None, t["alias"], "도달 가능(HTTP %d, 키 미전송)" % status, t["port"], t["proto"]))
        elif status == 429:
            out.append(F("FAIL", "RATE_LIMITED", t["alias"], "429", t["port"], t["proto"]))
        else:
            out.append(F("FAIL", "HTTP_%d" % status, t["alias"], str(status), t["port"], t["proto"]))
    if not out:
        out.append(F("SKIP", None, detail="llm·embed·vectordb·s3 대상 없음"))
    return out


STEP_FUNCS = {
    "E01": e01_python, "E02": e02_dns, "E03": e03_tcp, "E04": e04_tls, "E05": e05_proxy, "E06": e06_pkg_mirror,
    "E07": e07_pip, "E08": e08_py_build, "E09": e09_chromium, "E10": e10_clock, "E11": e11_tz, "E12": e12_ports,
    "E13": e13_fs, "E14": e14_env, "E15": e15_endpoints,
}


def run_step(ctx, sid):
    t0 = time.time()
    try:
        findings = STEP_FUNCS[sid](ctx) or []
    except Exception as e:  # 단계 하나의 예외가 doctor 전체를 멈추지 않는다
        findings = [F("FAIL", "UNEXPECTED_" + type(e).__name__)]
    sts = [f["status"] for f in findings]
    status = "FAIL" if "FAIL" in sts else "WARN" if "WARN" in sts else "PASS" if "PASS" in sts else "SKIP"
    return {"id": sid, "name": STEP_NAMES[sid], "status": status, "elapsed_s": round(time.time() - t0, 2),
            "findings": findings}


def run_steps(ctx, selected):
    """E05를 먼저 돌린다(프록시가 다른 검사를 막을 수 있다). 결과는 E01~E15 순서로 돌려준다."""
    order = (["E05"] if "E05" in selected else []) + [s for s, _ in STEPS if s in selected and s != "E05"]
    res = {}
    for sid in order:
        res[sid] = run_step(ctx, sid)
    return [res[s] for s, _ in STEPS if s in res]


# ---------------- 출력 ----------------

MARK = {"PASS": "✔", "FAIL": "✖", "WARN": "!", "SKIP": "—"}


def relay_sentence(code, f):
    entry = lookup(code)
    if not entry or not entry[2]:
        return None
    alias = f.get("alias") or "대상"
    host = "<%s 호스트>" % alias
    text = entry[2].format(host=host, port=f.get("port") or "<포트>", proto=proto_label(f.get("proto")),
                           detail=f.get("detail") or "")
    if "{host}" in entry[2]:
        text += ' (%s는 doctor_targets.json "%s" 항목의 host로 바꿔 전달)' % (host, alias)
    return text


def failure_block(step, f):
    code = f["code"] or "UNKNOWN"
    word = "실패" if f["status"] == "FAIL" else "경고"
    head = "[%s/%s %s] %s  사유=%s" % (MILESTONE, step["id"], step["name"], word, code)
    if f.get("alias"):
        head += "  대상=%s" % f["alias"]
    if f.get("port"):
        head += "  포트=%s" % f["port"]
    if f.get("detail"):
        head += "  ( %s )" % f["detail"]
    entry = lookup(code) or ("카탈로그에 없는 코드", "doctor_report.json을 로컬 담당에게 전달", None)
    lines = [head, "  원인: " + entry[0], "  조치: " + entry[1]]
    rel = relay_sentence(code, f)
    if rel:
        lines.append('  담당자에게: "%s"' % rel)
    return lines


def _summary(step):
    bad = [f for f in step["findings"] if f["status"] in ("FAIL", "WARN")]
    if bad:
        counts = {}
        for f in bad:
            counts[f["code"]] = counts.get(f["code"], 0) + 1
        return ", ".join("%s×%d" % (c, n) if n > 1 else str(c) for c, n in counts.items())
    first = next((f for f in step["findings"] if f.get("detail") or f.get("code")), None)
    if not first:
        return ""
    return (first.get("code") or first.get("detail") or "") if step["status"] == "SKIP" else (first.get("detail") or "")


def first_fail(steps):
    for s in steps:
        for f in s["findings"]:
            if f["status"] == "FAIL":
                return {"step": s["id"], "name": s["name"], "code": f["code"], "alias": f.get("alias")}
    return None


def proxy_summary(step):
    bad = [f for f in step["findings"] if f["status"] == "FAIL"]
    warn = [f for f in step["findings"] if f["status"] == "WARN"]
    if bad:
        f = bad[0]
        return "프록시 판정(E05): ✖ %s (대상=%s) — 다른 네트워크 단계 결과가 이 판정의 영향을 받는다" % (f["code"], f.get("alias"))
    if warn:
        return "프록시 판정(E05): ! %s %d건 — 사내 호스트가 프록시로 나간다" % (warn[0]["code"], len(warn))
    detail = next((f.get("detail") for f in step["findings"] if f.get("detail")), "")
    return "프록시 판정(E05): ✔ %s" % detail


def render_text(report, targets_label, report_label):
    lines = ["BEOL doctor — %s  (대상 파일: %s)" % (MILESTONE, targets_label)]
    p = next((s for s in report["steps"] if s["id"] == "E05"), None)
    if p:
        lines.append(proxy_summary(p))
    lines.append("")
    ff = report["first_fail"]
    lines.append("   %-4s %-12s %-7s %s" % ("단계", "이름", "결과", "요약"))
    for s in report["steps"]:
        mark = "▶" if ff and ff["step"] == s["id"] else " "
        lines.append("%s  %-4s %-12s %s %-5s %s" % (mark, s["id"], s["name"], MARK[s["status"]], s["status"], _summary(s)))
    lines.append("")
    if ff:
        lines.append("▶ 처음 실패: %s %s — %s%s" % (ff["step"], ff["name"], ff["code"],
                                               " (대상=%s)" % ff["alias"] if ff.get("alias") else ""))
        lines.append("")
    for s in report["steps"]:
        for f in s["findings"]:
            if f["status"] in ("FAIL", "WARN"):
                lines.extend(failure_block(s, f))
                lines.append("")
    lines.append("주의: 미러·프록시가 User-Agent로 허용 목록을 거는 경우 doctor 판정과 실제 apt·pip 결과가 다를 수 있다.")
    lines.append("결과: %s  보고: %s (별칭·사유 코드만)" % (report["result"], report_label))
    return lines


def _label(path):
    """출력용 경로 표시. 저장소 안이면 상대경로, 밖이면 파일 이름만(사용자 경로를 내보내지 않는다)."""
    try:
        rel = os.path.relpath(os.path.abspath(path), CODE_ROOT)
    except ValueError:
        return os.path.basename(path)
    if rel.startswith(".."):
        return os.path.basename(path)
    return rel.replace("\\", "/")


def load_targets(path):
    if not os.path.isfile(path):
        return {}, "missing"
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        if not isinstance(doc, dict):
            return {}, "invalid"
        return doc, "present"
    except (OSError, ValueError):
        return {}, "invalid"


def build_report(steps, selected, targets_state):
    ff = first_fail(steps)
    clean = []
    for s in steps:
        fs = [dict((k, v) for k, v in f.items() if v not in (None, "")) for f in s["findings"]]
        clean.append(dict(s, findings=fs))
    return {"tool": "beol_doctor", "milestone": MILESTONE,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "targets_file": targets_state, "steps_selected": selected, "steps": clean,
            "first_fail": ff, "result": "FAIL" if ff else "PASS", "exit_code": 1 if ff else 0}


def write_report(path, text):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def parse_steps(value):
    out = []
    for part in (value or "").replace(" ", "").split(","):
        if not part:
            continue
        sid = part.upper()
        if sid not in STEP_FUNCS:
            raise argparse.ArgumentTypeError("알 수 없는 단계: %s (E01~E15)" % part)
        out.append(sid)
    return out


def build_parser():
    ap = argparse.ArgumentParser(prog="beol_doctor", description="BEOL 환경·설치 진단(M00 ENV, E01~E15)")
    ap.add_argument("--step", type=parse_steps, action="append", help="이 단계만(E07 또는 E02,E03). 여러 번 줄 수 있다")
    ap.add_argument("--json", action="store_true", help="표 대신 JSON 보고를 출력")
    ap.add_argument("--targets", default=DEFAULT_TARGETS, help="대상 파일(기본 workspaces/_site/doctor_targets.json)")
    ap.add_argument("--python", help="E07·E08에서 검사할 Python 실행 파일(예: 빌드한 python3.14)")
    ap.add_argument("--report", default=DEFAULT_REPORT, help="보고 파일(기본 workspaces/_site/doctor_report.json)")
    return ap


def _reconfigure_stdout():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv=None, env=None):
    _reconfigure_stdout()
    args = build_parser().parse_args(argv)
    ctx = None
    try:
        selected = [s for group in (args.step or []) for s in group] or [s for s, _ in STEPS]
        selected = [s for s, _ in STEPS if s in selected]
        doc, state = load_targets(args.targets)
        ctx = Ctx(doc, env=env, python=args.python, targets_state=state, force_e15=bool(args.step) and "E15" in selected)
        steps = run_steps(ctx, selected)
        report = build_report(steps, selected, state)
        report_text = ctx.redact(json.dumps(report, ensure_ascii=False, indent=2))
        saved = True
        try:
            write_report(args.report, report_text + "\n")
        except OSError:
            saved = False
        if args.json:
            print(report_text)
        else:
            label = _label(args.targets) + ("" if state == "present" else " (%s)" % {"missing": "없음", "invalid": "형식 오류"}[state])
            rep_label = _label(args.report) if saved else "저장 실패(FS_NOT_WRITABLE)"
            for line in render_text(report, label, rep_label):
                print(ctx.redact(line))
        sys.stdout.flush()
        return report["exit_code"]
    except KeyboardInterrupt:
        print("[%s] 중단(사용자)" % MILESTONE)
        return 1
    except Exception as e:  # 최상위 가드: traceback 대신 사유 코드
        code = "UNEXPECTED_" + type(e).__name__
        for line in failure_block({"id": "E00", "name": "DOCTOR"}, F("FAIL", code)):
            print(ctx.redact(line) if ctx else line)
        return 1


if __name__ == "__main__":
    sys.exit(main())
