"""MCP 서버 (stdio).

Claude가 이 서재의 손님으로서 쓰는 도구 4개를 노출한다.
서버 instructions에 컬렉션 목록과 설명을 주입해서, Claude가 "어느 책장을 열지"를
먼저 고르게 만든다 — 이게 전체 색인에 top_k를 던지는 방식과의 차이다.

stdout은 MCP 프로토콜 채널이다. 이 모듈은 stdout에 아무것도 출력하지 않는다.
"""

from __future__ import annotations

import base64
import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable

from mcp.server.mcpserver import MCPServer

from . import __version__, organize
from .index import open_db
from .parsers.image import is_image, mime_type
from .paths import OutsideRootError
from .search import (
    collection_guide,
    document_total,
    get_document,
    list_collections,
    list_documents,
    search,
    search_hint,
    term_document_counts,
)

# get_document가 한 번에 돌려주는 최대 분량. 넘으면 잘라내고 section을 쓰라고 알린다.
MAX_DOCUMENT_CHARS = 40_000


def _image_result(root: Path, doc: dict[str, Any]):
    """이미지 문서를 MCP 이미지 블록으로 돌려준다.

    OCR을 하지 않는다. 원본을 그대로 넘기면 멀티모달 모델이 표·다이어그램까지
    OCR보다 잘 읽는다. 판단은 손님이 한다는 원칙 그대로다.
    """
    from mcp_types import ImageContent, TextContent

    path = root / doc["path"]
    try:
        data = path.read_bytes()
    except OSError as e:
        return {"error": f"이미지를 읽지 못했다: {e}"}

    return [
        TextContent(
            type="text",
            text=f"{doc['path']} (이미지). 아래 그림을 직접 보고 판단하라.",
        ),
        ImageContent(
            type="image",
            data=base64.b64encode(data).decode("ascii"),
            mimeType=mime_type(path),
        ),
    ]


def build_instructions(conn: sqlite3.Connection, root: Path) -> str:
    """컬렉션 설명 목록을 서버 instructions로 만든다 (SPEC 4절)."""
    collections = list_collections(conn, include_inbox=False)

    lines = [
        f"로컬 서재({root.name})에 꽂힌 문서를 검색하는 도구다. 답변에는 반드시 출처(source, location)를 함께 밝힌다.",
        "",
    ]

    if collections:
        lines.append("이 서재에는 다음 책장이 있다. 질문에 맞는 책장을 골라 collection 인자와 함께 search를 호출하라.")
        for c in collections:
            desc = c.description.replace("\n", " ").strip()
            if len(desc) > 300:
                desc = desc[:300] + "…"
            lines.append(f"- {c.dirname} ({c.doc_count}건): {desc}")
    else:
        lines.append("아직 책장이 없다. 루트 폴더 아래에 폴더를 만들고 문서를 넣으면 색인된다.")

    pending = organize.inbox_count(conn)
    if pending:
        lines.append("")
        lines.append(
            f"아직 분류되지 않은 파일이 {pending}건 있다 (검색 결과에서는 기본 제외). "
            "사용자가 정리를 부탁하면 list_inbox로 내용을 보고 file_document로 알맞은 책장에 꽂아라."
        )

    lines += [
        "",
        "검색이 빗나가면 포기하지 말고 표현을 바꿔 다시 검색하라.",
        "이 서재는 형태소 기반 키워드 검색이라 문서가 쓰는 어휘와 어긋나면 못 찾는다.",
        "search 응답의 hint에 색인에 없는 단어와 그 책장에서 실제로 쓰이는 용어가 담겨 온다.",
    ]
    return "\n".join(lines)


def create_server(
    root: Path,
    conn: sqlite3.Connection | None = None,
    lock: threading.Lock | None = None,
) -> MCPServer:
    """루트 하나에 묶인 MCP 서버를 만든다.

    conn·lock을 넘기면 파일 감시자와 같은 연결을 공유한다.
    그래야 방금 들어온 파일을 검색이 곧바로 본다.
    """
    if conn is None:
        conn = open_db(root, check_same_thread=False)
    if lock is None:
        lock = threading.Lock()

    server = MCPServer(
        name="seojae",
        title=f"서재 — {root.name}",
        version=__version__,
        instructions=build_instructions(conn, root),
    )

    @server.tool(
        name="list_collections",
        description=(
            "이 서재의 책장(컬렉션) 목록과 각 책장의 설명을 돌려준다. "
            "어느 책장을 검색할지 고를 때 먼저 호출한다."
        ),
    )
    def list_collections_tool() -> list[dict[str, Any]]:
        with lock:
            collections = list_collections(conn, include_inbox=False)
        return [
            {
                "name": c.dirname,
                "title": c.name,
                "description": c.description,
                "tags": c.tags,
                "doc_count": c.doc_count,
                "updated": c.updated,
            }
            for c in collections
        ]

    @server.tool(
        name="list_documents",
        description="한 책장에 꽂힌 문서 목록. get_document에 넘길 id를 여기서 얻는다.",
    )
    def list_documents_tool(collection: str) -> list[dict[str, Any]]:
        with lock:
            docs = list_documents(conn, collection=collection)
        return [
            {
                "id": d.id,
                "title": d.title,
                "path": d.path,
                "pages": d.pages,
                "indexed_at": d.indexed_at,
            }
            for d in docs
        ]

    @server.tool(
        name="search",
        description=(
            "서재 안의 문서를 검색한다. 결과마다 출처(source 파일 경로, location 헤딩/페이지)가 붙는다. "
            "collection을 지정하면 그 책장만 본다. "
            "결과가 부실하면 응답의 hint를 읽고 표현을 바꿔 다시 호출하라."
        ),
    )
    def search_tool(
        query: str,
        collection: str | None = None,
        top_k: int = 5,
        include_inbox: bool = False,
    ) -> dict[str, Any]:
        with lock:
            hits = search(
                conn, query, collection=collection, top_k=top_k, include_inbox=include_inbox
            )
            counts = term_document_counts(conn, query, collection)
            hint = search_hint(conn, query, hits, collection, counts=counts)
            total_docs = document_total(conn, collection)

        return {
            "query": query,
            # 검색어별로 몇 개 문서에 나오는지. 0이면 이 서재가 쓰지 않는 말이다.
            # document_count가 분모다 (269/576이면 흔한 말, 27/576이면 특정적인 말).
            "term_document_counts": counts,
            "document_count": total_docs,
            "results": [
                {
                    "text": h.text,
                    "collection": h.collection,
                    "source": h.source,
                    "location": h.location,
                    "score": h.score,
                    "document_id": h.doc_id,
                    "also_in": h.also_in,
                }
                for h in hits
            ],
            "hint": hint,
        }

    @server.tool(
        name="get_collection_guide",
        description=(
            "책장을 고른 다음 '여기 무엇이 있는지'를 알려주는 안내. "
            "README 본문 + 폴더 구성 + 파일 형식 분포 + 자주 쓰는 용어. "
            "문서를 전부 나열하지 않으므로 가볍다. 어디를 뒤질지 정할 때 쓴다."
        ),
    )
    def get_collection_guide_tool(collection: str) -> dict[str, Any]:
        with lock:
            guide = collection_guide(conn, collection)
        if guide is None:
            return {"error": f"'{collection}' 책장을 찾을 수 없다. list_collections로 확인하라."}
        if not guide["guide"]:
            guide["note"] = (
                "이 책장에는 아직 안내문(README 본문)이 없다. "
                "describe_collection으로 재료를 보고 write_collection_readme로 써두면 "
                "다음부터 이 자리에서 바로 읽을 수 있다."
            )
        return guide

    @server.tool(
        name="get_document",
        description=(
            "문서 원문을 읽는다. section을 주면 그 헤딩·페이지 부분만 읽는다. "
            "검색 결과의 location을 section으로 넘기면 그 대목만 정확히 볼 수 있다. "
            "이미지 파일이면 이미지 자체를 돌려주므로 직접 보고 판단하면 된다."
        ),
    )
    def get_document_tool(document_id: int, section: str | None = None):
        with lock:
            doc = get_document(conn, document_id, section=section)
        if doc is None:
            return {"error": f"문서 {document_id}를 찾을 수 없다. list_documents로 id를 확인하라."}

        # 이미지는 우리가 읽지 않는다. 원본을 넘겨 Claude가 직접 보게 한다.
        if is_image(doc["path"]):
            return _image_result(root, doc)

        text_parts = []
        total = 0
        truncated = False
        for part in doc["sections"]:
            piece = f"— {part['location']}\n{part['text']}"
            if total + len(piece) > MAX_DOCUMENT_CHARS:
                truncated = True
                break
            text_parts.append(piece)
            total += len(piece)

        result = {
            "id": doc["id"],
            "title": doc["title"],
            "path": doc["path"],
            "collection": doc["collection"],
            "pages": doc["pages"],
            "text": "\n\n".join(text_parts),
        }
        if truncated:
            result["note"] = (
                f"문서가 길어 앞부분 {MAX_DOCUMENT_CHARS}자만 돌려줬다. "
                "section 인자로 필요한 부분을 지정해 다시 호출하라."
            )
        return result

    # ── 정리 축 ──────────────────────────────────────────────────────────

    @server.tool(
        name="list_inbox",
        description=(
            "아직 어느 책장에도 꽂히지 않은 파일 목록. 각 파일의 본문 앞부분이 함께 온다. "
            "이걸 읽고 어느 책장에 속하는지 판단한 뒤 file_document로 옮긴다."
        ),
    )
    def list_inbox_tool(limit: int = 20) -> dict[str, Any]:
        with lock:
            items = organize.list_inbox(conn, root, limit=limit)
            shelves = [
                {"name": c.dirname, "description": c.description}
                for c in list_collections(conn, include_inbox=False)
            ]
        return {
            "files": [
                {
                    "document_id": i.id,
                    "filename": i.filename,
                    "path": i.path,
                    "size": i.size,
                    "added_at": i.added_at,
                    "excerpt": i.excerpt,
                    "status": i.status,
                    "error": i.error,
                }
                for i in items
            ],
            # 어디로 보낼지 고르려면 선택지가 같이 있어야 한다
            "collections": shelves,
        }

    @server.tool(
        name="file_document",
        description=(
            "미분류 파일을 책장으로 옮긴다. 파일을 실제로 이동시키므로 신중히 부른다. "
            "없는 책장으로 보내려면 create_collection=true가 필요하다. "
            "같은 이름이 있으면 덮어쓰지 않고 접미사를 붙인다. "
            "잘못했으면 사용자가 CLI에서 'seojae undo'로 되돌릴 수 있다."
        ),
    )
    def file_document_tool(
        document_id: int,
        collection: str,
        new_name: str | None = None,
        create_collection: bool = False,
    ) -> dict[str, Any]:
        try:
            with lock:
                result = organize.file_document(
                    conn,
                    root,
                    document_id,
                    collection,
                    new_name=new_name,
                    create_collection=create_collection,
                )
        except (organize.OrganizeError, OutsideRootError) as e:
            return {"error": str(e)}

        return {
            "moved": True,
            "document_id": result.document_id,
            "from": result.src,
            "to": result.dst,
            "collection": result.collection,
            "created_collection": result.created_collection,
            "note": result.note,
        }

    @server.tool(
        name="describe_collection",
        description=(
            "책장 설명(README)을 쓰기 위한 재료를 모아준다. 문서 제목·헤딩·발췌·자주 쓰는 용어. "
            "이걸 읽고 '어떤 질문에 이 책장을 써야 하는지'를 문장으로 써서 "
            "write_collection_readme로 저장한다."
        ),
    )
    def describe_collection_tool(collection: str) -> dict[str, Any]:
        try:
            with lock:
                material = organize.describe_collection(conn, root, collection)
        except organize.OrganizeError as e:
            return {"error": str(e)}

        return {
            "collection": material.collection,
            "document_count": material.document_count,
            "has_readme": material.has_readme,
            "current_description": material.current_description,
            "documents": material.documents,
            "frequent_terms": material.frequent_terms,
            "guidance": (
                "description은 '어떤 질문에 이 책장을 써야 하는지'를 적는다. "
                "책장에 무엇이 들어있는지가 아니라, 무엇을 물어볼 때 여는지를 쓴다. "
                "이 문장이 다음 연결부터 검색 라우팅의 근거가 된다."
            ),
        }

    @server.tool(
        name="write_collection_readme",
        description=(
            "책장의 README.md 프론트매터를 갱신한다. 본문은 그대로 두고 원본은 백업한다. "
            "describe_collection으로 재료를 먼저 읽어라."
        ),
    )
    def write_collection_readme_tool(
        collection: str,
        name: str,
        description: str,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        try:
            with lock:
                path = organize.write_collection_readme(
                    conn, root, collection, name, description, tags
                )
        except organize.OrganizeError as e:
            return {"error": str(e)}

        return {
            "written": path,
            "note": "설명이 검색 라우팅에 반영되는 것은 다음 연결부터다 (instructions는 연결 시 한 번 전달된다).",
        }

    return server


def serve(
    root: Path,
    watch: bool = True,
    on_change: Callable[[str, str], None] | None = None,
) -> None:
    """stdio MCP 서버를 띄운다. watch=True면 파일 감시도 함께 돈다."""
    conn = open_db(root, check_same_thread=False)
    lock = threading.Lock()
    server = create_server(root, conn=conn, lock=lock)

    watcher = None
    if watch:
        from .watcher import ShelfWatcher

        watcher = ShelfWatcher(root, conn, lock, on_change=on_change)
        watcher.start()

    try:
        server.run("stdio")
    finally:
        if watcher is not None:
            watcher.stop()
        conn.close()
