# pages.md - dependency trees and line ranges

All paths relative to repo root `C:\Users\dltkd\Desktop\261004 BEOL AX day2`. Verified by reading imports of each module.
Templates have no JS imports; the only "includes" are the `fill_template` text substitutions.

## results.html
```
labelbot/screens/results.html            (template, standalone; no partials)
  <- filled by labelbot/review.py :: fill_template("results.html", data)      [replaces /*__DATA__*/null]
  <- DATA built by labelbot/dashboard.py :: build_results(ws, con, run_id, tax)
        imports: labelbot.alerts (na_ratio, dup_ratio -> kpi/alerts), labelbot.finals (final_labels -> chunk axes/answers),
                 labelbot.review (REASONS, REASON_LABELS, _run_population, fill_template), labelbot.util,
                 labelbot.questions (CTL_PREFIX, GEN_PREFIX, all_questions)
  <- written to <workspace>/screens/results.html, served by labelbot/serve.py
  <- CLI: labelbot/cli.py "dashboard"
```
Line ranges in `labelbot/screens/results.html` (293 lines):
- CSS: `7-136` (`<style>`; tokens 8-18, base 19-33, primitives 34-98, big-KPI layout 100-135)
- Markup: `138-140` (`#app.wrap`, `#tip`)
- JS: `141-291` (`const DATA = /*__DATA__*/null;` at 142; IIFE 143-290: helpers 146-164, KPI/alerts 166-176, reasons+questions 178-193, axes stacks 195-206, folded value bars 208-216, chunk table + filters 218-230, table render/detail 234-289)

## review.html
```
labelbot/screens/review.html             (template)
  inlines <- labelbot/screens/slide_preview.css   at /*__SLIDE_PREVIEW_CSS__*/ (line 111)
  inlines <- labelbot/screens/slide_preview.js    at /*__SLIDE_PREVIEW_JS__*/  (line 237)  -> global SlidePreview.build(layout, image_map)
  <- filled by labelbot/review.py :: fill_template("review.html", data)
  <- DATA built by labelbot/review.py :: build_review(ws, con, run_id, tax)
        imports: labelbot.finals (bot_labels), labelbot.ingest, labelbot.revisit (REASON_LABELS, TARGET_REASONS, MEMO_MAX, SHORT_MAX -> revisit_* DATA keys),
                 labelbot.store, labelbot.util, labelbot.questions (all_questions, is_control; lazily control_answers, map_questions),
                 labelbot.synonyms (SynonymTable, lazy), labelbot.workspace (CODE_ROOT), labelbot.pptx_parser (slide_layouts, lazy, for chunk "layout")
        local constants: REASONS, REASON_LABELS, EVIDENCE_* (review.py:11-31)
  <- runtime endpoints (served by labelbot/serve.py): GET inbox/status, POST inbox/review, POST inbox/review/done
  <- CLI: labelbot/cli.py "review"
```
Line ranges in `labelbot/screens/review.html` (1589 lines):
- CSS: `7-220` (`<style>`; tokens 8-18, base 19-34, app shell 36-46, list 47-75, detail/actions/btn 77-95, card/text/legend 96-113, feature boxes syn/rv/ev/ctx 114-149, axis/opt/question 151-189, dialog/zoom/sib/toast 191-209, media 211-219)
- Markup: `222-234` (`#root`, `#zoom`, `#toast`, `<dialog id="dlg">`)
- JS: `236-1587` (partial marker 237, `const DATA` 238; helpers `h`/`toast` 244-259; state 281-313; load/save/inbox 315-390; bot/edit helpers 393-465; revisit output 467-565; download/dialog 565-624; zoom/sib 625-692; list render 695-821; body text + synonyms 823-945; evidence 946-1091; axis/question editors 1094-1382; revisit form 1118-1253; detail render 1385-1523; keyboard 1539-1557; `init()` 1559-1588)

## compare.html
```
labelbot/screens/compare.html  (no partials; 484 lines; DATA marker line 155)
  <- labelbot/review.py :: build_compare(ws, con, run_id)  -> fill_template("compare.html", data)
  <- CLI "compare"
```

## slides.html
```
labelbot/screens/slides.html (50 lines) inlines slide_preview.css/js; DATA built inline in labelbot/slideimg.py :: _render_file
  slideimg imports labelbot.cdp, labelbot.review (fill_template, _template, _data_urls), labelbot.store, labelbot.util, labelbot.embed
```

## Shared partials
- `labelbot/screens/slide_preview.css` (9 lines), `slide_preview.js` (56 lines): consumed by review.html and slides.html only.
- Server: `labelbot/serve.py` (serves `<ws>/screens/` + inbox endpoints), launcher `.claude/skills/BEOL-labeling/scripts/serve_screens.py`.

## Suggested `path:start:end` ranges for design calls
- results full page: `labelbot/screens/results.html:7:136` (CSS) + `labelbot/screens/results.html:141:290` (JS)
- results big KPIs: `labelbot/screens/results.html:100:112` + `labelbot/screens/results.html:170:176`
- review shell: `labelbot/screens/review.html:36:46` + `labelbot/screens/review.html:1559:1588`
- review list: `labelbot/screens/review.html:47:75` + `labelbot/screens/review.html:730:800`
- review detail: `labelbot/screens/review.html:77:113` + `labelbot/screens/review.html:151:189` + `labelbot/screens/review.html:1254:1302` + `labelbot/screens/review.html:1385:1523`
- tokens: `labelbot/screens/review.html:8:18`
