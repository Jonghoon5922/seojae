"""데스크톱 앱 진입점 (PyInstaller 로 묶이는 대상, 창 모드).

CLI와 다른 점이 셋이다.

1. **인자가 없다.** 아이콘을 더블클릭해서 실행되므로 서재 위치를 스스로 알아야 한다.
   그 판단은 `seojae.bootstrap` 한 곳에 있다. MCP 서버 진입점도 같은 곳을 보므로
   둘이 반드시 같은 서재를 연다.
2. **콘솔이 없다.** 오류가 나도 화면에 아무것도 안 나온다. 그래서 로그를 파일로 남기고
   치명적 오류는 메시지 상자로 띄운다. 안 그러면 "아이콘 눌렀는데 아무 일도 안 남"이 된다.
3. **경로가 다르다.** 묶인 실행 파일 안에서는 sys._MEIPASS 아래에 자원이 풀린다.

콘솔이 없다는 것은 stdin/stdout도 없다는 뜻이다. 그래서 이 실행 파일로는 MCP를
띄울 수 없다. MCP는 `mcp_launcher.py` 로 묶는 콘솔 실행 파일이 맡는다.
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime
from pathlib import Path

APP_NAME = "서재"


def log(message: str) -> None:
    """창 모드에는 콘솔이 없다. 무슨 일이 있었는지 파일에만 남는다."""
    from seojae.appconfig import log_path

    try:
        with log_path().open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')}  {message}\n")
    except OSError:
        pass


def show_error(message: str) -> None:
    """치명적 오류를 사용자에게 보인다. 콘솔이 없으므로 메시지 상자로."""
    from seojae.appconfig import log_path

    log(f"[오류] {message}")
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None,
            f"{message}\n\n자세한 기록: {log_path()}",
            f"{APP_NAME} — 실행할 수 없습니다",
            0x10,  # MB_ICONERROR
        )
    except Exception:
        print(message, file=sys.stderr)


def main() -> int:
    log("=" * 40)
    log(f"{APP_NAME} 시작 (frozen={getattr(sys, 'frozen', False)})")

    try:
        from seojae.bootstrap import resolve_shelf

        root = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else resolve_shelf()
    except Exception as e:
        show_error(f"서재 폴더를 준비하지 못했습니다.\n{e}")
        return 2

    log(f"서재: {root}")

    try:
        from seojae.app import AppError, run

        run(root, on_status=log)
    except AppError as e:
        show_error(str(e))
        return 1
    except Exception:
        show_error("예기치 못한 오류가 났습니다.\n" + traceback.format_exc(limit=3))
        log(traceback.format_exc())
        return 1

    log("정상 종료")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
