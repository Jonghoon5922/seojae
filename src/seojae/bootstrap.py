"""인자 없이 시작할 때 서재를 찾아내는 곳.

진입점이 둘이다. 아이콘을 더블클릭하는 앱(`서재.exe`)과, Claude Desktop이 띄우는
MCP 서버(`seojae-mcp.exe`). 둘 다 인자가 없이 실행되므로 같은 방법으로 같은 서재를
찾아야 한다. **둘이 다른 폴더를 열면 앱에서 정리한 것이 Claude에게 안 보인다.**

그래서 이 판단은 여기 한 곳에만 둔다.
"""

from __future__ import annotations

from pathlib import Path

from .appconfig import default_root, read_root, write_root
from .paths import INBOX_DIRNAME

APP_NAME = "서재"

EXAMPLE_SHELF = "예시책장"

_INBOX_GUIDE = """\
분류하기 전 파일을 이 폴더에 넣어두면 됩니다.
검색 결과에는 기본으로 나오지 않습니다.
Claude에게 '미분류 정리해줘'라고 하면 알맞은 책장으로 옮겨줍니다.
"""

#: 첫 실행에 넣어두는 설명 견본. 사용자가 아직 안 고쳤는지 알아보려고 상수로 둔다.
#: 안 고친 견본을 진짜 설명으로 착각하면 엉뚱한 일이 생긴다 — 시나리오 생성기가
#: 이 문구를 주제로 쪼개 헛소리를 만든 적이 있었다.
PLACEHOLDER_DESCRIPTION = "이 책장이 어떤 질문에 쓰이는지 한두 문장으로 적습니다. 이 문장이 Claude가 책장을 고르는 근거가 됩니다."

_EXAMPLE_README = f"""\
---
name: 예시책장
description: {PLACEHOLDER_DESCRIPTION}
---

# 예시책장

폴더 하나가 책장 하나입니다. md, txt, pdf, docx, hwpx, xlsx 등을 넣으면 색인됩니다.
"""


def resolve_shelf() -> Path:
    """열 서재를 정한다. 기억해둔 것이 없으면 문서 폴더 아래에 만든다.

    MCP 서버도 이 길로 온다. 없으면 만드는 이유가 거기 있다 — Claude Desktop이
    서버를 띄우는 시점에 사용자가 앱을 한 번도 안 켰을 수 있는데, 폴더가 없다고
    서버가 죽으면 "seojae 연결 실패"만 보이고 왜인지는 안 보인다.
    """
    saved = read_root()
    if saved is not None:
        return saved

    root = default_root(APP_NAME)
    if not root.exists():
        make_skeleton(root)

    write_root(root)
    return root


def make_skeleton(root: Path) -> None:
    """첫 실행에 빈 서재를 만든다. CLI의 init 과 같은 골격."""
    (root / INBOX_DIRNAME).mkdir(parents=True, exist_ok=True)
    (root / EXAMPLE_SHELF).mkdir(exist_ok=True)

    guide = root / INBOX_DIRNAME / "여기에-던져두세요.txt"
    if not guide.exists():
        guide.write_text(_INBOX_GUIDE, encoding="utf-8")

    readme = root / EXAMPLE_SHELF / "README.md"
    if not readme.exists():
        readme.write_text(_EXAMPLE_README, encoding="utf-8")
