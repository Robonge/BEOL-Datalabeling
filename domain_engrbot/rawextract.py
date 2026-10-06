"""독립 경량 추출기(5.1절). labelbot 파서를 쓰지 않고 zipfile·xml.etree만으로 원본 bytes를 읽는다.

- 입력은 디코딩한 bytes다. 경로를 받지 않는다(CLAUDE.md). OOXML은 zipfile.ZipFile(io.BytesIO(b))로 연다.
- 형식별로 등록한다(EXTRACTORS, register). 등록되지 않은 형식은 L0이 L0_FORMAT_UNSUPPORTED로 기록한다.
- 이 모듈은 labelbot을 import하지 않는다(독립성 경계, 2절).

pptx 결과:
  {"kind": "pptx", "slides": [{"part", "index", "hidden", "shapes": [[줄, ...], ...], "placeholder_lines": [줄, ...],
                               "tables", "cells", "pictures": [{"sha256", "size"}]}]}
  - shapes: 도형·표 하나마다 단락 줄 목록. 반복 줄(바닥글) 판정에 쓴다. 표 셀 줄도 표 하나를 한 묶음으로 넣는다.
  - placeholder_lines: 슬라이드 번호·날짜 placeholder와 필드 글자. 커버리지 분모에서 빼려고 따로 둔다.
  - tables: 비지 않은 셀이 하나 이상인 a:tbl 수. cells: 비지 않은 셀 수(hMerge·vMerge 이어지는 칸 제외).
  - pictures: p:pic이 내장 참조하는 미디어의 해시와 크기(슬라이드 안 중복 제거).
docx 결과:
  {"kind": "docx", "lines": [줄, ...], "tables": 본문 직속 표 수, "pictures": [{"sha256", "size"}]}
"""
import hashlib
import io
import posixpath
import xml.etree.ElementTree as ET
import zipfile

OOXML_SIG = b"PK\x03\x04"
OLE_SIG = b"\xd0\xcf\x11\xe0"
OOXML_EXT = (".pptx", ".docx", ".xlsx")
OLE_EXT = (".ppt", ".doc", ".xls")

_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
_REL_BASE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
_SKIP_PH = ("sldNum", "dt")
_SKIP_FLD = ("slidenum", "datetime")

EXTRACTORS = {}


class RawError(Exception):
    def __init__(self, reason_code):
        Exception.__init__(self, reason_code)
        self.reason_code = reason_code


def register(ext, fn):
    EXTRACTORS[ext.lower()] = fn
    return fn


def supported(ext):
    return (ext or "").lower() in EXTRACTORS


def signature_reason(data, ext):
    """디코딩 직후 시그니처 독립 재확인. 맞으면 None, 아니면 사유 코드."""
    ext = (ext or "").lower()
    if ext in OOXML_EXT:
        if data.startswith(OOXML_SIG):
            return None
        if data.startswith(OLE_SIG):
            return "ENCRYPTED"
        return "NOT_OOXML"
    if ext in OLE_EXT:
        return "OLE_LEGACY"
    return None


def extract(ext, data):
    """등록된 추출기로 bytes를 읽는다. 등록되지 않았으면 RawError("FORMAT_UNSUPPORTED")."""
    fn = EXTRACTORS.get((ext or "").lower())
    if fn is None:
        raise RawError("FORMAT_UNSUPPORTED")
    return fn(data)


# ---- OOXML 공통 ---------------------------------------------------------------

def _zip(data):
    try:
        return zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise RawError("RAW_ZIP_INVALID")


def _read(zf, name):
    try:
        return zf.read(name)
    except KeyError:
        return None
    except (zipfile.BadZipFile, OSError, RuntimeError):
        raise RawError("RAW_ZIP_INVALID")


def _xml(zf, name):
    b = _read(zf, name)
    if b is None:
        return None
    try:
        return ET.fromstring(b)
    except ET.ParseError:
        raise RawError("RAW_XML_INVALID")


def _rels(zf, part):
    """{rId: (type, 패키지 안 파트 이름 또는 None(외부))}."""
    d, f = posixpath.split(part)
    root = _xml(zf, posixpath.join(d, "_rels", f + ".rels"))
    out = {}
    if root is None:
        return out
    for rel in root:
        target = rel.get("Target") or ""
        if rel.get("TargetMode") == "External":
            name = None
        elif target.startswith("/"):
            name = posixpath.normpath(target.lstrip("/"))
        else:
            name = posixpath.normpath(posixpath.join(d, target))
        out[rel.get("Id")] = (rel.get("Type") or "", name)
    return out


def _main_part(zf, default):
    for typ, name in _rels(zf, "").values():
        if typ == _REL_BASE + "officeDocument" and name:
            return name
    return default


def _children(el):
    """mc:AlternateContent는 Choice(없으면 Fallback) 한쪽만 따라간다. 같은 내용을 두 번 세지 않기 위해서다."""
    for ch in el:
        if ch.tag == _MC + "AlternateContent":
            pick = ch.find(_MC + "Choice")
            if pick is None:
                pick = ch.find(_MC + "Fallback")
            if pick is not None:
                for sub in _children(pick):
                    yield sub
        else:
            yield ch


def _walk(el):
    """전위 순회(AlternateContent 처리 포함)."""
    for ch in _children(el):
        yield ch
        for sub in _walk(ch):
            yield sub


def _media(zf, name, seen, out):
    if not name or name in seen:
        return
    seen.add(name)
    b = _read(zf, name)
    if b is None:
        return
    sha = hashlib.sha256(b).hexdigest()
    if all(p["sha256"] != sha for p in out):
        out.append({"sha256": sha, "size": len(b)})


# ---- pptx ---------------------------------------------------------------------

def _para_lines(p):
    """단락 하나 → 줄 목록과 placeholder 필드 글자. a:br은 줄바꿈이다."""
    parts, skipped = [], []

    def texts(el):
        return "".join(t.text or "" for t in el.iter(_A + "t"))

    for el in _children(p):
        if el.tag == _A + "br":
            parts.append("\n")
        elif el.tag == _A + "fld" and (el.get("type") or "").lower().startswith(_SKIP_FLD):
            skipped.append(texts(el))
        elif el.tag != _A + "pPr" and el.tag != _A + "endParaRPr":
            parts.append(texts(el))
    lines = [s.replace("\x0b", " ").strip() for s in "".join(parts).split("\n")]
    return [s for s in lines if s], [s for s in skipped if s.strip()]


def _body_lines(tx_body):
    lines, skipped = [], []
    if tx_body is None:
        return lines, skipped
    for p in _walk(tx_body):
        if p.tag == _A + "p":
            l, s = _para_lines(p)
            lines += l
            skipped += s
    return lines, skipped


def _cell_text_lines(tc):
    lines, _ = _body_lines(tc.find(_A + "txBody"))
    return lines


def _table(tbl):
    """반환: (셀 줄 목록, 비지 않은 셀 수). 병합으로 이어지는 칸(hMerge, vMerge)은 세지 않는다."""
    lines, cells = [], 0
    for tr in tbl.findall(_A + "tr"):
        for tc in tr.findall(_A + "tc"):
            if tc.get("hMerge") in ("1", "true") or tc.get("vMerge") in ("1", "true"):
                continue
            cl = _cell_text_lines(tc)
            if cl:
                cells += 1
                lines += cl
    return lines, cells


def _slide(zf, part, index):
    root = _xml(zf, part)
    if root is None:
        raise RawError("RAW_SLIDE_MISSING")
    rels = _rels(zf, part)
    s = {"part": part, "index": index, "hidden": root.get("show") in ("0", "false"), "shapes": [],
         "placeholder_lines": [], "tables": 0, "cells": 0, "pictures": []}
    tree = root.find(_P + "cSld/" + _P + "spTree")
    seen_media = set()
    for el in (_walk(tree) if tree is not None else ()):
        if el.tag == _P + "sp":
            ph = el.find(_P + "nvSpPr/" + _P + "nvPr/" + _P + "ph")
            lines, skipped = _body_lines(el.find(_P + "txBody"))
            if ph is not None and ph.get("type") in _SKIP_PH:
                s["placeholder_lines"] += lines + skipped
                continue
            s["placeholder_lines"] += skipped
            if lines:
                s["shapes"].append(lines)
        elif el.tag == _A + "tbl":
            lines, cells = _table(el)
            if cells:
                s["tables"] += 1
                s["cells"] += cells
                s["shapes"].append(lines)
        elif el.tag == _P + "pic":
            blip = el.find(_P + "blipFill/" + _A + "blip")
            rid = blip.get(_R + "embed") if blip is not None else None
            if rid and rid in rels:
                _media(zf, rels[rid][1], seen_media, s["pictures"])
    return s


def extract_pptx(data):
    zf = _zip(data)
    pres = _main_part(zf, "ppt/presentation.xml")
    root = _xml(zf, pres)
    if root is None:
        raise RawError("RAW_PRESENTATION_MISSING")
    rels = _rels(zf, pres)
    parts = []
    lst = root.find(_P + "sldIdLst")
    for sid in (lst if lst is not None else ()):
        rel = rels.get(sid.get(_R + "id"))
        if rel and rel[0] == _REL_BASE + "slide" and rel[1] and _read(zf, rel[1]) is not None:
            parts.append(rel[1])
    return {"kind": "pptx", "slides": [_slide(zf, p, i) for i, p in enumerate(parts, 1)]}


# ---- docx ---------------------------------------------------------------------

def _w_para_lines(p):
    parts = []
    for el in p.iter():
        if el.tag == _W + "t":
            parts.append(el.text or "")
        elif el.tag == _W + "tab":
            parts.append(" ")
        elif el.tag in (_W + "br", _W + "cr"):
            parts.append("\n")
    return [s.strip() for s in "".join(parts).split("\n") if s.strip()]


def extract_docx(data):
    zf = _zip(data)
    doc = _main_part(zf, "word/document.xml")
    root = _xml(zf, doc)
    if root is None:
        raise RawError("RAW_DOCUMENT_MISSING")
    body = root.find(_W + "body")
    lines, tables, pictures = [], 0, []
    if body is not None:
        for p in body.iter(_W + "p"):
            lines += _w_para_lines(p)
        for el in _children(body):
            if el.tag == _W + "tbl" and any((t.text or "").strip() for t in el.iter(_W + "t")):
                tables += 1
        rels = _rels(zf, doc)
        seen = set()
        for blip in body.iter(_A + "blip"):
            rid = blip.get(_R + "embed")
            if rid and rid in rels:
                _media(zf, rels[rid][1], seen, pictures)
    return {"kind": "docx", "lines": lines, "tables": tables, "pictures": pictures}


register(".pptx", extract_pptx)
register(".docx", extract_docx)
