"""txt 파서."""

from __future__ import annotations

from pathlib import Path

from .base import Block, ParsedDoc, ParseError


def read_text(path: Path) -> str:
    """인코딩을 모르는 로컬 파일을 최대한 살려 읽는다."""
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def parse_txt(path: Path) -> ParsedDoc:
    try:
        text = read_text(path)
    except OSError as e:
        raise ParseError(str(e)) from e

    blocks = []
    for i, chunk in enumerate(text.split("\n\n"), start=1):
        if chunk.strip():
            blocks.append(Block(text=chunk.strip(), location=f"문단 {i}", group=f"p{i}"))
    return ParsedDoc(title=path.stem, blocks=blocks)
