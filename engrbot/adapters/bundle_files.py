"""jsonl 번들 폴더 → Bundle. fixture나 다른 라벨러의 출력을 붙일 때 쓴다.

폴더 구성:
  bundle.json        {"labeler_run_id": "...", "taxonomy": {...스냅샷}}
  sources.jsonl      SourceRef 한 줄씩. b64_ref는 이 폴더 기준 상대 경로(.b64)
  units.jsonl        ParsedUnit 한 줄씩. images[].rel_file도 이 폴더 기준
  records.jsonl      LabelRecord 한 줄씩
"""
import os

from engrbot import io, model


class FilesLoader(object):
    def __init__(self, root):
        self.root = root

    def _path(self, rel):
        p = os.path.normpath(os.path.join(self.root, rel or ""))
        if not rel or os.path.commonpath([os.path.abspath(p), os.path.abspath(self.root)]) != os.path.abspath(self.root):
            raise model.LoaderError("REF_OUTSIDE_BUNDLE")
        return p

    def source_bytes(self, source):
        return io.load_b64_file(self._path(source.get("b64_ref")))

    def image_bytes(self, image):
        return io.load_b64_file(self._path(image.get("rel_file")))


def load(root):
    if not os.path.isdir(root):
        raise model.BundleError("BUNDLE_DIR_MISSING")
    head = io.read_own_json(os.path.join(root, "bundle.json"))
    if not head:
        raise model.BundleError("BUNDLE_HEAD_MISSING")
    sources = {s["file_id"]: s for s in io.read_own_jsonl(os.path.join(root, "sources.jsonl"))}
    units = {u["unit_id"]: u for u in io.read_own_jsonl(os.path.join(root, "units.jsonl"))}
    records = io.read_own_jsonl(os.path.join(root, "records.jsonl"))
    b = model.Bundle(head.get("labeler_run_id"), sources, units, records, head["taxonomy"], FilesLoader(root),
                     meta={"adapter": "bundle_files"})
    model.check_bundle(b)
    return b


def save(bundle, root, blobs=None, images=None):
    """번들을 폴더로 쓴다. blobs: {file_id: bytes}, images: {rel_file: bytes}. 모두 .b64로만 쓴다."""
    import base64

    io.write_json(os.path.join(root, "bundle.json"),
                  {"labeler_run_id": bundle.labeler_run_id, "taxonomy": bundle.taxonomy})
    io.write_jsonl(os.path.join(root, "sources.jsonl"), [bundle.sources[k] for k in sorted(bundle.sources)])
    io.write_jsonl(os.path.join(root, "units.jsonl"), [bundle.units[k] for k in sorted(bundle.units)])
    io.write_jsonl(os.path.join(root, "records.jsonl"), sorted(bundle.records, key=lambda r: r["record_id"]))
    for fid, data in (blobs or {}).items():
        io.write_text(os.path.join(root, bundle.sources[fid]["b64_ref"]), base64.b64encode(data).decode("ascii"))
    for rel, data in (images or {}).items():
        io.write_text(os.path.join(root, rel), base64.b64encode(data).decode("ascii"))
