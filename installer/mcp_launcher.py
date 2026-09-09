"""MCP 서버 진입점 (PyInstaller 로 묶이는 대상, 콘솔 모드).

Claude Desktop이 이 실행 파일을 자식 프로세스로 띄우고 stdin/stdout으로 대화한다.
그래서 **창 모드로 묶으면 안 된다** — 창 모드 실행 파일에는 표준 입출력이 없어서
프로토콜이 오갈 통로가 없다. 파이썬이 `python.exe` 와 `pythonw.exe` 로 나뉘어 있는
것과 같은 이유로 실행 파일이 둘이다. 무거운 자원(`_internal`)은 둘이 공유한다.

인자 없이 실행되면 앱과 같은 설정을 보고 같은 서재를 연다. 그래서 설정 화면에서
서재를 옮기면 Claude가 보는 서재도 따라 옮겨진다.

    seojae-mcp.exe                MCP 서버 (Claude Desktop이 이렇게 부른다)
    seojae-mcp.exe <폴더>          그 폴더를 서재로 삼아 서버
    seojae-mcp.exe register       Claude Desktop 설정에 등록 (인스톨러가 부른다)
    seojae-mcp.exe unregister     등록 해제 (제거 프로그램이 부른다)
"""

from __future__ import annotations

import sys

PASSTHROUGH = {"register": "mcp-register", "unregister": "mcp-unregister"}


def main() -> int:
    args = sys.argv[1:]

    if args and args[0] in PASSTHROUGH:
        forwarded = [PASSTHROUGH[args[0]], *args[1:]]
    else:
        if args:
            root = args[0]
        else:
            from seojae.bootstrap import resolve_shelf

            root = str(resolve_shelf())
        forwarded = ["serve", root, *args[1:]]

    # CLI를 그대로 쓴다. 색인·stderr 인코딩·오류 처리를 두 벌로 두지 않기 위해서다.
    sys.argv = ["seojae-mcp", *forwarded]
    from seojae.cli import app

    app()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
