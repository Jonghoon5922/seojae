"""이미지 파서.

**우리는 이미지를 읽지 않는다.** OCR을 붙이면 의존성이 무거워지고 품질도 들쭉날쭉하다.
대신 파일명·폴더 경로만 색인해서 "찾을 수 있게" 해두고, 실제로 읽는 것은
`get_document`가 이미지 원본을 그대로 넘겨 **Claude가 직접 보게** 한다.

판단은 손님이 한다는 원칙 그대로다. 그리고 멀티모달 모델은 표·다이어그램을
OCR보다 잘 읽는다.
"""

from __future__ import annotations

import re
from pathlib import Path

from .base import Block, ParsedDoc, ParseError, register

# 이보다 큰 이미지는 색인하지 않는다 (모델에 넘기기도 어렵다)
MAX_IMAGE_BYTES = 20 * 1024 * 1024

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")

#: 확장자 → MCP 이미지 블록에 실을 MIME 타입
MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}

_SEPARATORS = re.compile(r"[_\-.]+")


def is_image(path: Path | str) -> bool:
    suffix = Path(path).suffix.lower()
    return suffix in MIME_TYPES


def mime_type(path: Path | str) -> str:
    return MIME_TYPES.get(Path(path).suffix.lower(), "application/octet-stream")


@register(*IMAGE_EXTS, label="이미지 (파일명으로 검색, 열람은 Claude가 직접)")
def parse_image(path: Path) -> ParsedDoc:
    try:
        size = path.stat().st_size
    except OSError as e:
        raise ParseError(str(e)) from e

    if size > MAX_IMAGE_BYTES:
        raise ParseError(
            f"이미지가 너무 크다 ({size / 1024 / 1024:.0f}MB). "
            f"{MAX_IMAGE_BYTES // 1024 // 1024}MB까지 다룬다."
        )

    # 파일명과 상위 폴더 이름을 검색 가능한 글로 만든다.
    # "설계서_흐름도-v2.png" → "설계서 흐름도 v2"
    words = " ".join(w for w in _SEPARATORS.split(path.stem) if w)
    folder = path.parent.name

    text = "\n".join(
        part
        for part in (
            path.name,
            words if words != path.stem else "",
            f"폴더: {folder}" if folder else "",
            "(이미지 파일. 내용은 get_document로 열어 직접 볼 수 있다.)",
        )
        if part
    )

    return ParsedDoc(
        title=path.stem,
        blocks=[Block(text=text, location="파일 정보", group="image")],
    )
