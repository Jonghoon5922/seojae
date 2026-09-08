"""MCPB 번들 진입점.

Claude Desktop이 설치 시 사용자에게 서재 폴더를 물어보고, 그 경로를 인자로 넘긴다.
여기서는 경로를 확인해 서버로 넘기기만 한다.

stdout은 MCP 프로토콜 채널이다. 사람이 볼 메시지는 전부 stderr로 보낸다.
"""

from __future__ import annotations

import sys


def main() -> int:
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print(
            "서재 폴더가 지정되지 않았다. Claude Desktop의 확장 설정에서 폴더를 고르라.",
            file=sys.stderr,
        )
        return 2

    from seojae.index import index_root, open_db
    from seojae.paths import resolve_root
    from seojae.server import serve

    try:
        root = resolve_root(sys.argv[1])
    except (FileNotFoundError, NotADirectoryError) as e:
        print(f"{e}", file=sys.stderr)
        print("Claude Desktop의 확장 설정에서 올바른 폴더를 고르라.", file=sys.stderr)
        return 2

    print(f"서재: {root}", file=sys.stderr)

    conn = open_db(root)
    stats = index_root(root, conn)
    conn.close()
    print(
        f"색인 — 새로 읽음 {stats.indexed} / 변경 없음 {stats.skipped} / "
        f"실패 {stats.failed} / 청크 {stats.chunks}",
        file=sys.stderr,
    )

    def on_change(kind: str, detail: str) -> None:
        print(f"{kind}: {detail}", file=sys.stderr)

    serve(root, watch=True, on_change=on_change)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
