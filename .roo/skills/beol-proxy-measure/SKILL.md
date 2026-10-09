---
name: beol-proxy-measure
description: 'VS Code 포트 패널·사내 프록시 뒤에서 화면 서버(검수·질문·taxonomy 보드)가 받는 Host·Origin·경로 접두어를 재고(C5), 그 값으로 workspaces/_site/beol.env의 BEOL_ALLOWED_HOSTS·BEOL_PATH_PREFIX를 정한 뒤, 아무것도 쓰지 않는 요청으로 labelbot serve가 프록시 주소는 받고 위조 Origin은 403으로 막는지 확인한다. 사용자가 "프록시 측정", "포트 패널 403", "화면이 저장 안 돼", "BEOL_ALLOWED_HOSTS 정하기", "프록시 뒤 화면 확인"이라고 하면 이 스킬을 쓴다.'
---

# beol-proxy-measure: 프록시 측정 (C5)

> 수작성 skill(폐쇄망 운영). 근거: 폐쇄망 계획 C5, `CLOSED_NETWORK_RUNBOOK.md` "설정만으로 고칠 수 있는 것".

실제 프록시 호스트 이름은 `beol.env`(비추적)에만 적고, 이 대화·저장소 파일에는 `<프록시 호스트>`로 쓴다.

## 절차

1. **측정 서버(헤더 기록).** 서버는 끝날 때까지 막히므로 사용자에게 별도 VS Code 터미널에서 실행해 달라고 안내한다.
   ```bash
   python -c "import http.server as h;exec(\"class H(h.BaseHTTPRequestHandler):\n def do_GET(s):\n  print(s.headers.get('Host'),s.headers.get('Origin'),s.headers.get('X-Forwarded-Host'),s.headers.get('X-Forwarded-Proto'),s.headers.get('X-Forwarded-Prefix'),s.path,flush=True);s.send_response(200);s.end_headers();s.wfile.write(b'ok')\");h.HTTPServer(('127.0.0.1',8771),H).serve_forever()"
   ```
   사용자가 포트 패널(또는 프록시 URL)로 `…/8771/x`를 브라우저에서 연 뒤, 그 터미널에 찍힌 한 줄과 브라우저 주소의 호스트 부분을 알려 달라고 한다. 다 보면 Ctrl+C로 끈다.
2. **값 정하기.**
   - 브라우저 주소의 호스트 → `BEOL_ALLOWED_HOSTS`(쉼표로 여러 개, 포트 무관).
   - 서버가 받은 경로가 `/x`가 아니고 앞에 접두어가 붙어 있으면(예: `/<접두어>/8771/x`) 그 접두어 → `BEOL_PATH_PREFIX`(포트마다 다르면 런북 표처럼 포트별로 적는다).
   - 사용자가 `workspaces/_site/beol.env`에 `export BEOL_ALLOWED_HOSTS=…`, `export BEOL_PATH_PREFIX=…`를 추가하고 새 터미널을 연다(또는 `set -a; . workspaces/_site/beol.env; set +a`).
3. **수락 확인(아무것도 쓰지 않는 요청).** 화면 서버를 별도 터미널에서 띄운다.
   ```bash
   python -m labelbot serve --workspace workspaces/_proxy_check --port 8771
   ```
   `[M05 REVIEW_SERVE] 대기 중 URL=…`이 나오면 프록시 URL로 두 요청을 보낸다. 본문 `{}`는 형식 검사에서 거절되므로 inbox에 아무것도 쓰지 않는다.
   ```bash
   curl -s -o /dev/null -w "%{http_code}\n" -X POST -H 'Origin: https://<프록시 호스트>' -H 'Content-Type: application/json' --data '{}' 'https://<프록시 호스트>/<접두어>/inbox/review'
   curl -s -o /dev/null -w "%{http_code}\n" -X POST -H 'Origin: https://evil.example' -H 'Content-Type: application/json' --data '{}' 'https://<프록시 호스트>/<접두어>/inbox/review'
   ```
   - 첫 요청: **400**(`KIND_MISMATCH`·`JSON_INVALID` 등 본문 거절)이면 Host·Origin 검사는 통과한 것이다. **403**(`HOST_REJECTED`·`ORIGIN_REJECTED`)이면 2의 값을 다시 본다.
   - 둘째 요청(위조 Origin): **403**이어야 한다.
4. **정리.** 화면 서버를 Ctrl+C로 끄고(`중단(사용자)`는 실패가 아니다) `rm -rf workspaces/_proxy_check`. taxonomy 보드의 "최종 완료"처럼 무언가를 쓰는 버튼은 누르지 않는다.

## 수락

- 정상 Origin 요청이 403이 아니고(본문 거절 400), 위조 Origin이 403.
- `beol.env`에 두 값이 있고, 같은 프록시 URL로 검수 화면이 열린다.

## 마일스톤

| 명령 | 마일스톤 |
|---|---|
| `labelbot serve` | M05 REVIEW_SERVE |

담당 마일스톤: M05

## 실패하면

터미널의 `[Mxx …] 실패` 블록을 먼저 읽는다 → `python -m labelbot status --workspace <작업 폴더>`(Python 3.14가 없으면 `python3 tools/beol_status.py status --workspace <작업 폴더>`) 출력을 복사해 알려 달라. 환경 문제면 `python3 tools/beol_doctor.py`. `BEOL_TRACE=1`은 Roo 명령으로 실행하지 말고 일반 터미널에서만.
