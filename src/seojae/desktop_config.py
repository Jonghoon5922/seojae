"""Claude Desktop 설정 파일에 서재를 등록한다.

설치할 때 인스톨러가 이 코드를 불러 `claude_desktop_config.json` 에 항목 하나를
더한다. 사용자가 `.mcpb` 를 받아 더블클릭하거나 JSON을 직접 고칠 필요가 없어진다.

**남의 설정을 건드리지 않는 것이 이 파일의 전부다.** 그 파일에는 다른 MCP 서버들이
같이 들어 있고, 그건 우리 것이 아니다. 그래서:

- 통째로 덮어쓰지 않고 `mcpServers` 안의 우리 키 하나만 손댄다
- 고치기 전에 원본을 백업한다
- 임시 파일에 다 쓴 뒤 바꿔치기한다. 설치가 중간에 끊겨도 설정이 잘리지 않게
- 읽을 수 없는 JSON이면 **멈춘다.** 망가진 파일을 우리 마음대로 새로 쓰면
  남의 서버 설정이 통째로 사라진다
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

SERVER_KEY = "seojae"


class ConfigError(Exception):
    """설정 파일을 안전하게 고칠 수 없을 때."""


def config_path() -> Path:
    """Claude Desktop 설정 파일 위치."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_CONFIG_HOME")
        root = Path(base) if base else Path.home() / ".config"
    return root / "Claude" / "claude_desktop_config.json"


def _load(path: Path) -> dict:
    """기존 설정을 읽는다. 없으면 빈 것, 망가졌으면 예외."""
    if not path.is_file():
        return {}
    try:
        # utf-8-sig: 앞에 BOM이 있으면 떼고, 없으면 utf-8과 똑같이 읽는다.
        # 메모장이나 PowerShell의 Out-File 로 설정을 고치면 BOM이 붙는데,
        # 그대로 json에 넣으면 "형식이 깨졌다"고 거부하게 된다. 실제로 그랬다.
        text = path.read_text(encoding="utf-8-sig")
    except OSError as e:
        raise ConfigError(f"설정 파일을 읽지 못했다: {e}") from e

    if not text.strip():
        return {}

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ConfigError(
            f"설정 파일의 형식이 깨져 있다 ({path}, {e.lineno}번째 줄).\n"
            "직접 고친 뒤 다시 시도하라. 여기서 새로 쓰면 다른 MCP 서버 설정이 사라진다."
        ) from e

    if not isinstance(data, dict):
        raise ConfigError(f"설정 파일의 최상위가 객체가 아니다: {path}")
    return data


def _backup(path: Path) -> Path | None:
    """고치기 전 원본을 남긴다."""
    if not path.is_file():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.stem}.{stamp}.bak")
    try:
        target.write_bytes(path.read_bytes())
    except OSError:
        return None
    return target


def _save(path: Path, data: dict) -> None:
    """임시 파일에 다 쓴 뒤 바꿔치기한다. 중간에 끊겨도 원본이 잘리지 않는다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(tmp, path)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        raise ConfigError(f"설정 파일을 쓰지 못했다: {e}") from e


def register(command: Path | str, args: list[str] | None = None) -> str:
    """서재를 Claude Desktop에 등록한다. 이미 있으면 명령 경로를 갱신한다.

    루트 폴더는 인자로 넘기지 않는다. 서버가 앱과 같은 설정 파일을 보고 스스로
    찾으므로, 설정 화면에서 서재를 옮기면 MCP도 따라간다. 여기에 경로를 박아두면
    두 곳이 어긋난다.
    """
    path = config_path()
    data = _load(path)

    servers = data.get("mcpServers")
    if servers is None:
        servers = {}
        data["mcpServers"] = servers
    elif not isinstance(servers, dict):
        raise ConfigError(f"설정 파일의 mcpServers 가 객체가 아니다: {path}")

    entry = {"command": str(command)}
    if args:
        entry["args"] = args

    existed = SERVER_KEY in servers
    if existed and servers[SERVER_KEY] == entry:
        return f"이미 등록되어 있다: {path}"

    backup = _backup(path)
    servers[SERVER_KEY] = entry
    _save(path, data)

    what = "갱신했다" if existed else "등록했다"
    others = [k for k in servers if k != SERVER_KEY]
    note = f" (다른 서버 {len(others)}개는 그대로)" if others else ""
    tail = f"\n원본 백업: {backup}" if backup else ""
    return f"서재를 Claude Desktop에 {what}{note}: {path}{tail}"


def unregister() -> str:
    """등록을 지운다. 우리 항목만 지우고 나머지는 건드리지 않는다."""
    path = config_path()
    if not path.is_file():
        return "등록된 것이 없다 (설정 파일 없음)."

    data = _load(path)
    servers = data.get("mcpServers")
    if not isinstance(servers, dict) or SERVER_KEY not in servers:
        return "등록된 것이 없다."

    backup = _backup(path)
    del servers[SERVER_KEY]
    _save(path, data)

    tail = f"\n원본 백업: {backup}" if backup else ""
    return f"서재 등록을 지웠다: {path}{tail}"


def registered_command() -> str | None:
    """지금 등록된 실행 명령. 없으면 None. (설정 화면에서 상태를 보이는 용도)"""
    try:
        servers = _load(config_path()).get("mcpServers")
    except ConfigError:
        return None
    if not isinstance(servers, dict):
        return None
    entry = servers.get(SERVER_KEY)
    return entry.get("command") if isinstance(entry, dict) else None
