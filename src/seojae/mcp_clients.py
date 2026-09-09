"""MCP 클라이언트 설정에 서재를 등록한다.

설치할 때 인스톨러가 이 코드를 불러 클라이언트 설정 파일에 항목 하나를 더한다.
사용자가 JSON을 직접 고칠 필요가 없어진다.

**남의 설정을 건드리지 않는 것이 이 파일의 전부다.** 그 파일에는 다른 MCP 서버와
그 앱의 설정이 같이 들어 있고, 그건 우리 것이 아니다. 그래서:

- 통째로 덮어쓰지 않고 서버 목록 안의 우리 키 하나만 손댄다
- 고치기 전에 원본을 백업한다
- 임시 파일에 다 쓴 뒤 바꿔치기한다. 설치가 중간에 끊겨도 설정이 잘리지 않게
- 읽을 수 없는 JSON이면 **멈춘다.** 망가진 파일을 우리 마음대로 새로 쓰면
  남의 서버 설정이 통째로 사라진다

**LLM에게 이 파일을 직접 고치게 하지 마라.** 위의 안전장치가 전부 사라진다.
대신 LLM이 `seojae-mcp.exe register --client cursor` 를 실행하게 하면 된다.
말로 시키는 편함은 그대로고, 조심하는 일은 이 코드가 한다.

## 클라이언트를 더하려면

`CLIENTS` 에 한 줄 더하면 된다. 파서 등록기와 같은 구조다 — 새 클라이언트가
생겼을 때 고칠 곳이 한 군데뿐이어야 한다.

앱마다 다른 것이 둘이다. **설정 파일 위치**와 **서버 목록의 키 이름**
(대부분 `mcpServers` 지만 VS Code는 `servers` 다).
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SERVER_KEY = "seojae"

DEFAULT_CLIENT = "claude-desktop"


class ConfigError(Exception):
    """설정 파일을 안전하게 고칠 수 없을 때."""


class UnknownClient(ConfigError):
    """모르는 클라이언트 이름."""


def _roaming() -> Path:
    base = os.environ.get("APPDATA")
    return Path(base) if base else Path.home() / "AppData" / "Roaming"


def _app_support() -> Path:
    """앱 설정이 놓이는 곳. 윈도우는 Roaming, 맥은 Application Support."""
    if sys.platform == "win32":
        return _roaming()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    base = os.environ.get("XDG_CONFIG_HOME")
    return Path(base) if base else Path.home() / ".config"


@dataclass(frozen=True)
class Client:
    """MCP 클라이언트 하나. 앱마다 다른 것은 파일 위치와 키 이름뿐이다."""

    name: str
    label: str
    path: Callable[[], Path]
    #: 서버 목록이 담기는 키. 대부분 mcpServers 지만 VS Code는 servers 다.
    servers_key: str = "mcpServers"
    #: 등록한 뒤 사용자가 해야 할 일. **화면에 그대로 나가므로 존댓말로 쓴다.**
    after: str = "앱을 껐다 켜면 서재가 붙습니다."


#: 아는 클라이언트들. 새로 생기면 여기 한 줄 더한다.
CLIENTS: dict[str, Client] = {
    "claude-desktop": Client(
        name="claude-desktop",
        label="Claude Desktop",
        path=lambda: _app_support() / "Claude" / "claude_desktop_config.json",
        after="Claude Desktop을 껐다 켜세요. 설정은 시작할 때만 읽습니다.",
    ),
    "cursor": Client(
        name="cursor",
        label="Cursor",
        # 사용자 전체에 적용되는 설정. 프로젝트마다 두려면 <프로젝트>/.cursor/mcp.json 이다.
        path=lambda: Path.home() / ".cursor" / "mcp.json",
        after="Cursor를 껐다 켜거나, 설정에서 MCP 서버를 새로 고치세요.",
    ),
    "vscode": Client(
        name="vscode",
        label="VS Code (Copilot)",
        path=lambda: _app_support() / "Code" / "User" / "mcp.json",
        # VS Code만 키 이름이 다르다. 이것 때문에 등록기를 만들었다.
        servers_key="servers",
        after="VS Code를 껐다 켜세요.",
    ),
    "windsurf": Client(
        name="windsurf",
        label="Windsurf",
        path=lambda: Path.home() / ".codeium" / "windsurf" / "mcp_config.json",
    ),
    "claude-code": Client(
        name="claude-code",
        label="Claude Code (이 폴더)",
        # 프로젝트 단위 설정. 홈의 .claude.json 은 세션 기록까지 든 큰 파일이라
        # 건드리지 않는다.
        path=lambda: Path.cwd() / ".mcp.json",
        after="이 폴더에서 claude 를 다시 실행하세요.",
    ),
}


def get_client(name: str | None = None) -> Client:
    key = (name or DEFAULT_CLIENT).strip().lower()
    if key not in CLIENTS:
        아는것 = ", ".join(CLIENTS)
        raise UnknownClient(f"모르는 클라이언트다: {name}\n아는 것: {아는것}")

    return CLIENTS[key]


def config_path(client: str | None = None) -> Path:
    """그 클라이언트의 설정 파일 위치."""
    return get_client(client).path()



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


def register(
    command: Path | str, client: str | None = None, args: list[str] | None = None
) -> str:
    """서재를 그 클라이언트에 등록한다. 이미 있으면 명령 경로를 갱신한다.

    루트 폴더는 인자로 넘기지 않는다. 서버가 앱과 같은 설정 파일을 보고 스스로
    찾으므로, 설정 화면에서 서재를 옮기면 클라이언트가 보는 서재도 따라간다.
    등록에 경로를 박아두면 두 곳이 어긋난다.
    """
    app = get_client(client)
    path = app.path()
    data = _load(path)

    servers = data.get(app.servers_key)
    if servers is None:
        servers = {}
        data[app.servers_key] = servers
    elif not isinstance(servers, dict):
        raise ConfigError(f"설정 파일의 {app.servers_key} 가 객체가 아니다: {path}")

    entry = {"command": str(command)}
    if args:
        entry["args"] = args

    existed = SERVER_KEY in servers
    if existed and servers[SERVER_KEY] == entry:
        return f"{app.label}: 이미 등록되어 있다 ({path})"

    backup = _backup(path)
    servers[SERVER_KEY] = entry
    _save(path, data)

    what = "갱신했다" if existed else "등록했다"
    others = [k for k in servers if k != SERVER_KEY]
    note = f" (다른 서버 {len(others)}개는 그대로)" if others else ""
    tail = f"\n원본 백업: {backup}" if backup else ""
    return f"{app.label}에 서재를 {what}{note}: {path}{tail}"


def unregister(client: str | None = None) -> str:
    """등록을 지운다. 우리 항목만 지우고 나머지는 건드리지 않는다."""
    app = get_client(client)
    path = app.path()
    if not path.is_file():
        return f"{app.label}: 등록된 것이 없다 (설정 파일 없음)."

    data = _load(path)
    servers = data.get(app.servers_key)
    if not isinstance(servers, dict) or SERVER_KEY not in servers:
        return f"{app.label}: 등록된 것이 없다."

    backup = _backup(path)
    del servers[SERVER_KEY]
    _save(path, data)

    tail = f"\n원본 백업: {backup}" if backup else ""
    return f"{app.label}에서 서재 등록을 지웠다: {path}{tail}"


def registered_command(client: str | None = None) -> str | None:
    """지금 등록된 실행 명령. 없으면 None."""
    app = get_client(client)
    try:
        servers = _load(app.path()).get(app.servers_key)
    except ConfigError:
        return None
    if not isinstance(servers, dict):
        return None
    entry = servers.get(SERVER_KEY)
    return entry.get("command") if isinstance(entry, dict) else None


def survey() -> list[dict]:
    """아는 클라이언트를 전부 훑는다. 앱의 연결 화면이 이걸 그린다.

    설치돼 있지 않은 앱도 목록에 남긴다 — 사용자가 "Cursor는 왜 안 보이지"
    하고 헤매는 것보다, 보이되 "설정 파일이 아직 없다"고 말하는 편이 낫다.
    """
    out = []
    for app in CLIENTS.values():
        path = app.path()
        try:
            command = registered_command(app.name)
            broken = False
        except Exception:
            command, broken = None, True
        out.append(
            {
                "name": app.name,
                "label": app.label,
                "path": str(path),
                "exists": path.is_file(),
                "registered": command is not None,
                "command": command,
                "after": app.after,
                "broken": broken,
            }
        )
    return out
