"""파서 공통 자료구조."""

from __future__ import annotations

from dataclasses import dataclass, field


class ParseError(Exception):
    """파일을 읽지 못했을 때. 색인은 계속하고 실패 목록에 남긴다."""


@dataclass
class Block:
    """파서가 뽑아낸 최소 단위. location이 사용자에게 보여줄 출처가 된다.

    location 예: "## 예외 처리", "p.12", "문단 34"
    """

    text: str
    location: str
    group: str = ""  # 같은 group끼리만 청크로 합친다 (헤딩/페이지 경계 유지)


@dataclass
class ParsedDoc:
    title: str
    blocks: list[Block] = field(default_factory=list)
    pages: int = 0
