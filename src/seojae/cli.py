"""CLI. 1단계 범위: status / reindex / search."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import __version__, organize
from .index import index_root, last_indexed_at, open_db
from .paths import INBOX_DIRNAME, resolve_root
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
def init(
    root: str = typer.Argument(..., help="만들 서재 루트 폴더"),
) -> None:
    """서재 골격을 만든다. 인박스와 예시 책장, README 틀."""
    root_path = Path(root).expanduser().resolve()
    if root_path.exists() and not root_path.is_dir():
        console.print(f"[red]폴더가 아니다: {root_path}[/red]")
        raise typer.Exit(code=1)

    created: list[str] = []
    skipped: list[str] = []

    def make_dir(path: Path) -> None:
        if path.exists():
            skipped.append(f"{path.relative_to(root_path.parent)}\\")
        else:
            path.mkdir(parents=True)
            created.append(f"{path.relative_to(root_path.parent)}\\")

    def make_file(path: Path, body: str) -> None:
        rel_name = str(path.relative_to(root_path.parent))
        if path.exists():
            skipped.append(rel_name)  # 있는 파일은 절대 덮어쓰지 않는다
            return
        path.write_text(body, encoding="utf-8")
        created.append(rel_name)

    make_dir(root_path)
    make_dir(root_path / INBOX_DIRNAME)
    make_file(
        root_path / INBOX_DIRNAME / "여기에-던져두세요.txt",
        "분류하기 전 파일을 이 폴더에 넣어두면 된다.\n"
        "검색 결과에는 기본으로 나오지 않는다.\n"
        "나중에 Claude에게 '인박스 정리해줘'라고 하면 알맞은 책장으로 옮겨준다.\n",
    )

    example = root_path / "예시책장"
    make_dir(example)
    make_file(
        example / "README.md",
        "---\n"
        "name: 예시책장\n"
        "description: 이 책장이 어떤 질문에 쓰이는지 한두 문장으로 적는다. "
        "이 문장이 Claude가 책장을 고르는 근거가 된다.\n"
        "tags: [예시]\n"
        "---\n\n"
        "# 예시책장\n\n"
        "폴더 하나가 책장 하나다. 이 폴더에 md, txt, pdf, docx 파일을 넣으면 색인된다.\n"
        "하위 폴더를 만들어도 같은 책장으로 함께 색인된다.\n",
    )

    headline = "서재를 만들었다" if created else "이미 서재가 있다. 그대로 둔다"
    console.print(f"[bold]{headline}:[/bold] {root_path}\n")
    for name in created:
        console.print(f"  [green]+[/green] {name}", highlight=False)
    for name in skipped:
        console.print(f"  [dim]· {name} (이미 있어 건드리지 않음)[/dim]", highlight=False)

    console.print("\n[bold]다음 순서[/bold]")
    console.print("  1. 폴더를 만들고 문서를 넣는다 (폴더 하나 = 책장 하나)")
    console.print("  2. 각 폴더에 README.md를 두고 description을 적는다")
    console.print(f"  3. [cyan]seojae reindex {root}[/cyan]")
    console.print(f"  4. [cyan]seojae status {root}[/cyan] 로 확인")
    console.print(
        "\n[dim]serve로 띄워두면 파일을 넣거나 고칠 때 알아서 다시 색인된다.[/dim]"
    )


@app.command()
def serve(
    root: str = RootArg,
    skip_index: bool = typer.Option(False, "--skip-index", help="색인을 건너뛰고 바로 띄운다"),
    no_watch: bool = typer.Option(False, "--no-watch", help="파일 감시 없이 띄운다"),
) -> None:
    """색인 후 MCP(stdio) 서버를 띄운다. Claude Code가 이 명령을 실행한다."""
    # stdout은 MCP 프로토콜 채널이다. 사람에게 보여줄 것은 전부 stderr로 보낸다.
    # 윈도우 콘솔은 기본이 cp949라 한글 로그가 깨진다. stderr만 UTF-8로 돌린다
    # (stdout은 프로토콜 채널이라 손대지 않는다).
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    err = Console(stderr=True)

    try:
        root_path = resolve_root(root)
    except (FileNotFoundError, NotADirectoryError) as e:
        err.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    if not skip_index:
        conn = open_db(root_path)
        err.print(f"[dim]서재 색인 중: {root_path}[/dim]")
        stats = index_root(root_path, conn)
        err.print(
            f"[dim]색인 완료 — 새로 읽음 {stats.indexed} / 변경 없음 {stats.skipped} / "
            f"실패 {stats.failed} / 청크 {stats.chunks}[/dim]"
        )
        conn.close()

    from .server import serve as run_server

    def on_change(kind: str, detail: str) -> None:
        err.print(f"[dim]{kind}: {detail}[/dim]", highlight=False)

    watching = "" if no_watch else " + 파일 감시"
    err.print(f"[dim]MCP 서버 시작 (stdio){watching} — 루트: {root_path}[/dim]")
    run_server(root_path, watch=not no_watch, on_change=on_change)


@app.command()
def inbox(
    root: str = RootArg,
    limit: int = typer.Option(20, "--limit", "-n", help="보여줄 개수"),
) -> None:
    """미분류 파일 목록. Claude가 보는 것과 같은 내용이다."""
    root_path, conn = _open(root)
    items = organize.list_inbox(conn, root_path, limit=limit)

    if not items:
        console.print("[green]미분류 파일이 없다.[/green]")
        conn.close()
        return

    for item in items:
        flag = "" if item.status == "ok" else " [red](읽기 실패)[/red]"
        console.print(f"\n[bold cyan]#{item.id} {item.filename}[/bold cyan]{flag}")
        console.print(f"[dim]{item.path} · {item.size:,}바이트 · {item.added_at}[/dim]")
        if item.excerpt:
            console.print(item.excerpt[:300], highlight=False)
        elif item.error:
            console.print(f"[red]{item.error[:200]}[/red]", highlight=False)

    console.print(f"\n[dim]{len(items)}건. Claude에게 '인박스 정리해줘'라고 하면 분류해준다.[/dim]")
    conn.close()


@app.command()
def undo(root: str = RootArg) -> None:
    """마지막 파일 이동이나 README 수정을 되돌린다."""
    root_path, conn = _open(root)
    try:
        message = organize.undo_last(conn, root_path)
    except organize.OrganizeError as e:
        console.print(f"[yellow]{e}[/yellow]")
        conn.close()
        raise typer.Exit(code=1)

    console.print(f"[green]{message}[/green]")
    conn.close()


@app.command()
def moves(
    root: str = RootArg,
    limit: int = typer.Option(20, "--limit", "-n", help="보여줄 개수"),
) -> None:
    """파일을 옮기거나 README를 고친 기록."""
    root_path, conn = _open(root)
    records = organize.list_moves(conn, limit=limit)

    if not records:
        console.print("[dim]기록이 없다.[/dim]")
        conn.close()
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("시각")
    table.add_column("종류")
    table.add_column("내용", overflow="fold", max_width=70)
    table.add_column("되돌림")

    for r in records:
        detail = f"{r['src']} → {r['dst']}" if r["kind"] == "move" else r["dst"]
        if r["note"]:
            detail += f"\n[dim]{r['note']}[/dim]"
        table.add_row(
            r["ts"][:19].replace("T", " "),
            r["kind"],
            detail,
            "O" if r["undone"] else "",
        )
    console.print(table)
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
