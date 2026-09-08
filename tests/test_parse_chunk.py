"""파서와 청킹. 출처(location)가 정확해야 검색 결과를 믿을 수 있다."""

from __future__ import annotations

from pathlib import Path

from seojae.chunking import build_chunks
from seojae.collections import load_collection
from seojae.parsers import Block, parse_file
from seojae.parsers.markdown import strip_frontmatter


def test_strip_frontmatter() -> None:
    front, body = strip_frontmatter("---\nname: 규정\n---\n# 제목\n본문\n")
    assert "name: 규정" in front
    assert body.startswith("# 제목")


def test_strip_frontmatter_absent() -> None:
    front, body = strip_frontmatter("# 제목만 있다\n")
    assert front == ""
    assert body == "# 제목만 있다\n"


def test_markdown_heading_path(shelf: Path) -> None:
    parsed = parse_file(shelf / "업무규정" / "휴가규정.md")
    locations = [b.location for b in parsed.blocks]
    assert "휴가 규정 > 연차 휴가" in locations
    assert "휴가 규정 > 병가" in locations
    assert parsed.title == "휴가 규정"


def test_markdown_frontmatter_not_indexed(shelf: Path) -> None:
    parsed = parse_file(shelf / "업무규정" / "README.md")
    joined = "\n".join(b.text for b in parsed.blocks)
    assert "description:" not in joined  # 프론트매터는 본문에서 빠진다


def test_chunks_keep_group_boundary() -> None:
    blocks = [
        Block(text="가" * 50, location="A", group="A"),
        Block(text="나" * 50, location="A", group="A"),
        Block(text="다" * 50, location="B", group="B"),
    ]
    chunks = build_chunks(blocks, max_chars=1000)
    assert [c.location for c in chunks] == ["A", "B"]  # 다른 group끼리는 안 합친다


def test_chunks_split_oversize_block() -> None:
    blocks = [Block(text="문장이다. " * 400, location="A", group="A")]
    chunks = build_chunks(blocks, max_chars=500)
    assert len(chunks) > 1
    assert all(len(c.text) <= 500 for c in chunks)
    assert all(c.location == "A" for c in chunks)


def test_collection_reads_frontmatter(shelf: Path) -> None:
    info = load_collection(shelf / "업무규정", shelf)
    assert info.name == "업무규정"
    assert "휴가" in info.description
    assert info.tags == ["규정", "총무"]
    assert info.has_readme is True


def test_collection_without_readme_gets_auto_description(shelf: Path) -> None:
    other = shelf / "잡동사니"
    other.mkdir()
    (other / "회의록.md").write_text("# 2026 상반기 회의\n내용\n", encoding="utf-8")

    info = load_collection(other, shelf)
    assert info.has_readme is False
    assert "회의록" in info.description  # 파일명으로라도 설명을 만든다
