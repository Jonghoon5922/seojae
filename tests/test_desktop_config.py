"""Claude Desktop 설정 등록.

이 파일이 지키려는 것은 하나다: **남의 설정을 부수지 않는다.**
그 파일에는 다른 MCP 서버가 같이 들어 있고, 그건 우리 것이 아니다.
"""

from __future__ import annotations

import json

import pytest

from seojae import desktop_config as dc


@pytest.fixture
def config(tmp_path, monkeypatch):
    """설정 파일을 임시 폴더로 돌린다. 진짜 설정을 건드리지 않기 위해서."""
    monkeypatch.setattr(dc, "config_path", lambda: tmp_path / "claude_desktop_config.json")
    return tmp_path / "claude_desktop_config.json"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_설정_파일이_없으면_새로_만든다(config):
    dc.register("C:/seojae/seojae-mcp.exe")
    assert read(config)["mcpServers"]["seojae"]["command"] == "C:/seojae/seojae-mcp.exe"


def test_남의_서버는_그대로_둔다(config):
    config.write_text(
        json.dumps({"mcpServers": {"filesystem": {"command": "npx", "args": ["-y", "fs"]}}}),
        encoding="utf-8",
    )
    dc.register("seojae-mcp")

    servers = read(config)["mcpServers"]
    assert servers["filesystem"] == {"command": "npx", "args": ["-y", "fs"]}
    assert "seojae" in servers


def test_다른_최상위_설정도_그대로_둔다(config):
    config.write_text(
        json.dumps({"preferences": {"theme": "dark"}, "coworkUserFilesPath": "D:/x"}),
        encoding="utf-8",
    )
    dc.register("seojae-mcp")

    data = read(config)
    assert data["preferences"] == {"theme": "dark"}
    assert data["coworkUserFilesPath"] == "D:/x"


def test_다시_등록하면_경로만_갱신한다(config):
    dc.register("old.exe")
    dc.register("new.exe")
    assert read(config)["mcpServers"]["seojae"]["command"] == "new.exe"


def test_같은_내용이면_파일을_건드리지_않는다(config):
    dc.register("same.exe")
    before = config.stat().st_mtime_ns
    message = dc.register("same.exe")
    assert "이미 등록" in message
    assert config.stat().st_mtime_ns == before


def test_고치기_전에_백업을_남긴다(config):
    config.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}), encoding="utf-8")
    dc.register("seojae-mcp")

    backups = list(config.parent.glob("*.bak"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8"))["mcpServers"] == {
        "other": {"command": "x"}
    }


def test_깨진_JSON이면_멈춘다(config):
    """새로 써버리면 남의 서버 설정이 통째로 사라진다. 그러느니 실패하는 게 낫다."""
    config.write_text('{"mcpServers": {broken', encoding="utf-8")

    with pytest.raises(dc.ConfigError):
        dc.register("seojae-mcp")

    assert config.read_text(encoding="utf-8") == '{"mcpServers": {broken'


def test_빈_파일은_새로_시작해도_된다(config):
    config.write_text("   \n", encoding="utf-8")
    dc.register("seojae-mcp")
    assert "seojae" in read(config)["mcpServers"]


def test_해제하면_우리_것만_지운다(config):
    config.write_text(
        json.dumps({"mcpServers": {"filesystem": {"command": "npx"}}}), encoding="utf-8"
    )
    dc.register("seojae-mcp")
    dc.unregister()

    servers = read(config)["mcpServers"]
    assert servers == {"filesystem": {"command": "npx"}}


def test_등록된_적_없으면_해제는_조용히_넘어간다(config):
    assert "없다" in dc.unregister()


def test_루트_경로를_박아두지_않는다(config):
    """서버가 앱과 같은 설정을 보고 서재를 찾는다. 여기 경로를 넣으면 두 곳이 어긋난다."""
    dc.register("seojae-mcp.exe")
    entry = read(config)["mcpServers"]["seojae"]
    assert "args" not in entry


def test_등록된_명령을_읽어온다(config):
    assert dc.registered_command() is None
    dc.register("seojae-mcp.exe")
    assert dc.registered_command() == "seojae-mcp.exe"


def test_BOM이_붙어_있어도_읽는다(config):
    """메모장이나 PowerShell Out-File 로 고치면 BOM이 붙는다. 실제로 겪었다."""
    config.write_text(
        json.dumps({"mcpServers": {"filesystem": {"command": "npx"}}}), encoding="utf-8-sig"
    )
    dc.register("seojae-mcp")

    servers = read(config)["mcpServers"]
    assert servers["filesystem"] == {"command": "npx"}
    assert "seojae" in servers
