"""사유 코드 카탈로그(L3c, 단일 출처): 사유 코드 → 원인·조치·마일스톤. 마일스톤별 조치 덮어쓰기.

- 같은 HTTP_401이라도 마일스톤(M07 임베딩 / M02·M03 LLM / M08 벡터 저장)에 따라 원인·조치가 다르다.
- 패턴 항목: HTTP_\\d+, CDP_HTTP_\\d+, RC_\\d+, UNEXPECTED_.*, 그리고 doctor의 접두어 항목(키 끝 *).
- tools/beol_doctor.py의 CATALOG(3.8용 사본)는 아래 _DOCTOR에 그대로 들어 있다. 사본 일치는
  tests/test_reason_codes.py가 검사한다(doctor를 고치면 여기도 같이 고친다).
- 완전성: labelbot·domain_engrbot이 내는 사유 코드 문자열은 모두 여기 있어야 한다(tests/test_reason_codes.py).
- Python 3.8 문법·표준 라이브러리만, 다른 labelbot 모듈을 import하지 않는다(tools/beol_status.py가 읽는다).
"""
import re

ANY = "*"  # milestones에 넣으면 어느 마일스톤에도 쓰는 일반 항목

# ===== doctor CATALOG 사본 (tools/beol_doctor.py, M00 ENV) =====
_DOCTOR = {
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
# ===== doctor CATALOG 사본 끝 =====


def _e(cause, action, milestones, contact=None, by=None):
    return {"원인": cause, "조치": action, "담당자": contact, "milestones": tuple(milestones), "by_milestone": by or {}}


_SELFCHECK = "python -m labelbot selfcheck --workspace <ws>"
_SITE_ENV = "workspaces/_site/beol.env"
_LLM = ("M02", "M03", "M11", "M13", "M14")
_NET = ("M02", "M03", "M07", "M08", "M10", "M11", "M13", "M14", "M16")

# 앱 사유 코드(labelbot·domain_engrbot·code_engrbot·status). 키 = 코드.
_APP = {
    # ---- 공통·CLI·상태 ----
    "RC_\\d+": _e("명령이 사유 코드 없이 0이 아닌 종료 코드로 끝났다(숫자가 종료 코드)",
                  "바로 위 [오류]·진행 줄을 확인하고 python -m labelbot status로 처음 실패한 마일스톤을 본다", (ANY,)),
    "UNEXPECTED_.*": _e("예상하지 못한 예외(코드 위치·예외 이름만 추적 파일에 남는다)",
                        "추적 파일(trace_<run>.log)과 status 출력을 로컬 담당에게 전달. 자세히 보려면 일반 터미널에서 BEOL_TRACE=1로 다시 실행(출력 반출 금지)",
                        (ANY,)),
    "UNEXPECTED_OperationalError": _e("sqlite 작업 실패(DB 잠김·디스크 가득·파일 권한)",
                                      "같은 작업 폴더를 쓰는 다른 명령이 끝났는지 확인, 디스크 여유·쓰기 권한 확인 후 재실행", (ANY,)),
    "UNEXPECTED_PermissionError": _e("파일·폴더 권한이 없다", "작업 폴더·저장소 소유자와 권한(chmod/chown) 확인 후 재실행", (ANY,)),
    "UNEXPECTED_FileNotFoundError": _e("필요한 파일이나 폴더가 없다", "pipeline.json 경로·작업 폴더 구성을 확인(python -m labelbot selfcheck)", (ANY,)),
    "UNEXPECTED_JSONDecodeError": _e("JSON 파일 형식이 깨졌다(pipeline.json 등)", "최근에 손으로 고친 JSON 파일의 문법을 확인", (ANY,)),
    "UNEXPECTED_UnicodeDecodeError": _e("텍스트 인코딩을 읽지 못했다", "설정·입력 파일을 UTF-8로 저장했는지 확인", (ANY,)),
    "UNEXPECTED_MemoryError": _e("메모리가 부족하다", "llm.workers·batch_size를 줄이거나 입력을 나눠 실행", (ANY,)),
    "PIPELINE_ERROR": _e("파이프라인 오류(사유 코드 없는 옛 경로)", "바로 위 [오류] 줄을 확인", (ANY,)),
    "WORKSPACE_REQUIRED": _e("--workspace가 비었다", "--workspace workspaces/<작업 폴더>를 준다", ("M00", "M11", ANY)),
    "WORKSPACE_INSIDE_CODE": _e("작업 폴더를 코드 폴더 안(workspaces/ 밖)에 두려 했다", "작업 폴더는 코드 폴더의 workspaces/ 아래에만 둔다", (ANY,)),
    "WORKSPACE_INVALID": _e("작업 폴더를 열 수 없다", "--workspace 경로 확인", (ANY,)),
    "WORKSPACE_NOT_FOUND": _e("지정한 작업 폴더가 없다", "--workspace 경로 확인(목록: python -m labelbot status --all-workspaces)", ("M12", "M00")),
    "SELFCHECK_FAILED": _e("자체 점검에 FAIL 항목이 있다(위 표의 FAIL 줄)", "FAIL 항목(키·taxonomy·쓰기 권한·적재 설정)을 고친 뒤 다시 selfcheck. 설치·네트워크는 python3 tools/beol_doctor.py", ("M00",)),
    "TEST_LIST_EMPTY": _e("폐쇄망 테스트 목록(transfer/import_manifest.json test_modules)이 비었거나 manifest를 읽지 못했다",
                          "반입 확인(tools/verify_import.py)으로 manifest가 그대로인지 본다. 전체 테스트로 대신 돌리지 않는다(더미 의존 모듈이 오류를 낸다)",
                          ("M00",)),
    "SITE_TEMPLATE_MISSING": _e("사이트 설정 예시(config/site.example/)가 없다",
                                "릴리스 폴더가 온전한지 반입 확인(tools/verify_import.py)으로 본다", ("M00",)),
    "MILESTONE_UNKNOWN": _e("모르는 마일스톤 ID다", "python -m labelbot codes --entrypoints로 ID 목록 확인", ("M00",)),
    "USER_ABORT": _e("사용자가 Ctrl+C로 멈췄다(실패 아님)", "필요하면 같은 명령을 다시 실행", (ANY,)),
    "INVALID_CODE": _e("사유 코드 모양이 아닌 값이 들어왔다(문장은 기록하지 않는다)", "코드 문제 — status 출력과 추적 파일을 로컬 담당에게 전달", (ANY,)),
    "RUN_RECORD_MISSING": _e("작업 폴더에 실행 기록(runs)이 없다", "먼저 python -m labelbot run(또는 ingest)을 실행", ("M04", "M06", "M07", "M08", "M09", "M10", "M13", "M14")),
    "RUN_UNFINISHED": _e("실행이 시작됐지만 끝 기록이 없다(중단·강제 종료·진행 중)",
                         "진행 중이 아니면 같은 명령을 다시 실행(LLM 응답은 캐시되어 다시 쓴다)", ("M01", "M02", "M03", "M04", "M13", "M14")),
    "INPUT_DIR_NOT_FOUND": _e("입력 폴더가 없다(--input 또는 pipeline.json input_root)",
                              "입력 폴더 경로 확인. 옛 릴리스 폴더를 가리키면 python3 tools/cloud_migrate_paths.py로 변환", ("M00", "M01")),
    "TAXONOMY_MISSING": _e("taxonomy.json이 없다(pipeline.json taxonomy_path가 가리키는 곳)",
                           "pipeline.json taxonomy_path 확인. 옛 릴리스 폴더 경로면 tools/cloud_migrate_paths.py로 변환", ("M01", "M04", "M12", "M13", "M14", "M23")),
    "TAXONOMY_READ_FAILED": _e("taxonomy.json을 읽지 못했다(권한·잠금·쓰는 중)", "파일 권한 확인 후 재실행", ("M01", "M04", "M12", "M13", "M14", "M23")),
    "TAXONOMY_PARSE_ERROR": _e("taxonomy.json 내용 검증 실패(시트·행·코드가 [오류] 아래 나온다)",
                               "taxonomy 편집기(python -m domain_engrbot taxonomy-editor)로 표시된 행을 고친다", ("M01", "M04", "M12", "M13", "M14", "M23")),
    "TAXONOMY_XLSX_NEEDS_MIGRATION": _e("taxonomy 원본이 아직 xlsx다(taxonomy.json으로 바뀜)",
                                        "python -m labelbot taxonomy-migrate --xlsx <xlsx 경로>를 한 번 실행", ("M01", "M04", "M12", "M13", "M14", "M23")),
    "LABELING_RULES_INVALID": _e("검수 피드백 규칙 파일(taxonomy/labeling_rules.json) 형식 오류",
                                 "Domain-Engr-bot 승인 규칙 관리로 고치거나 git으로 마지막 정상본 확인(규칙 끄고 실행: --no-feedback)", ("M01", "M02", "M13", "M14", "M23")),
    "AXIS_BOARD_RUN_INVALID": _e("axis-board에 axis-update가 아닌 실행을 줬다", "--run에 axis-update 실행 ID를 준다(status로 확인)", ("M14",)),
    "RULES_BOARD_RUN_INVALID": _e("rules-board에 rules-update가 아닌 실행을 줬다", "--run에 rules-update 실행 ID를 준다(status로 확인)", ("M13",)),
    "NOT_AXIS_UPDATE_RUN": _e("axis-update 실행이 아니다", "--run에 axis-update 실행 ID를 준다", ("M14",)),
    "NOT_RULES_UPDATE_RUN": _e("rules-update 실행이 아니다", "--run에 rules-update 실행 ID를 준다", ("M13",)),
    "RUN_NOT_FOUND": _e("지정한 실행 ID가 작업 DB에 없다", "python -m labelbot status --workspace <ws>로 실행 ID 확인", ("M04", "M06")),
    "NO_FLAGGED_FOR_RUN": _e("그 실행의 불량 목록이 없다", "python -m labelbot review --workspace <ws>로 불량 목록을 먼저 만든다", ("M06",)),
    "REVIEW_REQUEST_CHANGES": _e("코드 검수 판정이 REQUEST_CHANGES다(critical·major 발견)",
                                 "code_engrbot/out/<review ID>/review.md의 critical을 고친 뒤 다시 검수", ("M20",)),
    "REVIEW_ERRORS": _e("코드 검수 중 일부 검사가 오류로 끝났다", "review.md의 errors 항목 확인", ("M20",)),
    "DUMMY_DIR_NOT_FOUND": _e("더미 테스트 폴더가 없다(폐쇄망에는 반입하지 않음)", "더미 의존 테스트는 폐쇄망에서 제외(C3)하고 로컬에서만 돌린다", ("M00",)),
    "SSE_UNAVAILABLE": _e("S3 서버측 암호화(SSE)를 쓸 수 없다(본문 포함 백업 금지 조건)", "백업을 멈추고 G-S3(SSE/KMS) 담당에게 확인, G-BODY 다시 결정", ("M17", "M27"),
                          "S3 버킷의 서버측 암호화(SSE-S3 또는 SSE-KMS) 지원 확인 요청"),
    # ---- 외부 전송(labelbot/llm.py) ----
    "EXTERNAL_BLOCKED": _e("허용 목록(BEOL_ALLOWED_HOST_SUFFIXES) 밖 호스트로 보내려 했다(요청 전 차단)",
                           "pipeline.json base_url·url 호스트를 사내 호스트로 고치거나 " + _SITE_ENV + "의 BEOL_ALLOWED_HOST_SUFFIXES 확인", _NET),
    "KEY_MISSING": _e("API 키 환경 변수가 비었다", _SITE_ENV + "에 api_key_env가 가리키는 키를 넣고 셸에 불러온 뒤 " + _SELFCHECK, _NET,
                      by={"M07": {"원인": "임베딩 API 키 환경 변수가 비었다", "조치": _SITE_ENV + "의 임베딩 키(embedding.api_key_env) 확인 → " + _SELFCHECK},
                          "M08": {"원인": "벡터 저장소 키 환경 변수가 비었다", "조치": _SITE_ENV + "의 벡터 저장소 키(supabase.key_env) 확인 → " + _SELFCHECK}}),
    "TIMEOUT": _e("API 응답 시간 초과", "네트워크·방화벽 확인(python3 tools/beol_doctor.py --step E03), timeout 값 확인 후 재실행", _NET),
    "NETWORK_ERROR": _e("API 연결 실패(DNS·연결 거부·끊김)", "python3 tools/beol_doctor.py --step E02,E03,E05로 원인 확인", _NET),
    "HTTP_REDIRECT_REFUSED": _e("API가 다른 주소로 리다이렉트했다(보안상 따라가지 않음)", "base_url을 리다이렉트 없는 최종 주소로 고친다", _NET),
    "RESPONSE_NOT_JSON": _e("API 응답이 JSON이 아니다(프록시 오류 페이지 등)", "base_url·경로·프록시 확인(tools/beol_doctor.py --step E05)", _NET),
    "RESPONSE_SHAPE": _e("API 응답 JSON 모양이 예상과 다르다(OpenAI 호환 아님)", "API 경로(chat_path·path)와 모델 이름 확인", _NET),
    "HTTP_\\d+": _e("API가 HTTP 오류 상태를 돌려줬다", "상태 코드별 원인(401 인증·403 권한·404 경로·429 한도·5xx 서버) 확인 후 재실행", _NET),
    "FORMAT_INVALID": _e("LLM 응답이 형식 검증을 통과하지 못했다", "재실행(캐시는 성공 응답만). 계속되면 모델·response_format 설정 확인", _LLM),
    "JSON_PARSE": _e("LLM 응답에서 JSON을 찾지 못했다", "모델이 JSON만 내도록 response_format_json 또는 모델 변경 검토", _LLM),
    "DUPLICATE_KEY": _e("LLM 응답 JSON에 같은 키가 두 번 있다", "재실행. 계속되면 모델 변경 검토", _LLM),
    "AXIS_MISSING": _e("1차 분류 응답에 활성 축이 빠졌다", "재실행. 계속되면 taxonomy 축 수·모델 확인", ("M02", "M13", "M14")),
    "AXIS_VALUES_INVALID": _e("1차 분류 응답의 축 값이 taxonomy 값 목록 밖이다", "taxonomy 값 목록·동의어 확인", ("M02", "M13", "M14")),
    "SINGLE_AXIS_MULTI": _e("단일값 축에 값이 여러 개 왔다", "taxonomy 축 종류(단일·다중) 확인", ("M02", "M13", "M14")),
    "BAD_CHUNK_TYPE": _e("chunk 종류 값이 허용 목록 밖이다", "재실행. 계속되면 모델 확인", ("M02", "M14")),
    "UNKNOWN_AXIS_KEY": _e("응답에 taxonomy에 없는 축 이름이 있다", "taxonomy.json 축 이름과 프롬프트 확인", ("M02", "M13", "M14")),
    "QUESTION_MISSING": _e("질문 생성·라벨 응답에 질문이 빠졌다", "재실행", ("M03", "M13")),
    "BAD_ANSWER": _e("라벨 응답의 답 형식이 맞지 않다", "재실행. 계속되면 questions 시트의 답 형식 확인", ("M03", "M13")),
    "NOT_YES_NO": _e("예/아니오 질문에 다른 답이 왔다", "재실행", ("M03", "M13")),
    "QUOTE_MISSING": _e("라벨 응답에 근거 인용이 없다", "재실행", ("M03", "M13")),
    "UNKNOWN_TARGET": _e("응답이 없는 대상(질문·축)을 가리켰다", "재실행", ("M03", "M13")),
    "UNMAPPED_QUESTION": _e("응답 질문 ID가 이번 chunk 질문 목록에 없다", "재실행", ("M03", "M13")),
    "QUOTE_NOT_IN_TEXT": _e("근거 인용이 chunk 본문에 없다(환각 인용)", "검수 화면에서 확인(불량 목록에 오른다)", ("M03",)),
    "PERSON_NOT_IN_QUOTE": _e("추출한 인명이 인용 안에 없다", "검수 화면에서 확인", ("M03",)),
    "RELABEL_FAILED": _e("규칙 변경 재라벨 호출이 실패했다(이어받은 값은 유지)", "rules-update를 다시 실행", ("M13",)),
    # ---- 수집·파싱(DRM) ----
    "ENCRYPTED": _e("OOXML 파일인데 암호가 걸려 있다(D0 CF 11 E0, DRM 미해제 포함)",
                    "업무 PC에서 DRM이 풀린 상태로 다시 ingest(원본 경로 open은 ingest 한 곳뿐)", ("M01", "M19")),
    "NOT_OOXML": _e("확장자는 OOXML인데 시그니처(PK)가 아니다(DRM 미해제·손상)", "업무 PC에서 DRM 해제 상태로 다시 ingest, 원본 손상 여부 확인", ("M01", "M19")),
    "OLE_LEGACY": _e("옛 Office 형식(ppt·doc·xls)은 파서가 없다", "pptx·docx·xlsx로 저장한 사본을 입력으로 쓴다", ("M01",)),
    "UNSUPPORTED_FORMAT": _e("지원하지 않는 파일 형식이다", "입력 폴더에서 빼거나 지원 형식으로 바꾼다", ("M01",)),
    "UNSUPPORTED_CHUNK_METHOD": _e("pipeline.json chunking.method 값이 지원 목록 밖이다", "chunking.method를 slide로 둔다", ("M01",)),
    "PARSE_ERROR": _e("문서 XML 파싱 실패(손상·비표준)", "원본을 다시 저장해 재시도, 계속되면 파일 ID를 로컬 담당에게 전달", ("M01",)),
    "B64_MISMATCH": _e("보관한 .b64가 원본 해시와 다르다", "그 파일을 다시 ingest(.b64 덮어쓰기)", ("M01",)),
    "B64_MISSING": _e(".b64 파일이 없다(이동·삭제됨)", "작업 폴더 b64/를 이어받았는지 확인, 없으면 다시 ingest", ("M01", "M10", "M11")),
    "NOT_B64_PATH": _e(".b64가 아닌 경로를 읽으려 했다(DRM 규칙)", "코드 문제 — 로컬 담당에게 trace 파일 전달", ("M01", ANY)),
    "FORBIDDEN_EXTENSION": _e("office·텍스트 확장자로 쓰려 했다(DRM 재적용 위험, 쓰기 규칙)", "코드 문제 — 로컬 담당에게 trace 파일 전달", (ANY,)),
    # ---- taxonomy 변환(taxmigrate·xlsx) ----
    "NOT_XLSX": _e("xlsx(zip)가 아니다", "--xlsx 경로 확인(DRM 해제된 사본인지)", ("M12",)),
    "PART_MISSING": _e("xlsx에 필요한 part가 없다", "엑셀에서 다시 저장 후 재시도", ("M12",)),
    "XML_PARSE": _e("xlsx 내부 XML이 깨졌다", "엑셀에서 다시 저장 후 재시도", ("M12",)),
    "XLSX_READ_FAILED": _e("xlsx를 읽지 못했다(권한·잠금)", "엑셀을 닫고 권한 확인 후 재시도", ("M12",)),
    "XLSX_UNUSABLE": _e("xlsx에 taxonomy 시트가 없거나 쓸 수 없다", "시트 이름(taxonomy·questions·synonyms) 확인", ("M12",)),
    "OUT_EXISTS": _e("taxonomy.json이 이미 있다", "덮어쓰려면 --force", ("M12",)),
    "OUT_NOT_JSON": _e("--out이 .json이 아니다", "--out을 .json으로 준다", ("M12",)),
    "SHEET_HASH_MISMATCH": _e("변환 결과 시트 해시가 원본과 다르다", "변환을 멈추고 xlsx를 로컬 담당에게 확인 요청", ("M12",)),
    "TAXONOMY_INVALID": _e("taxonomy 검증 실패", "taxonomy 편집기로 표시된 행을 고친다", ("M12",)),
    # ---- 검수·반영 ----
    "REVISITS_NOT_LIST": _e("검수 파일의 revisits가 목록이 아니다", "검수 화면에서 다시 저장", ("M06",)),
    "REVISITS_TOO_MANY": _e("taxonomy 재검토 요청이 너무 많다", "검수 화면에서 나눠 저장", ("M06",)),
    "RULES_JSON_INVALID": _e("labeling_rules.json이 JSON이 아니다", "git으로 마지막 정상본 확인 후 복구", ("M01", "M11", "M13", "M23")),
    "RULES_FORMAT_INVALID": _e("labeling_rules.json 형식이 맞지 않다", "Domain-Engr-bot 승인 규칙 관리로 고친다", ("M01", "M11", "M13", "M23")),
    "AXIS_UPDATE_LOCKED": _e("다른 axis-update·rules-update가 잠금을 잡고 있다", "끝날 때까지 기다린 뒤 재실행(logs/axis_update.lock.json)", ("M13", "M14")),
    "AXIS_UPDATE_LOCK_LOST": _e("실행 중 잠금을 다른 실행이 넘겨받았다", "다른 실행이 끝난 뒤 다시 실행", ("M13", "M14")),
    "PREV_PUSH_PENDING": _e("이전 실행의 적재가 끝나지 않았다", "이전 실행을 push-vectors까지 마친 뒤 재실행", ("M13", "M14")),
    "PREV_NOT_REVIEWED": _e("이전 실행 검수가 끝나지 않았다", "검수 완료 → feedback 반영 후 재실행", ("M13", "M14")),
    "REVIEW_IN_PROGRESS": _e("검수가 진행 중이다", "검수 완료 후 재실행", ("M13", "M14")),
    "NO_PREVIOUS_RUN": _e("비교할 이전 실행이 없다", "먼저 python -m labelbot run을 실행", ("M13", "M14", "M23")),
    "RULES_BASELINE_UNKNOWN": _e("이전 실행의 규칙 기준을 알 수 없다", "전체 run으로 새 기준을 만든다", ("M13", "M23")),
    "NO_RULE_CHANGE": _e("규칙 변경이 없다(할 일 없음)", "조치 없음", ("M13", "M23")),
    "STAGE_WIDE_ONLY": _e("축 없는 규칙만 바뀌었다(부분 재라벨 대상 아님)", "전체 run 검토", ("M13", "M23")),
    "NO_RELABEL_TARGET": _e("다시 라벨할 대상이 없다", "조치 없음", ("M13",)),
    "RULES_CHANGE_RATIO_HIGH": _e("규칙 변경으로 값이 바뀐 비율이 상한을 넘어 적재를 보류했다",
                                  "rules-board로 바뀐 슬라이드를 확인 후 push-vectors --force", ("M08", "M13")),
    # ---- 벡터·슬라이드 ----
    "CONFIG_MISSING": _e("적재 설정(url·키·테이블)이 비었다", "pipeline.json supabase 블록과 " + _SITE_ENV + " 확인 → " + _SELFCHECK, ("M08", "M10")),
    "MODEL_DIM_MIX": _e("한 테이블에 임베딩 모델·차원이 섞인다", "embedding.model을 테이블과 맞추거나 새 테이블로 적재", ("M08",)),
    "SHA_MISMATCH": _e("슬라이드 JPG 해시가 기록과 다르다", "python -m labelbot slide-images로 다시 렌더", ("M10",)),
    "ROW_MISSING": _e("올릴 행이 벡터 저장소에 없다", "push-vectors를 먼저 실행", ("M10",)),
    "UPLOAD_*": _e("슬라이드 JPG 업로드 실패(뒤 코드가 HTTP·네트워크 사유)", "뒤 사유 코드의 조치를 따른다", ("M10",)),
    "PATCH_*": _e("행에 slide_image_* 기록 실패(뒤 코드가 사유)", "뒤 사유 코드의 조치를 따른다", ("M10",)),
    "JPEG_SIGNATURE": _e("렌더 결과가 JPEG가 아니다", "chromium 버전 확인(tools/beol_doctor.py --step E09)", ("M09",)),
    "RENDER_MISMATCH": _e("렌더 결과 수가 슬라이드 수와 다르다", "slide-images 재실행", ("M09",)),
    "RENDER_EMPTY": _e("렌더 결과가 비었다", "CJK 글꼴·chromium 확인(tools/beol_doctor.py --step E09)", ("M09",)),
    "CAPTURE_EMPTY": _e("chromium 화면 캡처가 비었다", "tools/beol_doctor.py --step E09", ("M09",)),
    "CDP_BAD_MESSAGE": _e("chromium DevTools 응답이 깨졌다", "chromium 버전 확인 후 재시도", ("M09",)),
    "CDP_ERROR": _e("chromium DevTools 명령 오류", "chromium 버전 확인 후 재시도", ("M09",)),
    "CDP_HTTP_\\d+": _e("chromium DevTools HTTP 엔드포인트 오류(숫자가 상태 코드)", "chromium을 끄고 재시도, 계속되면 tools/beol_doctor.py --step E09", ("M09",)),
    "CDP_HTTP_FAILED": _e("chromium DevTools HTTP 연결 실패", "포트 충돌·chromium 실행 확인", ("M09",)),
    "CDP_NO_TARGET": _e("chromium 탭을 찾지 못했다", "slide-images 재실행", ("M09",)),
    "JS_ERROR": _e("렌더 페이지 스크립트 오류", "slide-images 재실행, 계속되면 로컬 담당에게 전달", ("M09",)),
    "RENDERER_EXITED": _e("chromium이 도중에 종료됐다", "ldd·메모리 확인(tools/beol_doctor.py --step E09)", ("M09",)),
    "RENDERER_MISSING": _e("chromium(Edge·Chrome) 실행 파일을 찾지 못했다", "chromium 설치 또는 pipeline.json render.browser_path 지정",
                           ("M09",), "서버 관리자에게 chromium 패키지 설치 요청"),
    "RENDERER_PORT_TIMEOUT": _e("chromium DevTools 포트가 열리지 않았다", "다른 chromium 프로세스 종료 후 재시도", ("M09",)),
    "RENDERER_START_FAILED": _e("chromium을 시작하지 못했다", "tools/beol_doctor.py --step E09", ("M09",)),
    "RENDER_TIMEOUT": _e("슬라이드 렌더 시간 초과", "render.timeout을 늘리거나 재시도", ("M09",)),
    "WS_CLOSED": _e("chromium DevTools 연결이 닫혔다", "slide-images 재실행", ("M09",)),
    "WS_CONNECT_FAILED": _e("chromium DevTools 연결 실패", "slide-images 재실행", ("M09",)),
    "WS_HANDSHAKE_FAILED": _e("chromium DevTools 핸드셰이크 실패", "chromium 버전 확인", ("M09",)),
    "WS_HOST_REJECTED": _e("DevTools 주소가 loopback이 아니다(거부)", "코드 문제 — 로컬 담당에게 전달", ("M09",)),
    # ---- 화면 서버(POST 실패 줄) ----
    "HOST_REJECTED": _e("허용되지 않은 Host로 접속했다(프록시 주소)", _SITE_ENV + "의 BEOL_ALLOWED_HOSTS에 프록시 호스트를 넣고 서버 재시작", ("M05", "M11", "M12")),
    "ORIGIN_REJECTED": _e("다른 출처(Origin)의 저장 요청이라 거절했다(프록시 뒤 Origin 불일치)",
                          "BEOL_ALLOWED_HOSTS·BEOL_PATH_PREFIX 확인 후 서버 재시작", ("M05", "M11", "M12")),
    "CONTENT_TYPE": _e("저장 요청이 JSON이 아니다", "화면을 새로고침 후 다시 저장", ("M05",)),
    "BODY_SIZE": _e("저장 요청 본문이 비었거나 너무 크다", "검수 내용을 나눠 저장", ("M05",)),
    "JSON_INVALID": _e("저장 요청 JSON이 깨졌다", "화면을 새로고침 후 다시 저장", ("M05",)),
    "KIND_MISMATCH": _e("저장 요청 종류가 경로와 다르다", "화면을 새로 만든 뒤(review·compare) 다시 저장", ("M05",)),
    "RUN_ID_INVALID": _e("저장 요청의 실행 ID 형식이 틀렸다", "화면을 새로 만든 뒤 다시 저장", ("M05",)),
    "COMPARE_INVALID": _e("검수 시작 신호의 compare 값이 틀렸다", "화면 새로고침", ("M05",)),
    "NOT_FOUND": _e("없는 주소로 요청했다", "화면 주소 확인(BEOL_PATH_PREFIX)", ("M05", "M11", "M12")),
    # ---- Domain-Engr-bot ----
    "QA_RUN_NOT_FOUND": _e("QA 실행이 없다", "python -m domain_engrbot run으로 먼저 만든다(--qa-run 확인)", ("M11",)),
    "REVIEW_SCREEN_MISSING": _e("QA 검토 화면이 없다", "python -m domain_engrbot review --qa-run <ID>로 다시 만든다", ("M11",)),
    "LAYER_UNKNOWN": _e("--layers에 모르는 층 이름이 있다", "L0,L1,L2 등 허용 층만 준다", ("M11",)),
    "LABELER_RUN_NOT_FOUND": _e("라벨러 실행 ID가 작업 DB에 없다", "python -m labelbot status로 실행 ID 확인", ("M11",)),
    "ADAPTER_CONFIG_INVALID": _e("작업 폴더 pipeline.json을 읽지 못했다", "pipeline.json 문법 확인", ("M11",)),
    "ADAPTER_DB_MISSING": _e("작업 폴더에 work.sqlite가 없다", "먼저 python -m labelbot run", ("M11",)),
    "ADAPTER_SCHEMA_MISMATCH": _e("작업 DB 스키마가 Domain-Engr-bot 기대와 다르다", "labelbot을 같은 릴리스로 맞춘다", ("M11",)),
    "ADAPTER_TAXONOMY_INVALID": _e("작업 폴더 taxonomy가 검증에 실패했다", "taxonomy 편집기로 고친다", ("M11",)),
    "ADAPTER_TAXONOMY_MISSING": _e("작업 폴더 taxonomy 경로에 파일이 없다", "pipeline.json taxonomy_path 확인(cloud_migrate_paths)", ("M11",)),
    "ADAPTER_TAXONOMY_UNREADABLE": _e("taxonomy를 읽지 못했다", "파일 권한 확인", ("M11",)),
    "REF_MISSING": _e("참조한 파일(.b64 등)이 없다", "작업 폴더 이어받기 확인", ("M11",)),
    "REF_OUTSIDE_BUNDLE": _e("참조 경로가 번들 밖이다(거부)", "번들 폴더 구성 확인", ("M11",)),
    "REF_OUTSIDE_WORKSPACE": _e("참조 경로가 작업 폴더 밖이다(거부)", "작업 폴더 경로 확인(cloud_migrate_paths)", ("M11",)),
    "B64_DECODE_FAILED": _e(".b64 디코딩 실패", "그 파일을 다시 ingest", ("M11",)),
    "NOT_B64": _e(".b64가 아닌 파일을 열려 했다(DRM 규칙)", "코드 문제 — 로컬 담당에게 전달", ("M11",)),
    "BUNDLE_DIR_MISSING": _e("--bundle 폴더가 없다", "경로 확인", ("M11",)),
    "BUNDLE_HEAD_MISSING": _e("번들 머리 파일이 없다", "번들을 다시 만든다", ("M11",)),
    "BUNDLE_FILE_MISMATCH": _e("번들 레코드와 단위의 파일 ID가 다르다", "번들을 다시 만든다", ("M11",)),
    "BUNDLE_RECORD_ID_INVALID": _e("번들 레코드 ID가 중복·형식 오류다", "번들을 다시 만든다", ("M11",)),
    "BUNDLE_SOURCE_MISSING": _e("번들 원본 항목이 없다", "번들을 다시 만든다", ("M11",)),
    "BUNDLE_TAXONOMY_INVALID": _e("번들 taxonomy가 깨졌다", "번들을 다시 만든다", ("M11",)),
    "BUNDLE_UNIT_MISSING": _e("번들 단위 항목이 없다", "번들을 다시 만든다", ("M11",)),
    "FORMAT_UNSUPPORTED": _e("원문 대조를 지원하지 않는 형식이다", "조치 없음(대조 생략)", ("M11",)),
    "RAW_DOCUMENT_MISSING": _e("원문 document part가 없다", "원본 .b64 확인", ("M11",)),
    "RAW_PRESENTATION_MISSING": _e("원문 presentation part가 없다", "원본 .b64 확인", ("M11",)),
    "RAW_SLIDE_MISSING": _e("원문 슬라이드 part가 없다", "원본 .b64 확인", ("M11",)),
    "RAW_XML_INVALID": _e("원문 XML이 깨졌다", "원본 .b64 확인", ("M11",)),
    "RAW_ZIP_INVALID": _e("원문이 zip(OOXML)이 아니다(DRM 미해제)", "업무 PC에서 DRM 해제 상태로 다시 ingest", ("M11",)),
    "MOCK_HINT_MISSING": _e("mock judge에 힌트가 없다(테스트 설정)", "--judge http 또는 테스트 설정 확인", ("M11",)),
    "LLM_CONFIG_MISSING": _e("도메인 질문용 LLM 설정이 없다", "작업 폴더 pipeline.json llm 블록과 키 확인 → " + _SELFCHECK, ("M11",)),
    "LLM_RESPONSE_INVALID": _e("도메인 질문 LLM 응답이 형식에 맞지 않다", "questions generate --force로 재시도", ("M11",)),
    "QUESTIONS_CONFIG_INVALID": _e("policy questions 설정이 틀렸다", "domain_engrbot policy 확인", ("M11",)),
    "QUESTIONS_INVALID": _e("질문 묶음 파일이 깨졌다", "questions generate --force로 다시 만든다", ("M11",)),
    "QUESTIONS_NOT_FOUND": _e("질문 묶음이 없다", "python -m domain_engrbot questions generate --workspace <ws>", ("M11",)),
    "QUESTION_SCREEN_MISSING": _e("질문 화면이 없다", "python -m domain_engrbot questions screen --workspace <ws>", ("M11",)),
    "QUESTION_NOT_OPEN": _e("이미 닫힌 질문이다", "질문 화면 새로고침", ("M11",)),
    "ASKED_INVALID": _e("질문 기록 형식이 틀렸다", "questions generate --force", ("M11",)),
    "ANSWER_TEXT_INVALID": _e("답 문장이 비었거나 형식이 틀렸다", "질문 화면에서 답을 고쳐 다시 저장", ("M11",)),
    "ANSWERS_DUPLICATE_ID": _e("답 파일에 같은 질문 ID가 두 번 있다", "질문 화면에서 다시 저장", ("M11",)),
    "ANSWERS_FORMAT_INVALID": _e("답 파일 형식이 틀렸다", "질문 화면에서 다시 저장", ("M11",)),
    "ANSWERS_JSON_INVALID": _e("답 파일이 JSON이 아니다", "질문 화면에서 다시 저장", ("M11",)),
    "ANSWERS_LOG_INVALID": _e("답 반영 기록이 깨졌다", "qa/ 아래 반영 기록을 로컬 담당에게 확인", ("M11",)),
    "ANSWERS_NOT_FOUND": _e("답 파일이 없다", "질문 화면에서 '답변 완료 · 저장'을 누르거나 --answers로 지정", ("M11",)),
    "ANSWERS_READ_FAILED": _e("답 파일을 읽지 못했다", "권한 확인", ("M11",)),
    "ANSWERS_TOO_LARGE": _e("답 파일이 너무 크다", "나눠 저장", ("M11",)),
    "PROPOSALS_INVALID": _e("taxonomy 제안 형식이 틀렸다", "질문 화면에서 초안을 고쳐 다시 저장", ("M11",)),
    "DRAFT_EMPTY": _e("초안 LLM이 빈 결과를 냈다", "다시 요청하거나 직접 작성", ("M11",)),
    "DRAFT_UNAVAILABLE": _e("초안 만들기를 쓸 수 없다(LLM 설정 없음·--no-draft)", "직접 작성하거나 LLM 설정 확인", ("M11",)),
    "DECISIONS_REQUIRED": _e("--decisions가 필요하다", "--decisions <결정 JSON>을 준다", ("M11",)),
    "DECISIONS_NOT_FOUND": _e("결정 JSON이 없다", "최종 검수 화면에서 저장한 파일 경로 확인", ("M11",)),
    "DECISIONS_DUPLICATE_ID": _e("결정 JSON에 같은 ID가 두 번 있다", "화면에서 다시 저장", ("M11",)),
    "DECISIONS_FORMAT_INVALID": _e("결정 JSON 형식이 틀렸다", "화면에서 다시 저장", ("M11", "M12")),
    "DECISIONS_ID_NOT_ON_SCREEN": _e("화면에 없던 ID를 결정했다", "화면을 다시 만든 뒤 결정", ("M11",)),
    "DECISIONS_ITEM_INVALID": _e("보드 결정 항목 형식이 틀렸다", "보드 새로고침 후 다시 표시", ("M12",)),
    "DECISIONS_JSON_INVALID": _e("결정 JSON이 깨졌다", "화면에서 다시 저장", ("M11",)),
    "DECISIONS_STALE": _e("결정이 지금 후보와 맞지 않다(그사이 후보가 바뀜)", "labeling-rules review로 화면을 다시 만든다", ("M11",)),
    "DECISIONS_TOO_LARGE": _e("결정 JSON이 너무 크다", "나눠 저장", ("M11",)),
    "DECISIONS_TOO_MANY": _e("결정 항목이 너무 많다", "나눠 저장", ("M11",)),
    "IDS_REQUIRED": _e("approve·reject에 대상이 없다", "--ids, --all, --examples all 중 하나를 준다", ("M11",)),
    "ACTION_INVALID": _e("labeling-rules 동작 이름이 틀렸다", "python -m domain_engrbot labeling-rules -h", ("M11",)),
    "LEDGER_CANDIDATES_INVALID": _e("규칙 후보 파일이 깨졌다", "python -m domain_engrbot ledger rebuild --workspace <ws>", ("M11",)),
    "LEDGER_DIR_OUTSIDE_WORKSPACES": _e("장부 폴더가 workspaces/ 밖이다(거부)", "policy의 장부 경로를 workspaces/ 아래로", ("M11",)),
    "LEDGER_DISABLED": _e("교정 장부가 꺼져 있다", "policy ledger.enabled 확인", ("M11",)),
    "LEDGER_FILE_INVALID": _e("장부 파일이 깨졌다", "ledger rebuild, 계속되면 로컬 담당에게 전달", ("M11",)),
    "LEDGER_LOCKED": _e("다른 명령이 장부 잠금을 잡고 있다", "끝날 때까지 기다린 뒤 재실행", ("M11",)),
    "LEDGER_RUN_NO_CORRECTIONS": _e("그 실행에 사람 교정이 없다", "검수 반영(labelbot apply) 후 intake", ("M11",)),
    "LEGACY_DATA_DIR": _e("옛 데이터 폴더(이전 봇 이름)가 남아 있다", "옛 폴더를 새 위치로 옮기거나 지운다(봇 이름 변경 메모 참고)", ("M11",)),
    "RULES_DOC_INVALID": _e("도메인 규칙 문서 형식이 틀렸다", "domain_engrbot 규칙 파일 확인", ("M11",)),
    "RULES_LIST_INVALID": _e("도메인 규칙 목록이 틀렸다", "domain_engrbot 규칙 파일 확인", ("M11",)),
    "RULES_FILE_UNREADABLE": _e("도메인 규칙 파일을 읽지 못했다", "권한·경로 확인", ("M11",)),
    "TEMPLATE_MARK_MISSING": _e("화면 템플릿 표지가 없다(템플릿 손상)", "릴리스 반입 확인(verify_import) 후 재시도", ("M11",)),
    "EDITOR_SCREEN_MISSING": _e("taxonomy 편집기 화면 파일이 없다", "릴리스 반입 확인(verify_import)", ("M12",)),
    "BOARD_DOC_MISSING": _e("보드 문서가 없다", "taxonomy-board를 다시 만든다", ("M12",)),
    "EDIT_INVALID": _e("보드 편집 칸 값이 틀렸다", "보드에서 값을 고친다", ("M12",)),
    "ITEM_CONFLICT": _e("보드 항목이 서로 충돌한다", "충돌 표시된 항목 중 하나만 반영", ("M12",)),
    "ITEM_NOT_APPLICABLE": _e("지금 taxonomy에 적용할 수 없는 항목이다", "항목 기각 또는 먼저 할 일 처리", ("M12",)),
    "TAXONOMY_CHANGED": _e("보드를 연 뒤 taxonomy.json이 바뀌었다", "보드를 새로고침한 뒤 다시 최종 완료", ("M11", "M12")),
    "TAXONOMY_NOT_FOUND": _e("taxonomy.json이 없다", "--taxonomy 경로 확인", ("M11", "M12")),
    "TAXONOMY_WRITE_FAILED": _e("taxonomy.json을 쓰지 못했다(권한·디스크)", "권한·디스크 확인 후 다시 최종 완료", ("M12",)),
}

# 여러 마일스톤에서 같은 코드 — 마일스톤 추가와 마일스톤별 원인·조치 덮어쓰기.
_EXTEND = {
    "HTTP_401": (_NET, {
        "M07": ("임베딩 API 인증 거부", _SITE_ENV + "의 임베딩 키 확인 → " + _SELFCHECK),
        "M02": ("LLM API 인증 거부", _SITE_ENV + "의 LLM 키(llm.api_key_env) 확인 → " + _SELFCHECK + " --probe-llm"),
        "M03": ("LLM API 인증 거부", _SITE_ENV + "의 LLM 키(llm.api_key_env) 확인 → " + _SELFCHECK + " --probe-llm"),
        "M08": ("벡터 저장소 인증 거부", _SITE_ENV + "의 벡터 저장소 키(supabase.key_env) 확인 → " + _SELFCHECK),
        "M11": ("Domain-Engr-bot LLM 인증 거부", _SITE_ENV + "의 LLM 키 확인 → " + _SELFCHECK + " --probe-llm"),
    }),
    "HTTP_403": (_NET, {
        "M07": ("임베딩 API 권한 거부(키 권한·출발지 IP)", "임베딩 키 권한과 이 서버 IP 허용 확인"),
        "M08": ("벡터 저장소 권한 거부(키 권한·RLS·IP)", "벡터 저장소 키 권한·테이블 정책 확인"),
    }),
    "HTTP_404": (_NET, {
        "M07": ("임베딩 API 경로가 없다", "pipeline.json embedding.base_url·path 확인"),
        "M02": ("LLM API 경로가 없다", "pipeline.json llm.base_url·chat_path·model 확인"),
        "M03": ("LLM API 경로가 없다", "pipeline.json llm.base_url·chat_path·model 확인"),
        "M08": ("벡터 저장소 테이블·경로가 없다", "pipeline.json supabase.table·url 확인"),
    }),
    "HTTP_5xx": (_NET, {}),
    "RATE_LIMITED": (_NET, {}),
    "PORT_IN_USE": (("M05", "M11", "M12"), {
        "M05": ("화면 서버 포트를 다른 프로세스가 쓰고 있다", "--port로 다른 포트를 주거나 그 프로세스를 끈다(ss -ltnp)"),
        "M11": ("질문·검토 서버 포트를 다른 프로세스가 쓰고 있다", "--port로 다른 포트를 주거나 --port 없이 실행(빈 포트 자동)"),
        "M12": ("보드·편집기 포트를 다른 프로세스가 쓰고 있다", "--port로 다른 포트를 주거나 --port 없이 실행(빈 포트 자동)"),
    }),
    "CLOCK_SKEW": (("M17", "M27"), {}),
}


def _build():
    codes = {}
    for k, v in _DOCTOR.items():
        codes[k] = _e(v[0], v[1], ("M00",), v[2])
    for k, v in _APP.items():
        codes[k] = v
    for k, (ms, by) in _EXTEND.items():
        e = codes[k]
        e["milestones"] = tuple(sorted(set(e["milestones"]) | set(ms)))
        e["by_milestone"] = dict(e["by_milestone"], **dict((m, {"원인": c, "조치": a}) for m, (c, a) in by.items()))
    return codes


CODES = _build()

# 정규식 패턴 키(이 문자열 그대로가 CODES 키다). 접두어 패턴은 키 끝의 * 로 따로 찾는다.
PATTERNS = tuple((re.compile(k + r"\Z"), k) for k in CODES if "\\" in k or k.endswith(".*"))
PREFIXES = tuple(sorted((k for k in CODES if k.endswith("*") and not k.endswith(".*")), key=len, reverse=True))
_HTTP_5XX = re.compile(r"HTTP_5\d\d\Z")


def candidates(code):
    """code에 맞는 카탈로그 키들(정확 → HTTP_5xx → 정규식 → 접두어 순)."""
    code = code or ""
    out = [code] if code in CODES and code not in PREFIXES else []
    if _HTTP_5XX.match(code):
        out.append("HTTP_5xx")
    out.extend(k for rx, k in PATTERNS if rx.match(code))
    out.extend(k for k in PREFIXES if code.startswith(k[:-1]) and len(code) > len(k) - 1)
    return out


def known(code):
    return bool(candidates(code))


def lookup(code, milestone=None):
    """{code, key, 원인, 조치, 담당자, milestones} 또는 None. milestone이 그 키의 마일스톤 목록에 있는 항목을 먼저 고르고,
    마일스톤별 덮어쓰기가 있으면 그 원인·조치를 쓴다."""
    keys = candidates(code)
    if not keys:
        return None
    key = keys[0]
    if milestone:
        key = next((k for k in keys if milestone in CODES[k]["milestones"]), None) \
            or next((k for k in keys if ANY in CODES[k]["milestones"]), keys[0])
    e = CODES[key]
    ov = e["by_milestone"].get(milestone) or {}
    return {"code": code, "key": key, "원인": ov.get("원인", e["원인"]), "조치": ov.get("조치", e["조치"]),
            "담당자": e["담당자"], "milestones": e["milestones"]}


def describe(code, milestone=None):
    """lookup과 같되 카탈로그에 없으면 일반 안내를 돌려준다(항상 dict)."""
    return lookup(code, milestone) or {
        "code": code, "key": None, "원인": "카탈로그에 없는 사유 코드",
        "조치": "python -m labelbot codes로 목록을 보고, status 출력과 추적 파일을 로컬 담당에게 전달",
        "담당자": None, "milestones": ()}


def for_milestone(mid):
    """그 마일스톤에 쓰는 카탈로그 키(일반 * 항목 제외), 정렬."""
    return sorted(k for k, e in CODES.items() if mid in e["milestones"])
