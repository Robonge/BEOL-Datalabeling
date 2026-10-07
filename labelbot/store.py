"""작업 DB(work.sqlite) 스키마와 연결. schema_version으로 관리하고 마이그레이션은 표·열 추가만 한다."""
import json
import pathlib
import sqlite3

SCHEMA_VERSION = 2

TABLES = {
    "meta": "key TEXT PRIMARY KEY, value TEXT",
    "llm_cache": "cache_key TEXT PRIMARY KEY, response TEXT NOT NULL, created_at TEXT",
    "runs": (
        "run_id TEXT PRIMARY KEY, command TEXT, started_at TEXT, finished_at TEXT, "
        "config_hash TEXT, sheet_hashes TEXT, sent_params TEXT, input_root TEXT"
    ),
    "failures": (
        "id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, stage TEXT, target_id TEXT, "
        "reason_code TEXT, created_at TEXT"
    ),
    "files": (
        "file_id TEXT PRIMARY KEY, file_name TEXT NOT NULL CHECK(file_name <> ''), "
        "rel_path TEXT NOT NULL CHECK(rel_path <> ''), ext TEXT, size INTEGER, status TEXT, "
        "reason_code TEXT, title TEXT, author TEXT, authored_at TEXT, author_source TEXT, "
        "date_source TEXT, near_dup_group TEXT, first_seen_run TEXT, chunk_method TEXT, doc_meta TEXT"
    ),
    "file_locations": (
        "file_id TEXT NOT NULL, rel_path TEXT NOT NULL CHECK(rel_path <> ''), "
        "file_name TEXT NOT NULL CHECK(file_name <> ''), first_seen_run TEXT, last_seen_run TEXT, "
        "PRIMARY KEY(file_id, rel_path)"
    ),
    "chunks": (
        "chunk_id TEXT PRIMARY KEY, file_id TEXT NOT NULL, seq INTEGER, part_name TEXT, title TEXT, "
        "text TEXT, text_hash TEXT, dup_hash TEXT, dup_group TEXT, warnings TEXT, images TEXT, view TEXT"
    ),
    "images": "image_id TEXT PRIMARY KEY, ext TEXT, size INTEGER, rel_file TEXT",
    "labels": (
        "id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, chunk_id TEXT, kind TEXT, key TEXT, "
        "value TEXT, status TEXT, evidence TEXT, confidence REAL, sheet_hashes TEXT, "
        "prompt_version TEXT, model TEXT, created_at TEXT"
    ),
    "candidates": (
        "id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, kind TEXT, content TEXT, axis TEXT, "
        "parent TEXT, evidence TEXT, chunk_id TEXT, source TEXT"
    ),
    "alerts": "run_id TEXT, condition TEXT, value REAL, threshold REAL",
    "gen_questions": (
        "qid TEXT PRIMARY KEY, chunk_id TEXT, axis TEXT, value TEXT, text TEXT NOT NULL,"
        " prompt_version TEXT, created_at TEXT"
    ),
    # 대조 질문(Q-CTL-): 이 chunk에 붙지 않은 라벨로 만든 질문. 답은 labels에 kind='control'로 남는다.
    "ctl_questions": (
        "qid TEXT PRIMARY KEY, chunk_id TEXT, axis TEXT, value TEXT, text TEXT NOT NULL,"
        " prompt_version TEXT, created_at TEXT"
    ),
    "flagged_chunks": (
        "run_id TEXT, chunk_id TEXT, reason_codes TEXT, unknown_ratio REAL, min_confidence REAL, "
        "text_hash TEXT, weak_quotes INTEGER, reason_axes TEXT DEFAULT '{}', PRIMARY KEY(run_id, chunk_id)"
    ),
    # evidence는 검증을 통과한 근거 JSON 목록(본문 인용 포함), reason은 이유, evidence_dropped는 버린 근거 수다.
    "corrections": (
        "review_run_id TEXT, chunk_id TEXT, target_kind TEXT, target_key TEXT, human_value TEXT, "
        "bot_value TEXT, review_status TEXT, recheck INTEGER, text_hash TEXT, question_hash TEXT, "
        "file_sha256 TEXT, applied_at TEXT, evidence TEXT, reason TEXT, evidence_dropped INTEGER, "
        "PRIMARY KEY(review_run_id, chunk_id, target_kind, target_key)"
    ),
    # taxonomy 재검토 요청. corrections와 분리한다(finals.corrections()가 그 표 전체를 라벨 교정으로 읽는다).
    "revisit_requests": (
        "review_run_id TEXT, chunk_id TEXT, target_kind TEXT, target_key TEXT, reason TEXT, "
        "proposed_value TEXT, proposed_parent TEXT, related_values TEXT, memo TEXT, bot_value TEXT, "
        "human_value TEXT, file_id TEXT, file_sha256 TEXT, applied_at TEXT, "
        "PRIMARY KEY(review_run_id, chunk_id, target_kind, target_key)"
    ),
    "compare_marks": (
        "chunk_id TEXT, status TEXT, memo TEXT, file_sha256 TEXT, applied_at TEXT, "
        "PRIMARY KEY(chunk_id)"
    ),
    "chunk_embeddings": (
        "chunk_id TEXT, model TEXT, dim INTEGER, text_hash TEXT, vector BLOB, run_id TEXT, "
        "PRIMARY KEY(chunk_id, model)"
    ),
    "vector_push_log": (
        "id INTEGER PRIMARY KEY AUTOINCREMENT, chunk_id TEXT, model TEXT, text_hash TEXT, "
        "label_hash TEXT, target_host_hash TEXT, pushed_at TEXT, result_code TEXT"
    ),
    # 슬라이드 근사 미리보기 JPG. bytes는 slide_images/<jpg_sha256>.b64에만 둔다(.jpg로 쓰지 않는다).
    "slide_images": (
        "chunk_id TEXT PRIMARY KEY, file_id TEXT, seq INTEGER, jpg_sha256 TEXT, width INTEGER, height INTEGER, "
        "quality INTEGER, rel_file TEXT, text_hash TEXT, layout_hash TEXT, renderer_version TEXT, created_at TEXT"
    ),
    "slide_image_push_log": (
        "id INTEGER PRIMARY KEY AUTOINCREMENT, chunk_id TEXT, jpg_sha256 TEXT, bucket TEXT, object_path TEXT, "
        "target_host_hash TEXT, pushed_at TEXT, result_code TEXT"
    ),
}

INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_labels_run_chunk ON labels(run_id, chunk_id)",
    "CREATE INDEX IF NOT EXISTS ix_chunks_file ON chunks(file_id)",
    "CREATE INDEX IF NOT EXISTS ix_failures_run ON failures(run_id, stage)",
]


def _split_top(spec):
    """괄호 밖의 쉼표로만 나눈다. 'PRIMARY KEY(a, b)'를 한 덩어리로 둔다."""
    parts, depth, cur = [], 0, ""
    for ch in spec:
        depth += ch == "("
        depth -= ch == ")"
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    parts.append(cur.strip())
    return parts


def _columns(spec):
    cols = []
    for part in _split_top(spec):
        name = part.split(" ", 1)[0]
        if name.upper() in ("PRIMARY", "UNIQUE", "CHECK", "FOREIGN"):
            continue
        cols.append((name, part))
    return cols


def connect(path):
    # 3차까지의 LLM 호출은 스레드로 돌고, 접근은 pipeline._LockedCon이 잠금으로 직렬화한다.
    con = sqlite3.connect(path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=DELETE")
    migrate(con)
    return con


def connect_ro(path):
    """sqlite 파일을 읽기 전용(mode=ro URI)으로 연다. 쓰지 않고 마이그레이션도 하지 않는다(row_factory는 기본값)."""
    return sqlite3.connect(pathlib.Path(path).resolve().as_uri() + "?mode=ro", uri=True)


def migrate(con):
    """없는 표는 만들고, 있는 표에는 빠진 열만 추가한다. 기존 열과 행은 건드리지 않는다."""
    for name, spec in TABLES.items():
        exists = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        if not exists:
            con.execute("CREATE TABLE %s (%s)" % (name, spec))
            continue
        have = {r[1] for r in con.execute("PRAGMA table_info(%s)" % name)}
        for col, decl in _columns(spec):
            if col not in have:
                decl = decl.replace("NOT NULL", "").replace("PRIMARY KEY", "")
                con.execute("ALTER TABLE %s ADD COLUMN %s" % (name, decl))
    for sql in INDEXES:
        con.execute(sql)
    con.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)", (str(SCHEMA_VERSION),)
    )
    con.commit()


def meta_get(con, key, default=None):
    r = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return r[0] if r else default


def meta_json(con, key):
    """meta 값을 JSON으로 읽는다. 없거나 JSON이 아니면 None."""
    try:
        return json.loads(meta_get(con, key) or "null")
    except ValueError:
        return None


def meta_set(con, key, value):
    con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (key, value))


# 라벨이 남는 실행 종류. axis-update는 이전 실행의 라벨을 이어받아 바뀐 축만 다시 분류한 실행,
# rules-update는 이전 실행의 라벨을 이어받아 바뀐 라벨링 규칙이 닿는 축·답만 다시 라벨한 실행이다.
LABEL_COMMANDS = ("run", "axis-update", "rules-update")


def _latest(con, commands, finished_only):
    q = "SELECT run_id FROM runs WHERE command IN (%s)%s ORDER BY run_id DESC LIMIT 1" % (
        ",".join("?" * len(commands)), " AND finished_at IS NOT NULL" if finished_only else "")
    r = con.execute(q, commands).fetchone()
    return r[0] if r else None


def latest_run(con, commands=LABEL_COMMANDS + ("ingest",), finished=True):
    """기본 --run 등 '최신 실행'. finished=True면 끝난 실행을 먼저 고르고, 끝난 실행이 없을 때만 진행 중 실행을 고른다."""
    return (_latest(con, commands, True) if finished else None) or _latest(con, commands, False)


def latest_label_run(con, finished=False):
    """최신 라벨 실행(run·axis-update·rules-update). finished=True면 끝난 실행만 본다."""
    return _latest(con, LABEL_COMMANDS, finished)


def add_failure(con, run_id, stage, target_id, reason_code):
    from labelbot.util import now_iso

    con.execute(
        "INSERT INTO failures(run_id, stage, target_id, reason_code, created_at) VALUES(?,?,?,?,?)",
        (run_id, stage, target_id, reason_code, now_iso()),
    )
