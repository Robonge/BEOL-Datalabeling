"""L0 파싱 충실도(5.1절). 파일 하나씩, 독립 추출기(rawextract) 결과와 파서 출력(ParsedUnit)을 대조한다.

- 원본 bytes는 ctx.bundle.loader.source_bytes로만 얻는다. 원본 경로를 열지 않는다.
- record 범위 코드는 record_id(=unit_id)를 달아 낸다. file 범위 코드는 record_id 없이 낸다.
- evidence에는 숫자와 코드만 넣는다. 본문, 파일명, 경로를 넣지 않는다.
- 커버리지는 순서와 무관한 글자 다중집합 비교다(NFKC, 공백 제거). 반복 줄과 슬라이드 번호·날짜 placeholder는
  분모에서 뺀다(파서가 반복 문구를 지우기 때문이다). 노트·차트처럼 파서 쪽에만 있는 글자는 커버리지를 낮추지 않는다.
"""
import collections
import hashlib
import re
import unicodedata

from qabot import model, rawextract
from qabot.registry import Check, register

SIGNATURE_REASONS = ("ENCRYPTED", "NOT_OOXML", "OLE_LEGACY")
_WS = re.compile(r"\s+")
# 파서 본문에서 뺄 구조 표지(labelbot chunk 텍스트의 '# 제목', '[표]', '[노트]', '[차트]' 줄)
_MARKER_LINE = re.compile(r"^\s*\[(표|노트|차트)\]\s*$")
_TITLE_MARK = re.compile(r"^\s*#\s?")
_CHART_KEY = re.compile(r"^\s*(제목|계열|범주):\s?")


def _chars(text):
    """NFKC 후 공백을 뺀 글자 다중집합."""
    return collections.Counter(_WS.sub("", model.nfkc(text)))


def line_key(s):
    return _WS.sub(" ", model.nfc(s)).strip()


def body_text(unit):
    """빈 unit 판정용 파서 본문: 구조 표지를 뺀 텍스트."""
    out = []
    for line in (unit.get("text") or "").split("\n"):
        if _MARKER_LINE.match(line):
            continue
        line = _CHART_KEY.sub("", _TITLE_MARK.sub("", line, count=1), count=1)
        out.append(line)
    return "\n".join(out)


def body_chars(unit):
    return len(_WS.sub("", body_text(unit)))


def is_garbled_char(ch):
    if ch in "\t\n\r":
        return False
    if ch == "�":
        return True
    cat = unicodedata.category(ch)
    return cat in ("Cc", "Co", "Cn", "Cs")


def garbled_ratio(text):
    if not text:
        return 0.0
    return sum(1 for ch in text if is_garbled_char(ch)) / float(len(text))


def coverage(raw_counter, parsed_counter):
    total = sum(raw_counter.values())
    if not total:
        return None
    hit = sum(min(n, parsed_counter.get(c, 0)) for c, n in raw_counter.items())
    return hit / float(total)


def repeated_keys(slides, ratio):
    """파일의 ratio 이상 슬라이드(최소 2장)에 나오는 줄 키 집합."""
    n = len(slides)
    need = max(2, ratio * n)
    counts = collections.Counter()
    for s in slides:
        counts.update({line_key(l) for shape in s["shapes"] for l in shape if l.strip()})
    return {k for k, c in counts.items() if c >= need}


def raw_slide_text(slide, repeated):
    """커버리지 분모용 원본 텍스트: 반복 줄을 뺀 도형·표 줄. placeholder 줄은 이미 빠져 있다."""
    return "\n".join(l for shape in slide["shapes"] for l in shape if line_key(l) not in repeated)


def _r(x):
    return round(x, 4)


@register
class ParseFidelityCheck(Check):
    id = "l0.parse_fidelity"
    layer = "L0"
    scope = "file"

    def run(self, target, ctx):
        cfg = ctx.policy["l0"]
        src = target.source
        ext = (src.get("ext") or "").lower()
        if src.get("status") == "failed":
            return [self._failed_issue(src, ext)]
        if not rawextract.supported(ext):
            return [model.issue("L0_FORMAT_UNSUPPORTED", evidence={"ext": ext})]
        try:
            data = ctx.bundle.loader.source_bytes(src)
        except model.LoaderError as e:
            return [model.issue("L0_SOURCE_UNREADABLE", evidence={"reason_code": e.reason_code})]
        if not data:
            return [model.issue("L0_SOURCE_UNREADABLE", evidence={"reason_code": "EMPTY"})]
        reason = rawextract.signature_reason(data, ext)
        if reason:
            return [model.issue("L0_SIGNATURE_MISMATCH", evidence={"reason_code": reason})]
        try:
            raw = rawextract.extract(ext, data)
        except rawextract.RawError as e:
            return [model.issue("L0_SOURCE_UNREADABLE", evidence={"reason_code": e.reason_code})]
        units = target.units
        issues = []
        for u in units:
            issues += self._unit_common(u, ctx, cfg)
        if raw["kind"] == "pptx":
            issues += self._pptx(raw, units, ctx, cfg)
        elif raw["kind"] == "docx":
            issues += self._docx(raw, units, cfg)
        if units:
            empty = sum(1 for u in units if body_chars(u) < cfg["empty_chars"])
            ratio = empty / float(len(units))
            if ratio >= cfg["empty_ratio_major"]:
                issues.append(model.issue("L0_EMPTY_RATIO_HIGH", evidence={
                    "empty_units": empty, "units": len(units), "ratio": _r(ratio)}))
        return issues

    # ---- 파일 상태 ---------------------------------------------------------

    @staticmethod
    def _failed_issue(src, ext):
        code = src.get("reason_code") or "UNKNOWN"
        if code in SIGNATURE_REASONS:
            return model.issue("L0_SIGNATURE_MISMATCH", evidence={"reason_code": code, "source_status": "failed"})
        if code == "UNSUPPORTED_FORMAT" and not rawextract.supported(ext):
            return model.issue("L0_FORMAT_UNSUPPORTED", evidence={"ext": ext, "source_status": "failed"})
        return model.issue("L0_PARSE_FAILED", evidence={"reason_code": code})

    # ---- 형식 공통(unit 단위) ------------------------------------------------

    def _unit_common(self, u, ctx, cfg):
        rid = u["unit_id"]
        out = []
        text = u.get("text") or ""
        ratio = garbled_ratio(text)
        if ratio >= cfg["garbled_major"] or ratio >= cfg["garbled_minor"]:
            sev = "major" if ratio >= cfg["garbled_major"] else "minor"
            out.append(model.issue("L0_GARBLED_TEXT", severity=sev, record_id=rid, evidence={
                "ratio": _r(ratio), "chars": len(text)}))
        wsev = cfg["warning_severity"]
        for w in sorted(set(x for x in (u.get("warnings") or []) if isinstance(x, str))):
            out.append(model.issue("L0_PARSER_WARNING", severity=wsev.get(w, wsev.get("*", "info")), record_id=rid,
                                   evidence={"warning": w}))
        for n, img in enumerate(u.get("images") or []):
            reason = self._image_ref_problem(img, ctx, cfg)
            if reason:
                out.append(model.issue("L0_IMAGE_REF_BROKEN", record_id=rid, evidence={
                    "image_index": n, "reason_code": reason}))
        return out

    @staticmethod
    def _image_ref_problem(img, ctx, cfg):
        if not isinstance(img, dict) or not img.get("rel_file"):
            return "REF_MISSING"
        try:
            b = ctx.bundle.loader.image_bytes(img)
        except model.LoaderError as e:
            return e.reason_code
        if not b:
            return "EMPTY"
        if cfg["verify_image_hash"] and hashlib.sha256(b).hexdigest() != img.get("image_id"):
            return "HASH_MISMATCH"
        return None

    # ---- pptx ---------------------------------------------------------------

    def _pptx(self, raw, units, ctx, cfg):
        slides = raw["slides"]
        out = []
        if len(slides) != len(units):
            out.append(model.issue("L0_PAGE_COUNT_MISMATCH", evidence={
                "raw_slides": len(slides), "units": len(units),
                "hidden_slides": sum(1 for s in slides if s["hidden"])}))
        by_part = {s["part"]: s for s in slides}
        repeated = repeated_keys(slides, cfg["repeated_line_ratio"])
        media_slides = collections.Counter()
        for s in slides:
            media_slides.update({p["sha256"] for p in s["pictures"]})
        for u in units:
            s = by_part.get(u.get("part_name"))
            if s is None and not u.get("part_name"):
                seq = u.get("seq")
                s = slides[seq - 1] if isinstance(seq, int) and 1 <= seq <= len(slides) else None
            if s is None:
                continue  # 원본에 대응 슬라이드가 없다. 슬라이드 수 비교가 잡는다
            out += self._slide_unit(u, s, repeated, media_slides, cfg)
        return out

    def _slide_unit(self, u, s, repeated, media_slides, cfg):
        rid = u["unit_id"]
        out = []
        raw_counter = _chars(raw_slide_text(s, repeated))
        raw_n = sum(raw_counter.values())
        parsed_n = body_chars(u)
        images = u.get("images") or []
        parsed_empty = parsed_n < cfg["empty_chars"]
        if parsed_empty and raw_n >= cfg["min_raw_chars"]:
            out.append(model.issue("L0_EMPTY_UNIT", record_id=rid, evidence={
                "parsed_chars": parsed_n, "raw_chars": raw_n}))
        elif parsed_empty and raw_n < cfg["min_raw_chars"] and (images or s["pictures"]):
            out.append(model.issue("L0_IMAGE_ONLY_UNIT", record_id=rid, evidence={
                "raw_pictures": len(s["pictures"]), "unit_images": len(images)}))
        elif raw_n >= cfg["min_raw_chars"]:
            cov = coverage(raw_counter, _chars(u.get("text") or ""))
            if cov < cfg["coverage_minor"]:
                sev = "major" if cov < cfg["coverage_major"] else "minor"
                out.append(model.issue("L0_TEXT_COVERAGE_LOW", severity=sev, record_id=rid, evidence={
                    "coverage": _r(cov), "raw_chars": raw_n}))
        tables = u.get("tables") or []
        if len(tables) < s["tables"]:
            out.append(model.issue("L0_TABLE_LOST", record_id=rid, evidence={
                "raw_tables": s["tables"], "parsed_tables": len(tables)}))
        if s["cells"]:
            cells = sum(1 for t in tables for row in (t or []) for c in (row or [])
                        if isinstance(c, str) and c.strip())
            ratio = cells / float(s["cells"])
            if ratio < cfg["cell_ratio_minor"]:
                out.append(model.issue("L0_TABLE_CELLS_LOST", record_id=rid, evidence={
                    "raw_cells": s["cells"], "parsed_cells": cells, "ratio": _r(ratio)}))
        raw_media = {p["sha256"] for p in s["pictures"]}
        bad = [n for n, img in enumerate(images) if isinstance(img, dict) and img.get("image_id") not in raw_media]
        if bad:
            out.append(model.issue("L0_IMAGE_LINK_MISMATCH", record_id=rid, evidence={
                "unit_images": len(images), "not_on_slide": len(bad)}))
        if not images:
            keep = [p for p in s["pictures"] if p["size"] >= cfg["image_min_bytes"] and media_slides[p["sha256"]] == 1]
            if keep:
                out.append(model.issue("L0_IMAGE_DROPPED", record_id=rid, evidence={"raw_pictures": len(keep)}))
        return out

    # ---- docx(파일 단위) ------------------------------------------------------

    def _docx(self, raw, units, cfg):
        out = []
        raw_counter = _chars("\n".join(raw["lines"]))
        raw_n = sum(raw_counter.values())
        if units and raw_n >= cfg["min_raw_chars"]:
            parsed = collections.Counter()
            for u in units:
                parsed.update(_chars(u.get("text") or ""))
            cov = coverage(raw_counter, parsed)
            if cov < cfg["coverage_minor"]:
                sev = "major" if cov < cfg["coverage_major"] else "minor"
                out.append(model.issue("L0_TEXT_COVERAGE_LOW", severity=sev, evidence={
                    "coverage": _r(cov), "raw_chars": raw_n}))
        parsed_tables = sum(len(u.get("tables") or []) for u in units)
        if parsed_tables < raw["tables"]:
            out.append(model.issue("L0_TABLE_LOST", evidence={"raw_tables": raw["tables"],
                                                              "parsed_tables": parsed_tables}))
        if not any(u.get("images") for u in units):
            keep = [p for p in raw["pictures"] if p["size"] >= cfg["image_min_bytes"]]
            if keep:
                out.append(model.issue("L0_IMAGE_DROPPED", evidence={"raw_pictures": len(keep)}))
        return out
