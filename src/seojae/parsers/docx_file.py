"""docx 파서.

문단만 읽으면 표 안의 내용이 통째로 빠진다. 설계서류는 대부분이 표라서
본문 요소를 문서 순서대로(문단·표 섞어서) 훑는다.
"""

from __future__ import annotations

from pathlib import Path

from .base import Block, ParsedDoc, ParseError, register

_HEADING_STYLES = ("heading", "제목", "title")


def _is_heading(style_name: str) -> bool:
    name = (style_name or "").strip().lower()
    return any(name.startswith(h) for h in _HEADING_STYLES)


def _render_table(table) -> str:
    """표를 마크다운 비슷한 줄로. 병합 셀 때문에 같은 값이 반복되면 접는다."""
    lines = []
    for row in table.rows:
        cells = []
        prev = None
        for cell in row.cells:
            text = " ".join(cell.text.split())
            if text == prev:  # 가로 병합
                continue
            prev = text
            cells.append(text)
        if any(cells):
            lines.append(" | ".join(cells))
    return "\n".join(lines)


@register(".docx", label="Word 문서")
def parse_docx(path: Path) -> ParsedDoc:
    try:
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        document = Document(str(path))
    except Exception as e:
        raise ParseError(f"docx를 열지 못했다: {e}") from e

    title = path.stem
    heading = ""
    blocks: list[Block] = []
    buffer: list[str] = []
    para_no = 0

    def location() -> str:
        return heading if heading else "(머리말)"

    def flush() -> None:
        text = "\n".join(buffer).strip()
        buffer.clear()
        if text:
            blocks.append(Block(text=text, location=location(), group=location()))

    body = document.element.body
    for child in body.iterchildren():
        tag = child.tag.split("}")[-1]

        if tag == "p":
            para = Paragraph(child, document)
            text = para.text.strip()
            if not text:
                continue
            para_no += 1
            style = para.style.name if para.style is not None else ""
            if _is_heading(style):
                flush()
                heading = text
                if title == path.stem:
                    title = text
                buffer.append(text)
            else:
                buffer.append(text)

        elif tag == "tbl":
            table = Table(child, document)
            rendered = _render_table(table)
            if rendered:
                buffer.append(rendered)

    flush()
    return ParsedDoc(title=title, blocks=blocks)
