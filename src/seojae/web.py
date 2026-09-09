"""로컬 웹 UI (127.0.0.1 전용).

목적이 둘이다.

1. **검증** — Claude가 답한 근거를 사람이 같은 검색어로 재현한다.
   그래서 이 화면은 Claude가 쓰는 것과 **같은 검색 함수**를 호출한다.
   따로 만든 검색이면 재현이 아니라 흉내다.
2. **정리** — AI가 분류한 결과를 사람이 승인·수정하는 자리.

인증은 없다. 대신 127.0.0.1에만 바인딩한다. 이 서버는 네트워크에 열리지 않는다.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from . import __version__, ledger, organize
from .appconfig import config_path, log_path, write_root
from .mcp_clients import ConfigError, register, survey, unregister
from .index import index_root, last_indexed_at
from .parsers import describe_formats, supported_extensions
from .paths import INBOX_DIRNAME, OutsideRootError
from .search import (
    document_total,
    failed_documents,
    get_document,
    list_collections,
    list_documents,
    search,
    search_hint,
    shelved_total,
    term_document_counts,
)

STATIC_DIR = Path(__file__).parent / "static"


class FileRequest(BaseModel):
    document_id: int
    collection: str
    new_name: str | None = None
    create_collection: bool = False


class ReadmeRequest(BaseModel):
    collection: str
    name: str
    description: str
    tags: list[str] | None = None


class CreateCollectionRequest(BaseModel):
    name: str
    description: str | None = None


class RenameCollectionRequest(BaseModel):
    name: str


class SetRootRequest(BaseModel):
    root: str
    create: bool = False


def _is_local_origin(origin: str) -> bool:
    """127.0.0.1 / localhost 에서 온 요청인가."""
    try:
        host = urlparse(origin).hostname or ""
    except ValueError:
        return False
    return host in {"127.0.0.1", "localhost", "::1"}


def _mcp_command() -> str:
    """클라이언트가 실행할 명령. 묶인 앱이면 옆에 있는 콘솔 실행 파일이다.

    창 모드 실행 파일(`서재.exe`)에는 표준 입출력이 없어서 MCP를 못 띄운다.
    그래서 같은 폴더의 `seojae-mcp.exe` 를 가리켜야 한다.
    """
    if getattr(sys, "frozen", False):
        mate = Path(sys.executable).with_name("seojae-mcp.exe")
        if mate.is_file():
            return str(mate)
    return "seojae-mcp"


def _open_in_file_manager(folder: Path) -> None:
    """탐색기(Finder, 파일 관리자)에서 폴더를 연다.

    **호출부가 경로를 정하지 않는다.** 이 함수는 web.py 안에서 서재 루트로만
    불린다. 사용자가 준 경로를 여기로 흘리면 로컬 서버가 아무 폴더나 여는
    수단이 된다.
    """
    if sys.platform == "win32":
        os.startfile(folder)  # noqa: S606 — 폴더를 여는 것뿐이다
    elif sys.platform == "darwin":
        subprocess.run(["open", str(folder)], check=True)
    else:
        subprocess.run(["xdg-open", str(folder)], check=True)


def create_app(
    root: Path,
    conn: sqlite3.Connection,
    lock: threading.Lock,
    allow_root_change: bool = False,
) -> FastAPI:
    app = FastAPI(title=f"서재 — {root.name}", version=__version__, docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def block_foreign_origins(request: Request, call_next):
        """다른 사이트가 이 서버를 조종하지 못하게 한다.

        127.0.0.1 서버는 인증이 없다. 그런데 브라우저는 아무 웹페이지에서나
        localhost 로 요청을 보내는 것 자체는 막지 않는다 — 응답을 '읽는' 것만
        CORS로 막는다. 그래서 쓰기 동작은 그대로 실행된다.

        JSON POST는 프리플라이트가 걸려 브라우저가 막아주지만,
        multipart/form-data 와 본문 없는 POST는 프리플라이트가 없다.
        실제로 악성 사이트 표식을 단 요청으로 파일이 심어지는 것을 확인했다.

        Origin 이 붙어 있으면서 우리 것이 아니면 거부한다. 브라우저는 모든 POST에
        Origin 을 붙이므로 이걸로 걸러진다. curl 처럼 Origin 이 없는 요청은
        사용자 본인의 도구로 보고 통과시킨다.
        """
        origin = request.headers.get("origin")
        if origin and not _is_local_origin(origin):
            return JSONResponse(
                {"error": "다른 사이트에서 온 요청은 받지 않는다."}, status_code=403
            )
        return await call_next(request)

    def fail(message: str, status: int = 400) -> JSONResponse:
        return JSONResponse({"error": message}, status_code=status)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        # 요청마다 읽는다. 개발 중에 새로고침만으로 반영되게.
        return (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    @app.get("/api/status")
    def api_status() -> dict[str, Any]:
        with lock:
            collections = list_collections(conn, include_inbox=False)
            failed = failed_documents(conn)
            return {
                "root": str(root),
                "name": root.name,
                "version": __version__,
                "last_indexed_at": last_indexed_at(conn),
                "document_count": document_total(conn),
                # 미분류·README를 뺀 수. 0이면 아직 아무것도 안 꽂힌 서재다.
                # 첫 실행 안내를 띄울지 여기서 판단한다.
                "shelved_count": shelved_total(conn),
                "inbox_count": organize.inbox_count(conn),
                "claude_registered": any(c["registered"] for c in survey()),
                # 첫 실행 안내가 쓰는 값들. 숫자를 화면에 적어두면 어긋나므로
                # 등록기에서 그때그때 센다.
                "inbox_dirname": INBOX_DIRNAME,
                "format_count": len(describe_formats()),
                "extension_count": len(supported_extensions()),
                "collections": [
                    {
                        "name": c.dirname,
                        "title": c.name,
                        "description": c.description,
                        "tags": c.tags,
                        "doc_count": c.doc_count,
                        "chunk_count": c.chunk_count,
                        "has_readme": c.has_readme,
                        "updated": c.updated,
                    }
                    for c in collections
                ],
                "failed": [{"path": d.path, "error": d.error} for d in failed],
            }

    @app.get("/api/search")
    def api_search(
        q: str,
        collection: str | None = None,
        top_k: int = 10,
        include_inbox: bool = False,
    ) -> dict[str, Any]:
        # Claude가 부르는 것과 같은 함수다. 여기가 갈리면 재현이 아니다.
        with lock:
            hits = search(
                conn, q, collection=collection, top_k=top_k, include_inbox=include_inbox
            )
            counts = term_document_counts(conn, q, collection)
            hint = search_hint(conn, q, hits, collection, counts=counts)
            total = document_total(conn, collection)
            # 내가 앱에서 한 검색도 같은 대출 기록에 남는다. 다른 것은 "누가"뿐이다.
            ledger.record(
                conn,
                tool="search",
                client=ledger.APP_CLIENT,
                query=q,
                collection=collection or "",
                hits=len(hits),
                docs=sorted({h.source for h in hits}),
                note=hint or "",
            )

        return {
            "query": q,
            "term_document_counts": counts,
            "document_count": total,
            "hint": hint,
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
        }

    @app.get("/api/documents")
    def api_documents(collection: str | None = None) -> list[dict[str, Any]]:
        with lock:
            docs = list_documents(conn, collection=collection)
        return [
            {
                "id": d.id,
                "title": d.title,
                "path": d.path,
                "collection": d.collection,
                "pages": d.pages,
                "chunk_count": d.chunk_count,
                "indexed_at": d.indexed_at,
            }
            for d in docs
        ]

    @app.get("/api/document/{document_id}")
    def api_document(document_id: int, section: str | None = None):
        with lock:
            doc = get_document(conn, document_id, section=section)
        if doc is None:
            return fail(f"문서 {document_id}를 찾을 수 없다.", 404)
        return doc

    @app.get("/api/inbox")
    def api_inbox(limit: int = 50) -> dict[str, Any]:
        with lock:
            items = organize.list_inbox(conn, root, limit=limit)
            shelves = [c.dirname for c in list_collections(conn, include_inbox=False)]
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
            "collections": shelves,
        }

    @app.post("/api/file")
    def api_file(req: FileRequest):
        try:
            with lock:
                result = organize.file_document(
                    conn,
                    root,
                    req.document_id,
                    req.collection,
                    new_name=req.new_name,
                    create_collection=req.create_collection,
                )
        except (organize.OrganizeError, OutsideRootError) as e:
            return fail(str(e))

        return {
            "from": result.src,
            "to": result.dst,
            "collection": result.collection,
            "created_collection": result.created_collection,
            "note": result.note,
        }

    @app.get("/api/moves")
    def api_moves(limit: int = 30) -> list[dict[str, Any]]:
        with lock:
            return organize.list_moves(conn, limit=limit)

    @app.get("/api/readings")
    def api_readings(limit: int = 60, only_empty: bool = False) -> dict[str, Any]:
        """대출 기록 — 누가 언제 왜 무엇을 꺼내 갔는지."""
        with lock:
            rows = ledger.readings(conn, limit=limit, only_empty=only_empty)
            stats = ledger.summary(conn)
        return {
            "summary": stats,
            "readings": [
                {
                    "ts": r.ts,
                    "client": r.client,
                    "tool": r.tool,
                    "query": r.query,
                    "collection": r.collection,
                    "hits": r.hits,
                    "docs": r.docs,
                    "note": r.note,
                }
                for r in rows
            ],
        }

    #: 이만큼은 검색해봐야 "안 나온 문서"가 뜻을 가진다. 3번 검색하고 나서
    #: 576건 중 573건이 "안 나왔다"고 늘어놓는 것은 통찰이 아니라 소음이다.
    ENOUGH_SEARCHES = 20

    @app.get("/api/readings/unread")
    def api_unread(limit: int = 50) -> dict[str, Any]:
        """한 번도 꺼내진 적 없는 문서. 아무도 안 찾은 책이다."""
        with lock:
            paths = ledger.unread_documents(conn, limit=limit)
            searches = ledger.summary(conn)["total"]
            shelved = shelved_total(conn)
        return {
            "documents": paths,
            "searches": searches,
            # 기록이 적으면 목록이 사실상 전체 문서다. 그걸 말해준다.
            "enough": searches >= ENOUGH_SEARCHES,
            "needed": ENOUGH_SEARCHES,
            "shelved": shelved,
        }

    @app.post("/api/undo")
    def api_undo():
        try:
            with lock:
                message = organize.undo_last(conn, root)
        except organize.OrganizeError as e:
            return fail(str(e))
        return {"message": message}

    @app.get("/api/collection/{collection}/material")
    def api_material(collection: str):
        try:
            with lock:
                material = organize.describe_collection(conn, root, collection)
        except organize.OrganizeError as e:
            return fail(str(e), 404)
        return {
            "collection": material.collection,
            "document_count": material.document_count,
            "has_readme": material.has_readme,
            "current_description": material.current_description,
            "documents": material.documents,
            "frequent_terms": material.frequent_terms,
        }

    @app.post("/api/readme")
    def api_readme(req: ReadmeRequest):
        try:
            with lock:
                path = organize.write_collection_readme(
                    conn, root, req.collection, req.name, req.description, req.tags
                )
        except organize.OrganizeError as e:
            return fail(str(e))
        return {"written": path}

    @app.post("/api/import")
    async def api_import(
        collection: str = Form(...),
        files: list[UploadFile] = File(...),
    ):
        """밖에서 끌어다 놓은 파일을 서재에 넣는다.

        브라우저는 파일의 실제 경로를 주지 않으므로 원본을 지울 수 없다.
        '이동'이 아니라 '가져오기'다.
        """
        added, failed = [], []
        for upload in files:
            try:
                data = await upload.read()
                with lock:
                    result = organize.import_file(
                        conn, root, collection, upload.filename or "", data
                    )
                added.append({"name": upload.filename, "to": result.dst, "note": result.note})
            except (organize.OrganizeError, OutsideRootError) as e:
                failed.append({"name": upload.filename, "error": str(e)})

        if not added and failed:
            return fail(failed[0]["error"])
        return {"added": added, "failed": failed}

    @app.post("/api/collection")
    def api_create_collection(req: CreateCollectionRequest):
        try:
            with lock:
                name = organize.create_collection(
                    conn, root, req.name, req.description or ""
                )
        except (organize.OrganizeError, OutsideRootError) as e:
            return fail(str(e))
        return {"created": name}

    @app.patch("/api/collection/{collection}")
    def api_rename_collection(collection: str, req: RenameCollectionRequest):
        try:
            with lock:
                name = organize.rename_collection(conn, root, collection, req.name)
        except (organize.OrganizeError, OutsideRootError) as e:
            return fail(str(e))
        return {"renamed": name}

    @app.delete("/api/collection/{collection}")
    def api_delete_collection(collection: str):
        try:
            with lock:
                organize.delete_collection_if_empty(conn, root, collection)
        except (organize.OrganizeError, OutsideRootError) as e:
            return fail(str(e))
        return {"deleted": collection}

    @app.post("/api/open-root")
    def api_open_root():
        """탐색기에서 서재 폴더를 연다.

        첫 실행에 제일 필요한 동작이다. "여기에 파일을 넣으세요"라고 말만 하고
        어디인지 안 열어주면 경로를 복사해서 붙여넣어야 한다.

        경로를 인자로 받지 않는다. 언제나 이 서재의 루트만 연다.
        """
        try:
            _open_in_file_manager(root)
        except OSError as e:
            return fail(f"폴더를 열지 못했다: {e}")
        return {"opened": str(root)}

    @app.get("/api/clients")
    def api_clients() -> list[dict[str, Any]]:
        """어느 앱에 연결돼 있는지. 설정 화면의 연결 목록이 이걸 그린다."""
        return survey()

    @app.post("/api/clients/{client}")
    def api_connect(client: str):
        """그 앱에 서재를 등록한다.

        **여기가 첫 연결의 진짜 입구다.** 설치하면 앱은 이미 열려 있으므로
        버튼 한 번이면 된다. LLM에게 시키려면 LLM이 먼저 서재를 알아야 하는데,
        연결 전에는 알 길이 없다 — 순환이다.
        """
        exe = _mcp_command()
        try:
            message = register(exe, client=client)
        except ConfigError as e:
            return fail(str(e))
        return {"message": message}

    @app.delete("/api/clients/{client}")
    def api_disconnect(client: str):
        try:
            return {"message": unregister(client=client)}
        except ConfigError as e:
            return fail(str(e))

    @app.get("/api/settings")
    def api_settings() -> dict[str, Any]:
        """설정 화면이 보여줄 것들. 앱으로 켰을 때만 서재 폴더를 바꿀 수 있다."""
        from .parsers import describe_formats

        return {
            "root": str(root),
            "version": __version__,
            "config_file": str(config_path()),
            "log_file": str(log_path()),
            "can_change_root": allow_root_change,
            "formats": [{"label": label, "extensions": exts} for label, exts in describe_formats()],
            "inbox_dirname": INBOX_DIRNAME,
        }

    @app.post("/api/settings/root")
    def api_set_root(req: SetRootRequest):
        """서재 폴더를 바꾼다. 실제 전환은 앱을 다시 켤 때 일어난다.

        지금 프로세스는 이미 그 폴더로 색인·감시를 붙들고 있어서, 도중에 갈아끼우면
        상태가 어긋난다. 설정만 바꾸고 재시작을 안내하는 편이 정직하다.
        """
        if not allow_root_change:
            return fail("이 방식으로는 서재 폴더를 바꿀 수 없다. 앱(seojae app)으로 실행하라.")

        target = Path(req.root).expanduser()
        if not target.is_absolute():
            return fail("전체 경로를 입력하라 (예: D:\\자료\\내서재).")
        if target.is_file():
            return fail(f"폴더가 아니다: {target}")

        created = False
        if not target.exists():
            if not req.create:
                return fail(f"그런 폴더가 없다: {target}\n새로 만들려면 '없으면 만들기'를 켜라.")
            try:
                target.mkdir(parents=True)
                created = True
            except OSError as e:
                return fail(f"폴더를 만들지 못했다: {e}")

        try:
            write_root(target)
        except OSError as e:
            return fail(f"설정을 저장하지 못했다: {e}")

        return {
            "root": str(target),
            "created": created,
            "note": "앱을 껐다 켜면 이 서재로 열립니다.",
        }

    @app.post("/api/reindex")
    def api_reindex() -> dict[str, Any]:
        with lock:
            stats = index_root(root, conn)
        return {
            "indexed": stats.indexed,
            "skipped": stats.skipped,
            "failed": stats.failed,
            "removed": stats.removed,
            "chunks": stats.chunks,
        }

    return app
