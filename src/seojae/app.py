"""데스크톱 앱 창.

웹 UI를 브라우저 대신 자체 창으로 띄운다. 한 프로세스 안에서 셋이 같이 돈다.

    창(WebView) ─┐
    파일 감시   ─┼→ 같은 색인, 같은 검색 함수
    웹 서버     ─┘   (127.0.0.1, 임의 포트)

Windows는 Edge의 WebView2, macOS는 WebKit을 쓴다. 별도 런타임을 받지 않는다.
"""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
from typing import Callable

import uvicorn

from .index import index_root, open_db
from .web import create_app

WINDOW_TITLE = "서재"
DEFAULT_SIZE = (1180, 820)
MIN_SIZE = (860, 600)
READY_TIMEOUT = 20.0


class AppError(Exception):
    """앱 창을 띄울 수 없을 때."""


def find_port(preferred: int = 8765) -> int:
    """쓸 수 있는 포트. 선호 포트가 막혀 있으면 아무거나 받는다."""
    for candidate in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", candidate))
                return s.getsockname()[1]
            except OSError:
                continue
    raise AppError("쓸 수 있는 포트를 찾지 못했다.")


def wait_until_ready(port: int, timeout: float = READY_TIMEOUT) -> bool:
    """서버가 뜰 때까지 기다린다. 안 기다리면 빈 창이 먼저 뜬다."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.4)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.1)
    return False


def run(
    root: Path,
    port: int | None = None,
    watch: bool = True,
    reindex: bool = True,
    on_status: Callable[[str], None] | None = None,
) -> None:
    """서버를 백그라운드로 띄우고 창을 연다. 창을 닫으면 전부 정리한다."""

    def say(message: str) -> None:
        if on_status:
            on_status(message)

    try:
        import webview
    except ImportError as e:
        raise AppError(
            "창을 띄우려면 pywebview가 필요하다.\n"
            "  uv pip install pywebview\n"
            "또는 브라우저로 쓰려면: seojae ui <폴더>"
        ) from e

    conn = open_db(root, check_same_thread=False)
    lock = threading.Lock()

    if reindex:
        say("색인 확인 중…")
        stats = index_root(root, conn)
        say(f"문서 {stats.total}건 (새로 읽음 {stats.indexed} / 실패 {stats.failed})")

    watcher = None
    if watch:
        from .watcher import ShelfWatcher

        watcher = ShelfWatcher(root, conn, lock)
        watcher.start()

    chosen = port or find_port()
    server = uvicorn.Server(
        uvicorn.Config(
            # 앱으로 켰을 때만 서재 폴더를 바꿀 수 있다.
            # CLI(`seojae ui <폴더>`)는 경로를 인자로 받으므로 설정을 바꿔도 소용없다.
            create_app(root, conn, lock, allow_root_change=True),
            host="127.0.0.1",  # 네트워크에 열지 않는다
            port=chosen,
            log_level="warning",
        )
    )
    thread = threading.Thread(target=server.run, name="seojae-web", daemon=True)
    thread.start()

    try:
        if not wait_until_ready(chosen):
            raise AppError(f"서버가 뜨지 않았다 (127.0.0.1:{chosen}).")

        say(f"창 여는 중… (127.0.0.1:{chosen})")
        webview.create_window(
            f"{WINDOW_TITLE} — {root.name}",
            f"http://127.0.0.1:{chosen}",
            width=DEFAULT_SIZE[0],
            height=DEFAULT_SIZE[1],
            min_size=MIN_SIZE,
        )
        webview.start()  # 창이 닫힐 때까지 여기서 멈춘다
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        if watcher is not None:
            watcher.stop()
        conn.close()
        say("종료했다.")
