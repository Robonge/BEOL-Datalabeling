"""chunk 방식 선택: 설정(chunking.method)과 확장자로 파서를 고른다(PRD FR-1).

방식을 추가할 때는 METHODS에 등록만 하면 되고, 호출하는 쪽(ingest.parse_files)은 바뀌지 않는다.
"""
import xml.etree.ElementTree as ET
import zipfile

from labelbot import docx_parser, ooxml, pptx_parser
from labelbot.ingest import signature_reason

# method -> {확장자: 파서}. "slide"는 각 형식의 자연 단위다: pptx는 슬라이드, docx는 제목 스타일 섹션.
METHODS = {
    "slide": {".pptx": pptx_parser.parse_pptx, ".docx": docx_parser.parse_docx},
}


class ChunkError(Exception):
    def __init__(self, reason_code):
        Exception.__init__(self, reason_code)
        self.reason_code = reason_code


def parse_document(ext, data, cfg):
    """bytes를 파싱해 {"doc": {...}, "units": [...]}를 돌려준다. 실패하면 reason_code가 있는 ChunkError."""
    ext = (ext or "").lower()
    method = cfg["chunking"]["method"]
    parsers = METHODS.get(method)
    if parsers is None:
        raise ChunkError("UNSUPPORTED_CHUNK_METHOD")
    parser = parsers.get(ext)
    if parser is None:
        raise ChunkError("UNSUPPORTED_FORMAT")
    reason = signature_reason(data, ext)
    if reason:
        raise ChunkError(reason)
    try:
        return parser(data, cfg)
    except ooxml.OoxmlError as e:
        raise ChunkError(e.reason_code)
    except (zipfile.BadZipFile, ET.ParseError, KeyError, ValueError, TypeError, IndexError, AttributeError):
        raise ChunkError("PARSE_ERROR")
