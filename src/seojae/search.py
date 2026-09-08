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


# ── 재검색 유도 ────────────────────────────────────────────────────────────
# BM25는 어휘가 어긋나면 못 찾는다("에러"로 물으면 "예외" 문서를 놓친다).
# 임베딩을 붙이는 대신 사실을 돌려준다: 각 검색어가 몇 개 문서에 나오는지.
#   0건  → 이 서재가 쓰지 않는 말이다
#   과반 → 아무 문서에나 나오는 흔한 말이라 변별력이 없다
# 둘 중 하나면 그 책장에서 실제로 쓰는 용어를 함께 준다. 말을 바꿔 다시 검색하는
# 판단은 고객(Claude)이 한다.

# 내용어 중 이 비율 이상이 색인에 없으면 질의가 이 서재와 겉돈다고 본다
ABSENT_TERM_RATIO = 0.5

# 힌트 판정에서만 무시하는 말. 색인에서는 빼지 않는다(검색 동작은 그대로 두고
# "이 검색어가 얼마나 특정적인가"를 볼 때만 제외한다).
# "며칠", "어떻게" 같은 의문사는 문서에 거의 안 나와서, 이걸 세면
# 잘 된 검색마다 재검색하라고 잔소리하게 된다.
_NON_CONTENT = {
    "어떻", "어떠", "며칠", "무엇", "뭐", "왜", "언제", "어디", "누구", "얼마",
    "어느", "무슨", "하", "해야", "하나", "하지", "되", "되나", "있", "없",
    "나", "저", "우리", "저희", "것", "수", "때", "등", "및", "그", "이",
    "경우", "관련", "대하", "위하", "통하", "알려", "주",
}


def term_document_counts(
    conn: sqlite3.Connection, query: str, collection: str | None = None
) -> dict[str, int]:
    """검색어별로 몇 개 문서에 나오는지. 0이면 색인에 없는 말이다."""
    from .tokenizer import tokenize

    counts: dict[str, int] = {}
    for token in tokenize(query):
        if token in counts:
            continue

        sql = (
            "SELECT COUNT(DISTINCT c.doc_id) AS n FROM chunks_fts"
            " JOIN chunks c ON c.id = chunks_fts.rowid"
            " JOIN documents d ON d.id = c.doc_id"
            " WHERE chunks_fts MATCH ? AND d.status = 'ok'"
        )
        params: list = ['"' + token.replace('"', '""') + '"']
        if collection:
            sql += " AND d.collection = ?"
            params.append(collection)

        counts[token] = conn.execute(sql, params).fetchone()["n"]
    return counts


def unmatched_terms(
    conn: sqlite3.Connection, query: str, collection: str | None = None
) -> list[str]:
    """질의 토큰 중 색인에 아예 없는 것들."""
    return [t for t, n in term_document_counts(conn, query, collection).items() if n == 0]


def document_total(conn: sqlite3.Connection, collection: str | None = None) -> int:
    """색인이 끝난 문서 수. 검색어 빈도를 해석할 때 분모가 된다."""
    sql = "SELECT COUNT(*) AS n FROM documents WHERE status = 'ok'"
    params: list = []
    if collection:
        sql += " AND collection = ?"
        params.append(collection)
    else:
        sql += " AND is_inbox = 0"
    return conn.execute(sql, params).fetchone()["n"]


def collection_terms(
    conn: sqlite3.Connection, collection: str | None = None, limit: int = 25
) -> list[str]:
    """그 책장에서 실제로 자주 쓰이는 용어. 재검색 힌트로 쓴다."""
    sql = "SELECT terms FROM documents WHERE status = 'ok'"
    params: list = []
    if collection:
        sql += " AND collection = ?"
        params.append(collection)
    else:
        sql += " AND is_inbox = 0"

    counter: dict[str, int] = {}
    for row in conn.execute(sql, params).fetchall():
        try:
            pairs = json.loads(row["terms"]) or []
        except (json.JSONDecodeError, TypeError):
            continue
        for term, count in pairs:
            counter[term] = counter.get(term, 0) + count

    return [t for t, _ in sorted(counter.items(), key=lambda kv: kv[1], reverse=True)[:limit]]


def search_hint(
    conn: sqlite3.Connection,
    query: str,
    hits: list[SearchHit],
    collection: str | None = None,
    counts: dict[str, int] | None = None,
) -> str:
    """검색이 실패했을 때만, 다시 검색할 방향을 알려준다.

    실패로 보는 경우는 둘뿐이다.
      1. 결과가 없다
      2. 내용어의 절반 이상이 색인에 없다 (질의가 이 서재와 겉돈다)

    다음 두 규칙은 실측에서 반증돼 쓰지 않는다.
    - "색인에 없는 말이 하나라도 섞였으면" — 의문사("며칠")가 매번 걸려 잔소리가 된다
    - "검색어가 전부 흔한 말이면" — 문서 집합이 동질적이면 도메인 용어가 원래 흔하다.
      576건 전부 같은 주제인 서재에서 "예외"(47%)·"처리"(68%)로 물으면 정확한 답이
      나오는데도 오탐이 났다. 흔하다는 것과 쓸모없다는 것은 다르고, 그 가중은
      BM25가 이미 IDF로 처리한다
    """
    if counts is None:
        counts = term_document_counts(conn, query, collection)
    if not counts:
        return ""

    content = {t: n for t, n in counts.items() if t not in _NON_CONTENT and len(t) > 1}
    if not content:  # 의문사만으로 이뤄진 질의 — 판정할 근거가 없다
        content = counts

    missing = [t for t, n in content.items() if n == 0]
    mostly_absent = bool(content) and len(missing) >= len(content) * ABSENT_TERM_RATIO

    if hits and not mostly_absent:
        return ""

    parts = []
    if not hits:
        parts.append("결과가 없다")
    if mostly_absent:
        parts.append(f"이 서재가 쓰지 않는 말: {', '.join(missing)}")

    terms = collection_terms(conn, collection, limit=25)
    if terms:
        where = f"'{collection}' 책장" if collection else "이 서재"
        parts.append(f"{where}에서 실제로 쓰는 용어: {', '.join(terms)}")
    parts.append("이 용어들로 바꿔 다시 검색하라")

    return ". ".join(parts) + "."
