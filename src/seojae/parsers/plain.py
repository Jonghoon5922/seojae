"""텍스트 파서.

일반 텍스트와 소스 코드를 맡는다. 둘은 파싱은 같지만 **자르는 방법이 다르다.**
산문은 빈 줄로 문단이 나뉘지만, 코드는 클래스·함수 경계로 잘라야 출처가 쓸모 있어진다
("MNz310Bean.java · execute()" 처럼).
"""

from __future__ import annotations

import re
from pathlib import Path

from .base import Block, ParsedDoc, ParseError, register

# 이보다 큰 텍스트 파일은 건너뛴다. 로그·덤프가 색인을 잡아먹는 것을 막는다.
MAX_TEXT_BYTES = 5 * 1024 * 1024

# 코드에서 "여기서부터 새 덩어리" 로 볼 줄.
# 언어마다 다르지만, 들여쓰기가 없는 선언부라는 공통점을 쓴다.
_CODE_HEAD = re.compile(
    r"^(?:"
    r"(?:@\w+\s*)*"  # 애너테이션·데코레이터
    r"(?:public|private|protected|internal|open|final|static|abstract|sealed|export|default)\s+"
    r"|(?:class|interface|enum|record|struct|trait|object|module|namespace|package)\s+"
    r"|(?:def|func|fun|function|sub|proc|procedure)\s+"
    r"|(?:const|let|var|type)\s+\w+\s*[=:]"
    r"|(?:CREATE|ALTER|DROP|INSERT|UPDATE|DELETE|SELECT|MERGE|WITH)\b"
    r")",
    re.IGNORECASE,
)

# 선언 줄에서 이름만 뽑는다
_NAME = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*(?:\(|[:=<{]|$)")


def read_text(path: Path) -> str:
    """인코딩을 모르는 로컬 파일을 최대한 살려 읽는다."""
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _guard_size(path: Path) -> None:
    size = path.stat().st_size
    if size > MAX_TEXT_BYTES:
        raise ParseError(
            f"텍스트 파일이 너무 크다 ({size / 1024 / 1024:.0f}MB). "
            f"{MAX_TEXT_BYTES // 1024 // 1024}MB까지 읽는다."
        )


@register(".txt", ".text", ".log", ".rst", label="일반 텍스트")
def parse_txt(path: Path) -> ParsedDoc:
    try:
        _guard_size(path)
        text = read_text(path)
    except OSError as e:
        raise ParseError(str(e)) from e

    blocks = []
    for i, chunk in enumerate(text.split("\n\n"), start=1):
        if chunk.strip():
            blocks.append(Block(text=chunk.strip(), location=f"문단 {i}", group=f"p{i}"))
    return ParsedDoc(title=path.stem, blocks=blocks)


@register(
    ".java", ".kt", ".scala", ".groovy",
    ".py", ".rb", ".go", ".rs", ".php",
    ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte",
    ".c", ".h", ".cpp", ".hpp", ".cs", ".swift", ".m",
    ".sql", ".sh", ".ps1", ".bat",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".xml", ".properties",
    ".dbio", ".omm", ".tmpl",
    label="소스 코드·설정",
)
def parse_code(path: Path) -> ParsedDoc:
    """소스 코드. 선언(클래스·함수·SQL문) 경계로 자르고 그 이름을 출처로 남긴다."""
    try:
        _guard_size(path)
        text = read_text(path)
    except OSError as e:
        raise ParseError(str(e)) from e

    lines = text.splitlines()
    blocks: list[Block] = []
    buffer: list[str] = []
    current = "(파일 머리)"
    start_line = 1

    def flush(end_line: int) -> None:
        body = "\n".join(buffer).strip()
        buffer.clear()
        if not body:
            return
        location = f"{current} · L{start_line}-{end_line}"
        blocks.append(Block(text=body, location=location, group=location))

    for i, line in enumerate(lines, start=1):
        # 들여쓰지 않은 선언 줄에서 새 덩어리를 시작한다.
        # 들여쓴 것까지 잡으면 중첩 함수마다 쪼개져 조각이 너무 작아진다.
        if line and not line[0].isspace() and _CODE_HEAD.match(line.strip()):
            if buffer:
                flush(i - 1)
                start_line = i
            match = _NAME.search(line)
            current = match.group(1) if match else line.strip()[:60]
        buffer.append(line)

    flush(len(lines))

    if not blocks and text.strip():  # 선언이 하나도 없는 파일
        blocks = [Block(text=text.strip(), location="(전체)", group="all")]

    return ParsedDoc(title=path.name, blocks=blocks)
