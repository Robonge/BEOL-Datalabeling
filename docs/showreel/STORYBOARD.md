# STORYBOARD.md: BEOL AX showreel, 15.000 s (rev 2)

1920x1080, 60 fps, 120 BPM (beat = 0.5 s, bar = 2.0 s, 7.5 bars). This board is written in the grammar
of the reference "Text-to-video, explained" and is binding for the build.

**Precedence.** The overrides listed in section 0 win over everything. Outside them, **STYLE.md** wins on
every look, typography and easing value, and **COPY.md** wins on every word. COPY.md carries no timing;
all timing lives here. If this board contradicts STYLE.md anywhere that section 0 does not list, fix the
board and do not improvise.

Restart note: two drafts were rejected for design quality. Nothing from the code of either carries over.
Every key frame below must hold up against its paired reference frame (section 10) before work moves on
to the next scene. Rev 2 applies two reviews: bigger 3D set pieces in the reference idiom (a chip queue
through glass for VERIFY, a ~1,300-cube voxel volume for VAULT, a concrete payoff image for the close), a
full-bleed hook, one hero action per step, and an MSAA render path.

---

## 0. Decisions, deviations and overrides (read first)

| # | Decision | Why |
|---|---|---|
| D1 | **Hook layout = ref_t00.30**: full-bleed hero image, eyebrow and a 108 px one-line headline at the bottom left (cap-top 843), over a scrim. STYLE §3's 116 px two-line "hero headline" (cap-top 288) is **not used** in this film. The headline is on screen at frame 0 (words already 88% risen) and settles by 0.45 s. It exits at 2.45 s. | One source of truth for the hook. The cold open still has motion from frame 0. |
| D2 | The overview carries the reference's section card: centered eyebrow "■ THE WHOLE PIPELINE" plus the centered headline **"Everything in between."** (58 px, cap-top 162), and mono floor labels. The hook headline hands off first: it drops back into its masks on the 1.50 shatter beat (gone by 1.76), the overview words rise at 1.75. | One headline reads at a time (approval checkpoint 2026-10-07). |
| D3 | The COPY beat "One slide in. Knowledge out." is **cut**. Its idea lives in the final title "Slide → knowledge." | Time goes to the close hold instead. |
| D4 | The rail is **hidden until STEP 01** (fade-in 2.60 → 3.00 s, during the whip) and stays up to 15.00. | Matches the reference (no rail in its hook or overview). |
| D5 | Only STEP 01 and STEP 03 carry a content card. VERIFY is a **chip queue through glass sheets** (ref STEP 02). VAULT is a **voxel volume resolving into a block** (ref STEP 03). | In the reference only the expansion step has a card; the other steps are object-only set pieces. |
| D6 | Cut: the "CODE-ENGR-BOT · watching" tag, the underline under "knowledge.", the fade to black. The film ends on a held end card that carries the **BEOL AX** slate and the credit "Motion design — Claude" under the slide (7.7). | Fewer elements. The last frame must read as a still and sign the film. |
| D7 | Type values come from STYLE §3, not COPY's old typography notes. | STYLE was measured from the reference. |
| D8 | Steps are exactly **2.5 s**. Truck starts: **T1 = 2.50** (the whip), **T2 = 5.00, T3 = 7.50, T4 = 10.00**, close **T5 = 12.50**. Every step's headline words rise at **T + 0.25**, which falls on a beat (2.75 is an 8th; 5.25, 7.75, 10.25 are 8ths; the whoosh peaks there). The overview drift is cut (the old 2.45 → 3.00 hold); those 0.5 s go to the close hold. | Each headline gets ≥ 1.65 s settled, each description ≥ 1.50 s, the final title 1.70 s (section 9). |
| D9 | **Descriptions are shortened** (COPY deviation, already written into COPY.md): 01 "An LLM labels the slide." (24 chars), 02 "Doubts go to an engineer." (25), 03 "Answers become rules." (21), 04 "Chunks become searchable." (25). Audit minimum for a description is now chars / 17 s. | The old 45–53 character lines needed about 3 s each. |
| D10 | **One hero action and at most one counter change per step.** LABEL: fragments into the orb, then 5 rows stream (counter value static, label GENERATING-style swap only). VERIFY: the chip queue (static counter). LEARN: Q out, A back, one RULE line plus a ring birth; **no counter**, no divider. VAULT: the resolve only (no packet hops). | The reference's polish comes from unhurried holds. |
| D11 | The lot ID is **`RDM8EA.62` everywhere** (slide, LABELS card, chips, vault label). `WF#9` appears only on the slide. | The one example must stay the same object through the pipeline. |
| D12 | **Look overrides of STYLE.md** (STYLE has been patched to match): floor grid minor **10%**, major **16%**, seam **22%** white, wall grid **9%**; orb shell `IcosahedronGeometry(r, 2)` plus vertex glints; ground ring **r 2.0, tube 0.04**; arcs **tube 0.06, ×3** with a comet trail; the composer renders with **4x MSAA** (section 5). | The first review measured the reference grid, rings and arcs as brighter and thicker than STYLE had them, and aliasing is the biggest amateur tell. |
| D13 | **Final payoff = the hook slide, reassembled** from the vault voxels and decoded back to a crisp image (about 960 x 540 px) with five label chips attached by short leaders. The knowledge graph is cut as a finale. | It calls back to the hook the way the reference returns to the corgi, and it gives the end card a concrete, dense center. |
| D14 | The hero slide is redesigned **SEM-first**: a full-bleed dark micrograph with a light text callout at the top right. A white-paper slide would put a white 108 px headline on near-white paper. | The headline must sit on a dark area of the image, as in ref_t00.30. |
| D15 | Content cards stay **DOM with a per-frame homography** (not CanvasTexture). Determinism: a matrix3d layer re-rasterizes depending on frame history, so the card frame is an SVG path through the exact homography and each text row carries its own 2D affine fitted to its band (ui.js `Card`), which keeps the ~2% right-edge taper and byte-identical frames. `tools/render.py` captures the full composited page (`Page.captureScreenshot`) for every subframe and averages them, so DOM and WebGL get identical motion blur. This is **verified at t = 5.30** with `--subframes 4 --shutter 0.5` before VERIFY is built. If the card and orb blur differ, switch the card to a CanvasTexture plane. | Crisper text. The blur consistency is checked, not assumed. |

---

## 1. Beat map (120 BPM)

Downbeats fall at 0, 2, 4, 6, 8, 10, 12 and 14 s. Notation: bar.beat, and "+" for the off-8th. With
2.5 s steps the trucks start on alternating strong and weak beats (2.50 = 2.2, 5.00 = 3.3, 7.50 = 4.4,
10.00 = 6.1, 12.50 = 7.2), and every step's words rise half a beat later. **Bold** rows are visual hits.

| t (s) | Beat | Visual event | Sound cue (later music pass) |
|---|---|---|---|
| **0.00** | 1.1 | Cold open: full-bleed slide, hook headline settling | pad in, soft kick |
| 0.50 | 1.2 | Parser sweep reaches callout row 1 (row flash) | tick |
| 0.75 | 1.2+ | Row 2 flash | tick |
| **1.00** | 1.3 | Row 3 flash; pixelate and camera pull-back start | riser |
| **1.50** | 1.4 | **Shatter**: voxels burst toward the lens; crane-up starts; packet launches from SLIDE | impact + whoosh |
| 1.75 | 1.4+ | Packet lands on LABEL (ring flare) | pluck |
| 2.00 | 2.1 | Lands on VERIFY | pluck |
| 2.25 | 2.1+ | Lands on LEARN | pluck |
| **2.50** | 2.2 | Lands on VAULT; **whip** starts (T1) | whoosh |
| **2.75** | 2.2+ | **Cut**; STEP 01 words rise | whoosh tail |
| **3.50** | 2.4 | Label tokens start streaming (0.12 s per token) | ticks per token |
| **4.50** | 3.2 | tem_ref row pulse | accent |
| **5.00** | 3.3 | Truck to STEP 02 (T2) | whoosh |
| 5.40 | — | Chip queue starts moving through the glass | low hum |
| **6.43** | — | First flagged chip leaves the glass and peels off | swell |
| **7.50** | 4.4 | Truck to STEP 03 (T3) | whoosh |
| **8.00** | 5.1 | Q chip launches | blip |
| **8.50** | 5.2 | A chip returns | blip (lower) |
| **9.00** | 5.3 | RULE: a new ring is born | chime |
| **10.00** | 6.1 | Truck to STEP 04 (T4) | whoosh |
| **10.50** | 6.2 | Voxel resolve starts (to 11.70) | granular |
| 11.45 | — | Hero cubes and orange links light up | pluck |
| **12.50** | 7.2 | Close (T5): the block flies apart into the slide | whoosh, soft |
| 12.75 | 7.2+ | Final title rises | — |
| **13.00** | 7.3 | Slide decodes crisp; rail turns orange | final chord |
| 13.50 | 7.4 | End card complete | chord rings |
| 14.00 | 8.1 | Hold, nothing new | — |
| 15.00 | — | End | — |

---

## 2. Master timeline

Scene modules overlap during handoffs. "Active" is when a module's `update()` must run; outside that
window its objects are hidden.

| Scene file | id | Active (s) | On-screen beat | Rail stop | Headline (settled) |
|---|---|---|---|---|---|
| `scenes/01_hook.js` | hook | 0.00 – 1.90 | Full-bleed slide; parser sweep; pull-back; pixelate; shatter | hidden | "This started as one slide." 0.45 – 2.45 |
| `scenes/02_overview.js` | overview | 1.40 – 2.80 | Crane-up, 5 plinths, packet run, whip | hidden (fades in 2.60) | (hook headline still up) |
| `scenes/03_label.js` | label | 2.70 – 5.65 | LLM orb + LABELS card | LABEL | "Context labeling" 3.25 – 4.95 |
| `scenes/04_verify.js` | verify | 4.95 – 8.15 | Chip queue through 4 glass sheets; engineer review panel | VERIFY | "Self-check" 5.70 – 7.45 |
| `scenes/05_learn.js` | learn | 7.45 – 10.65 | Q/A loop ring + DOMAIN-ENGR-BOT card | LEARN | "Agents ask engineers" 8.30 – 9.95 |
| `scenes/06_vault.js` | vault | 9.95 – 15.00 | 1,296-cube voxel volume resolving into a block; later re-laid out as the slide | VAULT | "Knowledge Vault" 10.75 – 12.45 |
| `scenes/07_close.js` | close | 12.25 – 15.00 | Decoded slide, five label chips, final title, caption, all-orange rail | all orange | "Slide → knowledge." 13.30 – 15.00 |

Global and shared: the rail, counter, room, dust and camera live in engine.js / ui.js, and the camera follows
ONE keyed track (section 4). The slide face texture is built once in engine.js
(`ctx.assets.slideCanvas`, 2560x1440, plus a 48x27 array of cell-average colors `ctx.assets.slideCells`)
and reused by 01_hook, 02_overview, 06_vault and 07_close.

---

## 3. World layout (world units, Y up, floor y = 0)

- Room: an infinite floor grid and one back wall at **z = -5.5** along the whole X track. Faint side walls at
  x = -30 and x = +95. Wall grid cells are 2 units, floor cells 1 unit, with a major line every 4 cells.
- **Hook slide**: a slab of 3.56 x 2.00 x 0.035, centered at **P_s = (-7.0, 1.30, 4.0)**, face toward +z.
  Its bottom edge is 0.30 above the floor.
- **Overview map**: 5 plinths of 3.0 x 0.12 x 2.2, centered at z = 0 and x = **-9.2, -4.6, 0.0, 4.6, 9.2**
  (SLIDE, LABEL, VERIFY, LEARN, VAULT).
- **Step stages** along +X with a 10.4-unit pitch: **S1 = 40.0** (LABEL), **S2 = 50.4** (VERIFY),
  **S3 = 60.8** (LEARN), **S4 = 71.2** (VAULT). The whip hides the jump from the map to the stages with a
  cut at peak velocity.
- Step framing: camera at (S, 3.55, 11.0) looking at (S, 1.65, 0), FOV 32°. That gives a 9.8° tilt,
  ≈ **169 px per world unit** on the z = 0 plane, and the floor/wall seam at y ≈ 617.
- Close framing: camera at (S4, 2.05, 10.6) looking at (S4, 1.85, 0), ≈ **178 px per unit** on z = 0. The
  floor/wall seam lands at y ≈ 748 (the reference final has it at ≈ 735) and is hidden behind the slide.

---

## 4. Camera track (engine.js `cameraAt(t)`, a pure function of t)

PerspectiveCamera, vertical FOV 32°, near 0.1, far 200, never any roll. Position and target are
interpolated with the named ease inside each segment.

| # | t0 → t1 | Ease | Position | Target | Notes |
|---|---|---|---|---|---|
| C0 | 0.00 → 1.00 | outSine | (-7.00, 1.30, 7.294) → (-7.00, 1.30, 7.195) | P_s | **Full bleed**: the slab fills 106% of the frame (2035 px wide) and is square to the lens. A 3% push-in. |
| C1 | 1.00 → 1.50 | inOutCubic | → A' (-7.84, 1.78, 8.75) | P_s | **Pull-back reveal** during the pixelate: the slab shrinks to ≈ 1380 px (72%), yaws ≈ 10° (right edge recedes), and its bottom edge (y ≈ 928) and floor decal come into view. |
| C2 | 1.50 → 2.45 | inOutQuart | A' → B (0.00, 10.20, 24.00) | P_s → (0.00, -1.00, 0.00) | Crane-up and pull-back to the 25° overview. The row centerline lands at y ≈ 455. |
| — | 2.45 → 2.50 | hold | B | — | — |
| C3 | 2.50 → 2.75 | inCubic | B → (14.0, 10.20, 24.00) | (14.0, -1.0, 0) | **Whip** truck +X (14 units). |
| — | **2.75** | CUT | — | — | Hard cut at peak velocity. Render with `--subframes 4 --shutter 0.5`. |
| C4 | 2.75 → 3.20 | outCubic | (S1-3.6, 3.62, 11.0) → (S1, 3.55, 11.0) | (S1-3.6, 1.65, 0) → (S1, 1.65, 0) | Continues the +X motion and decelerates into the LABEL framing. |
| C5 | 3.20 → 5.00 | linear | z 11.0 → 10.78 | (S1, 1.65, 0) | 2% push-in. |
| C6 | 5.00 → 5.60 | inOutCubic | → (S2, 3.55, 11.0) | → (S2, 1.65, 0) | Truck, plus a crane bump of +0.06·sin(πu) in y. |
| C7 | 5.60 → 7.50 | linear | orbit +1.2°/s about (S2-0.3, 1.5, 0) | (S2-0.3, 1.5, 0) | 2.3° in total; parallax through the glass. |
| C8 | 7.50 → 8.10 | inOutCubic | → (S3, 3.55, 11.0) | → (S3, 1.65, 0) | Truck plus bump. |
| C9 | 8.10 → 10.00 | linear | z 11.0 → 10.78 | (S3, 1.65, 0) | 2% push-in. |
| C10 | 10.00 → 10.60 | inOutCubic | → (S4, 3.55, 11.0) | → (S4, 1.65, 0) | Truck plus bump. |
| C11 | 10.60 → 12.50 | linear | orbit +1.0°/s about (S4+0.55, 1.50, 0) | (S4+0.55, 1.50, 0) blended from (S4, 1.65, 0) over 0.3 s | 1.9° in total; parallax on the voxels. |
| C12 | 12.50 → 13.20 | inOutCubic | → C (S4, 2.05, 10.60) | → (S4, 1.85, 0) | Drops to near eye level for the end card. |
| C13 | 13.20 → 15.00 | outSine | C → 3% toward the target | (S4, 1.85, 0) | Final push-in, as the reference finale does. |

---

## 5. Global layers and render path (present in every scene)

- **Render path (engine.js).** `WebGLRenderer({ antialias: true, preserveDrawingBuffer: true })`, pixel
  ratio 1. The composer is built on
  `new WebGLRenderTarget(1920, 1080, { samples: 4, type: HalfFloatType })`, with RenderPass →
  UnrealBloomPass → OutputPass. Without `samples`, the composer silently drops MSAA, and every hairline in
  this film aliases and crawls at 60 fps.
  - Gate: a 200% crop of the floor at t = 2.40 and at t = 6.50 must show no stair-stepping or moiré.
  - Fallback if it fails: supersample with `render.py --dsf 2` and downscale on encode. Check that
    render.py supports it before relying on it.
- **Background**: a screen-space vignette quad. Center `#31343B` at (50%, 45%), `#27282D` at 70%, corners
  `#232429`, mostly horizontal (STYLE §2).
- **Grid** (D12): a shader plane with `fwidth`-antialiased 1 px lines, not LineSegments.
  - Floor: minor 10%, major 16% and seam 22% white. Back wall: 9%.
  - Alpha fades with camera distance inside the shader (100% at ≤ 25 units, 0% at 60) so grazing angles do
    not moiré.
  - Gate: the mean luminance of an empty floor patch at t = 2.40 must be within ±3 levels of the same
    patch in ref_t03.80, and at t = 6.50 within ±3 levels of ref_t13.60.
- **Dust**: 80 seeded motes (white 15–35%, 1.5–3 px) and 8 square specks (4–6 px, 20%), drifting ≤ 6 px/s
  as f(t).
- **Lights**: hemisphere (`#C9CCD6` / `#1A1B1F`, 0.55), key from (-0.5, 1.0, 0.6) `#FFF4EA` 1.4, rim
  `#FF8A50` 0.35 from behind-right. ACES tone mapping, exposure 1.0.
- **Bloom**: strength 0.9, radius 0.75, threshold 0.82. Only emissive materials exceed the threshold. When
  a halo is weak, raise the source intensity, never the bloom strength.
- **Rail** (ui.js): stops SLIDE · LABEL · VERIFY · LEARN · VAULT at x = 200 / 579 / 960 / 1340 / 1719,
  centerline y = 974, label cap-top y = 1004.
  - Fade-in 2.60 → 3.00 (linear). On arrival SLIDE is passed (white) and the fill already covers 200 → 579.
  - Active stop k at step start T: the dot grows 11 → 15 px, outBack(1.4), at T + 0.30 (0.25 s). The ring
    (30 px, 1.5 px, orange 35%) and glow fade in over 0.3 s. The previous dot snaps to white; the label
    color crossfades over 0.2 s.
  - Fill during step k: `fillX = lerp(stop[k], stop[k+1], 0.88·p)` with
    `p = clamp((t - (T+0.30)) / 2.20)`. From T_next to T_next + 0.30 the last 12% completes (outQuint).
    VAULT has no next stop, so its fill is complete at T4 + 0.30.
  - Finale 13.00 → 13.40: every dot and label turns `#FF6A1A`, left to right, 0.05 s stagger, 0.2 s each.
    The VAULT ring fades out. The rail stays up to 15.00.
- **Counter** (ui.js): label Cascadia Mono 700 16 px +0.30em orange, right-aligned x = 1800, cap-top 855.
  Value Display 600 42 px tabular -0.01em white, right-aligned x = 1800, cap-top 887.
  - Enters at **T + 0.80** (0 → 1 over 0.3 s, brightness held at 45% for the first 0.2 s).
  - Exits at T_next − 0.20 (0.15 s). Values change only by instant swaps.
  - Per step: LABEL static value, label swap at stream end. VERIFY static. LEARN **none**. VAULT the
    two-column variant B (section 7.6).
- **Step title block** (ui.js): positions per STYLE §3. Relative schedule for all four steps:

| Event | Offset from T | Duration / ease |
|---|---|---|
| Description and counter fade out | T_next − 0.20 | 0.15 s linear |
| Headline words exit up (0 → −110%) | T_next − 0.05 | 0.22 s inQuint, 0.04 s stagger |
| Eyebrow and underline fade out | T_next − 0.05 | 0.15 s |
| New eyebrow in | T + 0.20 | 0.20 s |
| New words rise (+110% → 0) | **T + 0.25** (on the beat) | 0.45 s outExpo, **0.05 s** stagger |
| Underline draws (scaleX 0 → 1) | T + 0.50 | 0.35 s outExpo |
| Description in (y +8 → 0) | T + 0.50 | 0.30 s outQuint |
| World labels in (40% → 100%) | T + 0.75 | 0.30 s outQuint |
| Counter in | T + 0.80 | see Counter |

Absolute times:

| Step | T | Eyebrow | Words | Underline / desc | World label | Counter | Desc out | Headline out |
|---|---|---|---|---|---|---|---|---|
| 01 LABEL | 2.50 | 2.70 | 2.75 | 3.00 | 3.25 | 3.30 | 4.80 | 4.95 |
| 02 VERIFY | 5.00 | 5.20 | 5.25 | 5.50 | 5.75 | 5.80 | 7.30 | 7.45 |
| 03 LEARN | 7.50 | 7.70 | 7.75 | 8.00 | 8.00 (early, with the Q chip) | none | 9.80 | 9.95 |
| 04 VAULT | 10.00 | 10.20 | 10.25 | 10.50 | 10.75 | 10.80 | 12.30 | 12.45 |

---

## 6. Shared materials (define once in engine.js)

| Name | Definition |
|---|---|
| `M.plinth` | MeshStandard: top `#2A2B30`, sides `#202126`, roughness 0.9. 1 px orange (`#FF6A1A`, 0.9) lines on the two front-bottom edges; 1 px white 20% on the top edges. |
| `M.decal` | Floor plane with a radial black alpha texture (25% at center → 0), 1.2x the footprint, depthWrite off. The contact shadow under every object. |
| `M.arc` | TubeGeometry half-ellipse, **tube r 0.06**, MeshBasic `#FF6A1A` **× 3.0** (bloom), alpha tapered to 0 over the last 12% at each end. |
| `M.ring` | Flat torus **r 2.0, tube 0.04** (it encircles the 3.0 x 2.2 plinth), MeshBasic `#FF8A3A`, additive. States are driven by `ringLevel(t)` (section 7.2). |
| `M.packet` | Sphere r 0.12, MeshBasic `#FFF35A` × 4, plus a 40 px `#FF6A1A` glow sprite (additive). **Comet trail**: 10 sprites sampled at the packet's path position at t − 0.02k (k = 1…10), size × 0.9^k, alpha 0.55 × 0.78^k. |
| `M.orbCore` | Sphere with a radial shader `#FFF35A` → `#FFC12E`, × 3, toneMapped false. |
| `M.orbWire` | WireframeGeometry(`IcosahedronGeometry(r, 2)`, 180 faces) as LineSegments, `#E8893A` at **0.55**, additive. A second shell r·0.975 at detail 2, rotated 18°, at 30%. **Vertex glints**: `Points` on the main shell's unique vertices, 1.5 px white at 40%, additive. Gate: against a crop of ref_t10.00, the horizontal diameter must cross 9–11 wire edges. Raise to detail 3 (320 faces) only if it reads coarser than the reference. (three.js r186 has 20·(d+1)² faces, so detail 3 is 320 faces, not 1,280.) |
| `M.atmos` | Additive radial sprite, `#FF6A1A` 55% → 0. |
| `M.orbiter` | Sphere r 0.05, MeshBasic white × 2.5 (blooms to about 14 px). |
| `M.glass` | Face: MeshBasic white, opacity 0.09, depthWrite off, double-sided. Edges: EdgesGeometry 1 px white 45%. **Hot**: face `#F0A080` at 22%, edges `#FF7A40` at 70%; lerp in 0.15 s, decay 0.4 s. `hot(t)` is computed from the chip positions, never stored state. |
| `M.voxel` | InstancedMesh BoxGeometry, MeshStandard roughness 0.85, metalness 0, per-instance color. The lights give the three-tone read: top +15%, front base, side −20%. Gate: sample a resolved cube at t = 12.05 against ref_t21.00. |
| `M.chip` | Token chip, a CanvasTexture plane rendered at 2x. Radius 12 px, fill `#26272C`, 3 px border, Cascadia Mono. Text: the key in `#BFC2C9` at 70% (20 px), two spaces, the value in white (28 px). Height 0.30 units (≈ 51 px on screen); width fits the text plus 20 px padding each side. Border states: **queue** `#E5682F`; **pass** white 45% plus a "PASS" badge (Mono 700 14 px, white 70%) at the right end; **flag** `#E5682F` with emissive × 1.6 (bloom) plus a "FLAG" badge in `#FF6A1A`; **neutral** (finale) white 30%. Chips always billboard on yaw only. |
| `M.edge` | Hero links: thin tubes r 0.015, `#FF8A3A` × 3, additive, bloomed. |

---

## 7. Scenes

### 7.1 `01_hook`: "This started as one slide." (0.00 – 1.90)

**Intent:** the reference's full-bleed hero photo. Our "photo" is the engineer's slide, and its largest
element is a dark SEM micrograph, so the white headline sits on dark image as in ref_t00.30. Calm, rich,
one orange accent.

**Camera:** C0 (full bleed, 3% push-in), C1 (pull-back reveal during the pixelate), then C2 starts the crane.

**3D objects**
- **Hero slide slab** at P_s, 3.56 x 2.00 x 0.035, face toward the camera. The face is the shared
  2560x1440 CanvasTexture on MeshBasic, toneMapped false, with no face value above `#DCDDE2` (below the bloom
  threshold). Edges are 1 px white 45%, with a decal under the slab. At C0 the face maps to the screen at
  0.795 screen px per slide px, centered. All coordinates below are slide px.
  - **SEM micrograph, full bleed** (the "photo"): the whole face below the title band.
    - Field: a dark `#2E3036` → `#3A3C42` field with a soft vertical charging gradient.
    - 10 vertical metal lines: bright `#B8BAC0`, 120 px wide, soft 6 px edges, seeded 1–3 px edge
      roughness, grain at ±4 levels.
    - One **defect**: a bright bridge between lines 3 and 4 at about (700, 900), circled by a 3 px
      `#FF6A1A` annotation ellipse (150 x 95) with the Cascadia Mono 700 26 px orange label
      "open/short". **This is the slide's one orange accent.**
    - Mono 24 px `#BFC2C9` label "SEM TOP VIEW · 50 nm" at (223, 250).
  - **Title band**, y 0–190: `#1E1F23` at 88% over the image. Title "M1 SAUP spacer TiO2 → TiN" in
    Segoe UI Variable Display 600, 80 px, white, at x = 223 (screen x 120 once projected, aligned with the
    headline). At the right end: "ENGINEER SLIDE · SYNTHETIC" in Cascadia Mono 700 22 px +0.22em `#BFC2C9`,
    ending at x = 2337.
  - **Callout box** (light paper, top right): x 1560–2337, y 260–660, `#DCDDE2`, radius 10. Three rows in
    Cascadia Mono 500 44 px `#2A2B30`, pitch 110 px from y = 330: `RDM8EA.62   WF#9`,
    `CMBSRP open/short 100%`, `TDDB: still to check`.
  - **Ghost tag** under the callout at x 1560, y 700–770: a dashed 2 px white 40% outline, radius 10, with
    Cascadia Mono 500 32 px "TEM → messenger only" at white 45%. It is the missing link that STEP 01's
    tem_ref row and the finale's tem_ref chip resolve.
  - The lower-left 45% x 35% of the face holds only micrograph. The headline goes there.
- **Parser sweep, 0.50 → 1.00**: a 4 px soft horizontal orange line (`#FF6A1A` at 35%) travels down the
  callout box. Each row flashes as it passes: row background `#FF6A1A` at 14% plus a 6 px orange left bar,
  at **0.50 / 0.75 / 1.00**, each decaying over 0.25 s (outQuint). One pass, never repeated.
- **Pixelate, 1.00 → 1.50** (easeInQuad): the face shader quantizes UV from full resolution to **exactly
  the 48 x 27 cell grid** (block count interpolated in log space). Block colors are box-filtered (the
  precomputed `slideCells` at the end state), never point-sampled. The last pixelated frame is identical
  to the voxel wall that replaces it.
- **Shatter, 1.50 → 1.85**: the slab is swapped for a **48 x 27 InstancedMesh (1,296 cubes, `M.voxel`)**,
  cell 0.0742, cube 0.9 of the cell, each colored from `slideCells`. The palette matches the reference's
  noise voxels: dark and light grays from the micrograph, light paper from the callout, orange from the
  annotation.
  - Per voxel (seeded): delay 0–0.08 s.
  - Velocity toward the camera (+2 … +5 units of depth) and radially out from the slide center (0.5–1.8),
    with a slight lift. Rotation up to 1.5 rad on a random axis.
  - Scale 1 → 0.6. Opacity 1 → 0 with inQuad over 0.35 s. Motion outQuint.
  - The near voxels pass the lens while C2 cranes up, so the burst fills the frame as in ref_t02.50.

**Overlay (DOM)**
| Element | Spec | Position | Timing |
|---|---|---|---|
| Scrim | linear gradient, `#1E1F23` α 0 at y = 702 → α 0.70 at y = 1080, plus a left-weighted radial (α 0.25 at x = 120, 0 at x = 1200) | full frame, under the text | on at 0.00; fades out 1.20 → 1.60 |
| Hero eyebrow | "■ BEOL AX, EXPLAINED", Cascadia Mono 700 17 px +0.28em `#FF6A1A` | 12x12 square at x = 120, y = 792; text x = 146, cap-top 792 | on at 0.00; fades 1.45 → 1.58 |
| Hook headline | "This started as **one slide.**", Display 600, 108 px (cap 81), -0.025em; white, "one slide." `#FF6A1A` | x = 120, cap-top 843, baseline 924 (≈ 1490 px wide) | 5 spans in masks; at t = 0 each word is at +12% and settles by 0.45 (outQuint, 0.03 s stagger); exits **down** into the masks at 1.50 (0.18 s inQuint, 0.02 s stagger, gone 1.76); scrim fades 1.55 → 1.85 |

No rail, no counter. Legibility check at t = 0.60: the luminance behind the headline's cap band (y 843–924,
x 120–1610) must have a p90 ≤ `#5A5C62`.

**Key times:** **0.60** (full bleed, headline settled, row 1 flash decaying; compare to `ref_t00.30`), **1.30**
(mid-pull-back, half-pixelated, slab edge and decal visible) and **1.62** (shatter mid-burst, voxels at the
lens; compare to `ref_t02.50`).

**Reject if:** any slide edge is visible before 1.00 (it must be full bleed); the headline sits on light
paper; the SEM looks like a cartoon stripe pattern without grain and roughness; the pixelate looks like a
CSS blur; the voxel grid does not match the last pixelate frame; voxels pop off instead of flying through
depth.

### 7.2 `02_overview`: the pipeline flash (1.40 – 2.80)

**Intent:** the reference's "Here's everything in between." shot, its most luminous frame: blazing
ground rings, thick glowing arcs and a comet packet, all behind the locked hook headline.

**Camera:** C2 crane (1.50 → 2.45 inOutQuart), hold, C3 whip (2.50 → 2.75 inCubic), cut.

**3D objects** (the overview map, section 3)
- **5 plinths** (`M.plinth`) with decals. Mini heroes float 0.55 above each plinth top, each about 30% of
  its step's hero:
  - SLIDE: a 1.6 x 0.9 mini slide with the shared texture, tilted 12° back.
  - LABEL: a mini orb (core 0.22, wire 0.6, 4 orbiters).
  - VERIFY: 3 mini glass sheets with 4 mini chips in a diagonal.
  - LEARN: a mini loop ring (r 0.6) with one white orbiter.
  - VAULT: a mini voxel block, 9 x 4 x 3 cubes of 0.11.
- **Arcs** (`M.arc`, tube 0.06): 4 half-ellipses between consecutive plinth centers, peaking at y = 0.9.
  Emissive ramps 0 → full over 1.50 → 1.80.
- **Ground rings** (`M.ring`, r 2.0) under each plinth. `ringLevel` is 0 before the plinth's landing. On
  landing it flares to × 5 with scale 0.85 → 1.0 (0.3 s outQuint), settles to × 3.5 ("lit"), and holds
  until the next landing. It then decays to 30% over 0.6 s. So two rings read as blazing at most moments,
  as in ref_t03.80. The SLIDE ring flares at 1.50 with the launch.
- **Packet** (`M.packet` + comet trail): launches from SLIDE at **1.50** (the same beat as the shatter) and
  rides the arcs, 0.25 s per hop, inOutSine. It lands on LABEL **1.75**, VERIFY **2.00**, LEARN **2.25**
  and VAULT **2.50**. Each landing multiplies that plinth's mini hero emissive × 1.8, decaying over 0.3 s.
  The packet parks on VAULT.

**Overlay**
- The hook eyebrow and headline from 7.1 hand off on the 1.50 beat (mask-down, gone by 1.76).
- **Centered eyebrow** "■ THE WHOLE PIPELINE" (Cascadia Mono 700 17 px +0.28em orange, centered on
  x = 960, cap-top 114): in 1.62 → 1.80, out 2.50 → 2.62.
- **Centered headline** "Everything in between." (Display 700, 58 px, -0.02em, white, centered, cap-top 162):
  words rise 1.75 (0.45 s outExpo, 0.05 s stagger, settled ≈ 2.05), exit up on the whip beat 2.50
  (0.20 s inQuint, 0.03 s stagger, gone 2.76, before STEP 01 rises at 2.75 on the left).
- **Floor labels** (DOM, projected from 0.25 above each plinth's back edge), Cascadia Mono 700 17 px
  +0.28em: "SLIDE", "01  LABEL", "02  VERIFY", "03  LEARN", "04  VAULT". Numbers orange, words white. They
  fade in 1.55 → 1.75, staggered 0.03 left to right, and are masked while they cross the headline band
  (projected y < ~250 during the crane), so they appear under the headline at ≈ 2.0. They
  ride out with the whip and are hidden when off-frame.
- No rail until 2.60 (it fades in during the whip), no counter.

**Handoff to STEP 01:** whip 2.50, cut 2.75 (C3 → C4). STEP 01 text follows the section 5 schedule with
T = 2.50: its words rise at the cut.

**Key times:** **2.00** (mid-crane, VERIFY landing flare, comet in flight; compare to `ref_t02.50`) and
**2.40** (overview pose settled, LEARN ring blazing, LABEL/VERIFY decayed, packet mid-hop to VAULT with its
trail, eyebrow and hook headline up; compare to `ref_t03.80`).

**Reject if:** the rings sit inside the plinth footprint; fewer than two rings read as lit at 2.40; the
arcs read thinner than 6 px or unbloomed; the plinths lack the orange bottom edge lines; the row is not
level; any floor label collides with the hook headline; the floor grid at 200% zoom shows crawl or moiré.

### 7.3 `03_label`: STEP 01, LABEL (T1 = 2.50, active 2.70 – 5.65)

**Intent:** the reference's STEP 01: the LLM orb on the left, a streaming card on the right, a counter at the
bottom right. One hero action: slide fragments go into the orb, and five label rows stream out.

**Camera:** C4 (whip landing), C5 2% push-in, C6 truck out.

**3D objects** (stage S1 = 40.0)
- **LLM orb** at (S1-2.28, 1.44, 0), center projecting to about **(575, 575)**.
  - `M.orbCore` r 0.42 (≈ 72 px). `M.orbWire` shell r 1.18 (≈ 200 px) with the second shell and the
    vertex glints. `M.atmos` r 1.6.
  - 8 `M.orbiter`s on two rings: r 1.65 tilted 18° and r 1.90 tilted −26°, at 0.35 rad/s.
  - The shell rotates at 0.12 rad/s about (0.3, 1, 0.1). A decal sits on the floor.
  - Gate at 3.95: the halo is still `#9D4F33` or brighter at r ≈ 165 px from the core center.
- **Slide fragments → orb, 2.90 → 3.45**: 6 slide voxels (cubes of 0.22, colored from `slideCells`: 2 light
  callout, 3 micrograph grays, 1 annotation orange) enter from beyond the left frame edge. Each flies a
  shallow arc into the core, 0.30 s outQuint, staggered 0.05, shrinking 1 → 0.2. Each absorption raises the
  shell emissive × 1.6 (0.2 s decay).
- **Particle stream, 3.45 → 4.45**: 50 additive points (2–3 px, `#FF8A3A` → `#FFC12E`, lifetime 0.8 s)
  run from the shell toward the card's left edge on a slight upward arc. They pass behind the DOM card, so
  they appear to enter it.
- **LABELS card**: content card 864 x 438, radius 21, on a world plane centered at (S1+1.77, 1.41, 0.3)
  with yaw −4° (right edge about 2% taller). Screen bbox ≈ **x 826–1690, y 362–800**. DOM transformed by the
  plane's 4-corner homography every frame (D15). Styling per STYLE §4.4.

**Card content** (Cascadia Mono 500 25 px, line-height 44 px; padding 35 px left, 32 px top)
```
■ LABELS                                  (Mono 700 16px +0.22em #FF6A1A)

module     SAUP · TiN spacer
lot_id     RDM8EA.62
decision   pending
open_risk  TDDB
tem_ref    APM-…6524
```
Keys `#BFC2C9` at 70% in a fixed 11-character column, values white. The first row's top sits 28 px under the
label.

**Choreography**
| t | Event | Ease |
|---|---|---|
| 2.75 | Cut. The stage is already populated: orb spinning, card showing only its label | — |
| 2.90 – 3.45 | Fragments fly into the orb | outQuint |
| 3.25 | World label "LLM" (Mono 700 15 px +0.32em white) fades in under the orb at about (575, 880) | 0.3 s outQuint, from 40% |
| 3.30 | Counter in: label "LABELING", value **"1 slide → 5 labels"** (static; the value never changes) | section 5 |
| **3.50** | Tokens stream at **0.12 s each**. The newest token is `#FF6A1A` and turns white when the next lands. A row's key appears with its first token. `SAUP` 3.50, `·` 3.62, `TiN` 3.74, `spacer` 3.86, `RDM8EA.62` 3.98, `pending` 4.10, `TDDB` 4.22, `APM-…6524` 4.34 | step |
| 4.46 | The last token turns white; the counter label swaps to "DONE" (the only counter change) | instant |
| **4.50** | **tem_ref pulse**: a 2 px orange bar at the row's left, the row background `#FF6A1A` at 12%, the value orange; all three decay to rest by 4.90. It resolves the hook's ghost TEM tag | outQuint |
| 4.80 / 4.95 | Description and counter out / headline out | section 5 |
| 5.00 → 5.60 | Truck: the orb and card exit left in perspective | C6 |

**Overlay text:** eyebrow "■ STEP 01", headline "Context labeling" (2 spans), description "An LLM labels the
slide.", all at STYLE §3 step positions.

**Key times:** **2.85** (just after the cut: words mid-rise through masks, camera decelerating; compare to
`ref_t12.20`), **3.95** (streaming, "spacer" newest and orange; compare to `ref_t10.00`) and **4.60** (DONE,
tem_ref pulse decaying, rail fill at x ≈ 853; compare to `ref_t11.40`).

**Reject if:** the orb halo is weaker than the reference's; the wire reads low-poly or whites out under bloom;
the orbiters are flat dots without perspective size variation; the card does not follow the camera; any key or
value wraps; more than one thing animates in the card at once.

### 7.4 `04_verify`: STEP 02, VERIFY (T2 = 5.00, active 4.95 – 8.15)

**Intent:** ref_t13.60 in our terms. A diagonal queue of large, readable label chips steps through four
tall glass sheets. Chips that pass go on as embeddings. Doubtful chips are flagged and peel off to an
engineer's review list, where a human signs them off.

**Camera:** C6 truck in, then C7 slow orbit (+1.2°/s).

**3D objects** (stage S2 = 50.4; all screen numbers are at the C7 start pose)
- **Chip path**: a straight 3D line from Q0 = (S2−3.4, 0.55, 1.6) at the lower left (nearer the camera) to
  Q1 = (S2+1.6, 2.95, −1.0) at the upper right. The queue enters the frame at about (330, 840) and leaves
  the glass at about (1120, 330).
- **4 glass sheets** (`M.glass`), each 2.0 wide x 3.6 tall, standing on the floor, parallel to each other,
  spaced 0.55 along the path between path parameters u = 0.40 and 0.67. Each face normal is the path's
  horizontal direction, so a sheet projects about 150 px wide. Together they span **x ≈ 700–1090,
  y ≈ 225–860**.
  - Tinted faces read clearly: idle is 9% white; **hot** (a chip inside) is `#F0A080` at 22% with orange
    edges. Between 5.60 and 7.30 at least two sheets are hot at any moment.
- **World label "VERIFIER"** (Mono 700 24 px +0.32em white, 40% → 100% at 5.75), projected from 0.35
  above the tallest sheet, centered at about **(900, 172)**. It is the reference's "TEXT ENCODER"
  analogue.
- **12 chips** (`M.chip`, queue state), spaced 0.40 along the path, laid out at 5.00 so they truck in with
  the stage. In order from the head of the queue:

  | i | Chip text (key  value) | Outcome |
  |---|---|---|
  | 0 | `decision  pending` | FLAG |
  | 1 | `module  SAUP` | PASS |
  | 2 | `tem_ref  none` | FLAG |
  | 3 | `open_risk  TDDB` | FLAG |
  | 4 | `lot_id  RDM8EA.62` | PASS |
  | 5 | `module  TiN spacer` | PASS |
  | 6–11 | `decision  adopted`, `tem_ref  APM-…6524`, `open_risk  none`, `module  M1 Cu`, `decision  hold`, `open_risk  EM` | still queued when the step ends |

- **Conveyor**: the queue moves at 2.2 units/s from **5.40**, with a 0.15 s ease-in ramp. A chip crossing
  a sheet bobs +0.03 in y (0.12 s) and makes that sheet hot. The chips at i = 0…5 leave the last sheet at
  **6.43 + 0.18·i** (0: 6.43, 1: 6.61, 2: 6.79, 3: 6.97, 4: 7.15, 5: 7.33).
- **Leaving the glass** (state change over 0.15 s):
  - **PASS**: border → white 45%, "PASS" badge. The chip continues 0.3 along the path, then dissolves into
    a row of **8 tiny cubes** (0.07, three-tone grays, one salmon `#F0A080`). The rows stack downward at
    **x ≈ 1180–1330, y ≈ 300–400**, the reference's embedding rows (0.30 s outQuint).
  - **FLAG**: border stays orange with emissive × 1.6, "FLAG" badge. The chip peels off on a downward arc to
    the engineer panel (0.40 s outQuint, scale 1 → 0.75) and docks in the next free slot: chip 0 at 6.83,
    chip 2 at 7.19, chip 3 at 7.37.
- **Engineer review panel**: an `M.glass` sheet of 1.9 x 2.1 at (S2+3.5, 1.45, 0.2), yaw −18°, with a decal.
  Screen ≈ **x 1400–1720, y 410–770**.
  - Its face is a CanvasTexture (redrawn only when its state changes). A header "ENGINEER REVIEW" in Mono
    700 22 px +0.32em white sits 0.18 from the top.
  - Below it, **3 slot rows**, each a 1 px white 25% rounded outline. Each has a 0.22 square check slot at
    its right end.
  - When a chip docks, its slot goes hot for 0.4 s. **0.10 s later the check slot ticks**: a two-stroke
    white check mark is drawn on the canvas (vector strokes, not a glyph), at 6.93, 7.29 and 7.47. This is
    the engineer signing off.

**Overlay**
- Eyebrow "■ STEP 02". Headline "Self-check" (1 span). Description "Doubts go to an engineer."
- Counter (static): label **"PILOT RUN · 24 DECKS"**, value **"73 chunks → 35 flagged"**. It bridges "one
  slide" to the pilot's scale; the 12 chips on screen are a sample of it.

**Choreography summary:** 5.00 truck in → 5.40 conveyor starts → 5.75 VERIFIER label → 5.80 counter →
**6.43** first FLAG peels off → 6.83 / 7.19 / 7.37 docks, ticks 0.10 s later → 7.30 description and
counter out → 7.45 headline out → **7.50** truck.

**Key times:** **5.30** (mid-truck: the LABEL card exiting left in perspective, "Self-check" rising. This is
the D15 blur gate: render it with `--subframes 4` and check that the card and orb smear by the same amount;
compare to `ref_t12.20`), **6.50** (chip 0 FLAG just out and peeling, chips 1–4 inside hot sheets, queue
trailing lower left; compare to `ref_t13.60`) and **7.20** (two chips docked with ticks, embedding rows
stacking, counter up; compare to `ref_t13.60`).

**Reject if:** the chip text is unreadable at 1080 (value glyphs under 24 px); the sheets read as
hairlines or vanish (the faces must visibly tint); the queue reads as a flat line instead of receding in
depth; orange floods the chip faces (only borders are orange); the engineer panel is blank; the chips
bunch or overlap in the queue.

### 7.5 `05_learn`: STEP 03, LEARN (T3 = 7.50, active 7.45 – 10.65)

**Intent:** the question loop between an agent and a person. The agent asks, the engineer answers, and the
answer becomes a rule that adds a ring. One reading target at a time: no counter in this step.

**Camera:** C8 truck in, then C9 2% push-in.

**3D objects** (stage S3 = 60.8)
- **Loop ring**: a torus of R 1.24, tube 0.018, MeshBasic `#E8893A` × 3 (bloom), in a plane tilted 38° up
  from the floor toward the camera, centered at (S3−2.60, 1.30, 0). Screen ellipse ≈ center
  **(520, 615)**, rx 210, ry 128.
- **Agent node** at the ring's left extreme (≈ 310, 615): a mini LLM orb (core r 0.18, `M.orbWire` shell r
  0.42 at detail 2, its own small `M.atmos`).
- **Engineer node** at the ring's right extreme (≈ 730, 615): the STEP 02 engineer panel at 0.45 scale
  (0.85 x 0.95), yaw −18°, with the same CanvasTexture style.
  - Header "ENGINEER" at the top.
  - Below it, an answer line with an orange block cursor (STYLE §4.4 typing cursor). The cursor is solid
    while typing and blinks at 0.5 s after.
  - The line types **"TDDB not run"** at 8.45 → 8.60.
  - Screen ≈ x 660–800, so it clears the card's left edge (880).
- World labels (Mono 700 15 px +0.32em white), about 60 px under each node: "AGENT" and "ENGINEER". They
  fade in at 8.00.
- **Q chip / A chip** (`M.chip`, queue state, billboard on yaw only), riding the ring with inOutCubic:
  - Q (text "Q") goes over the far arc from agent to engineer, **8.00 → 8.45**. The engineer panel goes
    hot at 8.45 and types the answer.
  - A (text "A  TDDB not run") comes back over the near arc, **8.50 → 8.95**. The chip carries the answer,
    so the card does not repeat it.
  - Each chip fades out over 0.15 s on arrival.
- **RULE at 9.00**: the agent node flares (emissive × 2, 0.3 s decay). A second ring is born: scale 1.00 →
  1.19, opacity 0 → 0.55, 0.5 s outQuint. It stays coplanar and concentric for the rest of the scene.
- **DOMAIN-ENGR-BOT card**: content card 864 x 438, anchored at (S3+2.05, 1.41, 0.3) with yaw −4°. Screen ≈
  **x 880–1744, y 362–800**. Same styling and homography as 7.3.

**Card content** (Mono 500 25 px, line-height 44 px). Two lines only:
```
■ DOMAIN-ENGR-BOT

Q   Why pending?
+   RULE  TDDB open → pending
```
Prefixes "Q" and "+" are `#BFC2C9` at 70%. "RULE" is `#FF6A1A`, the card's single orange text at rest.
Values are white, and the newest streamed token is orange until the next lands. The second line sits two
line-heights below the first, leaving a deliberate gap.

| t | Event |
|---|---|
| **8.00** | Q chip launches; world labels in; the Q line streams `Q` 8.00, `Why` 8.10, `pending?` 8.20 |
| 8.45 | Engineer panel hot; answer types on the panel |
| **8.50** | A chip launches along the near arc |
| **9.00** | RULE: agent flare, ring born, RULE line streams `+` 9.00, `RULE` 9.10, `TDDB` 9.20, `open` 9.30, `→` 9.40, `pending` 9.50 (white at 9.60) |
| 9.80 / 9.95 | Description out / headline out |
| **10.00** | Truck |

**Overlay text:** eyebrow "■ STEP 03", headline "Agents ask engineers" (3 spans), description "Answers become
rules." No counter.

**Key times:** **8.20** (Q chip mid-flight over the far arc, Q line streamed, words finishing their rise;
compare to `ref_t10.00`) and **9.35** (new ring expanding, RULE line streaming with "open" newest and
orange; compare to `ref_t11.40`).

**Reject if:** the ring is a thick neon tube (it must be a hairline with bloom); the chips are DOM; the
engineer node is a blank rectangle; the card and the ring or engineer panel overlap; more than one orange
text run is in the card at rest.

### 7.6 `06_vault`: STEP 04, VAULT (T4 = 10.00, active 9.95 – 15.00)

**Intent:** the reference's denoise showpiece (ref_t17.60 → ref_t21.00). A dense cloud of ~1,300 shaded
voxels resolves into an ordered block: the vector DB. A light graph overlay links lot, process, yield and
TEM. The same voxels become the slide in the close.

**Camera:** C10 truck in, C11 slow orbit (+1.0°/s); the close owns C12 and C13.

**3D objects** (stage S4 = 71.2)
- **Voxel volume**: one `M.voxel` InstancedMesh of **1,296 cubes** (the same count as the hook's 48 x 27
  shatter).
  - **Block layout (resolved)**: 27 x 12 x 4 cubes, pitch 0.20, cube 0.18, centered at (S4+0.55, 1.50, 0).
    Screen ≈ **x 610–1500, y 360–770**, center ≈ (1053, 565).
  - **Resolved color**: three-tone grays from `--noise-cube`, with a faint layered banding (each of the 4
    depth layers 6% darker than the one in front). The block reads as an ordered store, not an image.
  - **Noise layout**: positions scattered in a 1.6x (x) by 1.4x (y, biased downward so the cloud stays
    under y = 330) by 1.6x (z) volume, random rotations, colors 82% `--noise-cube`, 12% `--noise-accent`,
    6% `--noise-dark` (seeded).
- **Resolve, 10.50 → 11.70**: s = (t − 10.50)/1.20, and per cube `p_i = clamp((s − d_i)/0.35)`.
  - `d_i ∈ [0, 0.65]` = 0.40·(layer height rank) + 0.25·(seeded noise), so the block builds bottom-up with
    a ragged front (the reference's per-voxel stagger).
  - Position and rotation lerp with outCubic; color lerps from the noise color to the resolved color.
  - Before 10.50 the cloud drifts slowly (≤ 0.05 units/s, pure f(t)) so it is alive during the truck.
- **World label "VECTOR DB"** (Mono 700 24 px +0.32em white) at 10.75, projected from 0.4 above the block's
  top center (≈ 1053, 300).
- **Hero overlay, 11.45 → 11.70** (the hero cubes sit in early-resolving cells, so the links appear while
  the top is still settling):
  - 4 hero cubes on the top layer: emissive white 0.6, a 1 px orange outline, and a scale pulse 1 → 1.15 → 1
    (0.3 s).
  - 3 hero links (`M.edge`) arc 0.25 above the top face, drawing source → target over 0.2 s with a 0.05 s
    stagger:
    - `RDM8EA.62` → `TiN spacer` (applies)
    - `RDM8EA.62` → `CMBSRP 100%` (yield)
    - `TiN spacer` → `APM-…6524` (TEM)
  - Hero labels (DOM projected, Mono 700 15 px +0.22em white, offset +18 px x and −18 px y, rounded to
    whole px): fade in 11.55 → 11.85 with a 0.05 s stagger. They fade out **12.30 → 12.45** with the step UI.
- No packet hops.

**Overlay**
- Eyebrow "■ STEP 04". Headline "Knowledge Vault" (2 spans). Description "Chunks become searchable."
- Counter **variant B** (STYLE §4.3), enters at 10.80. It is driven by the mean resolve progress P = mean(p_i).
  - Left: label "EMBEDDED", value `NN / 73` with NN = round(73·P), zero-padded.
  - Right: label "NOISE" over a 100 x 4 px mini bar (track `#6B6E75`, orange fill = 1 − P, shrinking right to
    left) with the 15 px mono value (1 − P) to 2 decimals.
  - It reaches "73 / 73" and "0.00" at 11.70.

**Key times:** **10.95** (mid-resolve: bottom rows ordered, top still a noise cloud, counter about "20 / 73";
compare to `ref_t17.60`) and **12.05** (block resolved, hero links and labels lit, counter "73 / 73", VAULT
active on the rail; compare to `ref_t21.00`, and to `ref_t23.80` for the rail state).

**Reject if:** the volume reads sparse or as a graph diagram (it must be a dense block of cubes); the cubes
lack three-tone shading; orange exceeds about 12% of the cubes; the noise cloud intrudes into the title
block during the hold; the labels jitter.

### 7.7 `07_close`: "Slide → knowledge." (T5 = 12.50, active 12.25 – 15.00)

**Intent:** the reference finale, which returns to its hero image. The vault's voxels fly back into the
slide, it decodes crisp at about 960 x 540, five label chips attach to the exact things they describe, and
the title sits above. This is the payoff: the same slide, now understood. It ends on a held end card.

**Camera:** C12 (12.50 → 13.20 inOutCubic, down to the close pose C), then C13 3% push-in to 15.00.

**3D**
- **Re-layout, 12.50 → 12.95** (06_vault's InstancedMesh, third layout): the 1,296 cubes fly from the
  block to a **48 x 27 wall** centered at (S4, 1.96, 0), pitch 0.1125, cube 0.101 (≈ 960 x 540 px at pose
  C, x 480–1440, y 250–790).
  - Per-cube delay 0–0.15 s (seeded, with a left-to-right bias), 0.30 s outQuint each.
  - Position, rotation and scale lerp; color lerps to that cube's `slideCells` color.
  - At 12.95 the wall is the pixelated slide.
- **Decode, 12.98 → 13.25** (easeOutQuad): at 12.98 the voxels hide and a slide plane (5.40 x 3.04, the
  shared texture, MeshBasic, toneMapped false, 1 px white 45% edges, decal) appears in exactly the
  48 x 27 pixelated state. It de-pixelates back to full resolution, the reverse of the hook. The swap must
  be invisible.
- **Five label chips** (`M.chip`, **neutral** border; `tem_ref` uses the orange border) on 3D planes at
  the wall's depth, facing the camera. Each chip has a 1 px white 35% leader ending in a 6 px white dot on
  its anchor (`tem_ref`'s leader is orange). Leaders run nearly horizontal. Screen positions at pose C:

  | Chip | Side, center y | Anchor on the slide (screen) |
  |---|---|---|
  | `module  SAUP · TiN` | left, x 150–450, y 290 | title text left end (≈ 564, 290) |
  | `decision  pending` | left, y 587 | the defect annotation (≈ 742, 587) |
  | `lot_id  RDM8EA.62` | right, x 1470–1790, y 374 | callout row 1 (≈ 1356, 374) |
  | `open_risk  TDDB` | right, y 464 | callout row 3 (≈ 1356, 464) |
  | `tem_ref  APM-…6524` | right, y 554 | the ghost tag (≈ 1305, 540) |

  - Attach 13.05 → 13.46: order module, decision, lot_id, open_risk, tem_ref, stagger 0.04. Each chip goes
    from 40% opacity and 24 px outward to rest (0.22 s outQuint).
  - Each leader draws from the chip toward the anchor over 0.15 s outExpo, starting 0.10 s after its chip.
  - When the tem_ref leader lands (≈ 13.45), the ghost tag's dashed outline turns solid white 80%
    (0.15 s, one texture redraw). The missing evidence is now linked.
- Hero links and labels from 7.6 fade out 12.45 → 12.60, before the re-layout reads.

**Overlay**
| Element | Spec | Position | Timing |
|---|---|---|---|
| Final title | "Slide → **knowledge.**", Display 650, 86 px (cap 62), -0.02em; "Slide" and "→" white, "knowledge." `#FF6A1A`; 3 spans, each in its own mask | centered on x = 960, cap-top 133 | rises **12.75** (0.45 s outExpo, 0.05 s stagger) → settled **13.30** |
| End slate | "BEOL AX", Display 700, 46 px, -0.01em, white; 2 spans in masks | centered on x = 960, cap-top 846 (the slide settles at S 1.02, x 455–1465, y 238–805, so the slate has its own band) | rises **13.50** (0.45 s outExpo, 0.06 s stagger) → settled ≈ 13.80 |
| Credit | Cascadia Mono 400 16 px +0.04em: "synthetic example  ·  " at white 55%, "Motion design — Claude" at 66% | centered on x = 960, cap-top 910 | 13.62 → 13.92 outQuint, 8 px rise |
| Rail | all stops orange | section 5 | 13.00 → 13.40 |
| Counter | none | — | — |

**Hold:** from **13.50 to 15.00** (1.5 s) the end card is complete. Only the 3% push-in and the dust move.
No fade to black (D6). The last frame is the end card.

**Key times:** **12.80** (voxels mid-flight from block to wall, step UI gone, title words starting to rise;
compare to `ref_t23.80`) and **14.40** (end-card hold; compare to `ref_t27.50`).

**Reject if:** the title is off-center by more than 2 px; the decode swap pops; the slide is smaller than
900 px wide; any chip or leader crosses the title or the caption; the chips together read louder than the
slide (neutral borders, one orange); any step UI is still visible after 12.66.

---

## 8. Frame-by-frame layout guardrails (all scenes)

- The step title block owns **x 120 → (right edge of the widest of its headline and description + 60 px)**,
  y 130–310. No 3D hero may project into that box during a hold; objects may pass through it during trucks.
  World labels such as "VERIFIER" may sit in the same band to the right of it, as "TEXT ENCODER" does in
  ref_t13.60.
- The counter owns x 1350–1800, y 850–920. The rail owns y 960–1020. No world label goes below y 900.
- The center of interest during step holds sits at 55–60% of the frame width.
- At most one orange text run per region (title block, card, counter label). Orange emissive light in 3D
  forms one cluster per frame.
- Every DOM element anchored to 3D is positioned by projection inside `seek(t)`, rounded to whole px, and
  hidden when behind the camera or outside the frame.

## 9. Readability audit

"Settled" means the last word's rise has finished and its exit has not started. A description or counter
counts from the end of its fade-in to the start of its fade-out. Minimums: headline 1.6 s (STYLE §7.4);
description chars / 17 s; counter value chars / 20 s (number-heavy); final caption chars / 17 s.

| Text | Chars | Readable from → to | Seconds | Min | OK |
|---|---|---|---|---|---|
| Hook "This started as one slide." | 26 | 0.00 → 1.50 (88% risen at frame 0; fully gone 1.76) | 1.50 (+0.26 exit) | 1.53 | yes, marginal |
| "Context labeling" | 16 | 3.25 → 4.95 | 1.70 | 1.60 | yes |
| "An LLM labels the slide." | 24 | 3.30 → 4.80 | 1.50 | 1.41 | yes |
| Counter "1 slide → 5 labels" | 18 | 3.60 → 4.80 | 1.20 | 0.90 | yes |
| "Self-check" | 10 | 5.70 → 7.45 | 1.75 | 1.60 | yes |
| "Doubts go to an engineer." | 25 | 5.80 → 7.30 | 1.50 | 1.47 | yes |
| Counter "73 chunks → 35 flagged" | 22 | 6.10 → 7.30 | 1.20 | 1.10 | yes |
| "Agents ask engineers" | 20 | 8.30 → 9.95 | 1.65 | 1.60 | yes |
| "Answers become rules." | 21 | 8.30 → 9.80 | 1.50 | 1.24 | yes |
| Card "+ RULE  TDDB open → pending" | 27 | 9.60 → truck exit ≈ 10.35 | 0.75 (+ stream 0.6) | — | streamed |
| "Knowledge Vault" | 15 | 10.75 → 12.45 | 1.70 | 1.60 | yes |
| "Chunks become searchable." | 25 | 10.80 → 12.30 | 1.50 | 1.47 | yes |
| "Slide → knowledge." | 18 | 13.30 → 15.00 | 1.70 | 1.60 | yes |
| Overview "Everything in between." | 22 | 2.05 → 2.50 (+ rise from 1.80) | 0.45–0.70 | section flash | yes |
| End slate "BEOL AX" | 7 | 13.80 → 15.00 | 1.20 | 1.00 | yes |
| Credit "synthetic example · Motion design — Claude" | 44 | 13.92 → 15.00 | 1.08 | 1.00 | yes |
| End card complete | — | 13.50 → 15.00 | 1.50 | ~1.0 hold | yes |

## 10. Style frames and reference pairs

Render each one with `python tools/render.py --times <t> --frames-dir <scratch>/lookdev/frames`. Compare
with `--compare "<ref.png>:<t>,..." --compare-out <scratch>/lookdev/cmp`. Reference paths are under
`<scratch>/lookdev/ref/curated/`.

| Our t | Scene | What must match the reference |
|---|---|---|
| 0.60 | hook | `ref_t00.30_open_hero_image.png`: full-bleed image dominance, headline on dark image, eyebrow and headline scale, orange key phrase |
| 1.30 | hook | (no ref) pull-back reveals the slab edge and decal; half-pixelated; scrim fading |
| 1.62 | hook/overview | `ref_t02.50_hero_headline_pipeline_floor.png`: room reveal, voxel burst filling the lens, orange glow only on emissives |
| 2.00 | overview | `ref_t02.50_hero_headline_pipeline_floor.png`: ring flare, thick arc and comet bloom quality |
| 2.40 | overview | `ref_t03.80_overview_pipeline.png`: plinth row, two blazing rings, arcs, mono floor labels, centered eyebrow, grid luminance ±3 |
| 2.85 | label | `ref_t12.20_handoff_title_mask_rise.png`: words clipped by masks mid-rise, eyebrow already in |
| 3.95 | label | `ref_t10.00_step01_streaming_card.png`: orb halo, wire density, orbiters, card styling, newest token orange, counter |
| 4.60 | label | `ref_t11.40_step01_done_orb_card.png`: DONE state, rail fill toward VERIFY (x ≈ 853) |
| 5.30 | verify | `ref_t12.20_handoff_title_mask_rise.png`: old card exiting left; DOM and WebGL blur match (D15 gate) |
| 6.50 | verify | `ref_t13.60_step02_tokens_glass.png`: diagonal chip queue, readable chip text, tinted hot glass, world label, grid luminance ±3 |
| 7.20 | verify | `ref_t13.60_step02_tokens_glass.png`: embedding rows, docked chips on the review panel, static counter |
| 8.20 | learn | `ref_t10.00_step01_streaming_card.png`: hero-left / card-right balance, streaming |
| 9.35 | learn | `ref_t11.40_step01_done_orb_card.png`: bloom on the hairline ring, card at rest |
| 10.95 | vault | `ref_t17.60_step03_noise_cubes.png`: noise palette 82/12/6, cube scale and density |
| 12.05 | vault | `ref_t21.00_step03_voxels_resolved.png`: resolved block, three-tone shading; and `ref_t23.80_step04_decode_frames.png` for the rail with the last stop active |
| 12.80 | close | `ref_t23.80_step04_decode_frames.png`: voxels becoming an image |
| 14.40 | close | `ref_t27.50_final_title.png`: centered title over a large image, caption typography, all-orange rail |

Gates before any mp4: (1) the determinism check
`python tools/render.py --times 0.6,3.95,6.5,10.95,14.4 --verify-determinism --frames-dir <scratch>/lookdev/det`
reports identical hashes; (2) the 200% floor crops at 2.40 and 6.50 show no aliasing (section 5); (3) the
5.30 blur gate passes (D15).
