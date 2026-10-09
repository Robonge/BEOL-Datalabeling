"""예전 taxonomy.xlsx → taxonomy.json 1회 변환(taxonomy-migrate).

xlsx는 ingest.read_input(시그니처 확인)으로만 읽는다. 변환 뒤 시트 해시(taxonomy·questions·synonyms)를
예전 xlsx 규칙(머리글 행 + 정의 열만 자른 원시 행)으로 따로 계산해 JSON 쪽과 같은지 대조한다.
작업 폴더 pipeline.json의 taxonomy_path가 변환한 xlsx를 가리키면 새 JSON 경로로 바꾼다
(JSON과 작업 폴더가 모두 저장소 안이면 작업 폴더 기준 상대경로, 아니면 절대경로).
출력·로그에는 건수·코드·행 번호만 낸다(셀 내용은 내지 않는다).
"""
import json
import os

from labelbot import ingest, taxonomy, util, workspace, xlsx

CONFIG_NAME = "pipeline.json"


class MigrateError(Exception):
    def __init__(self, reason_code, detail=None):
        Exception.__init__(self, reason_code)
        self.reason_code = reason_code
        self.detail = detail


def xlsx_sheet_hashes(b):
    """예전 파서와 같은 규칙의 시트 해시 {시트: 해시}(taxonomy·questions·synonyms). 시트가 없으면 빈 해시."""
    wb = xlsx.read_workbook(b)
    out = {}
    for name, header in taxonomy.HEADERS.items():
        sheet, _ = wb.find(name)
        rows = []
        if sheet is not None:
            for _n, cells in sheet.iter_rows():
                defined = taxonomy.trim_cells(cells[:len(header)])
                if defined:
                    rows.append(defined)
        out[name] = taxonomy.sheet_hash(rows)
    return out


def _where(issues):
    """오류 위치 요약(시트:행:코드). 셀 내용은 넣지 않는다."""
    return ",".join("%s:%s:%s" % (i.sheet or "-", i.row or "-", i.code) for i in issues[:20])


def dropped_rows(b):
    """변환에서 버리는 시트의 행 수 {"files": n, "files_excluded": n, "queries": n}."""
    wb = xlsx.read_workbook(b)
    out = {"files": 0, "files_excluded": 0, "queries": 0}
    for name in ("files", "queries"):
        sheet, _ = wb.find(name)
        for n, cells in sheet.iter_rows(2) if sheet is not None else []:
            if any(c != "" for c in cells[:4]):
                out[name] += 1
                if name == "files" and len(cells) > 2 and cells[2].strip().upper() == "Y":
                    out["files_excluded"] += 1
    return out


def _workspace_configs(workspaces_root, xlsx_path):
    """바꿀 작업 폴더 pipeline.json을 쓰기 전에 모두 읽는다. 반환: ([(이름, 경로, cfg)], [(이름, 사유 코드)])."""
    out, skipped = [], []
    names = sorted(os.listdir(workspaces_root)) if workspaces_root and os.path.isdir(workspaces_root) else []
    for name in names:
        cfg_path = os.path.join(workspaces_root, name, CONFIG_NAME)
        local = os.path.join(workspaces_root, name, "taxonomy.xlsx")
        if not os.path.isfile(cfg_path):
            if os.path.isfile(local) and not os.path.isfile(os.path.join(workspaces_root, name, "taxonomy.json")):
                skipped.append((name, "XLSX_LOCAL_NEEDS_MIGRATION"))
            continue
        try:
            cfg = json.loads(ingest.read_input(cfg_path, None, expect="text"))
        except (OSError, ValueError):
            skipped.append((name, "CONFIG_UNREADABLE"))
            continue
        cur = cfg.get("taxonomy_path") if isinstance(cfg, dict) else None
        if not cur:
            # 지정이 없으면 예전 기본값은 작업 폴더의 taxonomy.xlsx였다. 따로 변환해야 한다(--xlsx 그 경로)
            if os.path.isfile(local) and not os.path.isfile(os.path.join(workspaces_root, name, "taxonomy.json")):
                skipped.append((name, "XLSX_LOCAL_NEEDS_MIGRATION"))
            continue
        cur_abs = cur if os.path.isabs(cur) else os.path.join(workspaces_root, name, cur)
        if _same_path(cur_abs, xlsx_path):
            out.append((name, cfg_path, cfg))
    return out, skipped


def _stored_path(target, ws_dir):
    """pipeline.json에 적을 경로: 대상·작업 폴더가 모두 저장소(CODE_ROOT) 안이면 작업 폴더 기준 상대경로(/ 구분)."""
    target = os.path.abspath(target)
    root = workspace.CODE_ROOT
    if workspace.is_inside(target, root) and workspace.is_inside(ws_dir, root):
        return os.path.relpath(target, os.path.abspath(ws_dir)).replace("\\", "/")
    return target.replace("\\", "/")


def _same_path(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def migrate(xlsx_path, out_path=None, workspaces_root=None, force=False):
    """반환 dict: out, rows {시트: 건수}, rejected, dropped(files·queries 버린 행 수), warnings [코드],
    workspaces (pipeline.json을 바꾼 작업 폴더 이름), skipped [(작업 폴더, 사유 코드)]
    (CONFIG_UNREADABLE: pipeline.json을 못 읽음, XLSX_LOCAL_NEEDS_MIGRATION: 작업 폴더에만 있는 예전 xlsx).
    시트 해시(taxonomy·questions·synonyms)가 예전 xlsx와 다르면 쓰지 않고 SHEET_HASH_MISMATCH.
    xlsx 오류(병합 셀 등)나 검증 오류가 있으면 쓰지 않고 MigrateError(XLSX_UNUSABLE|TAXONOMY_INVALID, 위치)."""
    out_path = out_path or os.path.splitext(xlsx_path)[0] + ".json"
    if not out_path.lower().endswith(".json"):
        raise MigrateError("OUT_NOT_JSON")
    if os.path.exists(out_path) and not force:
        raise MigrateError("OUT_EXISTS")
    try:
        b = ingest.read_input(xlsx_path, None, expect=".xlsx")
    except ingest.InputError as e:
        raise MigrateError("XLSX_READ_FAILED", e.reason_code)
    except OSError:
        raise MigrateError("XLSX_READ_FAILED", "OS_ERROR")
    doc, errors, warnings = taxonomy.xlsx_to_doc(b)
    if doc is None or errors:
        # 병합 셀·수식 결과 없음·오류 셀은 빈 칸으로 읽혀 검증을 통과할 수 있으므로 쓰지 않고 멈춘다
        raise MigrateError("XLSX_UNUSABLE", _where(errors))
    doc = taxonomy.normalize_doc(doc)
    try:
        tax = taxonomy.parse_doc(doc)
    except taxonomy.TaxonomyError as e:
        raise MigrateError("TAXONOMY_INVALID", _where(e.issues))
    # 해시가 같으면 같은 행에서 같은 Taxonomy가 나오므로 axes_signature·sheet_hashes를 쓰는 비교(taxonomy-diff,
    # L2 stale, axis-update)가 변환 때문에 바뀌지 않는다.
    if any(tax.sheet_hashes.get(k) != v for k, v in xlsx_sheet_hashes(b).items()):
        raise MigrateError("SHEET_HASH_MISMATCH")
    configs, skipped = _workspace_configs(workspaces_root, xlsx_path)
    if os.path.exists(out_path):
        # --force: 지금 JSON을 덮어쓸 때도 잠금·이력·원자적 교체를 거친다(보드·편집기에서 저장한 내용이 이력에 남는다)
        try:
            _old, version, _b = taxonomy.load_doc(out_path)
        except taxonomy.TaxonomyError:
            version = taxonomy.doc_version(ingest.read_input(out_path, None))
        taxonomy.save_doc(out_path, doc, version, "migrate")
    else:
        util.write_text(out_path, taxonomy.dump_doc(doc))
    ws_done = []
    for name, cfg_path, cfg in configs:
        cfg["taxonomy_path"] = _stored_path(out_path, os.path.dirname(cfg_path))
        util.write_text(cfg_path, json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")
        ws_done.append(name)
    return {
        "out": out_path,
        "rows": {k: len(doc[k]) for k in taxonomy.HEADERS},
        "rejected": len(doc["rejected"]),
        "dropped": dropped_rows(b),
        "skipped": skipped,
        "warnings": sorted({i.code for i in list(warnings) + list(tax.warnings)}),
        "workspaces": ws_done,
    }
