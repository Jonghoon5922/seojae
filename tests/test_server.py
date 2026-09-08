"""MCP 서버. 도구 4개가 SPEC 이름 그대로 노출되고 출처가 붙어 나와야 한다."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from seojae.index import index_root, open_db
from seojae.search import (
    collection_terms,
    document_total,
    search,
    search_hint,
    term_document_counts,
    unmatched_terms,
)
from seojae.server import build_instructions, create_server


@pytest.fixture
def indexed(shelf: Path) -> Path:
    conn = open_db(shelf)
    index_root(shelf, conn)
    conn.close()
    return shelf


def run(coro):
    return asyncio.run(coro)


def test_instructions_list_collections(indexed: Path) -> None:
    conn = open_db(indexed)
    text = build_instructions(conn, indexed)
    conn.close()

    assert "업무규정" in text
    assert "휴가" in text  # description이 라우팅 근거로 들어간다
    assert "_inbox" not in text  # 인박스는 책장 목록에 끼지 않는다
    assert "분류되지 않은 파일이 1건" in text


def test_tools_exposed_with_spec_names(indexed: Path) -> None:
    server = create_server(indexed)
    tools = run(server.list_tools())
    names = {t.name for t in tools}
    assert names == {"list_collections", "list_documents", "search", "get_document"}


def test_every_tool_has_description(indexed: Path) -> None:
    server = create_server(indexed)
    for tool in run(server.list_tools()):
        assert tool.description, f"{tool.name}에 설명이 없다"


def _payload(result) -> dict | list:
    """call_tool 결과에서 구조화된 내용을 꺼낸다.

    목록을 돌려주는 도구는 {"result": [...]} 로 감싸여 온다.
    """
    structured = result.structured_content
    if structured is not None:
        return structured.get("result", structured) if isinstance(structured, dict) else structured
    return json.loads(result.content[0].text)


def test_search_tool_returns_sources(indexed: Path) -> None:
    server = create_server(indexed)
    payload = _payload(run(server.call_tool("search", {"query": "연차 휴가 며칠"})))

    assert payload["results"], "결과가 있어야 한다"
    top = payload["results"][0]
    assert top["source"].endswith("휴가규정.md")
    assert top["location"]
    assert top["document_id"] > 0


def test_search_tool_hint_when_nothing_matches(indexed: Path) -> None:
    server = create_server(indexed)
    payload = _payload(
        run(server.call_tool("search", {"query": "리프레시 정책", "collection": "업무규정"}))
    )
    assert payload["hint"], "아무 검색어도 색인에 없으면 재검색 힌트가 와야 한다"
    assert "쓰지 않는 말" in payload["hint"]
    assert "실제로 쓰는 용어" in payload["hint"]
    assert payload["term_document_counts"]["리프레시"] == 0


def test_no_hint_when_search_succeeded_despite_unknown_word(indexed: Path) -> None:
    """'며칠' 같은 의문사는 문서에 없다. 그것만으로 잔소리하면 안 된다."""
    server = create_server(indexed)
    payload = _payload(
        run(server.call_tool("search", {"query": "연차 휴가 며칠", "collection": "업무규정"}))
    )
    assert payload["results"], "결과는 나와야 한다"
    assert payload["term_document_counts"]["며칠"] == 0
    assert payload["hint"] == "", "결과가 멀쩡하면 힌트를 붙이지 않는다"


def test_get_document_tool_section(indexed: Path) -> None:
    server = create_server(indexed)
    docs = _payload(run(server.call_tool("list_documents", {"collection": "업무규정"})))
    doc = next(d for d in docs if d["path"].endswith("휴가규정.md"))

    payload = _payload(
        run(server.call_tool("get_document", {"document_id": doc["id"], "section": "병가"}))
    )
    assert "진단서" in payload["text"]
    assert "연차" not in payload["text"]  # section으로 좁혀졌다


def test_get_document_tool_missing(indexed: Path) -> None:
    server = create_server(indexed)
    payload = _payload(run(server.call_tool("get_document", {"document_id": 99999})))
    assert "error" in payload


def test_unmatched_terms(indexed: Path) -> None:
    conn = open_db(indexed)
    assert unmatched_terms(conn, "연차") == []
    assert "제주도" in unmatched_terms(conn, "제주도 연차")
    conn.close()


def test_term_document_counts(indexed: Path) -> None:
    conn = open_db(indexed)
    counts = term_document_counts(conn, "연차 제주도", collection="업무규정")
    assert counts["연차"] > 0
    assert counts["제주도"] == 0
    conn.close()


def test_no_hint_for_common_domain_words(indexed: Path) -> None:
    """흔하다고 쓸모없는 것이 아니다. 문서 집합이 동질적이면 도메인 용어가 원래 흔하다."""
    conn = open_db(indexed)
    hits = search(conn, "휴가")
    assert hits
    assert search_hint(conn, "휴가", hits, collection="업무규정") == ""
    conn.close()


def test_hint_when_most_content_words_absent(indexed: Path) -> None:
    """내용어 절반 이상이 색인에 없으면 질의가 이 서재와 겉돈다."""
    conn = open_db(indexed)
    query = "블록체인 합의 알고리즘"
    hits = search(conn, query, collection="업무규정")
    hint = search_hint(conn, query, hits, collection="업무규정")
    assert hint
    assert "블록체인" in hint
    conn.close()


def test_document_total(indexed: Path) -> None:
    conn = open_db(indexed)
    assert document_total(conn, "업무규정") == 3
    assert document_total(conn) == 3  # 인박스는 세지 않는다
    conn.close()


def test_collection_terms(indexed: Path) -> None:
    conn = open_db(indexed)
    terms = collection_terms(conn, "업무규정")
    assert terms
    assert any(t in terms for t in ("휴가", "연차", "출장"))
    conn.close()


def test_hint_absent_when_search_is_clean(indexed: Path) -> None:
    conn = open_db(indexed)
    hits = search(conn, "연차 휴가")
    assert search_hint(conn, "연차 휴가", hits) == ""
    conn.close()
