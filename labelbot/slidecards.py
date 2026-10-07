"""현황판 슬라이드 카드 공용 부분(axis_update.html·rules_update.html).

slide-images가 만든 slide_images/<sha256>.b64를 data URL로 넣고, 없으면 검수 화면과 같은 근사 미리보기 배치(layout)를
넣는다. 파일 번호는 카드 순서(파일 경로, 슬라이드 순서)대로 1부터 매긴다. 본문은 화면(HTML) 안에만 들어간다.
"""
from labelbot import review, util


def slide_image(ws, con, cid):
    """slide-images가 만든 JPG(.b64)의 data URL. 본문이 바뀐(text_hash가 다른) 예전 그림·읽기 실패는 None."""
    r = con.execute("SELECT s.rel_file FROM slide_images s JOIN chunks c ON c.chunk_id=s.chunk_id"
                    " AND c.text_hash=s.text_hash WHERE s.chunk_id=?", (cid,)).fetchone()
    if not r:
        return None
    try:
        return "data:image/jpeg;base64," + util.read_b64_text(ws.path(r["rel_file"]))
    except (OSError, ValueError):
        return None


def cards(ws, con, ids):
    """chunk ID 목록 → 카드 기본 칸 [{chunk_id, file_no, file_name, slide_no, title, image, layout}] (파일 경로·순서대로).

    JPG가 없으면 근사 배치만 넣는다. 삽입 그림은 넣지 않는다(chunk마다 달라 화면이 수십 MB가 된다. 자리 표시로 그린다).
    """
    ids = sorted(ids)
    meta = {r["chunk_id"]: r for r in con.execute(
        "SELECT c.chunk_id, c.file_id, c.seq, c.title, c.part_name, f.file_name, f.rel_path FROM chunks c"
        " JOIN files f ON f.file_id=c.file_id WHERE c.chunk_id IN (%s)" % ",".join("?" * len(ids)), ids)} if ids else {}
    files, layouts, out = {}, {}, []
    for cid in sorted(meta, key=lambda k: (meta[k]["rel_path"] or "", meta[k]["seq"] or 0, k)):
        c = meta[cid]
        file_no = files.setdefault(c["file_id"], len(files) + 1)
        image = slide_image(ws, con, cid)
        layout = None if image else review._slide_layout(ws, layouts, c["file_id"], c["file_name"], c["part_name"])
        out.append({"chunk_id": cid, "file_no": file_no, "file_name": c["file_name"], "slide_no": c["seq"],
                    "title": c["title"] or "", "image": image, "layout": layout})
    return out
