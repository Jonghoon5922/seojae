"""앱 설정과 로그 위치.

아이콘을 더블클릭해 실행할 때는 인자가 없으므로 서재 위치를 기억해둬야 한다.
그 설정을 읽고 쓰는 곳은 여기 하나다 — 진입점과 설정 화면이 같은 파일을 봐야 하니까.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

APP_DIRNAME = "seojae"
CONFIG_NAME = "config.json"
LOG_NAME = "app.log"


def app_data_dir() -> Path:
    """설정과 로그를 두는 곳 (%LOCALAPPDATA%\\seojae)."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    path = root / APP_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return app_data_dir() / CONFIG_NAME


def log_path() -> Path:
    return app_data_dir() / LOG_NAME


def read_root() -> Path | None:
    """기억해둔 서재 위치. 없거나 사라졌으면 None."""
    path = config_path()
    if not path.is_file():
        return None
    try:
        saved = json.loads(path.read_text(encoding="utf-8")).get("root")
    except (json.JSONDecodeError, OSError):
        return None
    if not saved:
        return None
    candidate = Path(saved)
    return candidate if candidate.is_dir() else None


def write_root(root: Path) -> None:
    config_path().write_text(
        json.dumps({"root": str(root)}, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def default_root(app_name: str = "서재") -> Path:
    """처음 실행할 때 쓸 서재 위치. 문서 폴더 아래."""
    documents = Path.home() / "Documents"
    if not documents.is_dir():
        documents = Path.home()
    return documents / app_name
