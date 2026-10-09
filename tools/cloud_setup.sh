#!/usr/bin/env bash
# 폐쇄망 리눅스 클라우드 환경 확인(C1)의 실행 형태 — CLOUD_SETUP.md의 확인 단계를 step 도우미로 차례로 돌린다.
#
# 사용(릴리스 폴더 어디서든):
#   bash tools/cloud_setup.sh --dry-run        단계 목록만 출력(아무것도 실행·생성하지 않는다)
#   bash tools/cloud_setup.sh                  처음부터
#   bash tools/cloud_setup.sh --from E09       그 단계부터 다시(앞 단계가 실패해 멈췄을 때)
#   bash tools/cloud_setup.sh --only C3        그 단계만
#
# - 패키지를 설치하지 않는다(sudo·사내 미러가 필요). 필요한 apt/dnf 명령은 실패 단계에서 이유와 함께 출력만 한다.
# - 실패한 단계 다음으로 넘어가지 않는다. 로그: workspaces/_site/setup_<YYYYMMDD>.log (키·토큰 값은 *** 로 가린다)
# - python  = Python 3.14(venv 또는 ~/.local/bin), python3 = 배포판 3.8+ (doctor·beol_status·site_init 등)
# - 아래 step 도우미 블록은 CLOUD_SETUP.md 0절과 바이트 단위로 같아야 한다(tests/test_linux_compat.py가 검사).
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"

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

DRY_RUN=0
FROM=""
ONLY=""
usage() {
  sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --from) FROM="${2:-}"; shift ;;
    --only) ONLY="${2:-}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "[M00 ENV/CLI] 실패  사유=ARG_INVALID  인자: $1 (--dry-run | --from <ID> | --only <ID>)" >&2; exit 2 ;;
  esac
  shift
done

# ---- 패키지 안내(설치는 하지 않는다) --------------------------------------------------
os_family() {
  local like=""
  if [ -r /etc/os-release ]; then
    like="$(. /etc/os-release; printf '%s %s' "${ID:-}" "${ID_LIKE:-}")"
  fi
  case "$like" in
    *debian*|*ubuntu*) echo deb ;;
    *rhel*|*fedora*|*centos*|*rocky*|*alma*) echo rpm ;;
    *) echo unknown ;;
  esac
}

pkg_help() {
  local what="$1" fam
  fam="$(os_family)"
  echo "  패키지 설치가 필요하다. 이 스크립트는 설치하지 않는다(sudo·사내 미러 필요) — 아래 명령을 직접 또는 서버 관리자에게 요청해 실행한 뒤"
  echo "  bash tools/cloud_setup.sh --from <이 단계 ID> 로 다시 돈다. 미러가 프록시 뒤면 sudo -E (CLOUD_SETUP.md 3절)."
  case "$what:$fam" in
    build:deb) echo "    sudo apt-get install -y build-essential pkg-config libsqlite3-dev libssl-dev zlib1g-dev libffi-dev libbz2-dev liblzma-dev libreadline-dev tk-dev uuid-dev ca-certificates fontconfig unzip" ;;
    build:rpm) echo "    sudo dnf install -y gcc make pkgconf-pkg-config sqlite-devel openssl-devel zlib-devel libffi-devel bzip2-devel xz-devel readline-devel tk-devel libuuid-devel ca-certificates fontconfig unzip" ;;
    chrome:deb) echo "    sudo apt-get install -y chromium fonts-noto-cjk fontconfig" ;;
    chrome:rpm) echo "    sudo dnf install -y chromium google-noto-sans-cjk-ttc-fonts fontconfig" ;;
    *) echo "    배포판을 판정하지 못했다 — CLOUD_SETUP.md 5절(빌드 의존)·7절(chromium·폰트)의 deb/rpm 명령을 본다" ;;
  esac
  if [ "$what" = chrome ]; then
    echo "    미러에 없으면 반입한 Chrome for Testing·Noto Sans CJK(CLOUD_SETUP.md 7절)를 ~/.local/opt 에 풀고"
    echo "    workspaces/_site/beol.env 에 export BEOL_CHROME=\$HOME/.local/opt 를 적는다(root·컨테이너면 BEOL_CHROME_NO_SANDBOX=1)."
  fi
}

# ---- 단계 함수 -------------------------------------------------------------------------
do_site_init() {
  python3 tools/site_init.py
}

do_doctor_report() {
  local rc=0
  python3 tools/beol_doctor.py || rc=$?
  echo "doctor rc=$rc — 이 단계는 보고만 한다(멈추지 않음). 처음 ✖ 줄의 '담당자에게:' 문장을 보안·인프라 담당에게 전달한다."
  return 0
}

do_python() {
  local out rc=0
  out="$(bash -c 'command -v python && python -V' 2>&1)" || rc=$?
  printf '%s\n' "$out"
  if [ "$rc" -eq 0 ] && printf '%s' "$out" | grep -q 'Python 3\.14\.'; then
    if [ -f workspaces/_site/beol.env ]; then
      # cron과 같은 빈 환경에서도 같은 python이어야 한다
      out="$(env -i HOME="$HOME" PATH=/usr/bin:/bin bash -c 'set -a; . workspaces/_site/beol.env; set +a; command -v python && python -V' 2>&1)" || rc=$?
      printf '빈 환경(cron): %s\n' "$out"
      if [ "$rc" -ne 0 ] || ! printf '%s' "$out" | grep -q 'Python 3\.14\.'; then
        echo "  cron 같은 빈 환경에서는 python이 3.14가 아니다 → workspaces/_site/beol.env 에 export PATH=\"<3.14가 있는 bin>:\$PATH\" 를 넣는다"
        return 1
      fi
    fi
    return 0
  fi
  echo "  python 이 Python 3.14.x 가 아니다(위 출력). 셋 중 하나로 맞춘 뒤 --from E08 로 다시:"
  echo "    a) 빌드한 3.14(CLOUD_SETUP.md 6절): mkdir -p ~/.local/bin && ln -sf ~/.local/python3.14/bin/python3.14 ~/.local/bin/python"
  echo "       그리고 workspaces/_site/beol.env 에 export PATH=\"\$HOME/.local/bin:\$PATH\""
  echo "    b) venv: ~/.local/python3.14/bin/python3.14 -m venv ~/.venvs/beol && echo 'export PATH=\"\$HOME/.venvs/beol/bin:\$PATH\"' >> workspaces/_site/beol.env"
  echo "    c) pyenv: pyenv install 3.14.2 (반입한 Python-3.14.2.tgz를 ~/.pyenv/cache 에 둔다) && pyenv local 3.14.2"
  echo "  빌드에 필요한 헤더가 없으면:"
  pkg_help build
  return 1
}

do_tz() {
  python3 tools/beol_doctor.py --step E11
}

do_chrome_font() {
  if python3 tools/beol_doctor.py --step E09; then
    return 0
  fi
  pkg_help chrome
  return 1
}

do_filesystem() {
  if [ ! -d workspaces ] || [ -L workspaces ]; then
    echo "  workspaces/ 는 실제 폴더여야 한다(심볼릭 링크 금지 — SQLite 잠금·상대경로 비교)"
    return 1
  fi
  python3 tools/beol_doctor.py --step E13
}

do_selfcheck() {
  # 라벨링 작업 폴더 없이: 임시 작업 폴더(저장소 taxonomy.json을 가리킴)로 selfcheck를 돌리고,
  # 사내 API 게이트(G-API) 전이라 비어 있는 llm_config·llm_key_env FAIL만 허용한다.
  local ws=workspaces/_setup_check out rc=0
  rm -rf "$ws"
  mkdir -p "$ws"
  printf '{\n  "taxonomy_path": "../../taxonomy/taxonomy.json"\n}\n' > "$ws/pipeline.json"
  out="$(python -m labelbot selfcheck --workspace "$ws" 2>&1)" || rc=$?
  rm -rf "$ws"
  printf '%s\n' "$out"
  if [ "$rc" -eq 0 ]; then
    return 0
  fi
  if printf '%s\n' "$out" | grep -E '^[A-Za-z_][A-Za-z0-9_. ]* FAIL( |$)' | grep -v -E '^(llm_config|llm_key_env) ' | grep -q .; then
    echo "  selfcheck에 G-API 밖의 FAIL이 있다(위 표) → 그 항목을 고친다. 설치·네트워크는 python3 tools/beol_doctor.py"
    return 1
  fi
  echo "  llm_config·llm_key_env FAIL은 사내 API 게이트(G-API) 전이라 허용한다. 나머지 항목은 PASS."
  return 0
}

do_codes() {
  local out
  out="$(python3 tools/beol_status.py codes --entrypoints)"
  printf '%s\n' "$out" | sed -n '1,40p'
  echo "  (앞 40줄만 표시. 전체: python3 tools/beol_status.py codes --entrypoints)"
}

compare_failures() {
  # $1=로그, $2=pytest|unittest. config/known_test_failures.txt 밖의 실패·오류가 있으면 1.
  python3 - "$1" "$2" <<'PY'
import io, re, sys
log, mode = sys.argv[1], sys.argv[2]
with io.open("config/known_test_failures.txt", encoding="utf-8") as f:
    known = set(l.strip() for l in f if l.strip() and not l.startswith("#"))
if mode == "unittest":
    known = set(k.replace(".py::", ".").replace("::", ".").replace("/", ".") for k in known)
with io.open(log, encoding="utf-8", errors="replace") as f:
    text = f.read()
got = set()
if mode == "pytest":
    for m in re.finditer(r"^(?:SUB)?(?:FAILED|ERROR)(?:\([^)]*\))? (\S+)", text, re.M):
        got.add(m.group(1))
else:
    for m in re.finditer(r"^(?:FAIL|ERROR): \S+ \(([\w.]+)\)", text, re.M):
        got.add(m.group(1))
new = sorted(got - known)
print("실패·오류 %d건(기준선 안 %d건, 새 실패 %d건)" % (len(got), len(got) - len(new), len(new)))
for n in new:
    print("  새 실패: " + n)
sys.exit(1 if new else 0)
PY
}

do_tests() {
  local mods log rc=0
  if ! mods="$(python3 tools/beol_status.py test-modules)" || [ -z "$mods" ]; then
    echo "[M00 ENV/C3] 실패  사유=TEST_LIST_EMPTY  manifest test_modules가 비었거나 읽히지 않는다 — 전체 테스트로 대신 돌리지 않는다"
    return 1
  fi
  log="workspaces/_site/c3_tests_$(date +%Y%m%d-%H%M%S).log"
  if python -c "import pytest" >/dev/null 2>&1; then
    # shellcheck disable=SC2086  # 목록은 공백으로 나뉜 모듈 경로(이름에 공백 없음)
    BEOL_NO_BROWSER=1 PYTHONIOENCODING=utf-8 python -m pytest -p no:cacheprovider -q -rfE $mods > "$log" 2>&1 || rc=$?
    tail -n 5 "$log"
    [ "$rc" -eq 0 ] && return 0
    compare_failures "$log" pytest
  else
    mods="$(python3 tools/beol_status.py test-modules --unittest)"
    # shellcheck disable=SC2086
    BEOL_NO_BROWSER=1 PYTHONIOENCODING=utf-8 python -m unittest $mods > "$log" 2>&1 || rc=$?
    tail -n 5 "$log"
    [ "$rc" -eq 0 ] && return 0
    compare_failures "$log" unittest
  fi
}

# ---- 단계 표: ID|설명|함수 (순서 = 실행 순서) -------------------------------------------
STEPS=(
  "S01|사이트 설정 폴더 workspaces/_site (없는 파일만)|do_site_init"
  "E00|설치 전 진단 doctor(보고만, 멈추지 않음)|do_doctor_report"
  "E08|python = Python 3.14.x (비로그인 셸·cron 빈 환경)|do_python"
  "E11|시간대 Asia/Seoul|do_tz"
  "E09|chromium·한글 글꼴(슬라이드 렌더)|do_chrome_font"
  "E13|작업 폴더·쓰기·디스크|do_filesystem"
  "S02|labelbot selfcheck(임시 작업 폴더, G-API 전 LLM 항목 제외)|do_selfcheck"
  "S03|사유 코드·진입점 표(배포판 python3)|do_codes"
  "C3|폐쇄망 테스트 목록(manifest test_modules, 기준선 밖 실패 0)|do_tests"
)

known_id() {
  local e
  for e in "${STEPS[@]}"; do
    [ "${e%%|*}" = "$1" ] && return 0
  done
  return 1
}
for opt in "$FROM" "$ONLY"; do
  if [ -n "$opt" ] && ! known_id "$opt"; then
    echo "[M00 ENV/CLI] 실패  사유=STEP_UNKNOWN  단계 ID: $opt (bash tools/cloud_setup.sh --dry-run 으로 목록을 본다)" >&2
    exit 2
  fi
done

started=0
[ -z "$FROM" ] && started=1
[ "$DRY_RUN" -eq 1 ] && echo "[dry-run] 실행할 단계(ID  설명):"
for entry in "${STEPS[@]}"; do
  IFS='|' read -r sid sdesc sfn <<<"$entry"
  if [ "$started" -eq 0 ] && [ "$sid" = "$FROM" ]; then
    started=1
  fi
  [ "$started" -eq 1 ] || continue
  if [ -n "$ONLY" ] && [ "$sid" != "$ONLY" ]; then
    continue
  fi
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '  %-4s %s\n' "$sid" "$sdesc"
    continue
  fi
  if ! step "$sid" "$sdesc" -- "$sfn"; then
    echo "멈춤: $sid 실패. 고친 뒤 bash tools/cloud_setup.sh --from $sid"
    exit 1
  fi
done
[ "$DRY_RUN" -eq 1 ] || [ -n "$ONLY" ] || echo "[M00 ENV] 모든 단계 완료 —CLOUD_SETUP.md 10절 수락 항목(doctor E01–E14 ✔, doctor_report.json 보관)을 확인한다"
