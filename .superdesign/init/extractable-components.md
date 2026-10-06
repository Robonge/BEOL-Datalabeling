# extractable-components.md

Candidate reusable components. No component library exists; each entry names the vanilla source to lift into a real component. Props are the data each reads from `DATA`.
Category: `layout` (page structure) or `basic` (leaf element).

| Name | Source (path:lines) | Category | Description | Extractable props |
|---|---|---|---|---|
| TopBar | `labelbot/screens/review.html:37-42` (CSS), `1566-1581` (JS) | layout | Review header: title, run/meta line, spacer, stat counts, inbox status text, primary "검수 완료" (hidden until server supports), "JSON 저장", "텍스트로 복사" buttons. Wraps on narrow widths. | `title`, `runId`, `generatedAt`, `flagThresholds{unknown_ratio_min, confidence_min}`, `stats{flagged,corrections,statuses,synonyms,revisits}`, `inboxMessage`, `inboxError`, `doneVisible`, `onDone`, `onSaveJson`, `onCopy` |
| AppShell | `labelbot/screens/review.html:36-46`, `211-219` | layout | 100vh grid: top bar + (344px list | detail); collapses to one column under 860px. | `listWidth`, `children: [bar, list, detail]` |
| ReviewList | `labelbot/screens/review.html:44-75` (CSS), `695-821` (JS) | layout | Left column: filters block + scrollable items; supports dup-group clustering (`.grp`), selection, empty note. | `chunks[]`, `selectedId`, `activeReasons{}`, `onlyTodo`, `onlyRevisit`, `onSelect`, `onToggleReason` |
| ReasonFilterChips | `labelbot/screens/review.html:45-54`, `753-774` | basic | Toggle chips with counts, "전체" reset, extra toggles ("처리 전만 보기", "재검토 요청 있음"). `aria-pressed` driven. | `reasons[{code,label,n}]`, `active{}`, `totalCount`, `extraToggles[{label,on,count}]` |
| ReviewItem | `labelbot/screens/review.html:58-70` (CSS), `730-749` (JS) | basic | List row: chunk id, page, status marks (확인/이미지/교정 n/재검토 n), title, reason tags. | `chunkId`, `slideNo`, `title`, `fileName`, `reasonCodes[]`, `status`, `correctionCount`, `revisitCount`, `selected` |
| ReasonTag / StatusMark | `labelbot/screens/review.html:67-75`, `730-733` | basic | Mono pill tag (hard=danger, soft=warning) and rounded status mark (ok/img/fix/rv). | `code`, `label`, `severity` (`hard`/`soft`/default), `markKind` |
| DetailHeader | `labelbot/screens/review.html:77-83`, `1399-1409` | layout | File name h2, mono path line, reason tags with labels, metric pairs (unknown ratio, min confidence with warning color). | `fileName`, `relPath`, `slideNo`, `chunkId`, `dupGroup`, `reasonCodes[]`, `unknownRatio`, `minConfidence`, `thresholds` |
| ActionBar | `labelbot/screens/review.html:84-94`, `1411-1423` | basic | Button row: apply-to-same-file, confirm (on-ok), undecidable-image (on-img), next/prev. | `sameFileCount`, `status`, `onApplySameFile`, `onSetStatus`, `onStep` |
| Button | `labelbot/screens/review.html:85-94` | basic | `.btn`, `.btn.primary` (148deg gradient), `.sm`, state variants. | `variant` (`default|primary|on-ok|on-img`), `size`, `disabled`, `label` |
| AxisCard (axis editor) | `labelbot/screens/review.html:151-187`, `1254-1302` | basic | Axis head with badges, bot values + confidence, evidence quote, definitions `<details>`, toggle `.opt` buttons incl. special values. | `axis{name,kind,multi,definition,values[]}`, `botValues[]`, `confidence`, `evidence`, `currentValues[]`, `changed`, `onToggle` |
| QuestionCard | `labelbot/screens/review.html:181-184`, `1349-1382` | basic | Question id + text, bot answer chip + confidence + quote, O/X/N/A/판단 불가 toggles. | `qid`, `text`, `botAnswer`, `confidence`, `quote`, `current`, `changed`, `onChange` |
| SlidePreview | `labelbot/screens/slide_preview.css:1-9`, `slide_preview.js:1-56` | basic | Approximate slide layout renderer (text boxes, tables, pictures) in container-query units. | `layout{w,h,items[],pics[]}`, `imageMap{sha:url}`, `big` |
| SiblingSlideStrip | `labelbot/screens/review.html:200-207`, `644-679` | basic | Large viewer + thumbnail strip with flagged dots and arrow-key navigation. | `slides[{seq,chunk_id,src}]`, `currentSeq`, `flaggedIds`, `onOpenZoom` |
| ValueChip | `labelbot/screens/review.html:159-161`, `1111-1116` | basic | Bot value pill: normal, 해당 없음 (outlined), unknown (dashed warning); title tooltip = definition. | `name`, `kind` (`value|na|unk`), `definition` |
| KpiCard / KpiHero (BigKpi) | `labelbot/screens/results.html:41-44`, `100-112`, `170-175` | basic | Large KPI tiles; hero tile has a donut ring and danger left border. | `label`, `value`, `unit`, `warnNote`, `hero`, `ratio`, `donutLabel` |
| Donut | `labelbot/screens/results.html:42-44`, `148-149` | basic | Conic-gradient ring with centered percentage (`--p`, `--c`). | `ratio` (0-1), `label`, `size`, `color` |
| ReasonBars | `labelbot/screens/results.html:61-67`, `119-124`, `179-184` | basic | Horizontal bar rows (label, track+bar, count + percent) for flag-reason counts with tooltip. | `items[{code,label,n}]`, `total`, `max`, `barClass` (`danger`) |
| AnswerDistribution | `labelbot/screens/results.html:47-56`, `185-193` | basic | Per-question O / X / N/A stacked bar with legend and percentage caption. | `questions[{qid,label,O,X,NA}]`, `colors` |
| AxisStateBars | `labelbot/screens/results.html:49-56`, `160-164`, `196-206` | basic | Per-axis value / unknown / 해당 없음 stacked bars (shared `stack()` helper). | `axes[{name,states{value,unknown,na}}]`, `colors` |
| StackBar | `labelbot/screens/results.html:49-56`, `160-164` | basic | Segment bar with min label threshold (>=8% shows count) and hover tooltips. | `label`, `parts[{name,n,color,cls}]`, `total` |
| ChunkTable | `labelbot/screens/results.html:68-96`, `218-289` | layout | Filterable table (file, axis value, BEOL answer, flagged-only, text search) with expandable detail row (body highlights, evidence, answers). | `chunks[]`, `files[]`, `axes[]`, `filters`, `openIds`, `onToggleRow` |
| Chip (axis value) | `labelbot/screens/results.html:78-80`, `236-242` | basic | Inline pill with axis prefix; `.unk` variant. | `axis`, `value`, `unknown` |
| AnswerBadge | `labelbot/screens/results.html:81-84` | basic | Mono O/X/N/A pill with color per answer. | `answer` (`O|X|NA`) |
| MiniDistributionCard | `labelbot/screens/results.html:57-67`, `209-216` | basic | Small card with title and value bars for one axis. | `title`, `values[{name,n}]` |
| Toast | `labelbot/screens/review.html:208-209`, `255-259` | basic | Bottom-right transient message. | `message`, `duration` |
| JsonDialog | `labelbot/screens/review.html:191-195`, `226-234`, `589-624` | basic | Modal with read-only textarea, select-all / close. | `title`, `message`, `text` |
| HoverTip | `labelbot/screens/results.html:95`, `152-158` | basic | Cursor-following tooltip bound to `[data-tip]`. | `text` |
