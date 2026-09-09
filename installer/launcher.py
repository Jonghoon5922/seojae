"""데스크톱 앱 진입점 (PyInstaller 로 묶이는 대상).

CLI와 다른 점이 셋이다.

1. **인자가 없다.** 아이콘을 더블클릭해서 실행되므로 서재 위치를 스스로 알아야 한다.
   설정 파일에 기억해두고, 없으면 문서 폴더 아래에 만든다.
2. **콘솔이 없다.** 오류가 나도 화면에 아무것도 안 나온다. 그래서 로그를 파일로 남기고
   치명적 오류는 메시지 상자로 띄운다. 안 그러면 "아이콘 눌렀는데 아무 일도 안 남"이 된다.
3. **경로가 다르다.** 묶인 실행 파일 안에서는 sys._MEIPASS 아래에 자원이 풀린다.

설정 파일의 위치와 형식은 `seojae.appconfig` 한 곳에만 정의한다.
설정 화면(웹 UI)도 같은 파일을 보므로, 두 군데서 정의하면 언젠가 어긋난다.
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


def resolve_shelf() -> Path:
    """열 서재를 정한다. 기억해둔 것이 없으면 문서 폴더 아래에 만든다."""
    from seojae.appconfig import default_root, read_root, write_root

    saved = read_root()
    if saved is not None:
        return saved

    root = default_root(APP_NAME)
    if not root.exists():
        log(f"서재를 새로 만든다: {root}")
        _make_skeleton(root)

    write_root(root)
    return root


def _make_skeleton(root: Path) -> None:
    """첫 실행에 빈 서재를 만든다. CLI의 init 과 같은 골격."""
    from seojae.paths import INBOX_DIRNAME

    (root / INBOX_DIRNAME).mkdir(parents=True, exist_ok=True)
    (root / "예시책장").mkdir(exist_ok=True)

    guide = root / INBOX_DIRNAME / "여기에-던져두세요.txt"
    if not guide.exists():
        guide.write_text(
            "분류하기 전 파일을 이 폴더에 넣어두면 됩니다.\n"
            "검색 결과에는 기본으로 나오지 않습니다.\n"
            "Claude에게 '미분류 정리해줘'라고 하면 알맞은 책장으로 옮겨줍니다.\n",
            encoding="utf-8",
        )

    readme = root / "예시책장" / "README.md"
    if not readme.exists():
        readme.write_text(
            "---\n"
            "name: 예시책장\n"
            "description: 이 책장이 어떤 질문에 쓰이는지 한두 문장으로 적습니다. "
            "이 문장이 Claude가 책장을 고르는 근거가 됩니다.\n"
            "---\n\n"
            "# 예시책장\n\n"
            "폴더 하나가 책장 하나입니다. md, txt, pdf, docx, hwpx, xlsx 등을 넣으면 색인됩니다.\n",
            encoding="utf-8",
        )


def main() -> int:
    log("=" * 40)
    log(f"{APP_NAME} 시작 (frozen={getattr(sys, 'frozen', False)})")

    try:
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
