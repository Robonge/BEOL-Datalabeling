# CLOUD_SETUP — 폐쇄망 서버 환경 구성 (C1)

반입 확인(C0, `CLOSED_NETWORK_RUNBOOK.md`)을 통과한 릴리스 폴더에서 한 번(R1) 한다. 셸은 bash, 위치는 릴리스 폴더 루트다.

- 저장소는 공개다. 이 문서에는 사내 호스트·IP·경로·키를 쓰지 않는다. `<proxy-host>` 같은 자리표시는 실제 값으로 바꿔 터미널에서만 쓰고, 남겨 둘 값은 비추적 `workspaces/_site/`에만 둔다.
- 모든 설치 명령은 아래 `step` 도우미로 실행한다. **실패한 단계 다음으로 넘어가지 않는다.**
- 순서는 doctor 단계 순서를 따른다. 내용은 폐쇄망 계획 C1의 1–7과 같고, 프록시·CA·시간대(C1-4·6)를 패키지 설치(C1-2) 앞으로 당겼다(미러 접속에 필요할 수 있어서).
- 환경 문제(접속·인증서·프록시·미러·pip·포트·시계)는 먼저 `python3 tools/beol_doctor.py`로 진단한다. 처음 ✖ 줄의 "담당자에게:" 문장을 보안·인프라 담당에게 그대로 전달한다.

```bash
B=/config/work/beol/<release_label>      # C0에서 만든 릴리스 폴더
cd "$B"
```

## 0. step 도우미

릴리스 폴더에서 아래 블록을 터미널에 붙여 넣는다(새 터미널마다 다시). `step <ID> "<설명>" -- <명령…>` 형식이다.

- 출력: `[M00 ENV/<ID>] 시작` → 명령 출력 → `[M00 ENV/<ID>] 완료` 또는 `[M00 ENV/<ID>] 실패 rc=<n>` + 마지막 20줄 + doctor 안내.
- 로그: `workspaces/_site/setup_<YYYYMMDD>.log`. 이름에 KEY·SECRET·TOKEN·PASSWORD가 들어간 환경 변수의 값은 `***`로 가린다.
- 한 단계가 실패하면 그 ID를 다시 성공시킬 때까지 다른 ID의 `step`은 실행되지 않는다.
- ID는 doctor 단계 ID(E01–E15)와 같아서 실패하면 `python3 tools/beol_doctor.py --step <ID>`로 바로 원인을 본다.

```bash
# >>> step 도우미
_beol_mask() {
  if command -v python3 >/dev/null 2>&1; then
    python3 -u -c '
import os, re, sys
sys.stdin.reconfigure(errors="replace")
pat = re.compile(r"(\w*(?:KEY|SECRET|TOKEN|PASSWORD)\w*)(\s*[=:]\s*)\S+", re.I)
vals = sorted((v for k, v in os.environ.items()
               if re.search("KEY|SECRET|TOKEN|PASSWORD", k, re.I) and len(v) >= 6), key=len, reverse=True)
for line in sys.stdin:
    for v in vals:
        line = line.replace(v, "***")
    sys.stdout.write(pat.sub(r"\1\2***", line))
    sys.stdout.flush()
'
  else
    sed -u -E 's/([A-Za-z0-9_]*(KEY|SECRET|TOKEN|PASSWORD)[A-Za-z0-9_]*)([[:space:]]*[=:][[:space:]]*)[^[:space:]]+/\1\3***/Ig'
  fi
}
step() {
  local id="$1" desc="$2" site="workspaces/_site" log mark tmp rc
  shift 2
  [ "${1:-}" = "--" ] && shift
  mkdir -p "$site" || return 1
  log="$site/setup_$(date +%Y%m%d).log"
  mark="$site/.step_failed"
  if [ -f "$mark" ] && [ "$(cat "$mark")" != "$id" ]; then
    echo "[M00 ENV/$id] 건너뜀  앞 단계 $(cat "$mark") 실패가 남아 있다 — 그 단계를 먼저 성공시킨다" | tee -a "$log"
    return 1
  fi
  tmp="$(mktemp)"
  echo "[M00 ENV/$id] 시작  $desc" | tee -a "$log"
  "$@" 2>&1 | _beol_mask | tee "$tmp"
  rc=${PIPESTATUS[0]}
  cat "$tmp" >> "$log"
  if [ "$rc" -eq 0 ]; then
    rm -f "$mark"
    echo "[M00 ENV/$id] 완료  $desc" | tee -a "$log"
  else
    echo "$id" > "$mark"
    { echo "[M00 ENV/$id] 실패 rc=$rc  $desc"
      echo "  --- 마지막 20줄 ---"
      tail -n 20 "$tmp"
      echo "  조치: python3 tools/beol_doctor.py --step $id 로 원인을 본다. 이 단계를 성공시키기 전에는 다음 단계로 가지 않는다"
    } | tee -a "$log"
  fi
  rm -f "$tmp"
  return "$rc"
}
# <<< step 도우미
```

## 1. 설치 전 진단 (doctor)

```bash
mkdir -p workspaces/_site
cp config/doctor_targets.example.json workspaces/_site/doctor_targets.json
chmod 600 workspaces/_site/doctor_targets.json
# 편집: host를 실제 사내 호스트로, 쓰지 않는 대상은 지운다(이 파일은 git에 올라가지 않는다)
python3 tools/beol_doctor.py
```

- 표에서 처음 ✖를 본다. 프록시 판정(E05)이 먼저 요약된다. `CONN_TIMEOUT`(방화벽)·`PROXY_AUTH_407`·`PROXY_BLOCKED_URL`·`DNS_UNRESOLVED`·`TLS_CA_UNKNOWN`·`PKG_NOT_IN_MIRROR`·`PIP_INDEX_UNREACHABLE`은 "담당자에게:" 문장을 그대로 전달한다.
- 보고 `workspaces/_site/doctor_report.json`(별칭·사유 코드만)은 반출할 수 있다.

## 2. OS 확인 (E01)

```bash
mkdir -p /config/work/beol/_import
step E01 "OS·아키텍처" -- sh -c 'cat /etc/os-release; uname -m'
step E01 "env.json 기록" -- python3 -c "import json,platform;d=dict(l.rstrip().split('=',1) for l in open('/etc/os-release') if '=' in l);json.dump({'id':d.get('ID','').strip(chr(34)),'version_id':d.get('VERSION_ID','').strip(chr(34)),'like':d.get('ID_LIKE','').strip(chr(34)),'machine':platform.machine()},open('/config/work/beol/_import/env.json','w'))"
```

`ID`/`ID_LIKE`가 debian·ubuntu면 아래 **deb**, rhel·rocky·alma·fedora면 **rpm** 명령을 쓴다.

## 3. 사이트 설정 — `.env`, `workspaces/_site/beol.env` (E05, E11, E14)

`.env`는 저장소 루트에서 labelbot이 읽는다. 폐쇄망에서는 키 값을 `.env`에 두지 않고 `beol.env`에 둔다(셸 값이 `.env`보다 우선). 둘 다 git에 올라가지 않는다.

```bash
step E14 ".env 만들기" -- sh -c 'cp .env.example .env && chmod 600 .env'
step E14 "beol.env 만들기" -- sh -c 'mkdir -p workspaces/_site && touch workspaces/_site/beol.env && chmod 600 workspaces/_site/beol.env'
```

`workspaces/_site/beol.env` 내용(R1 시점, 편집기로 작성). 사내 API·S3·벡터 DB·미러는 `NO_PROXY`에 넣는다.

```bash
export TZ=Asia/Seoul
export PYTHONIOENCODING=utf-8
export BEOL_NO_BROWSER=1
export PATH="$HOME/.local/bin:$PATH"
export HTTPS_PROXY=http://<proxy-host>:<proxy-port>
export HTTP_PROXY="$HTTPS_PROXY" https_proxy="$HTTPS_PROXY" http_proxy="$HTTPS_PROXY"
export NO_PROXY=localhost,127.0.0.1,<사내 도메인 접미사>
export no_proxy="$NO_PROXY"
# C5(프록시 측정) 뒤: BEOL_ALLOWED_HOSTS, BEOL_PATH_PREFIX
# B2b·B4 릴리스(C6) 뒤: BEOL_ALLOWED_HOST_SUFFIXES=<사내 도메인 접미사>, BEOL_*_API_KEY, BEOL_S3_*
```

셸 rc가 읽게 한다(VS Code 터미널 포함). 릴리스를 바꿀 때(CU)는 이 경로를 새 폴더로 바꾼다.

```bash
echo 'set -a; . /config/work/beol/<release_label>/workspaces/_site/beol.env; set +a' >> ~/.bashrc
. ~/.bashrc
step E05 "프록시" -- python3 tools/beol_doctor.py --step E05
step E11 "시간대" -- python3 tools/beol_doctor.py --step E11
```

`sudo`는 프록시 env를 넘기지 않는다. 미러가 프록시 뒤에 있으면 `sudo -E`를 쓰거나 apt(`/etc/apt/apt.conf.d/`)·dnf(`/etc/dnf/dnf.conf`)의 proxy 설정을 서버 관리자에게 요청한다.

## 4. 인증서·시계 (E04, E10)

```bash
# 사내 루트 CA → 시스템 저장소
step E04 "CA 등록(deb)" -- sh -c 'sudo cp <사내 루트 CA 파일>.crt /usr/local/share/ca-certificates/ && sudo update-ca-certificates'
step E04 "CA 등록(rpm)" -- sh -c 'sudo cp <사내 루트 CA 파일>.crt /etc/pki/ca-trust/source/anchors/ && sudo update-ca-trust'
step E04 "TLS 확인" -- python3 tools/beol_doctor.py --step E04
step E10 "시계 동기" -- sh -c 'timedatectl status; python3 tools/beol_doctor.py --step E10'
```

시계가 동기화 안 되면 서버 관리자에게 NTP(`<ntp-host>`) 설정을 요청한다(S3 서명은 시계 오차에 민감하다 — `CLOCK_SKEW`).

## 5. 빌드 의존 패키지 (E06)

```bash
# deb
step E06 "빌드 의존(deb)" -- sudo apt-get install -y build-essential pkg-config libsqlite3-dev libssl-dev zlib1g-dev libffi-dev libbz2-dev liblzma-dev libreadline-dev tk-dev uuid-dev ca-certificates fontconfig unzip
# rpm
step E06 "빌드 의존(rpm)" -- sudo dnf install -y gcc make pkgconf-pkg-config sqlite-devel openssl-devel zlib-devel libffi-devel bzip2-devel xz-devel readline-devel tk-devel libuuid-devel ca-certificates fontconfig unzip
```

벡터 DB가 pgvector로 정해지면(G-VDB) `postgresql-client`도 넣는다.

## 6. Python 3.14.2 (E08)

미러에 3.14.2 패키지가 있으면 그것을 쓴다. 없으면 반입한 `Python-3.14.2.tgz`로 빌드한다(`transfer/download_list.json`).

```bash
export R=<반입 폴더>              # 설치 파일과 transfer-received.json이 있는 폴더(릴리스 폴더 밖)
step E08 "tgz sha256(transfer-received.json과 대조)" -- sha256sum "$R/Python-3.14.2.tgz"
step E08 "압축 해제" -- sh -c 'mkdir -p "$HOME/src" && tar -xzf "$R/Python-3.14.2.tgz" -C "$HOME/src"'
step E08 "configure" -- sh -c 'cd "$HOME/src/Python-3.14.2" && ./configure --prefix="$HOME/.local/python3.14" --with-ensurepip=install'
step E08 "make" -- sh -c 'make -C "$HOME/src/Python-3.14.2" -j"$(nproc)"'
step E08 "altinstall" -- make -C "$HOME/src/Python-3.14.2" altinstall
step E08 "모듈 확인" -- "$HOME/.local/python3.14/bin/python3.14" -c "import sqlite3,ssl,zlib,lzma,bz2;print('ok')"
step E08 "python 이름" -- sh -c 'mkdir -p "$HOME/.local/bin" && ln -sf "$HOME/.local/python3.14/bin/python3.14" "$HOME/.local/bin/python"'
step E08 "python 해석(비로그인 셸)" -- bash -c 'command -v python && python -V'
step E08 "python 해석(cron과 같은 빈 환경)" -- env -i HOME="$HOME" B="$B" bash -c '. "$B/workspaces/_site/beol.env"; command -v python && python -V'
```

- 마지막 두 확인 모두 `Python 3.14.2`여야 한다.
- `make` 출력 끝의 "Failed to build these modules"에 `_ssl`·`_sqlite3`·`_lzma`·`_bz2`가 있으면 5번 패키지가 빠진 것이다 → `python3 tools/beol_doctor.py --step E08 --python "$HOME/.local/python3.14/bin/python3.14"`.

## 7. 브라우저·폰트 (E09)

슬라이드 이미지 렌더에 쓴다. 미러 패키지가 있으면 그것, 없으면 반입 파일. 반입 파일은 먼저 `transfer-received.json`의 sha256과 대조한다.

```bash
# 미러 패키지
step E09 "chromium·폰트(deb)" -- sudo apt-get install -y chromium fonts-noto-cjk
step E09 "chromium·폰트(rpm)" -- sudo dnf install -y chromium google-noto-sans-cjk-ttc-fonts
# 반입 파일
step E09 "반입 파일 sha256" -- sh -c 'sha256sum "$R"/chrome-linux64.zip "$R"/NotoSansCJKkr-*.otf'
step E09 "폰트 설치" -- sh -c 'mkdir -p ~/.local/share/fonts && cp "$R"/NotoSansCJKkr-*.otf ~/.local/share/fonts/ && fc-cache -f'
step E09 "Chrome for Testing" -- sh -c 'mkdir -p ~/.local/opt && unzip -oq "$R/chrome-linux64.zip" -d ~/.local/opt'
step E09 "빠진 라이브러리 없음" -- sh -c '! ldd ~/.local/opt/chrome-linux64/chrome | grep "not found"'
step E09 "확인" -- sh -c 'fc-list | grep -i "Noto Sans CJK" | head -1 && ~/.local/opt/chrome-linux64/chrome --headless=new --version'
step E09 "doctor" -- python3 tools/beol_doctor.py --step E09
```

빠진 라이브러리가 나오면 그 이름의 패키지를 미러로 설치한다. 브라우저 경로는 작업 폴더 `pipeline.json`의 `render.browser_path`에 적는다(설정만으로 고치는 항목).

## 8. 작업 폴더·HOME (E13)

```bash
step E13 "HOME 다운로드 폴더" -- mkdir -p "$HOME/Downloads"
step E13 "workspaces는 실제 폴더(심볼릭 링크 금지)" -- sh -c 'test -d workspaces && test ! -L workspaces'
step E13 "쓰기·디스크" -- python3 tools/beol_doctor.py --step E13
```

`workspaces/`는 로컬 디스크의 실제 폴더나 bind mount여야 한다(SQLite 잠금, 상대경로·`realpath` 비교). `/config/work/beol/current` 같은 심볼릭도 쓰지 않는다.

## 9. crontab

`crontab -e` 맨 위에 폴더와 env를 둔다. 릴리스를 바꿀 때(CU 6단계) `B=`를 새 폴더로 고친다.

```cron
B=/config/work/beol/<release_label>
0 6 * * *  . $B/workspaces/_site/beol.env; cd $B && mkdir -p workspaces/_nightly && python nightly_run.py >> workspaces/_nightly/cron.log 2>&1
```

백업 줄(`tools/vector_backup.py` 등)은 B7 릴리스에서 `CLOSED_NETWORK_RUNBOOK.md`에 추가된다.

## 10. 확인

```bash
step E15 "doctor 재실행(E15는 게이트 후 릴리스)" -- python3 tools/beol_doctor.py
python -V                                                      # Python 3.14.2
mkdir -p workspaces/_setup_check && python -m labelbot selfcheck --workspace workspaces/_setup_check
python -m pytest -p no:cacheprovider -q tests/contracts
# 폐쇄망 테스트 목록(manifest test_modules, 더미 의존 모듈 제외)
python -m pytest -p no:cacheprovider -q $(python -c "import json;print(' '.join(json.load(open('transfer/import_manifest.json'))['test_modules']))")
# pytest가 미러에 없으면
python -m unittest $(python -c "import json;print(' '.join(m[:-3].replace('/','.') for m in json.load(open('transfer/import_manifest.json'))['test_modules']))")
```

- 상태·사유 코드 표(L3c 릴리스부터): `python3 tools/beol_status.py status --all-workspaces`, `python3 tools/beol_status.py codes --entrypoints`(배포판 python3), `python -m labelbot status --all-workspaces`, `python -m labelbot codes`(Python 3.14) — 두 출력이 같아야 한다.
- ZIP 압축 해제 뒤 파일 시각 때문에 selfcheck가 `TAXONOMY_XLSX_NEWER` 경고를 낼 수 있다(2초 차이까지는 무시). 그래도 나오면 `touch taxonomy/taxonomy.json`.
- 수락: 위 `step`이 모두 `완료`, `/config/work/beol/_import/env.json` 기록, doctor 재실행에서 E01–E14 ✔(E15는 게이트 후), `doctor_report.json` 보관. 실패 테스트는 로컬 기준선의 남은 것만이어야 한다(`CLOSED_NETWORK_RUNBOOK.md` C3).
- `workspaces/_setup_check`는 확인 뒤 지워도 된다.
