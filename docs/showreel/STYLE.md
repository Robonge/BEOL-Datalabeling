# STYLE.md — BEOL AX showreel style bible

Reverse-engineered from the reference explainer ("Text-to-video, explained", 1280x720, 30 fps, 30.0 s).
All pixel values below are **already converted to the 1920x1080 stage (x1.5)** unless marked `@720`.
Colors were measured from decoded frames (crop → average / percentile), then lightly corrected for
H.264 chroma smear. Use the tokens; do not eyeball new colors.

The single most important rule: **the reference is calm, sparse and exact.** One idea per shot, one
orange accent per shot, huge negative space, UI chrome that never moves while the 3D world does.
Everything that looked "cheap" in the rejected draft (busy layouts, many colors, bouncy easing,
text without masks, flat backgrounds, thin glow) is the opposite of this reference.

---

## 1. Color tokens

| Token | Hex | Measured from | Use |
|---|---|---|---|
| `--bg-center` | `#31343B` | flat floor/wall center, t=6.6 | background center (vignette core) |
| `--bg-edge` | `#232429` | all four corners, every shot | vignette edge / corners |
| `--bg-mid` | `#27282D` | mid-left/right edges | vignette at 75% radius |
| `--grid-minor` | `#FFFFFF` @ 10% (wall 9%) | re-measured on ref_t03.80 / ref_t13.60 (rev 2) | floor minor grid; back wall grid |
| `--grid-major` | `#FFFFFF` @ 16% (seam 22%) | lines read `#484B52`–`#55585F` | every 4th floor line; floor/wall seam at 22% |
| `--orange` | `#FF6A1A` | eyebrow square `#FF6D1D`, bar fill `#FF6610`, chevron `#F26A20` | THE accent. Eyebrows, active stop, fills, highlighted word |
| `--orange-soft` | `#E5682F` | underline, chip borders `#D36A55`→`#F26A2A` | underline (85% alpha), token chip borders |
| `--orange-wire` | `#E8893A` | orb wireframe lines | wire lines (additive, blooms to `#FF8A3A`) |
| `--glow-core` | `#FFF35A` | orb core center `#FFFE54` | emissive core center |
| `--glow-mid` | `#FFC12E` | orb core rim | core rim gradient stop |
| `--glow-halo` | `#F5772F` | halo r≈1.2x core | first halo ring |
| `--glow-outer` | `#C0603A` → transparent | halo r≈2.5x core | outer bloom falloff |
| `--white` | `#FFFFFF` | headlines, counters, passed stops | primary text |
| `--desc` | `#D8DBE2` | description strokes p98.5 `#DADDE4` | description line (cool light gray) |
| `--label-future` | `#BFC2C9` | future stop labels peak `#CED1D8` | not-yet-reached stop labels |
| `--track` | `#4A4B53` | bar track between stops | progress track (≈ white 14%) |
| `--dot-future` | `#6A6D74` | future stop dots | future stop dots |
| `--card-fill` | `#26272C` (opaque 0.94) | card interior, both card sizes | glass/console card fill |
| `--card-inner` | `#20232A` | 3–4 px band just inside border | inner shadow ring |
| `--card-border` | `#53565D` | 2 px@720 border | card stroke (≈ white 18%) |
| `--card-shadow` | `#000000` @ 18%, blur 24 px | 6–8 px darker halo outside card | card drop shadow |
| `--glass-fill` | `#FFFFFF` @ 9% | encoder sheets (`#34373E` on `#31343B`, brighter on dark) | glass sheet face |
| `--glass-edge` | `#FFFFFF` @ 45% | sheet edges peak `#62656C`–`#6A6D74` | glass sheet 1 px edge |
| `--glass-hot` | `#F0A080` @ 22% face, `#FF7A40` @ 70% edge | sheets while tokens pass | "active" glass tint |
| `--noise-cube` | `#8A8C92` … `#D2D3D7` | denoise noise cloud | gray noise voxels |
| `--noise-accent` | `#FF6A1A` (~12% of cubes) | denoise noise cloud | orange noise voxels |
| `--noise-dark` | `#2A2A2E` (~6% of cubes) | denoise noise cloud | dark noise voxels |

Rules:
- Orange is the ONLY saturated hue in UI chrome. Imagery (photos, voxels showing an image) may carry color;
  UI may not. No blue, no green, no purple gradients, ever.
- Never use pure black. The darkest pixel on screen in normal shots is `#1E1F24` (inside cards).
- White text is pure `#FFFFFF`; secondary text is cooler `#D8DBE2`; tertiary `#BFC2C9`. Three levels only.

## 2. Background, room and atmosphere

- **Vignette (screen space, behind everything):** elliptical radial gradient, center `#31343B` at
  (50%, 45%), `#27282D` at 70% radius, `#232429` at corners. The falloff is mostly horizontal:
  luminance profile left→right ≈ 38 · 44 · 52 · 52 · 52 · 44 · 38; top→bottom only ≈ 40 · 46 · 40.
  Implement as a full-screen quad behind the scene (or `scene.background` = gradient texture) so the
  grid draws on top of it.
- **The room:** an open box. Infinite-looking floor plane + back wall + faint side walls, all carrying
  grid lines. Floor/wall seam sits at ~y=450–720 depending on shot (camera tilts down 8–14°).
  - Floor grid cell: 1 world unit; major line every 4 cells. Wall grid cell: 2 units (wall cells read
    ~2x the floor cells). Line width 1 px, never thicker; use `LineSegments` with
    `LineBasicMaterial({transparent, opacity})` or a shader grid with fwidth AA.
  - Minor lines 10% white, major 16% white, seam line 22% white, wall grid 9% (STORYBOARD D12). Fade the
    floor grid to 0 with distance inside the grid shader (100% at 25 units to 0% at 60 units) so the horizon
    dissolves into the vignette and grazing angles do not moire — no hard horizon.
- **Dust motes:** 60–90 tiny points (1.5–3 px), white at 15–35% alpha, slow drift (≤ 6 px/s), a few
  square 4–6 px specks at 20% alpha. Deterministic (seeded) positions; motion = f(t).
- **No film grain** (measured stdev ≈ 1.5 → compression only). No chromatic aberration, no lens dirt.

## 3. Typography (DOM overlay)

Fonts (local): headline `"Segoe UI Variable Display", "Segoe UI Variable", "Bahnschrift", sans-serif`;
body `"Segoe UI Variable Text", "Segoe UI Variable", sans-serif`; mono `"Cascadia Mono", "DejaVu Sans Mono", monospace`.
The reference headline face is a tight neo-grotesk (Inter-Display-like). Segoe UI Variable Display at
600 with -0.02em tracking is the closest local match. Enable `font-optical-sizing: auto`,
`-webkit-font-smoothing: antialiased`, `font-feature-settings: "ss01", "tnum"` on counters.

All positions are for the fixed 1920x1080 stage. Left margin = right margin = **120 px**.

| Style | Font / weight | Size | Tracking | Color | Position (1080) |
|---|---|---|---|---|---|
| **Eyebrow** "■ STEP 01" | Cascadia Mono 700, UPPERCASE | 17 px (cap 13 px) | +0.28em | `--orange` | square 12x12 at x=120, y=138; text x=146, cap-top y=138 |
| **Headline** (step) | Display 600 | 74 px (cap 53 px) | -0.02em | `--white` | x=120 (optical: -2 px), cap-top y=181, baseline y=234 |
| **Underline** | rule | 54 x 3 px | — | `--orange-soft` 85% | x=120, y=258 |
| **Description** | Text 400 | 23 px | 0 | `--desc` | x=120, cap-top y=282, baseline y=299, max-width 840 px, line-height 36 px |
| **Hero headline** (2 lines) | Display 600 | 116 px (cap 88 px) | -0.025em | white, key word orange | x=120, line1 cap-top y=288, line pitch 150 px. **Not used in the BEOL AX reel**: its hook uses the ref_t00.30 one-line layout, 108 px, cap-top 843 (STORYBOARD D1) |
| **Hero eyebrow** | Cascadia Mono 700 | 17 px | +0.28em | `--orange` | x=120, cap-top y=225 |
| **Section title (centered)** "Here's everything in between." | Display 600 | 58 px | -0.02em | white | centered, cap-top y=162; eyebrow centered y=114 |
| **Final title** "Text → video." | Display 650 | 86 px (cap 62 px) | -0.02em | white + orange last word | centered x=960, cap-top y=133 |
| **Counter label** "GENERATING / DONE" | Cascadia Mono 700 | 16 px (cap 12 px) | +0.30em | `--orange` | right-aligned x=1800, cap-top y=855 |
| **Counter value** "5 → 34 words" | Display 600, tnum | 42 px (cap 30 px) | -0.01em | white | right-aligned x=1800, cap-top y=887 |
| **Stop labels** | Cascadia Mono 700 | 16 px (cap 12 px) | +0.30em | passed white / active orange / future `--label-future` | centered on dot, cap-top y=1004 |
| **World label** "TEXT ENCODER", "LLM" | Cascadia Mono 700 | 22–26 px (LLM: 15 px) | +0.32em | white (fades in from 40%) | anchored to a 3D point, projected each frame |
| **Card label** "■ EXPANDED PROMPT" | Cascadia Mono 700 | 16 px | +0.22em | `--orange` | card padding-left 35 px, top 32 px |
| **Card body** (streamed text) | Cascadia Mono 500 | 25 px | 0 | white, newest word orange | line-height 44 px, max 40 chars/line |
| **Prompt console text** | Cascadia Mono 500 | 44 px | +0.02em | white; chevron "›" orange | baseline-centered in card, x-pad 75 px |
| **Caption** (final) | Cascadia Mono 400 | 17 px | 0 | white 90% / meta 55% | centered under final image, y=930 |

Arrows: use "→" (U+2192) in the Display face at the same size; gap 0.25em both sides.
Never set text in all-caps sans; caps are ONLY mono + wide tracking. Never letter-space the Display face positively.

## 4. UI components

### 4.1 Title block (eyebrow + headline + underline + description)
Static in screen space for the whole step; the 3D world moves behind it. Layout above.
Each headline line sits in its own `overflow:hidden` mask box (height = 1.25em, padding-bottom 0.12em so
descenders are not clipped at rest). Words are separate inline-block spans for the stagger.

### 4.2 Progress bar ("pipeline rail")
- Five stops at x = **200, 579, 960, 1340, 1719** (pitch 380 px), centerline y = **974**.
- Track: 3 px, `--track`, from first to last stop.
- Fill: 3 px `--orange`, from x=200 to `lerp(stop[active], stop[active+1], stepProgress)`
  (fill leads the active dot toward the next stop as the step plays; it is NOT a global time bar).
- Dots: future 11 px `--dot-future`; passed 11 px white; active 15 px `--orange` + ring 30 px diameter,
  1.5 px `--orange` at 35% + 18 px orange glow (box-shadow `0 0 18px 4px rgba(255,106,26,.45)`).
- Labels 30 px below centerline (cap-top y=1004), centered. Label color by state as in §3.
- When the step changes: the passed dot snaps white, the next dot grows 11→15 px over 0.25 s
  (easeOutBack 1.4), ring fades in 0→35% over 0.3 s; label color crossfades 0.2 s.
- Final state (everything done): ALL dots and labels turn `--orange`, fill reaches 1719.
- The rail fades in once (opacity 0→1, 0.4 s) on the first step and stays until the outro.

### 4.3 Counter block (bottom-right)
- Mono label (orange, tracked) above a big Display number, both right-aligned at x=1800.
- Number changes are instant integer swaps (no tweened decimals, no rolling digits), driven by the
  same source as the visual (words streamed, tokens passed, step index).
- Variant B (two-column, denoise): left "STEP" label + "08 / 30" number; right "NOISE" label over a
  100x4 px mini bar (track `#6B6E75`, fill orange, shrinking right→left) with a 15 px mono value
  "0.63" right-aligned below. Zero-pad step numbers ("08 / 30").
- Label text changes state words: GENERATING → DONE (swap instantly when the stream ends).
- Enters 0.6–1.0 s after the headline, fading 0→1 over 0.3 s, starting at 45% brightness for the
  first 0.2 s (it "warms up").

### 4.4 Glass / console card
- Two sizes: **prompt console** (1374x296, radius 33 px) and **content card** (864x438, radius 21 px).
- Fill `--card-fill`, border 2.5 px `--card-border`, inner ring 4 px `--card-inner`
  (inset box-shadow `inset 0 0 0 4px #20232A`), outer shadow `0 12px 40px rgba(0,0,0,.28)`.
- Top edge is ~8% brighter than the bottom edge (subtle linear gradient on the border:
  `#5A5D64` top → `#4A4D54` bottom). That is the only "glass" cue — NO blur-backdrop rainbow, no
  frosted noise, no colored glass.
- Cards live in 3D: render as a CSS3D-like plane, or (preferred) a DOM element whose transform is
  computed from a three.js anchor so it trucks out of frame with the world and shows slight perspective
  (the reference card's right edge is ~2% taller than its left during the step-01 hold).
- Typing cursor: solid orange block, 0.55em wide x 1.1em tall, blink period 0.5 s, 50% duty, hard on/off;
  solid (no blink) while characters are arriving.

### 4.5 Token chip
Rounded rect, radius 12 px, fill `--card-fill`, 3 px `--orange-soft` border, mono 26 px white text,
padding 8x20 px. Chips are 3D objects stepping through glass sheets in a diagonal queue.

## 5. 3D materials & lighting

Renderer: `ACESFilmicToneMapping`, exposure 1.0, sRGB output, `antialias: true`, pixel ratio 1
(render exactly 1920x1080). The bloom composer must render into a `WebGLRenderTarget` with `samples: 4`
and `HalfFloatType`; otherwise MSAA is lost and every hairline aliases (STORYBOARD §5). Lights: hemisphere (sky `#C9CCD6`, ground `#1A1B1F`, 0.55) + one
directional key from upper-left-front (dir (-0.5, 1.0, 0.6), 1.4, warm white `#FFF4EA`) + a weak
rim from behind-right (`#FF8A50`, 0.35). No shadows needed; fake contact with a soft dark radial decal
(black 25%, radius 1.2x object footprint) on the floor under objects.

### 5.1 Bloom (UnrealBloomPass)
`strength 0.9, radius 0.75, threshold 0.82` (on ACES-mapped HDR). Only emissive things exceed threshold:
orb core, orange wires, rings, arcs, travelling packets, white orbit points. UI text is DOM so it never
blooms. Target look: orb halo extends to ~2.5x core radius and is clearly visible against the charcoal
(measured: core r=60 px@1080 → orange halo still `#9D4F33` at r=165 px). If halo is weak, raise the
emissive intensity of the source (2.5–4.0), not bloom strength.

### 5.2 "LLM" orb (geodesic wire + sun core)
- Core: sphere r=1.0, `MeshBasicMaterial` with a radial shader `#FFF35A` center → `#FFC12E` rim, emissive x3.
- Shell: `IcosahedronGeometry(2.1, 2)` (180 faces) → `WireframeGeometry` → `LineSegments`, color
  `--orange-wire`, opacity 0.55, additive. Plus a second shell `Icosahedron(2.05, 2)` rotated 18° at 30%
  opacity for the "double line" density the reference shows, and `Points` on the main shell's vertices
  (1.5 px, white 40%) for glints. Line width 1 px (never fat lines). Check against ref_t10.00: 9–11 wire
  edges across the horizontal diameter.
- Inner glow sprite: additive radial texture `#FF6A1A` 55% → 0 at r=2.6 (this is what makes the
  orange "atmosphere" behind the wire).
- Orbiting points: 8 white spheres r=0.09 (≈ 12–16 px on screen), emissive x2.5 so they bloom
  softly, on 2 tilted rings (radii 3.0 and 3.4, tilts 18° and -26°), angular speed 0.35 rad/s,
  phase-offset by seed. Depth makes them vary 10–16 px — keep perspective, it sells the 3D.
- Shell rotation: 0.12 rad/s around a tilted axis (0.3, 1, 0.1).
- Particle stream (orb → card while generating): 40–60 tiny additive points (2–3 px), orange→yellow,
  lifetime 0.8 s, emitted from the shell surface toward the card's left edge on a slight arc.

### 5.3 Glass sheets (encoder)
4 vertical planes (aspect 0.62, height 4.2 units), spacing 0.55 units, rotated ~28° about Y so they
read as a stack. Face: `MeshBasicMaterial` white, opacity 0.09, `depthWrite:false`, double-sided.
Edges: `EdgesGeometry` 1 px white at 45%. Hot state (token inside): face lerps to `#F0A080` @ 22%,
edges to `#FF7A40` @ 70% over 0.15 s, decays over 0.4 s.

### 5.4 Voxels (noise → image)
- Cube size 0.9 of cell (visible 10% gaps), slightly rounded (bevel 0.06) or plain `BoxGeometry`
  with `MeshStandardMaterial({ roughness 0.85, metalness 0 })`. Shading must show 3 tones:
  top face +15% brightness, front face base, side face -20%.
- Use `InstancedMesh` (16x9x4 grid = 576 cubes is enough; the reference reads ~20x10x6).
- Noise state: positions scattered in a 1.6x volume with random rotations, colors from
  `--noise-cube` (82%), `--noise-accent` (12%), `--noise-dark` (6%).
- Resolve: per-cube progress `p_i = clamp((s - delay_i)/0.35)` with `delay_i` seeded 0..0.65; position/rotation
  lerp with easeOutCubic, color lerps from noise color to target image color (sampled from a procedural
  "image" texture, not a photo).
- Conditioning lines: thin orange lines (1 px, 25–35% alpha) from an embedding cloud above-right
  to random cubes, flickering on/off per step.

### 5.5 Pipeline plinths (overview shot)
Dark slabs 3x0.12x2.2 units, top `#2A2B30`, sides `#202126`; 1 px orange outline on the two
front-bottom edges, 1 px white 20% on top edges. Between plinths: half-ellipse arcs (TubeGeometry,
r 0.06) emissive orange x3, tapered alpha at ends, with a 10-sprite comet trail behind the packet. A travelling packet (sphere r=0.12, emissive yellow-white
+ 40 px orange glow sprite) rides the arcs left→right at ~1 plinth per 0.5 s. Each plinth flashes an
orange ground ring (torus r 2.0 so it encircles the plinth, tube 0.04) that flares x5 and expands
0.85→1.0 when the packet lands, stays lit at x3.5 until the next landing, then decays (two rings lit at once).
Floor labels above each plinth: mono "01" orange + "EXPAND" white, 17 px, tracked.

## 6. Camera language

- `PerspectiveCamera` vertical FOV **32°** (moderate tele; very little wide-angle distortion).
- Default framing for a step: camera ~11 units from subject, 2.2 units above floor, tilted down 9–12°,
  subject sitting slightly right of center (center of interest x≈55–60% of frame) so the title block
  on the left has breathing room. The floor/wall seam stays in the lower-middle third.
- **Stages are laid out in a line along +X** ("the pipeline floor"). Step change = camera trucks +X
  (world slides left) by one stage pitch. Measured: total displacement ≈ 0.93 screen widths in
  **0.6 s**, velocity bell curve peaking at ~2.5x average → **easeInOutCubic**. Small simultaneous
  crane (≤ 2% of frame height). Previous stage's objects/cards exit left in perspective.
- During holds the camera is effectively locked; life comes from the objects (orb spin, orbiters,
  token queue, cubes resolving). Allowed: ≤ 1.5°/s slow orbit around the subject, or a 2–3% push-in over
  the whole hold (final shot uses a 3% push-in over 4 s).
- Big reveal move (overview): crane up + pull back over **1.0 s easeInOutQuart**, from eye-level to
  a 25° downward view that shows all stages in one row, then a **0.5 s whip truck** to the end of the row.
- Never roll the camera. Never use handheld shake. Never use dolly-zoom.

## 7. Motion grammar & timing

### 7.1 Easing library (implement in engine.js)
| Name | Curve | Used for |
|---|---|---|
| `outExpo` | cubic-bezier(0.16, 1, 0.3, 1) | headline word rise, underline draw, card arrive |
| `inQuint` | cubic-bezier(0.64, 0, 0.78, 0) | headline exit, element exits |
| `inOutCubic` | cubic-bezier(0.65, 0, 0.35, 1) | camera truck between stages |
| `inOutQuart` | cubic-bezier(0.76, 0, 0.24, 1) | big camera reveal |
| `outQuint` | cubic-bezier(0.22, 1, 0.36, 1) | 3D objects settling, chips landing |
| `outBack(1.4)` | overshoot 1.4 | ONLY dot growth / tiny pops (≤ 15 px objects) |
| `linear` | — | typing, streaming, counters, spins |

No springy wobble on text or cards. Overshoot only on tiny dots.

### 7.2 Step handoff (exact, from 15 fps strips at t=11.5–12.5)
Relative to `T` = moment the camera truck starts:
1. `T-0.20` description fades 1→0 (0.15 s, linear) — first thing to go; counter fades with it.
2. `T-0.05` headline words exit UP through their mask: y 0 → -110%, 0.22 s `inQuint`, word stagger 0.04 s.
   Eyebrow + underline fade 1→0 over 0.15 s.
3. `T` camera truck starts (0.6 s `inOutCubic`).
4. `T+0.25` new eyebrow fades in 0→1 (0.2 s).
5. `T+0.30` new headline words rise from below: y +110% → 0, **0.45 s `outExpo`, stagger 0.07 s/word**.
6. `T+0.45` underline draws scaleX 0→1 from left (0.35 s `outExpo`).
7. `T+0.52` description fades in 0→1 with y +8 px → 0 (0.3 s `outQuint`).
8. `T+0.60` world label (e.g. "TEXT ENCODER") fades in; the stage's first animation begins.
9. `T+1.0…1.4` counter block appears (§4.3). Progress rail active stop updates at `T+0.3`.
Total handoff ≈ 0.8 s from first fade-out to readable new title. Nothing ever cross-dissolves full-frame.

### 7.3 Other recurring motions
- **Typing (prompt console):** constant 27 chars/s (≈ 1 char every 2.2 frames @60), cursor solid while
  typing, blinking 0.5 s period after. Card arrives first: 0.5 s `outQuint`, from scale 0.96 + x +40 px.
- **Streaming text (LLM output):** word-by-word at 12–14 words/s; the newest word is `--orange`, it
  turns white the moment the next word lands. Counter "5 → N words" increments in lockstep.
- **Counters:** integer swaps tied to the visual source; denoise step counter ~5 steps/s.
- **Token flow:** chips enter from left in a diagonal queue (each 0.12 s apart), travel along a line
  through the glass stack in 0.9 s `outQuint`; when a chip passes a sheet the sheet goes hot (§5.3).
  After the last sheet each chip dissolves into a row of 8 tiny squares (embedding vector) on the right.
- **Hero/pixelation transition:** image → pixel grid (block size grows 1→48 px over 0.3 s) → blocks
  detach and scatter as voxels toward the camera while fading (0.35 s), revealing the dark room.
- **Outro:** final title words rise (same as headline), image push-in 3%, rail fades at -0.8 s,
  then everything fades to `#000` over the last 0.5 s (fade is linear on opacity of a black overlay).

### 7.4 Pacing (reference)
| Ref time | Beat | Duration |
|---|---|---|
| 0.0–1.5 | Hero photo + "This started as 5 words." → pixelate | 1.5 s |
| 1.5–2.5 | "5 words in. / A video out." (hero 2-line) | 1.0 s |
| 2.5–5.0 | Crane up → overview "Here's everything in between." → whip to end | 2.5 s |
| 5.4–7.4 | "How text becomes video" + typing console | 2.0 s |
| 7.8–11.7 | STEP 01 Prompt expansion | 3.9 s |
| 12.2–15.4 | STEP 02 Text encoding | 3.2 s |
| 15.8–22.2 | STEP 03 Denoising | 6.4 s |
| 22.8–25.3 | STEP 04 Decoding | 2.5 s |
| 25.6–29.5 | Final "Text → video." | 3.9 s |
| 29.4–30.0 | Fade out | 0.6 s |

Holds are 2.5–4 s per idea; transitions are fixed-length (≈ 0.6–0.8 s) and are NOT scaled down with
total duration. For a 15 s piece: keep transitions at full length, shorten holds (min 1.6 s readable
hold for a step headline + one counter).

## 8. Adapting to BEOL AX (15.000 s, 60 fps) — recommended mapping

Rail stops (5, mono caps): **SLIDES · PARSE · LABEL · REVIEW · LEARN**
(alternative last stop: EMBED). Final title: **"Slides → knowledge."** with "knowledge." orange.

| t (s) | Beat | Visual (ref analogue) | Counter |
|---|---|---|---|
| 0.00–1.60 | Eyebrow "■ BEOL AX, EXPLAINED" + hero 2-line "Engineers' slides in. / Searchable **knowledge** out." | stack of slide cards on floor, orange packet on arc (hero shot) | — |
| 1.60–2.60 | Crane-up overview "Here's the whole pipeline." | 5 plinths + arcs + packet (§5.5) | — |
| 2.60–4.80 | STEP 01 Parsing — "A slide deck is split into clean text chunks." | glass sheets slicing a slide into chips (§5.3/4.5) | `1 deck → 24 chunks` |
| 4.80–7.40 | STEP 02 Labeling — "An LLM tags each chunk, then checks its own answer." | LLM orb + content card streaming `module · lot_id · decision · open_risk · tem_ref` with O/X marks | `5 labels · 24 checked` |
| 7.40–9.80 | STEP 03 Review — "Only flagged chunks go to a human." | chip queue; most pass white, a few orange flagged chips lift out | `24 → 3 flagged` |
| 9.80–12.20 | STEP 04 Learning — "Engineer answers become labeling rules. It gets smarter every run." | voxel cloud resolving into an ordered block (rules), or Q/A cards | `run 3: 3 → 0 flagged` |
| 12.20–14.40 | Final "Slides → knowledge." | vector graph / ordered voxel block, push-in, rail all orange | — |
| 14.40–15.00 | Fade to black | — | — |

All examples are synthetic; never show real file names, lot IDs or engineer names.

## 9. Do / Don't checklist (reject a frame if any "Don't" is visible)

Do
- One orange accent cluster per frame; everything else charcoal/white/gray.
- Left-aligned title block at x=120 for steps; centered titles only for overview and finale.
- Mask-rise every headline; draw every underline; fade (never slide) descriptions.
- Keep UI chrome (title, counter, rail) locked while the 3D world moves.
- Bloom only on emissive 3D; generous halo on the orb and packets.

Don't
- No gradients on text, no text shadows/glows on DOM text, no outlines on headlines.
- No more than 2 font families (Display/Text sans + Cascadia Mono).
- No icons/emoji, no rounded "pill" buttons, no drop-shadowed DOM labels floating in 3D.
- No elements touching the 120 px margins, nothing below y=1040 except rail labels.
- No uniform scale-in pops on cards; no bouncy easing on anything larger than 15 px.
- No full-frame crossfades between steps; transitions are camera moves + masked text.
- No Hangul anywhere.
