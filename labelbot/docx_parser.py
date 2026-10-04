"""docx 파서: 제목 스타일(Heading 1.., 제목 1..) 단위 섹션 = 단위 1개. 제목 스타일이 없으면 일정 길이로 나눈다.

bytes만 받는다(CLAUDE.md). 대상 대부분이 pptx이므로 기본 수준으로 둔다(PRD FR-1).
"""
import re

from labelbot import ooxml, textnorm
from labelbot.ooxml import A, R, W

FIXED_SPLIT_CHARS = 3000
TITLE_MAX_CHARS = 80
LOW_TEXT_CHARS = 20
_HEADING = re.compile(r"^(heading|제목)\s*[1-9]$", re.I)


def _outline_level(ppr):
    """개요 수준 0~8이면 제목이다. 9는 본문 수준."""
    lvl = ppr.find(W + "outlineLvl") if ppr is not None else None
    val = lvl.get(W + "val", "") if lvl is not None else ""
    return val.isdigit() and int(val) < 9


def heading_styles(zf):
    """제목 스타일로 볼 styleId 집합: 이름·ID가 Heading N/제목 N이거나 개요 수준(outlineLvl)이 있는 스타일."""
    root = ooxml.read_xml(zf, "word/styles.xml")
    out = set()
    if root is None:
        return out
    for st in root.iter(W + "style"):
        if st.get(W + "type") != "paragraph":
            continue
        sid = st.get(W + "styleId") or ""
        name_el = st.find(W + "name")
        name = name_el.get(W + "val") if name_el is not None else ""
        if _HEADING.match(sid) or _HEADING.match(name or "") or _outline_level(st.find(W + "pPr")):
            out.add(sid)
    return out


def _para_text(p):
    parts = []
    for el in p.iter():
        if el.tag == W + "t" and el.text:
            parts.append(el.text)
        elif el.tag == W + "tab":
            parts.append(" ")
        elif el.tag in (W + "br", W + "cr"):
            parts.append("\n")
    return [s for s in (textnorm.clean_line(x) for x in "".join(parts).split("\n")) if s]


def _is_heading(p, headings):
    ppr = p.find(W + "pPr")
    if ppr is None:
        return False
    st = ppr.find(W + "pStyle")
    if st is not None and st.get(W + "val") in headings:
        return True
    return _outline_level(ppr)


def _table_rows(tbl):
    rows = []
    for tr in tbl.findall(W + "tr"):
        cells = [" ".join(line for p in tc.iter(W + "p") for line in _para_text(p)) for tc in tr.findall(W + "tc")]
        if any(cells) and not any(textnorm.is_always_removed(c) for c in cells):
            rows.append(cells)
    return rows


def _images(p, rels):
    out = []
    for blip in p.iter(A + "blip"):
        rel = rels.get(blip.get(R + "embed"))
        if rel and not rel["external"] and rel["target"] not in out:
            out.append(rel["target"])
    return out


def _blocks(body, headings, rels):
    """본문 요소를 순서대로: ("heading", 텍스트), ("lines", [str]), ("table", [[셀]]), 이미지 대상."""
    for el in body:
        if el.tag == W + "p":
            lines = [x for x in _para_text(el) if textnorm.keep_line(x)]
            if lines and _is_heading(el, headings):
                yield "heading", " ".join(lines), _images(el, rels)
            else:
                yield "lines", lines, _images(el, rels)
        elif el.tag == W + "tbl":
            yield "table", _table_rows(el), _images(el, rels)
        elif el.tag == W + "sdt":
            content = el.find(W + "sdtContent")
            if content is not None:
                for b in _blocks(content, headings, rels):
                    yield b


def _sections(blocks, doc_title):
    sections = []
    cur = None
    for kind, payload, imgs in blocks:
        if kind == "heading":
            cur = {"title": payload, "blocks": [], "images": list(imgs)}
            sections.append(cur)
            continue
        if cur is None:
            cur = {"title": doc_title or "", "blocks": [], "images": []}
            sections.append(cur)
        if payload:
            cur["blocks"].append((kind, payload))
        cur["images"].extend(imgs)
    return [s for s in sections if s["blocks"] or s["title"]]


def _fixed_sections(blocks):
    """제목 스타일이 없을 때 약 FIXED_SPLIT_CHARS 글자 단위로 나눈다. 표는 쪼개지 않는다."""
    sections, cur, size = [], None, 0
    for kind, payload, imgs in blocks:
        n = sum(len(x) for x in payload) if kind == "lines" else sum(len(c) for r in payload for c in r)
        if cur is None or (size and size + n > FIXED_SPLIT_CHARS):
            cur = {"title": "", "blocks": [], "images": []}
            sections.append(cur)
            size = 0
        if payload:
            cur["blocks"].append((kind, payload))
            size += n
        cur["images"].extend(imgs)
    for s in sections:
        first = next((b[1][0] if b[0] == "lines" else " | ".join(b[1][0]) for b in s["blocks"] if b[1]), "")
        s["title"] = first[:TITLE_MAX_CHARS]
    return [s for s in sections if s["blocks"]]


def parse_docx(data, cfg):
    zf = ooxml.open_zip(data)
    part = ooxml.main_part(zf, "word/document.xml")
    root = ooxml.read_xml(zf, part)
    if root is None:
        raise ooxml.OoxmlError("PARSE_ERROR")
    body = root.find(W + "body")
    if body is None:
        raise ooxml.OoxmlError("PARSE_ERROR")
    doc = ooxml.core_props(zf)
    headings = heading_styles(zf)
    blocks = list(_blocks(body, headings, ooxml.read_rels(zf, part)))
    if any(kind == "heading" for kind, _, _ in blocks):
        sections = _sections(blocks, doc["title"])
    else:
        sections = _fixed_sections(blocks)

    images = ooxml.collect_images(zf, [s["images"] for s in sections], cfg["parse"]["image_min_bytes"])
    limit = cfg["limits"]["chunk_char_limit"]
    units = []
    for i, s in enumerate(sections):
        body_lines = [x for kind, payload in s["blocks"] if kind == "lines" for x in payload]
        tables = [payload for kind, payload in s["blocks"] if kind == "table"]
        text, truncated = textnorm.fit_chunk(s["title"], s["blocks"], [], "", limit)
        warnings = []
        if sum(len(x) for x in body_lines) + sum(len(c) for t in tables for r in t for c in r) < LOW_TEXT_CHARS:
            warnings.append("LOW_TEXT")
        if truncated:
            warnings.append("TRUNCATED")
        units.append({
            "part_name": "section-%03d" % (i + 1),
            "seq": i + 1,
            "title": s["title"],
            "text": text,
            "warnings": warnings,
            "images": images[i],
            "view": {"title": s["title"], "body": body_lines, "tables": tables, "notes": "", "charts": []},
        })
    return {"doc": doc, "units": units}
