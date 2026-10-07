# BEOL AX 쇼릴 (15초)

BEOL AX가 하는 일을 15초로 보여 주는 설명 영상이다. 슬라이드 파싱 → 라벨링 → 검증 → 학습 → 저장(VAULT) 흐름을 한 번에 보여 준다.

- 화면은 three.js(WebGL) 3D 장면과 HTML 오버레이(글자·패널·진행 바)를 겹쳐 그린다.
- 화면 글자는 모두 영어다. 한글은 이 README에만 있고, 페이지가 읽는 파일(`.html` `.js` `.css`)에는 없다.
- 결과 영상은 `BEOL_AX_showreel_15s.mp4`다.
  - 1920×1080, 60fps, 정확히 900프레임(15.000초)이다.
  - 영상은 H.264 High(yuv420p, BT.709), 소리는 AAC 256k 스테레오 48kHz다. `+faststart`라 웹에서 바로 재생된다.
  - 프레임마다 서브프레임 4장을 섞어 모션 블러를 넣었다(셔터 180°).

## 바로 재생하기

ES 모듈과 import map을 쓰므로 `file://`로는 열리지 않는다. HTTP 서버로 연다.

방법 1. `docs/showreel` 폴더에서 서버를 띄운다.

```
cd "docs/showreel"
python -m http.server 8000
```

브라우저에서 http://localhost:8000/showreel.html 을 연다.

방법 2. 저장소의 launch 설정 `docs-static`을 쓴다(`docs` 폴더를 8790번 포트로 띄운다).

- 주소: http://localhost:8790/showreel/showreel.html

- 페이지를 열면 15초를 반복 재생한다. 스페이스로 멈추거나 다시 재생하고, ←/→로 한 프레임씩 옮긴다.
- 주소 뒤에 `?t=7.5`를 붙이면 그 시각의 정지 화면만 보여 준다(재생하지 않는다).

## 다시 렌더링하기

준비물은 Python 3.14(표준 라이브러리만 사용), Chrome(없으면 Edge), ffmpeg다.

- ffmpeg 기본 경로: `C:/Users/dltkd/AppData/Local/CapCut/Apps/9.5.0.4050/ffmpeg.exe`
- 다른 ffmpeg를 쓰려면 `--ffmpeg` 옵션으로 경로를 준다.
- 임시 파일(프레임, wav, Chrome 프로필)은 저장소 밖 scratch 폴더에만 쓴다.

### 1. 소리 만들기 (`tools/sound.py`)

```
python docs/showreel/tools/sound.py --out "<SCRATCH>/motion/sound/reel.wav" --target -14
```

- 모든 소리를 직접 합성한다. 샘플은 쓰지 않았다.
- 시드가 고정이라 매번 같은 바이트가 나온다. 12초쯤 걸린다.
- 결과는 15.000초, 48kHz/16bit 스테레오, 약 -14 LUFS, true peak 약 -1.3 dBTP다.
- `--stems`를 주면 스템별 음량을, `--curve`를 주면 0.5초 간격의 단기 음량을 출력한다.

### 2. 영상 렌더링 (`tools/render.py`)

최종본은 이 명령으로 만들었다.

```
python docs/showreel/tools/render.py ^
  --mp4 "docs/showreel/BEOL_AX_showreel_15s.mp4" ^
  --subframes 4 --shutter 0.5 ^
  --audio "<SCRATCH>/motion/sound/reel.wav" --audio-bitrate 256k ^
  --workers 3 --quality 14
```

- 인코더는 자동으로 고른다. 순서는 `h264_qsv`(Intel) → `h264_nvenc` → `h264_amf` → `h264_mf`다. 이 PC는 `h264_qsv` ICQ 14를 썼다.
- 3600장(900프레임 × 서브프레임 4장)을 캡처한다. 렌더링은 몇 분 걸린다.
- 끝나면 전체 디코드 검사를 하고 스트림 정보를 출력한다.

### 자주 쓰는 확인 명령

```
# 결정성 검사: 앞으로 렌더링한 뒤 거꾸로 다시 렌더링해서 PNG 바이트를 비교한다
python docs/showreel/tools/render.py --times 0,1.25,2.7,4.2,6.8,9.1,11.8,13.5,14.95 --verify-determinism --frames-dir "<SCRATCH>/det"

# 구간 연속 컷(contact sheet)
python docs/showreel/tools/render.py --start 2.3 --end 3.1 --every 2 --contact "<SCRATCH>/strip.png" --cols 8 --thumb-width 240

# 참고 영상과 나란히 비교
python docs/showreel/tools/render.py --compare "C:/Users/dltkd/Downloads/original.mp4@12.5:7.25" --compare-out "<SCRATCH>/cmp"

# 빠른 미리보기(절반 해상도)
python docs/showreel/tools/render.py --mp4 "<SCRATCH>/preview.mp4" --dsf 0.5 --out-width 960 --workers 3
```

`<SCRATCH>`는 세션 scratch 폴더다. 예: `C:/Users/dltkd/AppData/Local/Temp/claude/C--Users-dltkd-Desktop-261004-BEOL-AX-day2/<세션 ID>/scratchpad`

렌더러는 다음 페이지 계약에 기대어 동작한다.

- `window.REEL = {duration, fps, width, height, ready, seek(t)}`
- `seek(t)`는 순수 함수다. 화면 상태는 `t`로만 정해진다.
- 난수는 시드를 고정한 PRNG에서만 뽑는다.
- WebGL은 그 자리에서 동기로 그린다(`preserveDrawingBuffer: true`).
- 페이지는 `?render=1`로 열려 자동 재생 없이 `seek`만 받는다.

## 파일 지도

| 경로 | 내용 |
|---|---|
| `showreel.html` | 진입 페이지다. import map, 장면 등록, 하단 진행 바(Rail)를 둔다. `window.REEL`을 노출한다 |
| `engine.js` | 렌더러, 카메라, 그리드 바닥, 블룸, 시간축, PRNG를 담당한다. 상수 `DURATION`·`FPS`·`W`·`H`가 여기 있다 |
| `ui.js` | HTML 오버레이 부품(헤드라인 블록, 유리 패널, 칩, 진행 바 등)이다 |
| `reel.css` | 오버레이 스타일과 색 토큰이다 |
| `scenes/01_hook.js` | 0–2.7s: 엔지니어 슬라이드를 파싱하다가 픽셀로 흩어지는 도입부다 |
| `scenes/02_overview.js` | 1.4–2.8s: SLIDE → LABEL → VERIFY → LEARN → VAULT 다섯 받침대를 패킷이 건너는 개요다 |
| `scenes/03_label.js` | 2.7–5.65s, STEP 01 LABEL: LLM 구체가 슬라이드 조각을 받아 라벨 다섯 개를 카드로 흘려 보낸다 |
| `scenes/04_verify.js` | 4.95–8.15s, STEP 02 VERIFY: 라벨 칩이 유리판을 지나고, FLAG 칩은 엔지니어 검수 패널에 도킹해 체크된다 |
| `scenes/05_learn.js` | 7.45–10.65s, STEP 03 LEARN: 에이전트가 묻고(Q) 엔지니어가 답하면(A) 규칙(RULE)이 된다 |
| `scenes/06_vault.js` | 9.95–15s, STEP 04 VAULT: 흩어진 복셀이 벡터 DB 블록으로 정렬된다 |
| `scenes/07_close.js` | 12.25–15s: 슬라이드가 지식 카드로 바뀌고 라벨 칩이 붙은 뒤 엔드 카드로 끝난다 |
| `STYLE.md` | 룩(색, 빛, 재질, 타이포)의 기준이다 |
| `COPY.md` | 화면 문구의 기준이다(영어) |
| `STORYBOARD.md` | 비트 그리드(120 BPM)와 장면별 타이밍의 기준이다 |
| `tools/render.py` | 오프라인 렌더러다(headless Chrome + DevTools 프로토콜 → PNG → ffmpeg) |
| `tools/sound.py` | 사운드를 합성한다(표준 라이브러리만 쓴다) |
| `vendor/three/` | three.js를 저장소에 복사해 두었다(아래 참고) |
| `BEOL_AX_showreel_15s.mp4` | 최종 렌더링 결과다 |

## three.js 사본 안내

- `vendor/three/`는 three.js **0.186.1**(MIT 라이선스, `vendor/three/LICENSE`)을 npm 배포본에서 그대로 복사한 것이다.
  - 복사한 범위: `build/three.module.js`, `build/three.core.js`, `examples/jsm`의 일부 폴더
  - 출처와 범위는 `vendor/three/VENDOR.json`에 적혀 있다.
- 페이지는 CDN이나 웹 폰트 같은 외부 리소스를 하나도 쓰지 않는다. 그래서 네트워크 없이 재생하고 렌더링할 수 있다.
- 글꼴은 Windows 시스템 글꼴(Segoe UI Variable, Bahnschrift, Cascadia Mono)을 쓴다.
- three.js를 업데이트할 때는 `vendor/three/` 아래 파일만 바꾼다. 경로는 `showreel.html`의 import map이 정한다.
