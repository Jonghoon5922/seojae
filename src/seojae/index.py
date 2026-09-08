"""SQLite FTS5 색인.

색인 파일은 {root}\\.seojae\\index.db 하나. 지우면 전체 재색인된다.
파일 해시로 변경분만 다시 읽는다.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from .chunking import build_chunks
from .collections import CollectionInfo, load_collection
from .parsers import ParseError, parse_file
from .paths import (
    INBOX_DIRNAME,
    SUPPORTED_EXTS,
    collection_dirs,
    data_dir,
    db_path,
    inbox_files,
    rel,
    walk_files,
)
from .tokenizer import tokenize, tokens_to_fts

SCHEMA_VERSION = 2

# 문서마다 보관하는 대표 용어 수. 컬렉션 용어 목록을 만드는 재료이고,
# 검색어가 색인에 없을 때 Claude에게 "이런 말로 다시 찾아보라"고 알려주는 데 쓴다.
DOC_TERM_LIMIT = 40

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS collections (
    dirname     TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    tags        TEXT NOT NULL DEFAULT '[]',
    updated     TEXT NOT NULL DEFAULT '',
    has_readme  INTEGER NOT NULL DEFAULT 0,
    body        TEXT NOT NULL DEFAULT '',
    is_inbox    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS documents (
    id          INTEGER PRIMARY KEY,
    collection  TEXT NOT NULL,
    path        TEXT NOT NULL UNIQUE,
    title       TEXT NOT NULL DEFAULT '',
    ext         TEXT NOT NULL DEFAULT '',
    size        INTEGER NOT NULL DEFAULT 0,
    mtime       REAL NOT NULL DEFAULT 0,
    hash        TEXT NOT NULL DEFAULT '',
    pages       INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    is_readme   INTEGER NOT NULL DEFAULT 0,
    is_inbox    INTEGER NOT NULL DEFAULT 0,
    terms       TEXT NOT NULL DEFAULT '[]',
    indexed_at  TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'ok',
    error       TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_documents_collection ON documents(collection);
CREATE INDEX IF NOT EXISTS idx_documents_status     ON documents(status);

CREATE TABLE IF NOT EXISTS chunks (
    id       INTEGER PRIMARY KEY,
    doc_id   INTEGER NOT NULL,
    ordinal  INTEGER NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    text     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    tokens,
    tokenize = 'unicode61 remove_diacritics 0'
);

-- 파일을 옮기거나 README를 고친 기록. 되돌리기(undo)의 근거다.
-- 되돌릴 수 없는 정리는 하지 않는다는 원칙이 이 표에 걸려 있다.
CREATE TABLE IF NOT EXISTS moves (
    id          INTEGER PRIMARY KEY,
    ts          TEXT NOT NULL,
    kind        TEXT NOT NULL,                 -- move | readme
    src         TEXT NOT NULL DEFAULT '',      -- 루트 기준 상대 경로
    dst         TEXT NOT NULL DEFAULT '',
    backup      TEXT NOT NULL DEFAULT '',      -- README 원본 사본 (없었으면 빈 값)
    created_dir TEXT NOT NULL DEFAULT '',      -- 이 작업으로 만든 폴더
    note        TEXT NOT NULL DEFAULT '',
    undone      INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_moves_undone ON moves(undone, id);
"""


@dataclass
class IndexStats:
    indexed: int = 0
    skipped: int = 0
    failed: int = 0
    removed: int = 0
    chunks: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.indexed + self.skipped + self.failed


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def open_db(root: Path, check_same_thread: bool = True) -> sqlite3.Connection:
    """색인 DB 연결. 스키마 버전이 다르면 통째로 새로 만든다.

    MCP 서버는 도구 호출이 워커 스레드에서 올 수 있어 check_same_thread=False로 연다.
    그쪽에서는 호출자가 락으로 감싼다.
    """
    data_dir(root).mkdir(parents=True, exist_ok=True)
    path = db_path(root)
    conn = sqlite3.connect(path, check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    version = None
    try:
        row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        version = int(row["value"]) if row else None
    except sqlite3.DatabaseError:
        version = None

    if version is not None and version != SCHEMA_VERSION:
        conn.close()
        path.unlink(missing_ok=True)
        conn = sqlite3.connect(path, check_same_thread=check_same_thread)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        version = None

    conn.executescript(_SCHEMA)
    if version is None:
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
    conn.commit()
    return conn


def _delete_document(conn: sqlite3.Connection, doc_id: int) -> None:
    rows = conn.execute("SELECT id FROM chunks WHERE doc_id = ?", (doc_id,)).fetchall()
    for row in rows:
        conn.execute("DELETE FROM chunks_fts WHERE rowid = ?", (row["id"],))
    conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
    conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))


def _upsert_collection(conn: sqlite3.Connection, info: CollectionInfo) -> None:
    conn.execute(
        """
        INSERT INTO collections(dirname, name, description, tags, updated, has_readme, body, is_inbox)
        VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(dirname) DO UPDATE SET
            name=excluded.name, description=excluded.description, tags=excluded.tags,
            updated=excluded.updated, has_readme=excluded.has_readme, body=excluded.body,
            is_inbox=excluded.is_inbox
        """,
        (
            info.dirname,
            info.name,
            info.description,
            json.dumps(info.tags, ensure_ascii=False),
            info.updated,
            int(info.has_readme),
            info.body,
            int(info.is_inbox),
        ),
    )


def _record_failure(
    conn: sqlite3.Connection,
    collection: str,
    relpath: str,
    path: Path,
    stat,
    digest: str,
    is_readme: bool,
    is_inbox: bool,
    message: str,
) -> None:
    conn.execute(
        """
        INSERT INTO documents(collection, path, title, ext, size, mtime, hash, pages,
                              chunk_count, is_readme, is_inbox, indexed_at, status, error)
        VALUES(?,?,?,?,?,?,?,0,0,?,?,?,'failed',?)
        """,
        (
            collection,
            relpath,
            path.stem,
            path.suffix.lower(),
            stat.st_size,
            stat.st_mtime,
            digest,
            int(is_readme),
            int(is_inbox),
            now_iso(),
            message[:500],
        ),
    )


def _index_file(
    conn: sqlite3.Connection,
    root: Path,
    path: Path,
    collection: str,
    is_inbox: bool,
    stats: IndexStats,
    force: bool,
) -> None:
    relpath = rel(root, path)
    stat = path.stat()

    existing = conn.execute(
        "SELECT id, hash, status FROM documents WHERE path = ?", (relpath,)
    ).fetchone()

    digest = file_hash(path)
    if existing and not force and existing["hash"] == digest and existing["status"] == "ok":
        stats.skipped += 1
        return

    if existing:
        _delete_document(conn, existing["id"])

    is_readme = path.name.lower().startswith("readme.")

    try:
        parsed = parse_file(path)
    except (ParseError, OSError, ValueError, RuntimeError) as e:
        # 한 파일이 깨져도 색인 전체는 계속한다. 실패는 status로 남겨 CLI에서 보여준다.
        _record_failure(
            conn, collection, relpath, path, stat, digest, is_readme, is_inbox, str(e)
        )
        stats.failed += 1
        stats.errors.append((relpath, str(e)[:200]))
        return

    chunks = build_chunks(parsed.blocks)
    chunk_tokens = [tokenize(chunk.text) for chunk in chunks]

    counter: Counter[str] = Counter()
    for tokens in chunk_tokens:
        counter.update(t for t in tokens if len(t) > 1)
    terms = json.dumps(counter.most_common(DOC_TERM_LIMIT), ensure_ascii=False)

    cursor = conn.execute(
        """
        INSERT INTO documents(collection, path, title, ext, size, mtime, hash, pages,
                              chunk_count, is_readme, is_inbox, terms, indexed_at, status, error)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'ok','')
        """,
        (
            collection,
            relpath,
            parsed.title,
            path.suffix.lower(),
            stat.st_size,
            stat.st_mtime,
            digest,
            parsed.pages,
            len(chunks),
            int(is_readme),
            int(is_inbox),
            terms,
            now_iso(),
        ),
    )
    doc_id = cursor.lastrowid

    for chunk, tokens in zip(chunks, chunk_tokens):
        cur = conn.execute(
            "INSERT INTO chunks(doc_id, ordinal, location, text) VALUES(?,?,?,?)",
            (doc_id, chunk.ordinal, chunk.location, chunk.text),
        )
        conn.execute(
            "INSERT INTO chunks_fts(rowid, tokens) VALUES(?,?)",
            (cur.lastrowid, tokens_to_fts(tokens)),
        )

    stats.indexed += 1
    stats.chunks += len(chunks)


def collection_of(root: Path, path: Path) -> tuple[str, bool]:
    """파일이 어느 책장에 속하는지. (컬렉션명, 인박스인가)

    루트 직속 파일과 _inbox\\ 아래는 전부 미분류로 본다 (SPEC 3절).
    """
    parts = Path(rel(root, path)).parts
    if len(parts) == 1 or parts[0] == INBOX_DIRNAME:
        return INBOX_DIRNAME, True
    return parts[0], False


def ensure_collection(root: Path, conn: sqlite3.Connection, dirname: str) -> None:
    """컬렉션 행을 최신 README 내용으로 맞춘다."""
    if dirname == INBOX_DIRNAME:
        _upsert_collection(
            conn,
            CollectionInfo(
                dirname=INBOX_DIRNAME,
                name="미분류",
                description="아직 어느 책장에도 꽂히지 않은 파일. list_inbox로 확인하고 분류한다.",
            ),
        )
        return

    directory = root / dirname
    if directory.is_dir():
        _upsert_collection(conn, load_collection(directory, root))


def index_one(
    root: Path,
    conn: sqlite3.Connection,
    path: Path,
    force: bool = False,
    commit: bool = True,
) -> IndexStats:
    """파일 하나만 색인한다. 파일 감시가 쓰는 진입점이다."""
    stats = IndexStats()
    if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTS:
        return stats

    collection, is_inbox = collection_of(root, path)
    ensure_collection(root, conn, collection)
    _index_file(conn, root, path, collection, is_inbox, stats, force)

    # README가 바뀌면 그 책장의 설명(=Claude의 라우팅 근거)도 따라 바뀐다
    if path.name.lower().startswith("readme.") and not is_inbox:
        ensure_collection(root, conn, collection)

    if commit:
        conn.commit()
    return stats


def forget_one(
    root: Path, conn: sqlite3.Connection, path: Path, commit: bool = True
) -> bool:
    """지워진 파일을 색인에서 뺀다. 뺐으면 True."""
    try:
        relpath = Path(path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return False

    row = conn.execute("SELECT id FROM documents WHERE path = ?", (relpath,)).fetchone()
    if row is None:
        return False

    _delete_document(conn, row["id"])
    if commit:
        conn.commit()
    return True


def index_root(
    root: Path,
    conn: sqlite3.Connection,
    force: bool = False,
    on_file: Callable[[str], None] | None = None,
) -> IndexStats:
    """루트 전체를 훑어 색인을 최신 상태로 만든다."""
    stats = IndexStats()
    seen: set[str] = set()

    targets: list[tuple[str, bool, Iterable[Path]]] = []

    for directory in collection_dirs(root):
        info = load_collection(directory, root)
        _upsert_collection(conn, info)
        targets.append((directory.name, False, list(walk_files(directory, root))))

    inbox = inbox_files(root)
    if inbox:
        _upsert_collection(
            conn,
            CollectionInfo(
                dirname=INBOX_DIRNAME,
                name="미분류",
                description="아직 어느 책장에도 꽂히지 않은 파일. list_inbox로 확인하고 분류한다.",
            ),
        )
        targets.append((INBOX_DIRNAME, True, inbox))

    for collection, is_inbox, files in targets:
        for path in files:
            relpath = rel(root, path)
            seen.add(relpath)
            if on_file:
                on_file(relpath)
            _index_file(conn, root, path, collection, is_inbox, stats, force)

    # 사라진 파일 정리
    for row in conn.execute("SELECT id, path FROM documents").fetchall():
        if row["path"] not in seen:
            _delete_document(conn, row["id"])
            stats.removed += 1

    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES('last_indexed_at', ?)", (now_iso(),)
    )
    conn.commit()
    return stats


def last_indexed_at(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT value FROM meta WHERE key='last_indexed_at'").fetchone()
    return row["value"] if row else ""
