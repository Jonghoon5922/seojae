"""PDF 파서. 페이지 단위로 자르고 "p.N"을 출처로 남긴다."""

from __future__ import annotations

from pathlib import Path

from .base import Block, ParsedDoc, ParseError, register


@register(".pdf", label="PDF")
def parse_pdf(path: Path) -> ParsedDoc:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
    except Exception as e:
        raise ParseError(f"PDF를 열지 못했다: {e}") from e

    title = path.stem
    try:
        meta_title = (reader.metadata or {}).get("/Title")
        if meta_title and str(meta_title).strip():
            title = str(meta_title).strip()
    except Exception:
        pass

    blocks: list[Block] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        text = text.strip()
        if text:
            blocks.append(Block(text=text, location=f"p.{i}", group=f"p{i}"))

    return ParsedDoc(title=title, blocks=blocks, pages=len(reader.pages))
