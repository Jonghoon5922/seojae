"""데스크톱 앱 진입점 (PyInstaller 로 묶이는 대상).

CLI와 다른 점이 셋이다.

1. **인자가 없다.** 아이콘을 더블클릭해서 실행되므로 서재 위치를 스스로 알아야 한다.
   설정 파일에 기억해두고, 없으면 문서 폴더 아래에 만든다.
2. **콘솔이 없다.** 오류가 나도 화면에 아무것도 안 나온다. 그래서 로그를 파일로 남기고
   치명적 오류는 메시지 상자로 띄운다. 안 그러면 "아이콘 눌렀는데 아무 일도 안 남"이 된다.
3. **경로가 다르다.** 묶인 실행 파일 안에서는 sys._MEIPASS 아래에 자원이 풀린다.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

APP_NAME = "서재"
CONFIG_NAME = "config.json"


def app_data_dir() -> Path:
    """설정과 로그를 두는 곳 (%LOCALAPPDATA%\\seojae)."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    path = root / "seojae"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_path() -> Path:
    return app_data_dir() / "app.log"


def log(message: str) -> None:
    """창 모드에는 콘솔이 없다. 무슨 일이 있었는지 파일에만 남는다."""
    from datetime import datetime

    try:
        with log_path().open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')}  {message}\n")
    except OSError:
        pass


def show_error(message: str) -> None:
    """치명적 오류를 사용자에게 보인다. 콘솔이 없으므로 메시지 상자로."""
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


def default_root() -> Path:
    """처음 실행할 때 쓸 서재 위치. 문서 폴더 아래."""
    documents = Path.home() / "Documents"
    if not documents.is_dir():
        documents = Path.home()
    return documents / APP_NAME


def load_root() -> Path:
    """기억해둔 서재 위치. 없으면 기본 위치를 만들어 쓴다."""
    config = app_data_dir() / CONFIG_NAME

    if config.is_file():
        try:
            saved = json.loads(config.read_text(encoding="utf-8")).get("root")
            if saved and Path(saved).is_dir():
                return Path(saved)
            if saved:
                log(f"기억된 서재 폴더가 없어졌다: {saved}")
        except (json.JSONDecodeError, OSError) as e:
            log(f"설정을 읽지 못했다: {e}")

    root = default_root()
    if not root.exists():
        log(f"서재를 새로 만든다: {root}")
        _make_skeleton(root)

    save_root(root)
    return root


def save_root(root: Path) -> None:
    try:
        (app_data_dir() / CONFIG_NAME).write_text(
            json.dumps({"root": str(root)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        log(f"설정을 쓰지 못했다: {e}")


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
            "Claude에게 '인박스 정리해줘'라고 하면 알맞은 책장으로 옮겨줍니다.\n",
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
        root = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else load_root()
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
