"""루트 경계 규칙. 여기가 뚫리면 제품의 약속이 깨진다."""

from __future__ import annotations

from pathlib import Path

import pytest

from seojae.paths import (
    OutsideRootError,
    collection_dirs,
    ensure_inside,
    inbox_files,
    is_inside,
    rel,
    walk_files,
)


def test_collection_dirs_excludes_reserved(shelf: Path) -> None:
    (shelf / ".seojae").mkdir()
    (shelf / ".hidden").mkdir()
    names = [d.name for d in collection_dirs(shelf)]
    assert names == ["업무규정"]  # _inbox, .seojae, .hidden 은 컬렉션이 아니다


def test_ensure_inside_rejects_escape(shelf: Path) -> None:
    with pytest.raises(OutsideRootError):
        ensure_inside(shelf, shelf / ".." / "다른폴더" / "비밀.md")

    with pytest.raises(OutsideRootError):
        ensure_inside(shelf, Path("C:/Windows/System32") if Path("C:/Windows").exists() else Path("/etc"))


def test_ensure_inside_allows_relative(shelf: Path) -> None:
    got = ensure_inside(shelf, "업무규정/휴가규정.md")
    assert got == (shelf / "업무규정" / "휴가규정.md").resolve()


def test_is_inside(shelf: Path) -> None:
    assert is_inside(shelf, shelf / "업무규정")
    assert not is_inside(shelf, shelf.parent)


def test_walk_files_skips_unsupported(shelf: Path) -> None:
    (shelf / "업무규정" / "사진.png").write_bytes(b"fake image bytes")
    names = sorted(p.name for p in walk_files(shelf / "업무규정", shelf))
    assert names == ["README.md", "출장지침.md", "휴가규정.md"]


def test_inbox_files_includes_root_level_files(shelf: Path) -> None:
    (shelf / "루트에던진파일.md").write_text("# 아무거나", encoding="utf-8")
    names = sorted(p.name for p in inbox_files(shelf))
    assert names == ["루트에던진파일.md", "미분류메모.md"]


def test_rel_uses_posix_separator(shelf: Path) -> None:
    assert rel(shelf, shelf / "업무규정" / "휴가규정.md") == "업무규정/휴가규정.md"
