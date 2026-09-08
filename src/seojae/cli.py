"""CLI. 1단계 범위: status / reindex / search."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .index import index_root, last_indexed_at, open_db
from .paths import resolve_root
from .search import failed_documents, get_document, list_collections, list_documents, search

app = typer.Typer(
    name="seojae",
    help="서재 — 폴더에 문서를 꽂아두면 Claude가 꺼내 읽는 로컬 RAG MCP 서버.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()

RootArg = typer.Argument(..., help="서재 루트 폴더 (이 폴더 바깥은 절대 읽지 않는다)")


def _open(root_path: str):
    try:
        root = resolve_root(root_path)
    except (FileNotFoundError, NotADirectoryError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)
    return root, open_db(root)


@app.command()
def version() -> None:
    """버전 표시."""
    console.print(f"서재 (seojae) {__version__}")


@app.command()
def reindex(
    root: str = RootArg,
    full: bool = typer.Option(False, "--full", help="해시가 같아도 전부 다시 읽는다"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="진행 표시 없이"),
) -> None:
    """루트 전체를 색인한다. 변경된 파일만 다시 읽는다."""
    root_path, conn = _open(root)
    console.print(f"[bold]서재:[/bold] {root_path}")

    started = time.perf_counter()
    counter = {"n": 0}

    def on_file(relpath: str) -> None:
        counter["n"] += 1
        if not quiet and counter["n"] % 25 == 0:
            console.print(f"  … {counter['n']}개 처리", highlight=False)

    stats = index_root(root_path, conn, force=full, on_file=on_file)
    elapsed = time.perf_counter() - started

    console.print(
        f"[green]색인 완료[/green] {elapsed:.1f}초 — "
        f"새로 읽음 {stats.indexed} / 변경 없음 {stats.skipped} / "
        f"실패 {stats.failed} / 삭제 {stats.removed} / 청크 {stats.chunks}"
    )
    if stats.errors:
        console.print("[yellow]실패한 파일:[/yellow]")
        for path, message in stats.errors[:20]:
            console.print(f"  - {path}: {message}", highlight=False)
        if len(stats.errors) > 20:
            console.print(f"  … 외 {len(stats.errors) - 20}건")
    conn.close()


@app.command()
def status(root: str = RootArg) -> None:
    """컬렉션별 문서 수, 마지막 색인 시각, 실패 파일."""
    root_path, conn = _open(root)

    console.print(f"[bold]서재:[/bold] {root_path}")
    indexed_at = last_indexed_at(conn)
    console.print(f"[dim]마지막 색인: {indexed_at or '아직 없음'}[/dim]\n")

    collections = list_collections(conn)
    if not collections:
        console.print("[yellow]컬렉션이 없다. 루트 아래 폴더를 만들고 문서를 넣은 뒤 reindex 하라.[/yellow]")
        conn.close()
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("컬렉션")
    table.add_column("문서", justify="right")
    table.add_column("청크", justify="right")
    table.add_column("README")
    table.add_column("설명", overflow="fold", max_width=60)

    for c in collections:
        label = f"[yellow]{c.dirname}[/yellow]" if c.is_inbox else c.dirname
        table.add_row(
            label,
            str(c.doc_count),
            str(c.chunk_count),
            "O" if c.has_readme else "[dim]자동[/dim]",
            c.description[:200],
        )
    console.print(table)

    failed = failed_documents(conn)
    if failed:
        console.print(f"\n[red]읽지 못한 파일 {len(failed)}건[/red]")
        for doc in failed[:15]:
            console.print(f"  - {doc.path}: {doc.error[:120]}", highlight=False)
        if len(failed) > 15:
            console.print(f"  … 외 {len(failed) - 15}건")
    conn.close()


@app.command()
def documents(
    root: str = RootArg,
    collection: Optional[str] = typer.Option(None, "--collection", "-c", help="컬렉션 이름"),
) -> None:
    """색인된 문서 목록."""
    root_path, conn = _open(root)
    docs = list_documents(conn, collection=collection)
    if not docs:
        console.print("[yellow]문서가 없다.[/yellow]")
        conn.close()
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("id", justify="right")
    table.add_column("컬렉션")
    table.add_column("제목", overflow="fold", max_width=40)
    table.add_column("경로", overflow="fold", max_width=50)
    table.add_column("청크", justify="right")
    for doc in docs:
        table.add_row(str(doc.id), doc.collection, doc.title, doc.path, str(doc.chunk_count))
    console.print(table)
    console.print(f"[dim]{len(docs)}건[/dim]")
    conn.close()


@app.command(name="search")
def search_cmd(
    root: str = RootArg,
    query: str = typer.Argument(..., help="검색어"),
    collection: Optional[str] = typer.Option(None, "--collection", "-c", help="컬렉션으로 한정"),
    top_k: int = typer.Option(5, "--top-k", "-k", help="결과 개수"),
    include_inbox: bool = typer.Option(False, "--include-inbox", help="미분류 파일도 포함"),
    full: bool = typer.Option(False, "--full", help="청크 전문 표시"),
) -> None:
    """검색. Claude가 쓰는 것과 같은 함수다."""
    root_path, conn = _open(root)
    hits = search(conn, query, collection=collection, top_k=top_k, include_inbox=include_inbox)

    if not hits:
        console.print("[yellow]결과 없음[/yellow]")
        conn.close()
        return

    for i, hit in enumerate(hits, start=1):
        console.print(
            f"\n[bold cyan]{i}. {hit.collection}[/bold cyan] "
            f"[dim]{hit.source} · {hit.location} · score {hit.score}[/dim]"
        )
        text = hit.text if full else (hit.text[:400] + ("…" if len(hit.text) > 400 else ""))
        console.print(text, highlight=False)
        if hit.also_in:
            console.print(
                f"[dim]  ↳ 같은 내용이 {len(hit.also_in)}개 문서에 더 있음: "
                f"{', '.join(hit.also_in[:3])}[/dim]",
                highlight=False,
            )
    conn.close()


@app.command()
def show(
    root: str = RootArg,
    doc_id: int = typer.Argument(..., help="문서 id (documents 명령으로 확인)"),
    section: Optional[str] = typer.Option(None, "--section", "-s", help="헤딩·페이지로 한정"),
) -> None:
    """문서 원문 보기."""
    root_path, conn = _open(root)
    doc = get_document(conn, doc_id, section=section)
    if doc is None:
        console.print(f"[red]문서 {doc_id} 없음[/red]")
        conn.close()
        raise typer.Exit(code=1)

    console.print(f"[bold]{doc['title']}[/bold] [dim]{doc['path']}[/dim]\n")
    for part in doc["sections"]:
        console.print(f"[cyan]— {part['location']}[/cyan]")
        console.print(part["text"], highlight=False)
        console.print()
    conn.close()


if __name__ == "__main__":
    app()
