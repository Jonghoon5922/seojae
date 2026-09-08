"""웹 UI API.

핵심 요구는 하나다: **Claude가 쓰는 검색과 같은 결과가 나와야 한다.**
따로 만든 검색이면 "근거 재현"이 아니라 흉내다.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from seojae.index import index_root, open_db
from seojae.paths import INBOX_DIRNAME
from seojae.search import search
from seojae.web import create_app


@pytest.fixture
def client(shelf: Path):
    conn = open_db(shelf, check_same_thread=False)
    index_root(shelf, conn)
    app = create_app(shelf, conn, threading.Lock())
    with TestClient(app) as c:
        yield c, shelf, conn
    conn.close()


# ── 화면 ──────────────────────────────────────────────────────────────────


def test_index_page_served(client) -> None:
    c, _, _ = client
    res = c.get("/")
    assert res.status_code == 200
    assert "서재" in res.text
    assert "<script" in res.text  # 빌드 도구 없이 HTML 한 장


# ── 상태 ──────────────────────────────────────────────────────────────────


def test_status(client) -> None:
    c, shelf, _ = client
    data = c.get("/api/status").json()

    assert data["name"] == shelf.name
    assert data["document_count"] == 3
    assert data["inbox_count"] == 1
    assert {col["name"] for col in data["collections"]} == {"업무규정"}
    assert data["collections"][0]["has_readme"] is True
    assert data["failed"] == []


def test_status_reports_failed_files(client) -> None:
    c, shelf, conn = client
    broken = shelf / "업무규정" / "깨진문서.docx"
    broken.write_bytes("이건 docx가 아니다".encode("utf-8"))
    index_root(shelf, conn)

    data = c.get("/api/status").json()
    assert len(data["failed"]) == 1
    assert "깨진문서" in data["failed"][0]["path"]


# ── 검색 (Claude와 같은 함수인가) ─────────────────────────────────────────


def test_search_matches_the_function_claude_uses(client) -> None:
    c, _, conn = client
    query = "연차 휴가"

    web = c.get("/api/search", params={"q": query, "top_k": 5}).json()
    direct = search(conn, query, top_k=5)

    assert [r["source"] for r in web["results"]] == [h.source for h in direct]
    assert [r["score"] for r in web["results"]] == [h.score for h in direct]


def test_search_returns_source_and_terms(client) -> None:
    c, _, _ = client
    data = c.get("/api/search", params={"q": "연차 휴가 며칠"}).json()

    assert data["results"][0]["source"].endswith("휴가규정.md")
    assert data["results"][0]["location"]
    assert data["term_document_counts"]["며칠"] == 0
    assert data["hint"] == ""  # 검색이 성공했으면 잔소리하지 않는다


def test_search_hint_surfaces(client) -> None:
    c, _, _ = client
    data = c.get("/api/search", params={"q": "블록체인 합의 알고리즘"}).json()
    assert data["hint"]
    assert "블록체인" in data["hint"]


def test_search_filters_by_collection(client) -> None:
    c, _, _ = client
    ok = c.get("/api/search", params={"q": "숙박비", "collection": "업무규정"}).json()
    assert ok["results"]

    none = c.get("/api/search", params={"q": "숙박비", "collection": "없는것"}).json()
    assert none["results"] == []


def test_search_excludes_inbox_by_default(client) -> None:
    c, _, _ = client
    data = c.get("/api/search", params={"q": "낙서"}).json()
    assert all(INBOX_DIRNAME not in r["source"] for r in data["results"])

    with_inbox = c.get("/api/search", params={"q": "낙서", "include_inbox": True}).json()
    assert any(INBOX_DIRNAME in r["source"] for r in with_inbox["results"])


# ── 문서 보기 ─────────────────────────────────────────────────────────────


def test_document_view(client) -> None:
    c, _, _ = client
    docs = c.get("/api/documents", params={"collection": "업무규정"}).json()
    doc = next(d for d in docs if d["path"].endswith("휴가규정.md"))

    data = c.get(f"/api/document/{doc['id']}").json()
    assert data["title"] == "휴가 규정"
    assert len(data["sections"]) >= 2
    assert all("location" in s and "text" in s for s in data["sections"])


def test_document_missing(client) -> None:
    c, _, _ = client
    assert c.get("/api/document/99999").status_code == 404


# ── 인박스와 정리 ─────────────────────────────────────────────────────────


def test_inbox_lists_files_and_shelves(client) -> None:
    c, _, _ = client
    data = c.get("/api/inbox").json()

    assert len(data["files"]) == 1
    assert data["files"][0]["filename"] == "미분류메모.md"
    assert data["files"][0]["excerpt"]
    assert data["collections"] == ["업무규정"]  # 고를 선택지가 함께 온다


def test_file_moves_document(client) -> None:
    c, shelf, _ = client
    doc_id = c.get("/api/inbox").json()["files"][0]["document_id"]

    res = c.post("/api/file", json={"document_id": doc_id, "collection": "업무규정"})
    assert res.status_code == 200
    assert res.json()["to"] == "업무규정/미분류메모.md"
    assert (shelf / "업무규정" / "미분류메모.md").is_file()
    assert c.get("/api/status").json()["inbox_count"] == 0


def test_file_rejects_path_escape(client) -> None:
    c, shelf, _ = client
    doc_id = c.get("/api/inbox").json()["files"][0]["document_id"]

    res = c.post(
        "/api/file",
        json={"document_id": doc_id, "collection": "../탈출", "create_collection": True},
    )
    assert res.status_code == 400
    assert "error" in res.json()
    assert (shelf / INBOX_DIRNAME / "미분류메모.md").is_file()  # 원본 그대로


def test_undo_reverts_move(client) -> None:
    c, shelf, _ = client
    doc_id = c.get("/api/inbox").json()["files"][0]["document_id"]
    c.post("/api/file", json={"document_id": doc_id, "collection": "업무규정"})

    res = c.post("/api/undo")
    assert res.status_code == 200
    assert "되돌렸다" in res.json()["message"]
    assert (shelf / INBOX_DIRNAME / "미분류메모.md").is_file()


def test_undo_with_nothing_to_undo(client) -> None:
    c, _, _ = client
    res = c.post("/api/undo")
    assert res.status_code == 400


def test_moves_log(client) -> None:
    c, _, _ = client
    doc_id = c.get("/api/inbox").json()["files"][0]["document_id"]
    c.post("/api/file", json={"document_id": doc_id, "collection": "업무규정"})

    rows = c.get("/api/moves").json()
    assert len(rows) == 1
    assert rows[0]["kind"] == "move"
    assert rows[0]["undone"] is False


# ── 책장 설명 ─────────────────────────────────────────────────────────────


def test_collection_material(client) -> None:
    c, _, _ = client
    data = c.get("/api/collection/업무규정/material").json()

    assert data["document_count"] == 3
    assert data["frequent_terms"]
    assert any(d["headings"] for d in data["documents"])


def test_collection_material_missing(client) -> None:
    c, _, _ = client
    assert c.get("/api/collection/없는책장/material").status_code == 404


def test_write_readme(client) -> None:
    c, shelf, _ = client
    res = c.post(
        "/api/readme",
        json={
            "collection": "업무규정",
            "name": "업무규정",
            "description": "사규 안내. 근태 질문에 쓴다.",
            "tags": ["사규"],
        },
    )
    assert res.status_code == 200
    assert "사규 안내" in (shelf / "업무규정" / "README.md").read_text(encoding="utf-8")


def test_write_readme_rejects_empty_description(client) -> None:
    c, _, _ = client
    res = c.post(
        "/api/readme",
        json={"collection": "업무규정", "name": "업무규정", "description": "  "},
    )
    assert res.status_code == 400


# ── 재색인 ────────────────────────────────────────────────────────────────


def test_reindex_endpoint(client) -> None:
    c, shelf, _ = client
    (shelf / "업무규정" / "새문서.md").write_text("# 새 문서\n내용이다.\n", encoding="utf-8")

    stats = c.post("/api/reindex").json()
    assert stats["indexed"] == 1
    assert c.get("/api/search", params={"q": "새 문서"}).json()["results"]


# ── 책장 관리 ─────────────────────────────────────────────────────────────


def test_create_collection_endpoint(client) -> None:
    c, shelf, _ = client
    res = c.post("/api/collection", json={"name": "개발가이드", "description": "코딩 규약."})

    assert res.status_code == 200
    assert res.json()["created"] == "개발가이드"
    assert (shelf / "개발가이드" / "README.md").is_file()
    assert "개발가이드" in {x["name"] for x in c.get("/api/status").json()["collections"]}


def test_create_collection_rejects_duplicate(client) -> None:
    c, _, _ = client
    assert c.post("/api/collection", json={"name": "업무규정"}).status_code == 400


def test_create_collection_rejects_path(client) -> None:
    c, shelf, _ = client
    assert c.post("/api/collection", json={"name": "../탈출"}).status_code == 400
    assert not (shelf.parent / "탈출").exists()


def test_rename_collection_endpoint(client) -> None:
    c, shelf, _ = client
    res = c.patch("/api/collection/업무규정", json={"name": "사규"})

    assert res.status_code == 200
    assert (shelf / "사규").is_dir()
    assert not (shelf / "업무규정").exists()

    # 이름만 바뀌고 색인은 유지된다
    hits = c.get("/api/search", params={"q": "연차 휴가", "collection": "사규"}).json()
    assert hits["results"]
    assert hits["results"][0]["source"].startswith("사규/")


def test_rename_collection_rejects_taken_name(client) -> None:
    c, _, _ = client
    c.post("/api/collection", json={"name": "메모함"})
    assert c.patch("/api/collection/업무규정", json={"name": "메모함"}).status_code == 400


def test_delete_empty_collection_endpoint(client) -> None:
    c, shelf, _ = client
    c.post("/api/collection", json={"name": "메모함"})

    assert c.delete("/api/collection/메모함").status_code == 200
    assert not (shelf / "메모함").exists()


def test_delete_collection_refuses_when_not_empty(client) -> None:
    c, shelf, _ = client
    res = c.delete("/api/collection/업무규정")

    assert res.status_code == 400
    assert (shelf / "업무규정").is_dir()


def test_undo_collection_rename(client) -> None:
    c, shelf, _ = client
    c.patch("/api/collection/업무규정", json={"name": "사규"})

    assert c.post("/api/undo").status_code == 200
    assert (shelf / "업무규정").is_dir()
    assert not (shelf / "사규").exists()


# ── 밖에서 파일 가져오기 (드래그앤드롭) ───────────────────────────────────


def test_import_file_into_collection(client) -> None:
    c, shelf, _ = client
    res = c.post(
        "/api/import",
        data={"collection": "업무규정"},
        files={"files": ("복리후생.md", "# 복리후생\n\n## 경조사비\n결혼 50만원.\n", "text/markdown")},
    )

    assert res.status_code == 200
    assert res.json()["added"][0]["to"] == "업무규정/복리후생.md"
    assert (shelf / "업무규정" / "복리후생.md").is_file()
    assert c.get("/api/search", params={"q": "경조사비"}).json()["results"]


def test_import_into_inbox(client) -> None:
    c, shelf, _ = client
    res = c.post(
        "/api/import",
        data={"collection": "_inbox"},
        files={"files": ("아무거나.md", "# 메모\n사바티컬 검토.\n", "text/markdown")},
    )

    assert res.status_code == 200
    assert (shelf / "_inbox" / "아무거나.md").is_file()
    assert c.get("/api/status").json()["inbox_count"] == 2


def test_import_never_overwrites(client) -> None:
    c, shelf, _ = client
    before = (shelf / "업무규정" / "휴가규정.md").read_text(encoding="utf-8")

    res = c.post(
        "/api/import",
        data={"collection": "업무규정"},
        files={"files": ("휴가규정.md", "# 덮어쓰기 시도\n", "text/markdown")},
    )

    assert res.json()["added"][0]["to"] == "업무규정/휴가규정 (2).md"
    assert (shelf / "업무규정" / "휴가규정.md").read_text(encoding="utf-8") == before


def test_import_strips_path_from_filename(client) -> None:
    """브라우저가 준 이름은 믿지 않는다. 경로 성분을 떼고 이름만 쓴다."""
    c, shelf, _ = client
    res = c.post(
        "/api/import",
        data={"collection": "업무규정"},
        files={"files": ("../../탈출.md", "# 탈출 시도\n", "text/markdown")},
    )

    assert res.status_code == 200
    assert res.json()["added"][0]["to"] == "업무규정/탈출.md"
    assert not (shelf.parent / "탈출.md").exists()


def test_import_rejects_unsupported_type(client) -> None:
    c, shelf, _ = client
    res = c.post(
        "/api/import",
        data={"collection": "업무규정"},
        files={"files": ("압축.zip", "PK fake archive", "application/zip")},
    )

    assert res.status_code == 400
    assert not (shelf / "업무규정" / "압축.zip").exists()


def test_import_rejects_unknown_collection(client) -> None:
    c, _, _ = client
    res = c.post(
        "/api/import",
        data={"collection": "없는책장"},
        files={"files": ("a.md", "# a\n", "text/markdown")},
    )
    assert res.status_code == 400


def test_import_is_logged(client) -> None:
    c, _, _ = client
    c.post(
        "/api/import",
        data={"collection": "업무규정"},
        files={"files": ("복리후생.md", "# 복리후생\n내용\n", "text/markdown")},
    )

    rows = c.get("/api/moves").json()
    assert rows[0]["kind"] == "import"
    assert rows[0]["dst"] == "업무규정/복리후생.md"


# ── 다른 사이트의 조종 차단 ───────────────────────────────────────────────
# 127.0.0.1 서버는 인증이 없다. 브라우저는 아무 웹페이지에서나 localhost 로
# 요청을 보내는 것 자체는 막지 않는다 — 응답을 '읽는' 것만 CORS로 막는다.
# 실제로 악성 Origin 을 단 요청으로 파일이 심어지는 것을 확인하고 막았다.

EVIL = {"Origin": "https://evil.example.com"}


def test_foreign_origin_cannot_read(client) -> None:
    c, _, _ = client
    assert c.get("/api/search", params={"q": "연차"}, headers=EVIL).status_code == 403
    assert c.get("/api/status", headers=EVIL).status_code == 403


def test_foreign_origin_cannot_write(client) -> None:
    c, shelf, _ = client
    res = c.post(
        "/api/import",
        data={"collection": "업무규정"},
        files={"files": ("악성.md", "# 심어진 파일\n", "text/markdown")},
        headers=EVIL,
    )
    assert res.status_code == 403
    assert not (shelf / "업무규정" / "악성.md").exists()


def test_foreign_origin_cannot_undo(client) -> None:
    c, _, _ = client
    assert c.post("/api/undo", headers=EVIL).status_code == 403


def test_local_origin_is_allowed(client) -> None:
    c, _, _ = client
    for origin in ("http://127.0.0.1:8765", "http://localhost:8765"):
        assert c.get("/api/status", headers={"Origin": origin}).status_code == 200


def test_no_origin_is_allowed(client) -> None:
    """curl 처럼 Origin 이 없는 요청은 사용자 본인의 도구로 본다."""
    c, _, _ = client
    assert c.get("/api/status").status_code == 200
