# BEOL AX — Labeling Screens Design System

Source of truth: `design.md.md` (BEOL AX Unified Design System). This file adapts it to the labelbot screens. When the two disagree, `design.md.md` wins.

## Product context

- **Product**: labelbot. It auto-labels BEOL (back-end-of-line semiconductor) process documents (pptx slides → chunks) with a 10-axis taxonomy and O/X/N/A questions. Then a process engineer reviews the flagged chunks.
- **Users**: BEOL process/integration engineers. They are Korean-speaking and dense-data literate. They read the screens on desktop (1280–1600px).
- **Screens**:
  1. **Results dashboard** (`results.html`). Read-only overview of one labeling run.
     - JTBD: "In 10 seconds, tell me whether this run is healthy and what needs my review." Then let me drill into chunks.
     - Content: run id/model, KPI (files, chunks, flagged chunks + ratio), H5 alerts, flag-reason distribution, question answer distribution (Q-COM-001 BEOL relevance, Q-GEN verification, Q-CTL control/trap questions), per-axis state (value / unknown / N/A ratio), per-axis value distribution, and a filterable chunk table with expandable detail (body text with highlighted evidence, per-axis evidence + confidence, question answers).
  2. **Review screen** (`review.html`). Interactive human review of flagged chunks.
     - Layout: top bar (run id, counts, save/export, "검수 완료" primary action) + a left list of flagged chunks with reason-code filter chips + a right detail pane.
     - Detail pane contents: slide preview, body text with evidence highlights, same-file slide thumbnails, per-axis cards with bot value / confidence / evidence and correction options, question answers, control questions, revisit (taxonomy re-review) requests, and correction evidence picking.
     - JTBD: "Go through each flagged chunk fast, see why it was flagged, correct or confirm, then finish."

## Required change direction (user request, 2026-10-05)

- The current dashboard UI has degraded. Redo the **layout and visualization techniques**.
- **Shrink the per-axis "value · unknown · N/A ratio" section drastically.** It currently takes a full-width big card with one tall bar per axis. It should become a compact visualization, for example:
  - a single small-multiples strip,
  - a compact heat-row/table with tiny inline bars,
  - or a dot matrix.
  It should highlight only axes whose unknown ratio is high.
- Keep all information available. Rebalance the hierarchy: health summary first, review workload second, distributions third, chunk table last.

## Visual foundations

### Color tokens (exact values; no other hues)
| Token | Value | Use |
|---|---|---|
| `--primary-deep` | `#354690` | strongest indigo, gradient end, key headers |
| `--primary` | `#4A5FA8` | main accent, active, highlighted data |
| `--primary-soft` | `#6B82C4` | secondary nodes, gradient start |
| `--primary-mid` | `#4A6BAF` | hover/transition, info |
| `--bg-base` | `#EDF1F7` | page background (blue-gray) |
| `--bg-grid` | `#C8D4E4` | 48px square grid lines, borders |
| `--dot` | `#A8BDD4` | inactive markers |
| `--line` | `#7A9CC0` | neutral lines/edges, N/A-ish data |
| `--text-strong` | `#1E2D4A` | headings, body |
| `--text-muted` | `#9DAABF` (labels may use `#6F7F99` for contrast) | captions, units |
| `--text-footer` | `#B0BCCC` | footer, meta |
| `--danger` | `#C25450` | defects, flag reasons (small areas only) |
| `--warning` | `#C99A3B` | unknown, suspicion, alerts (small areas only) |
| `--success` | `#3B8A6E` | verified, OK (small areas only) |

- **Gradient signature**: emphasized cards use `linear-gradient(148deg, #4A5FA8 0%, #354690 100%)`. Secondary cards use `linear-gradient(148deg, #6B82C4 0%, #4A6BAF 100%)`.
- **Background rule**: the page is always `#EDF1F7` with a 48px grid (`#C8D4E4`, 0.4–0.5px, ~0.5 opacity). Never pure white `#FFFFFF` and never neutral gray backgrounds. Cards are translucent/tinted blue-gray surfaces (e.g. `rgba(246,248,252,0.85)` or `#F6F8FC`), never pure white.
- Semantic colors (danger/warning/success) go only on badges, dots, thin borders (1–1.5px) and small bar fills. Never use them on large areas.
- **Data colors**:
  - value = `--primary`
  - unknown = `--warning`. Do NOT use orange `#eb6834`; the old UI used it and it is off-palette.
  - N/A = `--bg-grid` or `--dot`
  - X answers = `--danger`
  - O answers = `--primary`

### Typography
- Body font: `'Apple SD Gothic Neo','Noto Sans KR','Inter',sans-serif` (Pretendard acceptable).
- Mono font: `'JetBrains Mono','Fira Code',monospace`. Use it for ids, codes, numbers, units (run id, `Q-COM-001`, `UNKNOWN_HIGH`, `0.72`).
- **Negative letter-spacing everywhere**:
  - logo/header: `-0.055em`
  - card/figure titles: `-0.048em`
  - body: `-0.02em`
  - captions: `-0.015em` to `-0.02em`
- **Weights**: only 400 and 700. No 500/600/800.
- Big KPI numerals: 700, mono or body font, tight `-0.04em`.

### Shape, spacing, depth
- Radius: 8px (sm), 12px (cards).
- Node/card shadow: `0 2px 8px rgba(53,70,144,.06)`. On hover/active: `0 8px 20px rgba(53,70,144,.16)`, border `--primary`.
- Spacing scale: 4/8/12/16/20/24/32. Dense but breathable. Max content width ~1360px.

### Motion & interaction
- All hover/transition motion uses elastic easing `cubic-bezier(0.34,1.56,0.64,1)` over 0.24–0.32s. Hover lifts are subtle (translateY −2 to −4px).
- Every chart reacts to hover: a tooltip (dark `#1E2D4A` pill, white mono text) plus a highlight of the hovered series while the rest dims (~0.35).
- Clicking a chart element filters the chunk table where meaningful: reason → flagged chunks with that reason, axis unknown cell → chunks with that axis unknown.
- Optional subtle background dot-repel / cursor trail per `design.md.md` §3. It must never reduce data legibility.
- Respect `prefers-reduced-motion`.

## Constraints
- Single self-contained HTML file per screen. Vanilla JS/CSS. **No external CDN scripts or fonts** (offline in-house rule). No frameworks.
- Data comes from an injected `const DATA = {...}` JSON. Layouts must handle 1 to hundreds of chunks, 0 alerts, and empty reason lists.
- Language: Korean UI copy. Keep the existing labels and terminology (불량 사유, 질문 답 분포, 축, unknown, 해당 없음, 검수 완료, 함정질문/대조 질문, 라벨 정합성).
- Don'ts:
  - purple `#9D4EDD`, neon, or pink
  - serif or handwriting fonts
  - positive letter-spacing
  - 3D or decorative illustration
  - static, non-interactive charts
