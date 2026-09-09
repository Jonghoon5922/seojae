"""색인과 검색. 1단계의 완료 기준이다."""

from __future__ import annotations

from pathlib import Path

import pytest

from seojae.index import index_root, last_indexed_at, open_db
from seojae.paths import INBOX_DIRNAME
from seojae.search import get_document, list_collections, list_documents, search
from seojae.tokenizer import build_match_query, tokenize


@pytest.fixture
def conn(shelf: Path):
    connection = open_db(shelf)
    index_root(shelf, connection)
    yield connection
    connection.close()


def test_tokenize_korean_morphemes() -> None:
    tokens = tokenize("연차 휴가는 며칠인가요?")
    assert "연차" in tokens
    assert "휴가" in tokens


def test_tokenize_keeps_ascii_identifier() -> None:
    assert "mnz310bean001" in tokenize("MNz310Bean001 파일을 보라")


def test_match_query_empty_for_blank() -> None:
    assert build_match_query("   ") == ""


def test_index_counts(shelf: Path) -> None:
    connection = open_db(shelf)
    stats = index_root(shelf, connection)
    assert stats.indexed == 4  # README + 휴가규정 + 출장지침 + 인박스 메모
    assert stats.failed == 0
    assert stats.chunks > 0
    assert last_indexed_at(connection)
    connection.close()


def test_reindex_skips_unchanged(shelf: Path) -> None:
    connection = open_db(shelf)
    index_root(shelf, connection)
    second = index_root(shelf, connection)
    assert second.indexed == 0
    assert second.skipped == 4
    connection.close()


def test_reindex_picks_up_changes(shelf: Path) -> None:
    connection = open_db(shelf)
    index_root(shelf, connection)
    (shelf / "업무규정" / "휴가규정.md").write_text("# 휴가 규정\n\n## 연차\n바뀐 내용\n", encoding="utf-8")
    stats = index_root(shelf, connection)
    assert stats.indexed == 1
    connection.close()


def test_reindex_removes_deleted(shelf: Path) -> None:
    connection = open_db(shelf)
    index_root(shelf, connection)
    (shelf / "업무규정" / "출장지침.md").unlink()
    stats = index_root(shelf, connection)
    assert stats.removed == 1
    assert not any(d.path.endswith("출장지침.md") for d in list_documents(connection))
    connection.close()


def test_search_returns_source(conn) -> None:
    hits = search(conn, "연차 휴가 며칠")
    assert hits
    top = hits[0]
    assert top.source.endswith("휴가규정.md")
    assert "연차" in top.location or "연차" in top.text
    assert top.score > 0


def test_search_excludes_inbox_by_default(conn) -> None:
    hits = search(conn, "연차", top_k=10)
    assert all(INBOX_DIRNAME not in h.source for h in hits)

    with_inbox = search(conn, "연차", top_k=10, include_inbox=True)
    assert any(INBOX_DIRNAME in h.source for h in with_inbox)


def test_search_filters_by_collection(conn) -> None:
    assert search(conn, "숙박비", collection="업무규정")
    assert not search(conn, "숙박비", collection="없는컬렉션")


def test_search_dedups_identical_text(shelf: Path) -> None:
    same = "# 공통\n\n## 같은 절\n똑같은 문장이 두 문서에 들어있다.\n"
    (shelf / "업무규정" / "사본A.md").write_text(same, encoding="utf-8")
    (shelf / "업무규정" / "사본B.md").write_text(same, encoding="utf-8")

    connection = open_db(shelf)
    index_root(shelf, connection)
    hits = search(connection, "똑같은 문장", top_k=5)

    sources = [h.source for h in hits]
    assert len(sources) == len(set(sources))
    assert any(h.also_in for h in hits)  # 중복은 also_in으로 알려준다
    connection.close()


def test_search_empty_query(conn) -> None:
    assert search(conn, "") == []


def test_list_collections(conn) -> None:
    names = {c.dirname for c in list_collections(conn)}
    assert "업무규정" in names
    assert INBOX_DIRNAME in names

    without = {c.dirname for c in list_collections(conn, include_inbox=False)}
    assert INBOX_DIRNAME not in without


def test_get_document_sections(conn) -> None:
    doc = next(d for d in list_documents(conn) if d.path.endswith("휴가규정.md"))
    full = get_document(conn, doc.id)
    assert full is not None
    assert len(full["sections"]) >= 2

    only = get_document(conn, doc.id, section="병가")
    assert only is not None
    assert len(only["sections"]) == 1
    assert "진단서" in only["sections"][0]["text"]


def test_get_document_missing(conn) -> None:
    assert get_document(conn, 99999) is None
