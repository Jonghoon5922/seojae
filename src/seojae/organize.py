"""정리 축 — 미분류 파일을 책장에 꽂고, 책장 설명을 쓴다.

여기서 처음으로 **파일을 실제로 건드린다.** 그래서 규칙이 셋이다.

1. 루트 밖으로는 한 발짝도 나가지 않는다
2. 무엇도 덮어쓰지 않는다 (이름이 겹치면 접미사를 붙인다)
3. 한 일은 전부 기록해서 되돌릴 수 있게 한다

판단은 하지 않는다. 어느 책장에 꽂을지, 설명을 뭐라고 쓸지는 사용자의 Claude가 정한다.
이 모듈은 재료를 주고 손을 빌려줄 뿐이다.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .collections import find_readme
from .index import ensure_collection, forget_one, index_one, now_iso
from .parsers.markdown import strip_frontmatter
from .parsers.plain import read_text
from .paths import (
    DATA_DIRNAME,
    INBOX_DIRNAME,
    SUPPORTED_EXTS,
    OutsideRootError,
    data_dir,
    is_inside,
    rel,
)

EXCERPT_CHARS = 400
DESCRIBE_DOC_LIMIT = 40
DESCRIBE_EXCERPT_CHARS = 200

# 파일명에 쓸 수 없는 글자 (윈도우 기준으로 잡는다)
_BAD_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class OrganizeError(Exception):
    """정리 작업을 할 수 없을 때. 사용자(=Claude)에게 이유를 그대로 돌려준다."""


@dataclass
class InboxItem:
    id: int
    filename: str
    path: str
    size: int
    added_at: str
    excerpt: str
    status: str = "ok"
    error: str = ""


@dataclass
class MoveResult:
    document_id: int
    src: str
    dst: str
    collection: str
    renamed: bool = False
    created_collection: bool = False
    note: str = ""


@dataclass
class CollectionMaterial:
    collection: str
    document_count: int
    current_description: str = ""
    has_readme: bool = False
    documents: list[dict[str, Any]] = field(default_factory=list)
    frequent_terms: list[str] = field(default_factory=list)


# ── 인박스 ────────────────────────────────────────────────────────────────


def _excerpt(conn, doc_id: int, budget: int) -> str:
    """문서 앞부분을 budget 글자만큼 모은다.

    첫 청크만 쓰면 안 된다. 마크다운은 H1이 혼자 한 청크가 되는 일이 흔해서
    "# 제목"만 돌아오고, 그걸로는 어느 책장에 속하는지 판단할 수 없다.
    """
    parts: list[str] = []
    used = 0
    for row in conn.execute(
        "SELECT text FROM chunks WHERE doc_id = ? ORDER BY ordinal LIMIT 10", (doc_id,)
    ).fetchall():
        text = row["text"].strip()
        if not text:
            continue
        remaining = budget - used
        if remaining <= 0:
            return "\n".join(parts) + "…"
        if len(text) > remaining:
            parts.append(text[:remaining] + "…")
            return "\n".join(parts)
        parts.append(text)
        used += len(text) + 1
    return "\n".join(parts)


def list_inbox(conn, root: Path, limit: int = 20) -> list[InboxItem]:
    """미분류 파일 목록. 분류를 판단할 수 있게 본문 앞부분을 함께 준다."""
    rows = conn.execute(
        """
        SELECT id, path, size, indexed_at, status, error
        FROM documents
        WHERE is_inbox = 1
        ORDER BY indexed_at DESC, id DESC
        LIMIT ?
        """,
        (max(1, limit),),
    ).fetchall()

    items: list[InboxItem] = []
    for row in rows:
        excerpt = _excerpt(conn, row["id"], EXCERPT_CHARS)

        items.append(
            InboxItem(
                id=row["id"],
                filename=Path(row["path"]).name,
                path=row["path"],
                size=row["size"],
                added_at=row["indexed_at"],
                excerpt=excerpt,
                status=row["status"],
                error=row["error"],
            )
        )
    return items


# ── 파일 이동 ─────────────────────────────────────────────────────────────


def _safe_collection_name(name: str) -> str:
    cleaned = (name or "").strip().strip("/\\")
    if not cleaned:
        raise OrganizeError("책장 이름이 비었다.")
    if cleaned in {INBOX_DIRNAME, DATA_DIRNAME} or cleaned.startswith("."):
        raise OrganizeError(f"'{cleaned}'는 책장으로 쓸 수 없는 이름이다.")
    if "/" in cleaned or "\\" in cleaned or cleaned in {".", ".."}:
        raise OrganizeError("책장은 루트 바로 아래 폴더 하나여야 한다. 경로를 넣지 마라.")
    if _BAD_NAME_CHARS.search(cleaned):
        raise OrganizeError(f"책장 이름에 쓸 수 없는 글자가 있다: {cleaned}")
    return cleaned


def _safe_filename(new_name: str, original: Path) -> str:
    cleaned = (new_name or "").strip()
    if "/" in cleaned or "\\" in cleaned or cleaned in {".", ".."}:
        raise OrganizeError("파일 이름에 경로를 넣지 마라. 이름만 준다.")
    if _BAD_NAME_CHARS.search(cleaned):
        raise OrganizeError(f"파일 이름에 쓸 수 없는 글자가 있다: {cleaned}")

    candidate = Path(cleaned)
    if candidate.suffix.lower() != original.suffix.lower():
        # 확장자를 바꾸면 파서가 달라진다. 원본 확장자를 지킨다.
        candidate = candidate.with_suffix(original.suffix)
    return candidate.name


def _free_path(directory: Path, filename: str) -> tuple[Path, bool]:
    """겹치지 않는 경로. 이미 있으면 접미사를 붙인다 (덮어쓰지 않는다)."""
    target = directory / filename
    if not target.exists():
        return target, False

    stem, suffix = target.stem, target.suffix
    for n in range(2, 1000):
        candidate = directory / f"{stem} ({n}){suffix}"
        if not candidate.exists():
            return candidate, True
    raise OrganizeError(f"'{filename}' 이름으로 둘 자리가 없다.")


def file_document(
    conn,
    root: Path,
    document_id: int,
    collection: str,
    new_name: str | None = None,
    create_collection: bool = False,
) -> MoveResult:
    """문서를 책장으로 옮기고 색인을 갱신한다. 되돌릴 수 있게 기록한다."""
    row = conn.execute(
        "SELECT id, path, collection FROM documents WHERE id = ?", (document_id,)
    ).fetchone()
    if row is None:
        raise OrganizeError(f"문서 {document_id}를 찾을 수 없다. list_inbox로 id를 확인하라.")

    src = root / row["path"]
    if not src.is_file():
        raise OrganizeError(f"원본 파일이 없다: {row['path']}")
    if not is_inside(root, src):
        raise OutsideRootError(f"루트 밖 파일은 옮기지 않는다: {row['path']}")

    target_name = _safe_collection_name(collection)
    directory = root / target_name

    created_collection = False
    if not directory.exists():
        if not create_collection:
            existing = [d.name for d in root.iterdir() if d.is_dir() and not d.name.startswith((".", "_"))]
            raise OrganizeError(
                f"'{target_name}' 책장이 없다. 있는 책장: {', '.join(existing) or '(없음)'}. "
                "새로 만들려면 create_collection=true로 다시 호출하라."
            )
        directory.mkdir(parents=True)
        created_collection = True
    elif not directory.is_dir():
        raise OrganizeError(f"'{target_name}'는 폴더가 아니다.")

    filename = _safe_filename(new_name, src) if new_name else src.name
    dst, renamed = _free_path(directory, filename)

    if dst.resolve() == src.resolve():
        raise OrganizeError("이미 그 자리에 있다.")
    if not is_inside(root, dst):
        raise OutsideRootError("루트 밖으로는 옮기지 않는다.")

    try:
        shutil.move(str(src), str(dst))
    except OSError as e:
        if created_collection:
            _remove_if_empty(directory)
        raise OrganizeError(f"옮기지 못했다: {e}") from e

    forget_one(root, conn, src, commit=False)
    ensure_collection(root, conn, target_name)
    index_one(root, conn, dst, commit=False)

    note = ""
    if renamed:
        note = f"같은 이름이 있어 '{dst.name}'로 두었다."
    if created_collection:
        note = (note + " " if note else "") + f"'{target_name}' 책장을 새로 만들었다."

    conn.execute(
        """
        INSERT INTO moves(ts, kind, src, dst, created_dir, note)
        VALUES(?, 'move', ?, ?, ?, ?)
        """,
        (now_iso(), row["path"], rel(root, dst), target_name if created_collection else "", note),
    )
    conn.commit()

    return MoveResult(
        document_id=document_id,
        src=row["path"],
        dst=rel(root, dst),
        collection=target_name,
        renamed=renamed,
        created_collection=created_collection,
        note=note.strip(),
    )


def _remove_if_empty(directory: Path) -> bool:
    try:
        next(directory.iterdir())
    except StopIteration:
        directory.rmdir()
        return True
    except OSError:
        return False
    return False


# ── 되돌리기 ──────────────────────────────────────────────────────────────


def undo_last(conn, root: Path) -> str:
    """마지막 작업을 되돌린다. 되돌린 내용을 문장으로 돌려준다."""
    row = conn.execute(
        "SELECT * FROM moves WHERE undone = 0 ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        raise OrganizeError("되돌릴 작업이 없다.")

    if row["kind"] == "move":
        message = _undo_move(conn, root, row)
    elif row["kind"] == "readme":
        message = _undo_readme(conn, root, row)
    elif row["kind"] == "collection":
        message = _undo_collection(conn, root, row)
    else:
        raise OrganizeError(f"모르는 작업 종류: {row['kind']}")

    conn.execute("UPDATE moves SET undone = 1 WHERE id = ?", (row["id"],))
    conn.commit()
    return message


def _undo_move(conn, root: Path, row) -> str:
    dst = root / row["dst"]
    src = root / row["src"]

    if not dst.is_file():
        raise OrganizeError(f"되돌릴 파일이 그 자리에 없다: {row['dst']}")

    src.parent.mkdir(parents=True, exist_ok=True)
    final, renamed = _free_path(src.parent, src.name)

    try:
        shutil.move(str(dst), str(final))
    except OSError as e:
        raise OrganizeError(f"되돌리지 못했다: {e}") from e

    forget_one(root, conn, dst, commit=False)
    index_one(root, conn, final, commit=False)

    if row["created_dir"]:
        _remove_if_empty(root / row["created_dir"])

    where = f"{row['dst']} → {rel(root, final)}"
    return f"되돌렸다: {where}" + (" (이름이 겹쳐 접미사를 붙였다)" if renamed else "")


def _undo_readme(conn, root: Path, row) -> str:
    target = root / row["dst"]

    if row["backup"]:
        backup = root / row["backup"]
        if not backup.is_file():
            raise OrganizeError(f"백업이 없다: {row['backup']}")
        shutil.copyfile(backup, target)
        index_one(root, conn, target, commit=False)
        return f"되돌렸다: {row['dst']} (이전 내용 복원)"

    # 원래 README가 없었다 — 우리가 만든 것이므로 지운다
    if target.is_file():
        forget_one(root, conn, target, commit=False)
        target.unlink()
    collection = Path(row["dst"]).parts[0]
    ensure_collection(root, conn, collection)
    return f"되돌렸다: {row['dst']} 삭제 (원래 없던 파일)"


def _undo_collection(conn, root: Path, row) -> str:
    """책장 생성/이름변경 되돌리기."""
    # 생성이었다면 (src 가 비었다) 빈 폴더만 치운다
    if not row["src"]:
        directory = root / row["dst"]
        if not directory.is_dir():
            return f"되돌릴 것이 없다: {row['dst']} 폴더가 이미 없다"

        leftovers = [
            p for p in directory.rglob("*")
            if p.is_file() and not p.name.lower().startswith("readme.")
        ]
        if leftovers:
            raise OrganizeError(
                f"'{row['dst']}'에 파일이 {len(leftovers)}건 있다. 되돌리면 사라지므로 멈춘다."
            )
        for doc in conn.execute(
            "SELECT id FROM documents WHERE collection = ?", (row["dst"],)
        ).fetchall():
            _delete_document_row(conn, doc["id"])
        conn.execute("DELETE FROM collections WHERE dirname = ?", (row["dst"],))
        shutil.rmtree(directory)
        return f"되돌렸다: '{row['dst']}' 책장 삭제"

    # 이름 변경이었다면 되돌린다
    current = root / row["dst"]
    previous = root / row["src"]
    if not current.is_dir():
        raise OrganizeError(f"'{row['dst']}' 책장이 없다.")
    if previous.exists():
        raise OrganizeError(f"'{row['src']}' 이름이 이미 쓰이고 있어 되돌릴 수 없다.")

    shutil.move(str(current), str(previous))
    _repoint_documents(conn, row["dst"], row["src"])
    conn.execute("DELETE FROM collections WHERE dirname = ?", (row["dst"],))
    ensure_collection(root, conn, row["src"])
    return f"되돌렸다: 책장 이름 {row['dst']} → {row['src']}"


def list_moves(conn, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM moves ORDER BY id DESC LIMIT ?", (max(1, limit),)
    ).fetchall()
    return [
        {
            "id": r["id"],
            "ts": r["ts"],
            "kind": r["kind"],
            "src": r["src"],
            "dst": r["dst"],
            "note": r["note"],
            "undone": bool(r["undone"]),
        }
        for r in rows
    ]


# ── 책장 설명 ─────────────────────────────────────────────────────────────


def describe_collection(conn, root: Path, collection: str) -> CollectionMaterial:
    """README를 쓰기 위한 재료를 모은다. 설명 문장은 Claude가 쓴다."""
    name = _safe_collection_name(collection)
    if not (root / name).is_dir():
        raise OrganizeError(f"'{name}' 책장이 없다.")

    info = conn.execute(
        "SELECT description, has_readme FROM collections WHERE dirname = ?", (name,)
    ).fetchone()

    rows = conn.execute(
        """
        SELECT id, path, title, is_readme FROM documents
        WHERE collection = ? AND status = 'ok'
        ORDER BY is_readme DESC, path
        LIMIT ?
        """,
        (name, DESCRIBE_DOC_LIMIT),
    ).fetchall()

    documents = []
    for row in rows:
        headings = [
            r["location"]
            for r in conn.execute(
                "SELECT DISTINCT location FROM chunks WHERE doc_id = ? ORDER BY ordinal LIMIT 8",
                (row["id"],),
            ).fetchall()
            if r["location"]
        ]
        excerpt = _excerpt(conn, row["id"], DESCRIBE_EXCERPT_CHARS).replace("\n", " ")

        documents.append(
            {
                "id": row["id"],
                "title": row["title"],
                "path": row["path"],
                "headings": headings,
                "excerpt": excerpt,
            }
        )

    total = conn.execute(
        "SELECT COUNT(*) AS n FROM documents WHERE collection = ? AND status = 'ok'", (name,)
    ).fetchone()["n"]

    from .search import collection_terms

    return CollectionMaterial(
        collection=name,
        document_count=total,
        current_description=info["description"] if info else "",
        has_readme=bool(info["has_readme"]) if info else False,
        documents=documents,
        frequent_terms=collection_terms(conn, name, limit=30),
    )


def write_collection_readme(
    conn,
    root: Path,
    collection: str,
    name: str,
    description: str,
    tags: list[str] | None = None,
) -> str:
    """README 프론트매터를 갱신한다. 본문은 보존하고 원본은 백업한다."""
    dirname = _safe_collection_name(collection)
    directory = root / dirname
    if not directory.is_dir():
        raise OrganizeError(f"'{dirname}' 책장이 없다.")

    description = (description or "").strip()
    if not description:
        raise OrganizeError("description은 비울 수 없다. 이 책장이 어떤 질문에 쓰이는지 적어라.")

    existing = find_readme(directory)
    body = ""
    backup_rel = ""

    if existing is not None:
        raw = read_text(existing)
        _, body = strip_frontmatter(raw)
        body = body.strip()

        backups = data_dir(root) / "backups"
        backups.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = backups / f"{dirname}-README-{stamp}.md"
        shutil.copyfile(existing, backup)
        backup_rel = rel(root, backup)
        target = existing
    else:
        target = directory / "README.md"

    front: dict[str, Any] = {"name": (name or dirname).strip(), "description": description}
    if tags:
        front["tags"] = [str(t).strip() for t in tags if str(t).strip()]
    front["updated"] = datetime.now().date()  # 날짜형으로 넣어야 따옴표가 안 붙는다

    rendered = yaml.safe_dump(front, allow_unicode=True, sort_keys=False, width=1000).strip()
    if not body:
        body = f"# {front['name']}"

    target.write_text(f"---\n{rendered}\n---\n\n{body}\n", encoding="utf-8")

    index_one(root, conn, target, commit=False)
    ensure_collection(root, conn, dirname)
    conn.execute(
        "INSERT INTO moves(ts, kind, src, dst, backup, note) VALUES(?, 'readme', '', ?, ?, ?)",
        (now_iso(), rel(root, target), backup_rel, f"'{dirname}' 책장 설명 갱신"),
    )
    conn.commit()

    return rel(root, target)


# ── 밖에서 파일 가져오기 ──────────────────────────────────────────────────

# 한 번에 받을 수 있는 파일 크기 상한
MAX_IMPORT_BYTES = 100 * 1024 * 1024


def import_file(
    conn,
    root: Path,
    collection: str,
    filename: str,
    data: bytes,
) -> MoveResult:
    """밖에서 온 파일을 서재에 넣는다 (드래그앤드롭·업로드).

    브라우저는 보안상 파일의 실제 경로를 주지 않는다. 내용만 받을 수 있어서
    원본을 지울 수 없다. 그래서 이건 '이동'이 아니라 '가져오기'다.

    안전 규칙은 file_document 와 같다. 루트 밖 금지, 덮어쓰기 금지, 기록 남기기.
    """
    if not data:
        raise OrganizeError("빈 파일이다.")
    if len(data) > MAX_IMPORT_BYTES:
        raise OrganizeError(
            f"파일이 너무 크다 ({len(data) / 1024 / 1024:.0f}MB). "
            f"{MAX_IMPORT_BYTES // 1024 // 1024}MB까지 받는다."
        )

    safe_name = _safe_import_name(filename)
    if Path(safe_name).suffix.lower() not in SUPPORTED_EXTS:
        supported = ", ".join(sorted(SUPPORTED_EXTS))
        raise OrganizeError(f"'{safe_name}'는 읽을 수 없는 형식이다. 지원: {supported}")

    if collection == INBOX_DIRNAME:
        directory = root / INBOX_DIRNAME
        directory.mkdir(parents=True, exist_ok=True)
        target_name = INBOX_DIRNAME
        is_inbox = True
    else:
        target_name = _safe_collection_name(collection)
        directory = root / target_name
        if not directory.is_dir():
            raise OrganizeError(f"'{target_name}' 책장이 없다.")
        is_inbox = False

    dst, renamed = _free_path(directory, safe_name)
    if not is_inside(root, dst):
        raise OutsideRootError("루트 밖에는 쓰지 않는다.")

    dst.write_bytes(data)

    ensure_collection(root, conn, target_name)
    index_one(root, conn, dst, commit=False)

    note = "밖에서 가져온 파일"
    if renamed:
        note += f" · 같은 이름이 있어 '{dst.name}'로 두었다"

    conn.execute(
        "INSERT INTO moves(ts, kind, src, dst, note) VALUES(?, 'import', ?, ?, ?)",
        (now_iso(), filename, rel(root, dst), note),
    )
    conn.commit()

    row = conn.execute(
        "SELECT id FROM documents WHERE path = ?", (rel(root, dst),)
    ).fetchone()

    return MoveResult(
        document_id=row["id"] if row else 0,
        src=filename,
        dst=rel(root, dst),
        collection=target_name,
        renamed=renamed,
        note=note,
    )


def _safe_import_name(filename: str) -> str:
    """브라우저가 준 이름은 믿지 않는다. 경로 성분을 전부 떼고 이름만 쓴다."""
    raw = (filename or "").replace("\\", "/").split("/")[-1].strip()
    if not raw or raw in {".", ".."}:
        raise OrganizeError("파일 이름이 없다.")
    cleaned = _BAD_NAME_CHARS.sub("_", raw)
    if not cleaned.strip("._ "):
        raise OrganizeError(f"쓸 수 없는 파일 이름이다: {filename}")
    return cleaned


# ── 책장 만들기·이름 바꾸기 ───────────────────────────────────────────────


def create_collection(conn, root: Path, name: str, description: str = "") -> str:
    """빈 책장(폴더)을 만든다. 설명을 주면 README도 함께 쓴다."""
    dirname = _safe_collection_name(name)
    directory = root / dirname

    if directory.exists():
        raise OrganizeError(f"'{dirname}' 책장이 이미 있다.")

    directory.mkdir(parents=True)
    conn.execute(
        "INSERT INTO moves(ts, kind, src, dst, created_dir, note) VALUES(?, 'collection', '', ?, ?, ?)",
        (now_iso(), dirname, dirname, f"'{dirname}' 책장 생성"),
    )

    if description.strip():
        # write_collection_readme 가 자체 커밋을 한다
        write_collection_readme(conn, root, dirname, dirname, description)
    else:
        ensure_collection(root, conn, dirname)
        conn.commit()

    return dirname


def rename_collection(conn, root: Path, old: str, new: str) -> str:
    """책장 폴더 이름을 바꾼다. 파일 내용은 그대로라 경로만 고쳐 색인을 유지한다."""
    old_name = _safe_collection_name(old)
    new_name = _safe_collection_name(new)

    if old_name == new_name:
        raise OrganizeError("이름이 같다.")

    source = root / old_name
    target = root / new_name
    if not source.is_dir():
        raise OrganizeError(f"'{old_name}' 책장이 없다.")
    if target.exists():
        raise OrganizeError(f"'{new_name}' 이름은 이미 쓰이고 있다.")
    if not is_inside(root, target):
        raise OutsideRootError("루트 밖으로는 옮기지 않는다.")

    try:
        shutil.move(str(source), str(target))
    except OSError as e:
        raise OrganizeError(f"이름을 바꾸지 못했다: {e}") from e

    _repoint_documents(conn, old_name, new_name)
    conn.execute("DELETE FROM collections WHERE dirname = ?", (old_name,))
    ensure_collection(root, conn, new_name)
    conn.execute(
        "INSERT INTO moves(ts, kind, src, dst, note) VALUES(?, 'collection', ?, ?, ?)",
        (now_iso(), old_name, new_name, f"책장 이름 변경: {old_name} → {new_name}"),
    )
    conn.commit()
    return new_name


def _repoint_documents(conn, old_name: str, new_name: str) -> None:
    """폴더만 바뀌었으므로 다시 읽지 않고 경로만 고친다.

    576건짜리 책장을 재색인하면 80초가 걸린다. 내용이 그대로인데 다시 읽을 이유가 없다.
    """
    conn.execute(
        """
        UPDATE documents
           SET path = ? || substr(path, ?),
               collection = ?
         WHERE collection = ?
        """,
        (new_name + "/", len(old_name) + 2, new_name, old_name),
    )


def delete_collection_if_empty(conn, root: Path, name: str) -> bool:
    """빈 책장만 지운다. 파일이 남아 있으면 거부한다."""
    dirname = _safe_collection_name(name)
    directory = root / dirname
    if not directory.is_dir():
        raise OrganizeError(f"'{dirname}' 책장이 없다.")

    remaining = [p for p in directory.rglob("*") if p.is_file() and not p.name.lower().startswith("readme.")]
    if remaining:
        raise OrganizeError(
            f"'{dirname}'에 파일이 {len(remaining)}건 남아 있다. 먼저 다른 책장으로 옮기라."
        )

    for row in conn.execute(
        "SELECT id FROM documents WHERE collection = ?", (dirname,)
    ).fetchall():
        _delete_document_row(conn, row["id"])
    conn.execute("DELETE FROM collections WHERE dirname = ?", (dirname,))
    shutil.rmtree(directory)
    conn.commit()
    return True


def _delete_document_row(conn, doc_id: int) -> None:
    from .index import _delete_document

    _delete_document(conn, doc_id)


def inbox_count(conn) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM documents WHERE is_inbox = 1"
    ).fetchone()
    return row["n"] if row else 0


__all__ = [
    "CollectionMaterial",
    "InboxItem",
    "MoveResult",
    "OrganizeError",
    "create_collection",
    "delete_collection_if_empty",
    "describe_collection",
    "file_document",
    "import_file",
    "inbox_count",
    "list_inbox",
    "list_moves",
    "rename_collection",
    "undo_last",
    "write_collection_readme",
]
