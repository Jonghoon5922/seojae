"""파일 형식별 파서.

형식을 추가하려면 새 모듈에 `@register` 를 붙인 함수를 만들고 여기서 import 한다.
지원 확장자 목록·파일 순회·업로드 검사·UI 안내가 전부 등록기에서 파생되므로
다른 곳을 고칠 필요가 없다.
"""

from __future__ import annotations

from .base import (
    Block,
    Format,
    ParsedDoc,
    ParseError,
    describe_formats,
    formats,
    parse_file,
    parser_for,
    register,
    supported_extensions,
)

# 아래 import 가 등록을 일으킨다. 순서는 UI에 보여줄 순서다.
from . import markdown as _markdown  # noqa: F401
from . import plain as _plain  # noqa: F401
from . import pdf_file as _pdf  # noqa: F401
from . import docx_file as _docx  # noqa: F401
from . import hwpx_file as _hwpx  # noqa: F401
from . import tabular as _tabular  # noqa: F401
from . import slides as _slides  # noqa: F401
from . import markup as _markup  # noqa: F401

#: 색인 대상 확장자. paths.walk_files 와 업로드 검사가 쓴다.
SUPPORTED_EXTS = supported_extensions()

__all__ = [
    "Block",
    "Format",
    "ParseError",
    "ParsedDoc",
    "SUPPORTED_EXTS",
    "describe_formats",
    "formats",
    "parse_file",
    "parser_for",
    "register",
    "supported_extensions",
]
