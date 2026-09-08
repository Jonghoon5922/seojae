"""마크다운 파서. 헤딩 단위로 쪼개고 헤딩 경로를 출처로 남긴다."""

from __future__ import annotations

import re
from pathlib import Path

from .base import Block, ParsedDoc, ParseError
from .plain import read_text

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")
_FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)


def strip_frontmatter(text: str) -> tuple[str, str]:
    """(프론트매터 원문, 본문). 프론트매터가 없으면 ("", 원문)."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return "", text
    return m.group(1), text[m.end():]


def parse_markdown(path: Path) -> ParsedDoc:
    try:
        raw = read_text(path)
    except OSError as e:
        raise ParseError(str(e)) from e

    _, body = strip_frontmatter(raw)

    title = path.stem
    heading_path: list[str] = []
    blocks: list[Block] = []
    buffer: list[str] = []
    in_code = False

    def flush() -> None:
        text = "\n".join(buffer).strip()
        buffer.clear()
        if not text:
            return
        location = " > ".join(heading_path) if heading_path else "(머리말)"
        blocks.append(Block(text=text, location=location, group=location))

    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            buffer.append(line)
            continue
        if in_code:
            buffer.append(line)
            continue

        m = _HEADING_RE.match(stripped)
        if m:
            flush()
            level = len(m.group(1))
            heading = m.group(2).strip()
            if level == 1 and title == path.stem:
                title = heading
            heading_path[:] = heading_path[: level - 1]
            while len(heading_path) < level - 1:
                heading_path.append("")
            heading_path.append(heading)
            # 헤딩 자체도 본문에 포함시켜 검색에 잡히게 한다
            buffer.append(f"{'#' * level} {heading}")
            continue

        buffer.append(line)

    flush()
    return ParsedDoc(title=title, blocks=blocks)
