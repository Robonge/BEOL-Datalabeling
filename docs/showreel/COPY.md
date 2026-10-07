# BEOL AX showreel: on-screen copy

15.000 s, 1920x1080, 60 fps. English only. The copy follows the voice of "Text-to-video, explained": short
declaratives, one idea per beat, mono for data, sans for claims.

**This file holds words only.** Every time, position and transition lives in STORYBOARD.md (sections 1, 2
and 5). Where an older note here disagrees with STORYBOARD.md, STORYBOARD.md wins.

## Pipeline rail (bottom; shown from STEP 01 to the end)

```
SLIDE · LABEL · VERIFY · LEARN · VAULT
```

SLIDE is the input stop, like PROMPT in the reference. The other four stops match STEP 01 to STEP 04. At the
end every stop turns orange.

## Beat sheet (words; for timing see STORYBOARD.md §2)

| # | Beat | Eyebrow | Headline | Description | Counter (label / value) |
|---|---|---|---|---|---|
| 0 | Hook | ■ BEOL AX, EXPLAINED | This started as **one slide.** | none | none |
| — | Overview | ■ THE WHOLE PIPELINE (centered) | Everything in between. (centered) | none | none |
| 1 | LABEL | ■ STEP 01 | Context labeling | An LLM labels the slide. | LABELING → DONE / 1 slide → 5 labels |
| 2 | VERIFY | ■ STEP 02 | Self-check | Doubts go to an engineer. | PILOT RUN · 24 DECKS / 73 chunks → 35 flagged |
| 3 | LEARN | ■ STEP 03 | Agents ask engineers | Answers become rules. | none |
| 4 | VAULT | ■ STEP 04 | Knowledge Vault | Chunks become searchable. | EMBEDDED NN / 73 · NOISE 0.00 |
| 5 | Close | none | Slide → **knowledge.** · end slate **BEOL AX** | none | none |

Every description is 25 characters or fewer.

---

## 0 · Hook

**Headline (bottom left, over the image):** This started as one slide.

**The engineer's slide** (synthetic). A full-bleed SEM micrograph, with:
- Title band: `M1 SAUP spacer TiO2 → TiN`, and at the right `ENGINEER SLIDE · SYNTHETIC`
- Image label: `SEM TOP VIEW · 50 nm`
- Defect annotation (orange): `open/short`
- Callout box rows:
  ```
  RDM8EA.62   WF#9
  CMBSRP open/short 100%
  TDDB: still to check
  ```
- Ghost tag (dashed, 40%): `TEM → messenger only`. This is the evidence the slide never links.

## Overview

**Headline (centered, under the eyebrow):** Everything in between.

Floor labels: `SLIDE`, `01  LABEL`, `02  VERIFY`, `03  LEARN`, `04  VAULT`.

## 1 · STEP 01 · LABEL

Card label `■ LABELS`, with keys in gray and values in white:

```
module     SAUP · TiN spacer
lot_id     RDM8EA.62
decision   pending
open_risk  TDDB
tem_ref    APM-…6524
```

World label: `LLM`.

## 2 · STEP 02 · VERIFY

World label: `VERIFIER`. Engineer panel header: `ENGINEER REVIEW`.

Chips (key, then value). Badges: `PASS`, `FLAG`.

```
decision  pending      FLAG
module  SAUP           PASS
tem_ref  none          FLAG
open_risk  TDDB        FLAG
lot_id  RDM8EA.62      PASS
module  TiN spacer     PASS
decision  adopted
tem_ref  APM-…6524
open_risk  none
module  M1 Cu
decision  hold
open_risk  EM
```

O/X is shown only as PASS/FLAG badges and as a check mark on the engineer panel. The letters "O/X" never
appear on screen, because English viewers do not read them as yes/no.

## 3 · STEP 03 · LEARN

Card label `■ DOMAIN-ENGR-BOT`, two lines:

```
Q   Why pending?
+   RULE  TDDB open → pending
```

Chips on the ring: `Q`, `A  TDDB not run`. Engineer node: header `ENGINEER`, answer line
`TDDB not run`. World labels: `AGENT`, `ENGINEER`.

## 4 · STEP 04 · VAULT

World label: `VECTOR DB`. Hero labels: `RDM8EA.62`, `TiN spacer`, `CMBSRP 100%`, `APM-…6524`.

## 5 · Close

**Title (centered):** Slide → **knowledge.** ("Slide →" white, "knowledge." orange.)

Five chips attached to the decoded slide:

```
module  SAUP · TiN
decision  pending
lot_id  RDM8EA.62
open_risk  TDDB
tem_ref  APM-…6524
```

**End slate (under the slide):** **BEOL AX** (Display 700, white), and under it the credit line
`synthetic example  ·  Motion design — Claude` (mono, muted).

No fade to black.

---

## Facts behind each number

| On screen | Value | Source in docs/project_intro.html | Status |
|---|---|---|---|
| Slide text: M1 SAUP spacer TiO2 → TiN, RDM8EA.62 WF#9, CMBSRP open/short 100%, TDDB still to check, SEM top view, TEM on messenger | as shown | s2 (01 Data labeling), synthetic example | real deck example, synthetic data |
| Label rows module / lot_id / decision / open_risk / tem_ref | SAUP · TiN spacer / RDM8EA.62 / pending / TDDB / APM-…6524 | s2 | real deck example (lot ID unified to the slide's form) |
| `1 slide → 5 labels` | 5 labels | s2 shows 5 label fields | derived |
| `24 decks`, `73 chunks → 35 flagged` | 24 pptx → 73 chunks, 35 flagged | s7 pilot | real (dummy-data pilot) |
| VERIFY chips | label values | s2 example plus invented synthetic values | synthetic |
| Q / RULE in the LEARN card, `TDDB not run` | dialogue | written for this film from the s2 example (pending decision, TDDB open) | invented, synthetic |
| Vault hero links | RDM8EA.62 → TiN spacer, → CMBSRP 100%, TiN spacer → APM-…6524 | s9 ontology examples | real deck example |
| `73 / 73` embedded | 73 | s7 "embedding 73" | real |

## Things to avoid

- No Hangul anywhere on screen.
- No real company names, no lot numbers beyond the deck's synthetic ones, no person names.
- No italics, no exclamation marks, no hype words.
- Never more than one description line on screen at once.
