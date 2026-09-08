"""청킹.

파서가 준 Block을 검색 단위(Chunk)로 묶는다.
- 같은 group(헤딩/페이지) 안에서만 합친다 — 출처가 흐려지면 안 되니까
- 너무 큰 블록은 문단·문장 경계로 쪼갠다
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .parsers import Block

MAX_CHARS = 1200
MIN_CHARS = 120

_SENT_RE = re.compile(r"(?<=[.!?。])\s+|\n{2,}")


@dataclass
class Chunk:
    text: str
    location: str
    ordinal: int


def _split_long(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    parts: list[str] = []
    current = ""
    for piece in _SENT_RE.split(text):
        piece = piece.strip()
        if not piece:
            continue
        if len(piece) > max_chars:
            if current:
                parts.append(current)
                current = ""
            for i in range(0, len(piece), max_chars):
                parts.append(piece[i : i + max_chars])
            continue
        if len(current) + len(piece) + 1 > max_chars:
            parts.append(current)
            current = piece
        else:
            current = f"{current}\n{piece}" if current else piece
    if current:
        parts.append(current)
    return parts


def build_chunks(blocks: list[Block], max_chars: int = MAX_CHARS) -> list[Chunk]:
    chunks: list[Chunk] = []
    buffer: list[str] = []
    buffer_group = None
    buffer_location = ""

    def flush() -> None:
        nonlocal buffer, buffer_group, buffer_location
        if not buffer:
            return
        text = "\n\n".join(buffer).strip()
        buffer = []
        if not text:
            return
        for part in _split_long(text, max_chars):
            chunks.append(Chunk(text=part, location=buffer_location, ordinal=len(chunks)))

    for block in blocks:
        text = block.text.strip()
        if not text:
            continue
        group = block.group or block.location
        current_len = sum(len(b) for b in buffer)
        if buffer_group is not None and (group != buffer_group or current_len + len(text) > max_chars):
            flush()
        if not buffer:
            buffer_group = group
            buffer_location = block.location
        buffer.append(text)

    flush()
    return chunks
