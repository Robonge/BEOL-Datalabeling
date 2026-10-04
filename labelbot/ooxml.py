"""OOXML 공통 도구: bytes에서 zip 열기, XML 파트 읽기, 관계(.rels) 해석, 네임스페이스 상수.

경로를 받는 파서는 쓰지 않는다(CLAUDE.md). 모든 입력은 디코딩한 bytes다.
"""
import hashlib
import io
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "dgm": "http://schemas.openxmlformats.org/drawingml/2006/diagram",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
}

A = "{%s}" % NS["a"]
P = "{%s}" % NS["p"]
R = "{%s}" % NS["r"]
C = "{%s}" % NS["c"]
DGM = "{%s}" % NS["dgm"]
W = "{%s}" % NS["w"]

REL_BASE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
REL_SLIDE = REL_BASE + "slide"
REL_NOTES = REL_BASE + "notesSlide"
REL_OFFICE_DOC = REL_BASE + "officeDocument"

URI_TABLE = "http://schemas.openxmlformats.org/drawingml/2006/table"
URI_CHART = "http://schemas.openxmlformats.org/drawingml/2006/chart"
URI_DGM = "http://schemas.openxmlformats.org/drawingml/2006/diagram"

_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


class OoxmlError(Exception):
    def __init__(self, reason_code):
        Exception.__init__(self, reason_code)
        self.reason_code = reason_code


def open_zip(data):
    """bytes를 zip으로 연다. 시그니처는 맞는데 zip이 깨졌으면 PARSE_ERROR."""
    try:
        return zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise OoxmlError("PARSE_ERROR")


def has_part(zf, name):
    try:
        zf.getinfo(name)
        return True
    except KeyError:
        return False


def read_bytes(zf, name):
    try:
        return zf.read(name)
    except KeyError:
        return None


def read_xml(zf, name):
    """파트를 XML 요소로 읽는다. 없으면 None."""
    b = read_bytes(zf, name)
    if b is None:
        return None
    try:
        return ET.fromstring(b)
    except ET.ParseError:
        raise OoxmlError("PARSE_ERROR")


def rels_path(part):
    d, f = posixpath.split(part)
    return posixpath.join(d, "_rels", f + ".rels")


def resolve_target(part, target):
    """관계 Target을 패키지 안 절대 파트 이름으로 바꾼다('/ppt/x' 절대 경로와 '../x' 상대 경로 모두)."""
    if target.startswith("/"):
        return posixpath.normpath(target.lstrip("/"))
    return posixpath.normpath(posixpath.join(posixpath.dirname(part), target))


def read_rels(zf, part):
    """{rId: {"type": str, "target": 파트 이름, "external": bool}}. rels가 없으면 빈 dict."""
    root = read_xml(zf, rels_path(part))
    out = {}
    if root is None:
        return out
    for rel in root:
        rid = rel.get("Id")
        target = rel.get("Target") or ""
        external = rel.get("TargetMode") == "External"
        out[rid] = {
            "type": rel.get("Type") or "",
            "target": target if external else resolve_target(part, target),
            "external": external,
        }
    return out


def rels_of_type(rels, rel_type):
    return [r["target"] for r in rels.values() if r["type"] == rel_type and not r["external"]]


def main_part(zf, default):
    """_rels/.rels의 officeDocument 대상. 없으면 default."""
    for r in read_rels(zf, "").values():
        if r["type"] == REL_OFFICE_DOC:
            return r["target"]
    return default


def _date(s):
    m = _DATE.match((s or "").strip())
    return m.group(1) if m else None


def _text(el):
    if el is None or el.text is None:
        return None
    s = el.text.strip()
    return s or None


def core_props(zf):
    """docProps/core.xml의 제목·작성자·작성/수정 날짜(YYYY-MM-DD)."""
    root = read_xml(zf, "docProps/core.xml")
    if root is None:
        return {"title": None, "author": None, "created": None, "modified": None}
    return {
        "title": _text(root.find("dc:title", NS)),
        "author": _text(root.find("dc:creator", NS)),
        "created": _date(_text(root.find("dcterms:created", NS))),
        "modified": _date(_text(root.find("dcterms:modified", NS))),
    }


def image_ext(part):
    ext = posixpath.splitext(part)[1].lower().lstrip(".")
    return "jpg" if ext == "jpeg" else (ext or "bin")


def collect_images(zf, targets_per_unit, min_bytes):
    """단위별 이미지 목록. 파일 안 해시 중복 제거, 최소 크기 미만과 여러 단위에 반복되는 장식 이미지는 뺀다."""
    found_per_unit, seen_on = [], {}
    for idx, targets in enumerate(targets_per_unit):
        found = []
        for target in targets:
            data = read_bytes(zf, target)
            if not data:
                continue
            sha = hashlib.sha256(data).hexdigest()
            seen_on.setdefault(sha, set()).add(idx)
            if all(f["sha256"] != sha for f in found):
                found.append({"sha256": sha, "ext": image_ext(target), "data": data})
        found_per_unit.append(found)
    return [
        [img for img in found if len(img["data"]) >= min_bytes and len(seen_on[img["sha256"]]) == 1]
        for found in found_per_unit
    ]
