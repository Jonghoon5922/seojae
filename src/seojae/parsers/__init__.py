"""파일 형식별 파서. 모두 Block 목록을 돌려준다."""

from __future__ import annotations

from pathlib import Path

from .base import Block, ParsedDoc, ParseError
from .docx_file import parse_docx
from .markdown import parse_markdown
from .pdf_file import parse_pdf
from .plain import parse_txt

__all__ = ["Block", "ParsedDoc", "ParseError", "parse_file"]

_PARSERS = {
    ".md": parse_markdown,
    ".markdown": parse_markdown,
    ".txt": parse_txt,
    ".pdf": parse_pdf,
    ".docx": parse_docx,
}


def parse_file(path: Path) -> ParsedDoc:
    """확장자에 맞는 파서로 파일을 읽는다. 지원하지 않으면 ParseError."""
    parser = _PARSERS.get(path.suffix.lower())
    if parser is None:
        raise ParseError(f"지원하지 않는 형식: {path.suffix}")
    return parser(path)
