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
    seojae-mcp.exe register cursor  다른 앱에 등록 (앱 이름은 mcp-list 로 확인)
    seojae-mcp.exe unregister     등록 해제 (제거 프로그램이 부른다)
"""

from __future__ import annotations

import sys

PASSTHROUGH = {
    "register": "mcp-register",
    "unregister": "mcp-unregister",
    "mcp-list": "mcp-list",
    "list": "mcp-list",
}


USAGE = """서재 (Seojae) — MCP 서버

Claude Desktop·Cursor 같은 앱이 이 파일을 띄워 서재를 검색한다.

  seojae-mcp.exe                     MCP 서버 (앱이 이렇게 부른다)
  seojae-mcp.exe <폴더>               그 폴더를 서재로 삼아 서버

연결:
  seojae-mcp.exe mcp-list            어느 앱에 연결돼 있는지 훑는다
  seojae-mcp.exe register            Claude Desktop에 연결
  seojae-mcp.exe register cursor     다른 앱에 연결 (이름은 mcp-list 로)
  seojae-mcp.exe unregister cursor   연결 해제

앱 창(시작 메뉴 → 서재)의 설정 탭에서 버튼으로도 연결할 수 있다.
그쪽이 쉽다 — 아는 앱을 목록으로 보여주고 상태도 같이 나온다.

그 밖의 명령(readings, status, search 등)은:
  seojae-mcp.exe --commands
"""


def main() -> int:
    args = sys.argv[1:]

    # `--help` 를 서재 폴더 이름으로 넘기면 serve 의 도움말만 나온다.
    # register 나 mcp-list 가 있는지 알 길이 없어진다.
    if args and args[0] in ("--help", "-h", "/?"):
        print(USAGE)
        return 0
    if args and args[0] == "--commands":
        sys.argv = ["seojae-mcp", "--help"]
        from seojae.cli import app

        app()
        return 0

    if args and args[0] in PASSTHROUGH:
        rest = list(args[1:])
        # `register cursor` 처럼 앱 이름을 바로 받는다. 사람도 LLM도 그렇게 쓴다.
        if rest and not rest[0].startswith("-"):
            rest = ["--client", *rest]
        forwarded = [PASSTHROUGH[args[0]], *rest]
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
