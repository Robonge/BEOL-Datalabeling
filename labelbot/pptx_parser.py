"""pptx 파서: 슬라이드 1장 = 단위 1개. bytes만 받는다(CLAUDE.md).

읽기 순서는 위→아래, 왼쪽→오른쪽(도형 offset의 y, x). 그룹 도형은 자식 좌표를 변환해 펼친다.
표처럼 배치된 낱개 텍스트 상자는 좌표로 행·열을 복원한다(PRD 7.1).
"""
from labelbot import ooxml, textnorm
from labelbot.ooxml import A, C, DGM, P, R

DEFAULT_SLIDE_SIZE = (12192000, 6858000)
SKIP_PLACEHOLDERS = ("sldNum", "dt")
TITLE_PLACEHOLDERS = ("title", "ctrTitle")
# 제목 추정: 제목 placeholder가 비면 슬라이드 위쪽 이 비율 안의 텍스트 상자 중 가장 큰 글자를 고른다.
TITLE_ZONE = 0.3
# 좌표 표 복원에서 낱개 상자를 셀로 볼 최대 크기
CELL_MAX_LINES = 3
CELL_MAX_CHARS = 120
CELL_MAX_WIDTH = 0.5  # 슬라이드 폭 대비
LOW_TEXT_CHARS = 20
_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"


class _Item(object):
    """슬라이드 위 요소 하나. kind: text, table, smartart, chart."""

    __slots__ = ("kind", "x", "y", "w", "h", "lines", "rows", "chart", "sz", "ph", "order")

    def __init__(self, kind, box, order, lines=None, rows=None, chart=None, sz=None, ph=None):
        self.kind = kind
        self.x, self.y, self.w, self.h = box
        self.order = order
        self.lines = lines or []
        self.rows = rows or []
        self.chart = chart
        self.sz = sz
        self.ph = ph

    @property
    def cy(self):
        return self.y + self.h / 2.0


# ---------------------------------------------------------------- 좌표 변환


def _identity(x, y, w, h):
    return x, y, w, h


def _xfrm_box(xfrm):
    if xfrm is None:
        return None
    off = xfrm.find(A + "off")
    ext = xfrm.find(A + "ext")
    if off is None or ext is None:
        return None
    return (int(off.get("x", 0)), int(off.get("y", 0)), int(ext.get("cx", 0)), int(ext.get("cy", 0)))


def _group_transform(grp, parent):
    xfrm = grp.find(P + "grpSpPr/" + A + "xfrm")
    box = _xfrm_box(xfrm)
    if box is None:
        return parent
    ox, oy, cx, cy = box
    ch_off = xfrm.find(A + "chOff")
    ch_ext = xfrm.find(A + "chExt")
    chx = int(ch_off.get("x", 0)) if ch_off is not None else ox
    chy = int(ch_off.get("y", 0)) if ch_off is not None else oy
    chw = int(ch_ext.get("cx", 0)) if ch_ext is not None else cx
    chh = int(ch_ext.get("cy", 0)) if ch_ext is not None else cy
    sx = float(cx) / chw if chw else 1.0
    sy = float(cy) / chh if chh else 1.0

    def tf(x, y, w, h):
        return parent(ox + (x - chx) * sx, oy + (y - chy) * sy, w * sx, h * sy)

    return tf


# ---------------------------------------------------------------- 텍스트


def _paragraph_lines(p):
    parts = []
    for el in p:
        if el.tag in (A + "r", A + "fld"):
            t = el.find(A + "t")
            if t is not None and t.text:
                parts.append(t.text)
        elif el.tag == A + "br":
            parts.append("\n")
    return [textnorm.clean_line(s) for s in "".join(parts).split("\n")]


def _body_lines(tx_body):
    lines = []
    if tx_body is None:
        return lines
    for p in tx_body.iter(A + "p"):
        lines.extend(s for s in _paragraph_lines(p) if s)
    return lines


def _max_size(tx_body):
    sizes = [int(r.get("sz")) for r in tx_body.iter(A + "rPr") if r.get("sz", "").isdigit()]
    return max(sizes) if sizes else None


def _table_rows(tbl):
    rows = []
    for tr in tbl.findall(A + "tr"):
        cells = []
        for tc in tr.findall(A + "tc"):
            if tc.get("hMerge") == "1":
                continue
            cells.append(" ".join(_body_lines(tc.find(A + "txBody"))))
        if any(cells):
            rows.append(cells)
    return rows


# ---------------------------------------------------------------- 차트·SmartArt


def _pt_values(parent, path):
    out = []
    for v in parent.iterfind(path):
        s = textnorm.clean_line(v.text or "")
        if s:
            out.append(s)
    return out


def _chart_info(root):
    chart = root.find(C + "chart")
    if chart is None:
        return None
    title = ""
    t = chart.find(C + "title")
    if t is not None:
        runs = [x.text or "" for x in t.iter(A + "t")]
        if not runs:
            runs = [x.text or "" for x in t.iter(C + "v")]
        title = textnorm.clean_line(" ".join(runs))
    series, categories = [], []
    for ser in chart.iter(C + "ser"):
        tx = ser.find(C + "tx")
        if tx is not None:
            names = _pt_values(tx, ".//" + C + "v") or [textnorm.clean_line("".join(x.text or "" for x in tx.iter(A + "t")))]
            name = " ".join(n for n in names if n)
            if name and name not in series:
                series.append(name)
        cat = ser.find(C + "cat")
        if cat is None:
            continue
        # 문자열 범주만 읽는다(strRef·strLit·multiLvlStrRef). 숫자 캐시는 넣지 않는다.
        found = _pt_values(cat, C + "strRef/" + C + "strCache/" + C + "pt/" + C + "v")
        found += _pt_values(cat, C + "strLit/" + C + "pt/" + C + "v")
        for lvl in cat.iterfind(C + "multiLvlStrRef/" + C + "multiLvlStrCache/" + C + "lvl"):
            found += _pt_values(lvl, C + "pt/" + C + "v")
        for name in found:
            if name not in categories:
                categories.append(name)
    return {"title": title, "series": series, "categories": categories}


def _smartart_lines(root):
    lines = []
    for pt in root.iter(DGM + "pt"):
        t = pt.find(DGM + "t")
        if t is not None:
            lines.extend(_body_lines(t))
    return lines


# ---------------------------------------------------------------- placeholder 위치 상속


class _Layouts(object):
    """layout·master의 placeholder 위치. xfrm이 없는 slide placeholder가 상속한다."""

    def __init__(self, zf):
        self.zf = zf
        self.cache = {}

    def _positions(self, part):
        if part in self.cache:
            return self.cache[part]
        by_idx, by_type, parent = {}, {}, None
        root = ooxml.read_xml(self.zf, part)
        if root is not None:
            for sp in root.iter(P + "sp"):
                ph = sp.find(P + "nvSpPr/" + P + "nvPr/" + P + "ph")
                box = _xfrm_box(sp.find(P + "spPr/" + A + "xfrm"))
                if ph is None or box is None:
                    continue
                if ph.get("idx"):
                    by_idx.setdefault(ph.get("idx"), box)
                by_type.setdefault(ph.get("type", "body"), box)
            for r in ooxml.read_rels(self.zf, part).values():
                if r["type"].endswith("/slideLayout") or r["type"].endswith("/slideMaster"):
                    parent = r["target"]
        self.cache[part] = (by_idx, by_type, parent)
        return self.cache[part]

    def lookup(self, start, ph):
        part, seen = start, set()
        while part and part not in seen:
            seen.add(part)
            by_idx, by_type, parent = self._positions(part)
            if ph.get("idx") and ph.get("idx") in by_idx:
                return by_idx[ph.get("idx")]
            if ph.get("type", "body") in by_type:
                return by_type[ph.get("type", "body")]
            part = parent
        return None


# ---------------------------------------------------------------- 슬라이드 읽기


class _Slide(object):
    def __init__(self, part):
        self.part = part
        self.items = []
        self.pictures = []
        self.warnings = []
        self.notes = ""
        self.hidden = False
        self.counter = 0

    def warn(self, code):
        if code not in self.warnings:
            self.warnings.append(code)

    def next_order(self):
        self.counter += 1
        return self.counter


def _read_slide(zf, part, layouts):
    s = _Slide(part)
    root = ooxml.read_xml(zf, part)
    if root is None:
        raise ooxml.OoxmlError("PARSE_ERROR")
    s.hidden = root.get("show") == "0"
    rels = ooxml.read_rels(zf, part)
    layout = None
    for r in rels.values():
        if r["type"].endswith("/slideLayout"):
            layout = r["target"]
    tree = root.find(P + "cSld/" + P + "spTree")
    if tree is not None:
        _walk(zf, s, tree, _identity, rels, layouts, layout)
    for target in ooxml.rels_of_type(rels, ooxml.REL_NOTES):
        s.notes = _notes_text(zf, target)
    return s


def _walk(zf, s, parent, tf, rels, layouts, layout):
    for el in parent:
        tag = el.tag
        if tag == _MC + "AlternateContent":
            choice = el.find(_MC + "Choice")
            if choice is None:
                choice = el.find(_MC + "Fallback")
            if choice is not None:
                _walk(zf, s, choice, tf, rels, layouts, layout)
        elif tag == P + "grpSp":
            before = len(s.items)
            _walk(zf, s, el, _group_transform(el, tf), rels, layouts, layout)
            if len(s.items) > before:
                s.warn("GROUP_SHAPE")
        elif tag == P + "sp":
            _read_shape(s, el, tf, layouts, layout)
        elif tag == P + "graphicFrame":
            _read_frame(zf, s, el, tf, rels)
        elif tag == P + "pic":
            blip = el.find(P + "blipFill/" + A + "blip")
            rid = blip.get(R + "embed") if blip is not None else None
            rel = rels.get(rid) if rid else None
            if rel and not rel["external"] and rel["target"] not in s.pictures:
                s.pictures.append(rel["target"])
        elif tag == P + "contentPart":
            s.warn("UNHANDLED_GRAPHIC")


def _read_shape(s, sp, tf, layouts, layout):
    lines = _body_lines(sp.find(P + "txBody"))
    if not lines:
        return
    ph = sp.find(P + "nvSpPr/" + P + "nvPr/" + P + "ph")
    ph_type = None
    if ph is not None:
        ph_type = ph.get("type", "body")
        if ph_type in SKIP_PLACEHOLDERS:
            return
    box = _xfrm_box(sp.find(P + "spPr/" + A + "xfrm"))
    if box is None and ph is not None and layout:
        box = layouts.lookup(layout, ph)
    box = tf(*(box or (0, 0, 0, 0)))
    s.items.append(_Item("text", box, s.next_order(), lines=lines, sz=_max_size(sp.find(P + "txBody")), ph=ph_type))


def _read_frame(zf, s, frame, tf, rels):
    box = tf(*(_xfrm_box(frame.find(P + "xfrm")) or (0, 0, 0, 0)))
    gd = frame.find(A + "graphic/" + A + "graphicData")
    uri = gd.get("uri") if gd is not None else ""
    if uri == ooxml.URI_TABLE:
        tbl = gd.find(A + "tbl")
        rows = _table_rows(tbl) if tbl is not None else []
        if rows:
            s.items.append(_Item("table", box, s.next_order(), rows=rows))
        return
    if uri == ooxml.URI_CHART:
        ref = gd.find(C + "chart")
        rel = rels.get(ref.get(R + "id")) if ref is not None else None
        root = ooxml.read_xml(zf, rel["target"]) if rel and not rel["external"] else None
        info = _chart_info(root) if root is not None else None
        if info is None:
            s.warn("UNHANDLED_GRAPHIC")
        else:
            s.items.append(_Item("chart", box, s.next_order(), chart=info))
        return
    if uri == ooxml.URI_DGM:
        s.warn("SMARTART")
        ids = gd.find(DGM + "relIds")
        rel = rels.get(ids.get(R + "dm")) if ids is not None else None
        root = ooxml.read_xml(zf, rel["target"]) if rel and not rel["external"] else None
        lines = _smartart_lines(root) if root is not None else []
        if lines:
            s.items.append(_Item("smartart", box, s.next_order(), lines=lines))
        return
    s.warn("UNHANDLED_GRAPHIC")


def _notes_text(zf, part):
    root = ooxml.read_xml(zf, part)
    if root is None:
        return ""
    lines = []
    for sp in root.iter(P + "sp"):
        ph = sp.find(P + "nvSpPr/" + P + "nvPr/" + P + "ph")
        if ph is not None and ph.get("type", "body") != "body":
            continue
        lines.extend(_body_lines(sp.find(P + "txBody")))
    return "\n".join(lines)


# ---------------------------------------------------------------- 제목


def _pick_title(items, slide_h):
    for it in items:
        if it.kind == "text" and it.ph in TITLE_PLACEHOLDERS:
            return it
    texts = [it for it in items if it.kind == "text"]
    if not texts:
        return None
    zone = [it for it in texts if it.y <= slide_h * TITLE_ZONE] or texts
    top = min(zone, key=lambda it: (it.y, it.x, it.order))
    sized = [it for it in zone if it.sz]
    if not sized:
        return top
    return min(sized, key=lambda it: (-it.sz, it.y, it.x, it.order))


# ---------------------------------------------------------------- 좌표 표 복원


def _is_cell(it, slide_w):
    return (
        len(it.lines) <= CELL_MAX_LINES
        and sum(len(x) for x in it.lines) <= CELL_MAX_CHARS
        and it.w <= CELL_MAX_WIDTH * slide_w
    )


def _cluster_rows(items, slide_h):
    """세로 중심이 가까운 상자끼리 잇고, 이어진 묶음을 한 행으로 본다(연결 요소)."""
    items = sorted(items, key=lambda i: (i.cy, i.x, i.order))
    parent = list(range(len(items)))

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for a in range(len(items)):
        for b in range(a + 1, len(items)):
            ia, ib = items[a], items[b]
            tol = max(0.35 * min(ia.h, ib.h), 0.002 * slide_h)
            if ib.cy - ia.cy > max(0.35 * ia.h, 0.002 * slide_h):
                break  # cy 순으로 정렬했으므로 뒤는 더 멀다
            if ib.cy - ia.cy <= tol:
                parent[find(b)] = find(a)
    groups = {}
    for k, it in enumerate(items):
        groups.setdefault(find(k), []).append(it)
    rows = sorted(groups.values(), key=lambda r: (min(i.cy for i in r), min(i.x for i in r)))
    return [sorted(r, key=lambda i: (i.x, i.order)) for r in rows]


def _match_anchor(x, anchors, tol):
    for k, a in enumerate(anchors):
        if abs(x - a) <= tol:
            return k
    return None


def _coordinate_tables(items, slide_w, slide_h):
    """낱개 텍스트 상자에서 좌표 표를 찾는다. 반환: (표 목록, 표에 쓰인 상자 id 집합)."""
    tol_x = 0.01 * slide_w
    runs = []
    for row in _cluster_rows([it for it in items if _is_cell(it, slide_w)], slide_h):
        remaining = list(row)
        top = min(i.y for i in row)
        for run in runs:
            if top - run["bottom"] > max(2 * run["row_h"], 0.03 * slide_h):
                continue
            taken, used = [], set()
            for it in remaining:
                k = _match_anchor(it.x, run["anchors"], tol_x)
                if k is not None and k not in used:
                    used.add(k)
                    taken.append(it)
            if len(used) < 2 or len(used) < 0.5 * len(run["anchors"]):
                continue
            # 표 가로 범위 안에 있는 새 x는 열로 추가한다(머리글이 병합된 표).
            for it in remaining:
                if it not in taken and run["left"] <= it.x < run["right"] and _match_anchor(it.x, run["anchors"], tol_x) is None:
                    run["anchors"].append(it.x)
                    taken.append(it)
            run["rows"].append(taken)
            run["bottom"] = max(i.y + i.h for i in taken)
            run["row_h"] = max(run["row_h"], max(i.h for i in taken))
            remaining = [i for i in remaining if i not in taken]
        if len(remaining) >= 2:
            runs.append({
                "anchors": [i.x for i in remaining],
                "rows": [remaining],
                "left": min(i.x for i in remaining),
                "right": max(i.x + i.w for i in remaining),
                "bottom": max(i.y + i.h for i in remaining),
                "row_h": max(i.h for i in remaining),
            })
    tables, used_ids = [], set()
    for run in runs:
        anchors = sorted(run["anchors"])
        support = [0] * len(anchors)
        for r in run["rows"]:
            for it in r:
                support[_match_anchor(it.x, anchors, tol_x)] += 1
        cols = [k for k, n in enumerate(support) if n >= 2]
        grid, cells = [], []
        for r in run["rows"]:
            by_col = {}
            for it in r:
                k = _match_anchor(it.x, anchors, tol_x)
                if k in cols and k not in by_col:
                    by_col[k] = it
            if len(by_col) >= 2:
                grid.append([" ".join(by_col[k].lines) if k in by_col else "" for k in cols])
                cells.extend(by_col.values())
        if (len(grid) >= 2 and len(cols) >= 3) or (len(grid) >= 3 and len(cols) >= 2):
            tables.append((grid, min(i.y for i in cells), min(i.x for i in cells), min(i.order for i in cells)))
            used_ids.update(id(i) for i in cells)
    return tables, used_ids


# ---------------------------------------------------------------- chunk 조립


def _arrange(s, slide_w, slide_h):
    """제목, 표에 들어가지 않은 낱개 요소, 좌표 표. 좌표 표 셀은 반복 문구 제거 대상이 아니다(표 데이터)."""
    title_item = _pick_title(s.items, slide_h)
    title = " ".join(title_item.lines) if title_item is not None else ""
    title = title if textnorm.keep_line(title) else ""
    loose = []
    for it in s.items:
        if it is title_item or it.kind not in ("text", "smartart"):
            continue
        lines = [x for x in it.lines if textnorm.keep_line(x)]
        if lines:
            it.lines = lines
            loose.append(it)
    tables, used = _coordinate_tables([i for i in loose if i.kind == "text"], slide_w, slide_h)
    return title, [it for it in loose if id(it) not in used], tables


def _build_unit(seq, s, arranged, boiler, images, limit):
    warnings = list(s.warnings)
    if s.hidden:
        warnings.append("HIDDEN_SLIDE")
    title, loose, coord_tables = arranged

    placed = []  # (y, x, order, kind, payload)
    for it in loose:
        lines = [x for x in it.lines if textnorm.line_key(x) not in boiler]
        if lines:
            placed.append((it.y, it.x, it.order, "lines", lines))
    for grid, y, x, order in coord_tables:
        placed.append((y, x, order, "table", grid))
    view_tables = []
    for it in s.items:
        if it.kind == "table":
            rows = [r for r in it.rows if not any(textnorm.is_always_removed(c) for c in r)]
            if rows:
                placed.append((it.y, it.x, it.order, "table", rows))
    placed.sort(key=lambda b: (b[0], b[1], b[2]))
    blocks = [(b[3], b[4]) for b in placed]
    body = []
    for kind, payload in blocks:
        if kind == "lines":
            body.extend(payload)
        else:
            view_tables.append(payload)

    charts = [it.chart for it in sorted(s.items, key=lambda i: (i.y, i.x, i.order)) if it.kind == "chart"]
    notes = s.notes if s.notes and not textnorm.is_trivial_note(s.notes) else ""
    notes = "\n".join(x for x in notes.split("\n") if textnorm.keep_line(x))

    content = sum(len(x) for x in body) + sum(len(c) for t in view_tables for r in t for c in r)
    content += sum(len(c["title"]) + sum(map(len, c["series"] + c["categories"])) for c in charts)
    if content < LOW_TEXT_CHARS:
        warnings.append("LOW_TEXT")

    text, truncated = textnorm.fit_chunk(title, blocks, charts, notes, limit)
    if truncated:
        warnings.append("TRUNCATED")
    return {
        "part_name": s.part,
        "seq": seq,
        "title": title,
        "text": text,
        "warnings": warnings,
        "images": images,
        "view": {"title": title, "body": body, "tables": view_tables, "notes": notes, "charts": charts},
    }


def slide_parts(zf):
    """presentation.xml의 sldIdLst 순서대로 슬라이드 파트 이름과 슬라이드 크기."""
    pres = ooxml.main_part(zf, "ppt/presentation.xml")
    root = ooxml.read_xml(zf, pres)
    if root is None:
        raise ooxml.OoxmlError("PARSE_ERROR")
    size = root.find(P + "sldSz")
    if size is not None:
        dims = (int(size.get("cx")), int(size.get("cy")))
    else:
        dims = DEFAULT_SLIDE_SIZE
    rels = ooxml.read_rels(zf, pres)
    parts = []
    lst = root.find(P + "sldIdLst")
    for sid in (lst if lst is not None else []):
        rel = rels.get(sid.get(R + "id"))
        if rel and rel["type"] == ooxml.REL_SLIDE and ooxml.has_part(zf, rel["target"]):
            parts.append(rel["target"])
    return parts, dims


def parse_pptx(data, cfg):
    zf = ooxml.open_zip(data)
    parts, (slide_w, slide_h) = slide_parts(zf)
    layouts = _Layouts(zf)
    slides = [_read_slide(zf, part, layouts) for part in parts]

    arranged = [_arrange(s, slide_w, slide_h) for s in slides]
    boiler = textnorm.boilerplate_keys(
        [[x for it in loose for x in it.lines] for _, loose, _ in arranged], cfg["parse"]["boilerplate_ratio"]
    )
    images = ooxml.collect_images(zf, [s.pictures for s in slides], cfg["parse"]["image_min_bytes"])
    limit = cfg["limits"]["chunk_char_limit"]
    units = [
        _build_unit(i + 1, s, arranged[i], boiler, images[i], limit) for i, s in enumerate(slides)
    ]
    return {"doc": ooxml.core_props(zf), "units": units}
