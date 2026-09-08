"""검색과 조회.

MCP 도구와 웹 UI와 CLI가 **모두 이 함수들을 쓴다.**
Claude가 본 근거를 사람이 같은 검색어로 재현할 수 있어야 하기 때문이다.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field

from .tokenizer import build_match_query

# README 본문은 컬렉션을 설명하는 글이라 살짝 가중한다 (SPEC 6절)
README_BOOST = 1.15

_WS_RE = re.compile(r"\s+")


def _dedup_key(text: str) -> str:
    """같은 내용이 여러 문서에 복사돼 있을 때 상위 K개를 중복이 잡아먹지 않게 한다.

    (예: 개별 설계서와 통합 설계서에 같은 절이 그대로 들어있는 경우)
    """
    return hashlib.sha1(_WS_RE.sub(" ", text).strip().encode("utf-8")).hexdigest()


@dataclass
class SearchHit:
    text: str
    collection: str
    source: str  # 루트 기준 상대 경로
    location: str  # "## 예외 처리", "p.12" 등
    score: float
    doc_id: int
    chunk_id: int
    title: str = ""
    also_in: list[str] = field(default_factory=list)  # 같은 내용이 있는 다른 문서


@dataclass
class CollectionSummary:
    name: str
    dirname: str
    description: str
    tags: list[str] = field(default_factory=list)
    updated: str = ""
    doc_count: int = 0
    chunk_count: int = 0
    has_readme: bool = False
    is_inbox: bool = False


@dataclass
class DocumentSummary:
    id: int
    title: str
    path: str
    collection: str
    ext: str
    pages: int
    chunk_count: int
    indexed_at: str
    status: str = "ok"
    error: str = ""


def search(
    conn: sqlite3.Connection,
    query: str,
    collection: str | None = None,
    top_k: int = 5,
    include_inbox: bool = False,
) -> list[SearchHit]:
    """BM25 검색. 질의는 색인과 같은 형태소 토크나이저를 거친다."""
    match = build_match_query(query)
    if not match:
        return []

    sql = [
        "SELECT c.id AS chunk_id, c.text, c.location, d.id AS doc_id, d.path,",
        "       d.title, d.collection, d.is_readme, bm25(chunks_fts) AS rank",
        "FROM chunks_fts",
        "JOIN chunks c ON c.id = chunks_fts.rowid",
        "JOIN documents d ON d.id = c.doc_id",
        "WHERE chunks_fts MATCH ? AND d.status = 'ok'",
    ]
    params: list = [match]

    if collection:
        sql.append("AND d.collection = ?")
        params.append(collection)
    elif not include_inbox:
        sql.append("AND d.is_inbox = 0")

    # 가중치를 다시 매길 여유분을 넉넉히 가져온 뒤 정렬한다
    sql.append("ORDER BY rank LIMIT ?")
    params.append(max(top_k * 5, 50))

    rows = conn.execute("\n".join(sql), params).fetchall()

    hits: list[SearchHit] = []
    for row in rows:
        score = -float(row["rank"])  # bm25()는 작을수록 좋다
        if row["is_readme"]:
            score *= README_BOOST
        hits.append(
            SearchHit(
                text=row["text"],
                collection=row["collection"],
                source=row["path"],
                location=row["location"],
                score=round(score, 4),
                doc_id=row["doc_id"],
                chunk_id=row["chunk_id"],
                title=row["title"],
            )
        )

    hits.sort(key=lambda h: h.score, reverse=True)

    # 같은 내용은 하나만 남기고, 어디에 또 있는지만 알려준다
    deduped: list[SearchHit] = []
    by_key: dict[str, SearchHit] = {}
    for hit in hits:
        key = _dedup_key(hit.text)
        kept = by_key.get(key)
        if kept is None:
            by_key[key] = hit
            deduped.append(hit)
        elif hit.source not in kept.also_in and hit.source != kept.source:
            kept.also_in.append(hit.source)

    return deduped[:top_k]


def list_collections(conn: sqlite3.Connection, include_inbox: bool = True) -> list[CollectionSummary]:
    sql = """
        SELECT c.dirname, c.name, c.description, c.tags, c.updated, c.has_readme, c.is_inbox,
               (SELECT COUNT(*) FROM documents d WHERE d.collection = c.dirname AND d.status='ok')
                   AS doc_count,
               (SELECT COALESCE(SUM(d.chunk_count), 0) FROM documents d
                    WHERE d.collection = c.dirname AND d.status='ok') AS chunk_count
        FROM collections c
        ORDER BY c.is_inbox, c.dirname
    """
    out = []
    for row in conn.execute(sql).fetchall():
        if not include_inbox and row["is_inbox"]:
            continue
        try:
            tags = json.loads(row["tags"]) or []
        except (json.JSONDecodeError, TypeError):
            tags = []
        out.append(
            CollectionSummary(
                name=row["name"],
                dirname=row["dirname"],
                description=row["description"],
                tags=tags,
                updated=row["updated"],
                doc_count=row["doc_count"],
                chunk_count=row["chunk_count"],
                has_readme=bool(row["has_readme"]),
                is_inbox=bool(row["is_inbox"]),
            )
        )
    return out


def list_documents(
    conn: sqlite3.Connection, collection: str | None = None, status: str | None = "ok"
) -> list[DocumentSummary]:
    sql = ["SELECT * FROM documents WHERE 1=1"]
    params: list = []
    if collection:
        sql.append("AND collection = ?")
        params.append(collection)
    if status:
        sql.append("AND status = ?")
        params.append(status)
    sql.append("ORDER BY collection, path")

    return [
        DocumentSummary(
            id=row["id"],
            title=row["title"],
            path=row["path"],
            collection=row["collection"],
            ext=row["ext"],
            pages=row["pages"],
            chunk_count=row["chunk_count"],
            indexed_at=row["indexed_at"],
            status=row["status"],
            error=row["error"],
        )
        for row in conn.execute(" ".join(sql), params).fetchall()
    ]


def get_document(
    conn: sqlite3.Connection, doc_id: int, section: str | None = None
) -> dict | None:
    """문서 원문. section을 주면 그 위치(헤딩/페이지)만 돌려준다."""
    doc = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if doc is None:
        return None

    sql = "SELECT location, text FROM chunks WHERE doc_id = ?"
    params: list = [doc_id]
    if section:
        sql += " AND location LIKE ?"
        params.append(f"%{section}%")
    sql += " ORDER BY ordinal"

    chunks = conn.execute(sql, params).fetchall()
    return {
        "id": doc["id"],
        "title": doc["title"],
        "path": doc["path"],
        "collection": doc["collection"],
        "pages": doc["pages"],
        "sections": [{"location": c["location"], "text": c["text"]} for c in chunks],
    }


def failed_documents(conn: sqlite3.Connection) -> list[DocumentSummary]:
    return list_documents(conn, status="failed")
