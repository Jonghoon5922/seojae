"""파서 공통 자료구조와 등록기.

형식을 추가하는 방법은 하나다. 새 모듈을 만들고 `@register` 를 붙인 뒤
`parsers/__init__.py` 에서 import 하면 끝이다. 지원 확장자 목록·파일 순회·
UI 안내가 전부 이 등록기에서 파생되므로, 두 군데를 고칠 일이 없다.

    @register(".xlsx", label="Excel 문서")
    def parse_xlsx(path: Path) -> ParsedDoc:
        ...
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable


class ParseError(Exception):
    """파일을 읽지 못했을 때. 색인은 계속하고 실패 목록에 남긴다."""


@dataclass
class Block:
    """파서가 뽑아낸 최소 단위. location이 사용자에게 보여줄 출처가 된다.

    location 예: "## 예외 처리", "p.12", "Sheet1!A2:F2", "class UserService"
    """

    text: str
    location: str
    group: str = ""  # 같은 group끼리만 청크로 합친다 (헤딩/페이지 경계 유지)


@dataclass
class ParsedDoc:
    title: str
    blocks: list[Block] = field(default_factory=list)
    pages: int = 0


Parser = Callable[[Path], ParsedDoc]


@dataclass(frozen=True)
class Format:
    """등록된 형식 하나."""

    extensions: tuple[str, ...]
    label: str
    parser: Parser


_FORMATS: list[Format] = []
_BY_EXT: dict[str, Parser] = {}


def register(*extensions: str, label: str = "") -> Callable[[Parser], Parser]:
    """파서를 확장자에 연결한다."""

    def decorate(fn: Parser) -> Parser:
        exts = tuple(e.lower() if e.startswith(".") else f".{e.lower()}" for e in extensions)
        _FORMATS.append(Format(extensions=exts, label=label or fn.__name__, parser=fn))
        for ext in exts:
            _BY_EXT[ext] = fn
        return fn

    return decorate


def parser_for(extension: str) -> Parser | None:
    return _BY_EXT.get(extension.lower())


def supported_extensions() -> frozenset[str]:
    """색인 대상 확장자. 파일 순회와 업로드 검사가 이걸 쓴다."""
    return frozenset(_BY_EXT)


def formats() -> list[Format]:
    """등록된 형식 목록. `seojae formats` 와 UI 안내에 쓴다."""
    return list(_FORMATS)


def describe_formats() -> list[tuple[str, str]]:
    """(설명, 확장자 나열) 목록. 사람에게 보여주기 위한 것."""
    return [(f.label, " ".join(f.extensions)) for f in _FORMATS]


def parse_file(path: Path) -> ParsedDoc:
    """확장자에 맞는 파서로 파일을 읽는다. 지원하지 않으면 ParseError."""
    parser = parser_for(path.suffix)
    if parser is None:
        raise ParseError(f"지원하지 않는 형식: {path.suffix}")
    return parser(path)


def blocks_from_lines(
    lines: Iterable[str], location: str, group: str = ""
) -> list[Block]:
    """줄 묶음을 블록 하나로. 여러 파서가 공통으로 쓴다."""
    text = "\n".join(lines).strip()
    return [Block(text=text, location=location, group=group or location)] if text else []
