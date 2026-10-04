"""구조 통계만 내는 probe. 본문 텍스트는 절대 넣지 않는다(개수·스타일 ID·불리언만)."""
import io
import zipfile

from labelbot import ooxml
from labelbot.docx_parser import heading_styles
from labelbot.ingest import signature_reason
from labelbot.ooxml import A, P, W
from labelbot.pptx_parser import slide_parts


def _pptx_stats(zf):
    parts, (w, h) = slide_parts(zf)
    st = {
        "slides": len(parts),
        "slide_size": [w, h],
        "hidden_slides": 0,
        "group_shapes": 0,
        "tables": 0,
        "charts": 0,
        "smartart": 0,
        "other_graphic_frames": 0,
        "pictures": 0,
        "text_shapes": 0,
        "slides_with_notes": 0,
    }
    for part in parts:
        root = ooxml.read_xml(zf, part)
        if root is None:
            continue
        if root.get("show") == "0":
            st["hidden_slides"] += 1
        st["group_shapes"] += sum(1 for _ in root.iter(P + "grpSp"))
        st["pictures"] += sum(1 for _ in root.iter(P + "pic"))
        st["text_shapes"] += sum(1 for sp in root.iter(P + "sp") if sp.find(P + "txBody") is not None)
        for gd in root.iter(A + "graphicData"):
            uri = gd.get("uri")
            if uri == ooxml.URI_TABLE:
                st["tables"] += 1
            elif uri == ooxml.URI_CHART:
                st["charts"] += 1
            elif uri == ooxml.URI_DGM:
                st["smartart"] += 1
            else:
                st["other_graphic_frames"] += 1
        if ooxml.rels_of_type(ooxml.read_rels(zf, part), ooxml.REL_NOTES):
            st["slides_with_notes"] += 1
    return st


def _docx_stats(zf):
    part = ooxml.main_part(zf, "word/document.xml")
    root = ooxml.read_xml(zf, part)
    headings = heading_styles(zf)
    usage = {}
    paragraphs = tables = 0
    if root is not None:
        for p in root.iter(W + "p"):
            paragraphs += 1
            ps = p.find(W + "pPr/" + W + "pStyle")
            sid = ps.get(W + "val") if ps is not None else None
            if sid in headings:
                usage[sid] = usage.get(sid, 0) + 1
        tables = sum(1 for _ in root.iter(W + "tbl"))
    return {
        "paragraphs": paragraphs,
        "tables": tables,
        "pictures": sum(1 for _ in root.iter(A + "blip")) if root is not None else 0,
        "heading_styles_defined": sorted(headings),
        "heading_style_usage": dict(sorted(usage.items())),
    }


def probe_bytes(data, ext):
    """파일 구조 통계. 본문·제목·노트 텍스트는 넣지 않는다."""
    ext = (ext or "").lower()
    out = {"ext": ext, "size": len(data), "signature": signature_reason(data, ext), "zip_ok": False}
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        out["zip_ok"] = zf.testzip() is None
        out["parts"] = len(zf.namelist())
        out["media_parts"] = sum(1 for n in zf.namelist() if "/media/" in n)
        if ext == ".pptx":
            out.update(_pptx_stats(zf))
        elif ext == ".docx":
            out.update(_docx_stats(zf))
    except (zipfile.BadZipFile, ooxml.OoxmlError) as e:
        out["error"] = getattr(e, "reason_code", "NOT_OOXML")
    return out
