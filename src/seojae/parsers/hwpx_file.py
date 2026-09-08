"""한글 문서(.hwpx) 파서.

hwpx는 OWPML 표준으로, 안이 zip + XML이다. 별도 라이브러리 없이 읽을 수 있다.

구형 `.hwp`(OLE 복합문서 안의 독자 포맷)는 다루지 않는다. 절반쯤 깨져 나오는
지원은 안 하느니만 못하다. 한글에서 "다른 이름으로 저장 → hwpx"로 바꾸면 된다.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from .base import Block, ParsedDoc, ParseError, register

# 본문 XML 위치. 구현체마다 조금씩 달라서 넓게 잡는다.
_SECTION_PATTERN = re.compile(r"Contents/section\d+\.xml$", re.IGNORECASE)

# OWPML 태그는 네임스페이스가 붙어 온다. 로컬 이름만 본다.
_PARA = "p"
_TEXT = "t"
_TABLE = "tbl"
_CELL = "tc"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _para_text(node: ElementTree.Element) -> str:
    """문단 하나의 글자를 모은다. <t> 조각이 여러 개로 쪼개져 있다."""
    return "".join(
        piece.text or "" for piece in node.iter() if _local(piece.tag) == _TEXT
    ).strip()


def _table_text(node: ElementTree.Element) -> str:
    """표를 행 단위로. docx와 같은 이유로 표를 빠뜨리면 안 된다."""
    rows: list[str] = []
    for cell_row in node:
        if _local(cell_row.tag) not in {"tr", "row"}:
            continue
        cells = []
        for cell in cell_row:
            if _local(cell.tag) != _CELL:
                continue
            text = " ".join(
                _para_text(p) for p in cell.iter() if _local(p.tag) == _PARA
            ).strip()
            cells.append(text)
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows)


@register(".hwpx", label="한글 문서 (hwpx)")
def parse_hwpx(path: Path) -> ParsedDoc:
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        raise ParseError(f"hwpx를 열지 못했다: {e}") from e

    sections = sorted(n for n in archive.namelist() if _SECTION_PATTERN.search(n))
    if not sections:
        archive.close()
        raise ParseError("hwpx 안에서 본문(Contents/sectionN.xml)을 찾지 못했다.")

    blocks: list[Block] = []
    title = path.stem

    with archive:
        for index, name in enumerate(sections, start=1):
            try:
                root = ElementTree.fromstring(archive.read(name))
            except (ElementTree.ParseError, KeyError) as e:
                raise ParseError(f"{name} 을 읽지 못했다: {e}") from e

            location = f"구역 {index}" if len(sections) > 1 else "본문"
            buffer: list[str] = []

            # 표 안의 문단은 표 쪽에서 이미 담는다. 여기서 걸러내지 않으면
            # 같은 글이 두 번 들어가 검색 결과가 중복된다.
            in_table = {
                id(p)
                for node in root.iter()
                if _local(node.tag) == _TABLE
                for p in node.iter()
                if _local(p.tag) == _PARA
            }

            for node in root.iter():
                kind = _local(node.tag)
                if kind == _TABLE:
                    rendered = _table_text(node)
                    if rendered:
                        buffer.append(rendered)
                elif kind == _PARA and id(node) not in in_table:
                    text = _para_text(node)
                    if text:
                        buffer.append(text)

            if not buffer:
                continue
            if title == path.stem and buffer[0]:
                title = buffer[0][:80]

            blocks.append(
                Block(text="\n".join(buffer), location=location, group=location)
            )

    if not blocks:
        raise ParseError("hwpx에서 읽어낸 글이 없다.")

    return ParsedDoc(title=title, blocks=blocks, pages=len(sections))
