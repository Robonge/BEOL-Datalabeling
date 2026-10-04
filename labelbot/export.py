"""산출 SQLite(out/labeling.sqlite), SCHEMA.md, 이미지 폴더. base64 원문, LLM 캐시, 절대 경로는 넣지 않는다."""
import json
import os
import re
import shutil
import sqlite3

from labelbot import finals, util
from labelbot.questions import all_questions

SCHEMA = [
    ("files", "파일 단위 정보. 파일 1개 = 행 1개", [
        ("file_id", "TEXT PRIMARY KEY", "원본 bytes의 sha256"),
        ("file_name", "TEXT NOT NULL", "파일명(처음 본 위치 기준)"),
        ("rel_path", "TEXT NOT NULL", "대표 상대 경로(입력 루트 기준, 구분자 /)"),
        ("title", "TEXT", "문서 속성의 제목"),
        ("authored_at", "TEXT", "작성일(YYYY-MM-DD)"),
        ("author", "TEXT", "작성자"),
        ("memo", "TEXT", "taxonomy.xlsx files 시트의 맥락 메모"),
        ("chunk_count", "INTEGER", "chunk 수"),
    ]),
    ("file_locations", "같은 파일(해시)이 놓인 모든 위치. files와 1:N", [
        ("file_id", "TEXT NOT NULL", "files.file_id"),
        ("rel_path", "TEXT NOT NULL", "상대 경로"),
        ("file_name", "TEXT NOT NULL", "그 위치의 파일명"),
        ("first_seen_run", "TEXT", "처음 본 실행 ID"),
        ("last_seen_run", "TEXT", "마지막으로 본 실행 ID"),
    ]),
    ("chunks", "검색 단위. pptx는 슬라이드 1장 = chunk 1개", [
        ("chunk_id", "TEXT PRIMARY KEY", "<파일 ID 앞 16자>:<part 이름>"),
        ("file_id", "TEXT NOT NULL", "files.file_id"),
        ("seq", "INTEGER", "파일 안 순서(슬라이드 번호)"),
        ("chunk_type", "TEXT", "내용/표지/목차/참고문헌"),
        ("title", "TEXT", "슬라이드 제목"),
        ("text", "TEXT", "chunk 본문([표], [노트], [차트] 구간 포함)"),
        ("text_hash", "TEXT", "본문 해시"),
        ("dup_group", "TEXT", "같은 본문 chunk 묶음 ID(없으면 NULL)"),
        ("image_paths", "TEXT", "이미지 파일 경로 JSON 목록(images/<id>.b64)"),
        ("parse_warnings", "TEXT", "파싱 경고 코드 JSON 목록"),
    ]),
    ("facet_values", "분류 체계(축과 표준 값)", [
        ("axis", "TEXT", "축 이름"),
        ("value", "TEXT", "표준 값"),
        ("parent", "TEXT", "상위값(계층 축)"),
        ("kind", "TEXT", "분류/상태"),
        ("definition", "TEXT", "정의·판정 규칙"),
    ]),
    ("aliases", "동의어 → 표준어", [("alias", "TEXT", "본문 표현"), ("canonical", "TEXT", "표준어")]),
    ("questions", "O/X 질문", [
        ("question_id", "TEXT PRIMARY KEY", "질문 ID"),
        ("text", "TEXT", "질문 문장"),
        ("target", "TEXT", "적용 대상(공통 또는 축=값)"),
    ]),
    ("facet_labels", "chunk와 축 값의 관계. 값마다 1행", [
        ("chunk_id", "TEXT", "chunks.chunk_id"),
        ("axis", "TEXT", "축 이름"),
        ("value", "TEXT", "표준 값. state가 value가 아니면 '해당 없음' 또는 'unknown'"),
        ("state", "TEXT", "value / 해당 없음 / unknown"),
        ("evidence", "TEXT", "근거 인용"),
        ("confidence", "REAL", "확신도 0~1"),
        ("review_status", "TEXT", "검수하지 않음 / 사람이 확인 / 사람이 교정"),
    ]),
    ("answers", "chunk별 질문 답", [
        ("chunk_id", "TEXT", "chunks.chunk_id"),
        ("question_id", "TEXT", "questions.question_id"),
        ("answer", "TEXT", "O / X / N/A"),
        ("quote", "TEXT", "근거 인용"),
        ("confidence", "REAL", "확신도 0~1"),
        ("review_status", "TEXT", "검수하지 않음 / 사람이 확인 / 사람이 교정"),
    ]),
    ("extracted_values", "날짜·담당자 값", [
        ("target_type", "TEXT", "file 또는 chunk"),
        ("target_id", "TEXT", "file_id 또는 chunk_id"),
        ("item", "TEXT", "date 또는 person"),
        ("value", "TEXT", "값(날짜는 YYYY-MM-DD)"),
        ("evidence", "TEXT", "근거 인용"),
        ("source", "TEXT", "docprops / filename / body"),
    ]),
    ("meta", "산출 정보", [("key", "TEXT PRIMARY KEY", "키"), ("value", "TEXT", "값")]),
]

_FNAME_DATE = re.compile(r"^(\d{2})(\d{2})(\d{2})_")


def _create(con):
    for name, _, cols in SCHEMA:
        con.execute("CREATE TABLE %s (%s)" % (name, ", ".join("%s %s" % (c, t) for c, t, _ in cols)))


def export(ws, con, run_id, tax):
    out_dir = ws.path("out")
    db_path = os.path.join(out_dir, "labeling.sqlite")
    if os.path.exists(db_path):
        os.remove(db_path)
    img_dir = os.path.join(out_dir, "images")
    os.makedirs(img_dir, exist_ok=True)
    memos = {f.file_id: f.memo for f in tax.files}
    excluded = {f.file_id for f in tax.files if f.exclude}
    files = [f for f in con.execute(
        "SELECT DISTINCT f.* FROM files f JOIN file_locations l ON l.file_id=f.file_id "
        "WHERE f.status='ok' AND l.last_seen_run=? ORDER BY f.rel_path", (run_id,))
        if f["file_id"] not in excluded]
    fids = [f["file_id"] for f in files]
    chunks = [dict(r) for r in con.execute(
        "SELECT * FROM chunks WHERE file_id IN (%s) ORDER BY file_id, seq" % ",".join("?" * len(fids)), fids)] if fids else []
    labels = finals.final_labels(con, run_id, [c["chunk_id"] for c in chunks], {q.qid: q.text for q in all_questions(con, tax)})
    out = sqlite3.connect(db_path)
    try:
        out.execute("PRAGMA journal_mode=DELETE")
        _create(out)
        for f in files:
            n = sum(1 for c in chunks if c["file_id"] == f["file_id"])
            out.execute("INSERT INTO files VALUES(?,?,?,?,?,?,?,?)", (
                f["file_id"], f["file_name"], f["rel_path"], f["title"], f["authored_at"], f["author"],
                memos.get(f["file_id"]), n))
            for loc in con.execute("SELECT * FROM file_locations WHERE file_id=?", (f["file_id"],)):
                out.execute("INSERT INTO file_locations VALUES(?,?,?,?,?)", (
                    loc["file_id"], loc["rel_path"], loc["file_name"], loc["first_seen_run"], loc["last_seen_run"]))
            for item, value, src in _file_values(f):
                out.execute("INSERT INTO extracted_values VALUES(?,?,?,?,?,?)", ("file", f["file_id"], item, value, None, src))
        for c in chunks:
            img_paths = []
            for iid in json.loads(c["images"] or "[]"):
                r = con.execute("SELECT rel_file FROM images WHERE image_id=?", (iid,)).fetchone()
                if r:
                    dst = os.path.join(img_dir, iid + ".b64")
                    if not os.path.exists(dst):
                        shutil.copyfile(ws.path(r["rel_file"]), dst)
                    img_paths.append("images/%s.b64" % iid)
            d = labels.get(c["chunk_id"]) or {}
            out.execute("INSERT INTO chunks VALUES(?,?,?,?,?,?,?,?,?,?)", (
                c["chunk_id"], c["file_id"], c["seq"], d.get("chunk_type"), c["title"], c["text"], c["text_hash"],
                c["dup_group"], util.dumps(img_paths), c["warnings"]))
            for axis, a in (d.get("axes") or {}).items():
                for v in a["values"]:
                    state = "value" if a["status"] == "value" else v
                    out.execute("INSERT INTO facet_labels VALUES(?,?,?,?,?,?,?)", (
                        c["chunk_id"], axis, v, state, a.get("evidence"), a.get("confidence"), a.get("review")))
            for qid, a in (d.get("answers") or {}).items():
                out.execute("INSERT INTO answers VALUES(?,?,?,?,?,?)", (
                    c["chunk_id"], qid, a["answer"], a.get("quote"), a.get("confidence"), a.get("review")))
            for e in d.get("extracted") or []:
                out.execute("INSERT INTO extracted_values VALUES(?,?,?,?,?,?)", (
                    "chunk", c["chunk_id"], e["item"], e["value"], e["quote"], "body"))
        for a in tax.axes:
            for v in a.values:
                out.execute("INSERT INTO facet_values VALUES(?,?,?,?,?)", (a.name, v.name, v.parent, a.kind, v.definition))
        for s in tax.synonyms:
            out.execute("INSERT INTO aliases VALUES(?,?)", (s.alias, s.canonical))
        for q in all_questions(con, tax):
            target = q.target if isinstance(q.target, str) else "%s=%s" % tuple(q.target)
            out.execute("INSERT INTO questions VALUES(?,?,?)", (q.qid, q.text, target))
        meta = {
            "run_id": run_id, "created_at": util.now_iso(),
            "taxonomy_sha256": _meta(con, "taxonomy_sha256"),
            "sheet_hashes": util.dumps(tax.sheet_hashes),
            "inactive_axes": util.dumps([a.name for a in tax.axes if not a.active]),
            "sent_params": _meta(con, "sent_params"),
            "file_count": str(len(files)), "chunk_count": str(len(chunks)),
        }
        out.executemany("INSERT INTO meta VALUES(?,?)", sorted(meta.items()))
        out.commit()
    finally:
        out.close()
    util.write_text(os.path.join(out_dir, "SCHEMA.md"), schema_md(tax))
    return db_path


def _meta(con, key):
    r = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return r[0] if r else None


def _file_values(f):
    out = []
    if f["authored_at"]:
        out.append(("date", f["authored_at"][:10], "docprops"))
    else:
        m = _FNAME_DATE.match(f["file_name"] or "")
        if m:
            out.append(("date", "20%s-%s-%s" % m.groups(), "filename"))
    if f["author"]:
        out.append(("person", f["author"], "docprops"))
    return out


def schema_md(tax):
    L = ["# labeling.sqlite 스키마", "",
         "BEOL 비정형 자료 라벨링 결과다. 읽기 전용 SELECT로 조회한다. 라벨은 chunk와 축 값의 관계(facet_labels)로 저장된다.", ""]
    for name, desc, cols in SCHEMA:
        L += ["## %s" % name, "", desc, "", "| 열 | 형식 | 설명 |", "|---|---|---|"]
        L += ["| %s | %s | %s |" % (c, t, d) for c, t, d in cols]
        L.append("")
    L += ["## 관계", "",
          "- files 1 : N file_locations (file_id). 같은 파일이 여러 폴더에 있으면 file_locations에 모두 있다.",
          "- files 1 : N chunks (file_id)",
          "- chunks 1 : N facet_labels, answers (chunk_id)",
          "- facet_labels.(axis, value) → facet_values.(axis, value) (state='value'일 때)",
          "- answers.question_id → questions.question_id", "",
          "## 분류 체계", ""]
    for a in tax.axes:
        L.append("- **%s** (%s, 다중값 %s)%s: %s" % (
            a.name, a.kind, "Y" if a.multi else "N", "" if a.active else " 비활성",
            ", ".join(v.name + ("(<%s)" % v.parent if v.parent else "") for v in a.values) or "(값 없음)"))
    L += ["", "## 질문", ""] + ["- %s: %s" % (q.qid, q.text) for q in tax.questions]
    L += ["", "## 예시 SQL", "",
          "경로로 파일과 chunk 찾기:", "", "```sql",
          "SELECT f.file_id, l.rel_path, c.chunk_id, c.title",
          "FROM file_locations l JOIN files f ON f.file_id = l.file_id JOIN chunks c ON c.file_id = f.file_id",
          "WHERE l.rel_path LIKE '%M2%' ORDER BY l.rel_path, c.seq;", "```", "",
          "특정 축 값이 붙은 chunk:", "", "```sql",
          "SELECT c.chunk_id, c.title FROM facet_labels fl JOIN chunks c ON c.chunk_id = fl.chunk_id",
          "WHERE fl.axis = '불량 모드' AND fl.value = 'Short';", "```", "",
          "미해결 위험이 있다고 답한 chunk:", "", "```sql",
          "SELECT a.chunk_id, a.quote FROM answers a WHERE a.question_id = 'Q-COM-001' AND a.answer = 'O';", "```", ""]
    return "\n".join(L)
