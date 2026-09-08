"""HTML 파서.

스크립트·스타일을 걷어내고 글만 남긴다. 헤딩(h1~h6)을 만나면 거기서 자르고
헤딩 경로를 출처로 쓴다 — 마크다운과 같은 방식이다.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

from .base import Block, ParsedDoc, ParseError, register
from .plain import read_text

_SKIP = {"script", "style", "noscript", "template", "svg"}
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_BREAKS = {"p", "div", "br", "li", "tr", "section", "article", "td", "th"}
_SPACES = re.compile(r"[ \t ]+")


class _Reader(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[Block] = []
        self.title = ""
        self._path: list[str] = []
        self._buffer: list[str] = []
        self._skip_depth = 0
        self._in_title = False
        self._heading_level = 0
        self._heading_text: list[str] = []

    # ── 수집 ──
    def _flush(self) -> None:
        text = _SPACES.sub(" ", "\n".join(self._buffer)).strip()
        self._buffer.clear()
        if not text:
            return
        location = " > ".join(self._path) if self._path else "(머리말)"
        self.blocks.append(Block(text=text, location=location, group=location))

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = True
        elif tag in _HEADINGS:
            self._flush()
            self._heading_level = int(tag[1])
            self._heading_text = []
        elif tag in _BREAKS:
            self._buffer.append("")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = False
        elif tag in _HEADINGS and self._heading_level:
            heading = " ".join(self._heading_text).strip()
            level = self._heading_level
            self._heading_level = 0
            if heading:
                self._path[:] = self._path[: level - 1]
                while len(self._path) < level - 1:
                    self._path.append("")
                self._path.append(heading)
                self._buffer.append(heading)
                if not self.title:
                    self.title = heading

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title = self.title or text
        elif self._heading_level:
            self._heading_text.append(text)
        else:
            self._buffer.append(text)

    def close(self) -> None:  # type: ignore[override]
        super().close()
        self._flush()


@register(".html", ".htm", ".xhtml", label="HTML")
def parse_html(path: Path) -> ParsedDoc:
    try:
        raw = read_text(path)
    except OSError as e:
        raise ParseError(str(e)) from e

    reader = _Reader()
    try:
        reader.feed(raw)
        reader.close()
    except Exception as e:
        raise ParseError(f"HTML을 읽지 못했다: {e}") from e

    if not reader.blocks:
        raise ParseError("HTML에서 읽어낸 글이 없다.")

    return ParsedDoc(title=reader.title or path.stem, blocks=reader.blocks)
