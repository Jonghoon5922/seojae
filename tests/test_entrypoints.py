"""진입점이 한글을 찍다 죽지 않는지.

윈도우 콘솔·파이프의 기본 인코딩은 cp949다. `—` 같은 문자에서 UnicodeEncodeError로
죽는다. 이 버그를 세 번 겪었다.

1. `seojae --help` 를 파이프로 넘길 때
2. 설치 프로그램이 `register` 를 숨겨서 실행할 때 (그게 곧 파이프다)
3. `seojae-mcp.exe --help` — CLI를 import 하기 전에 찍어서, cli.py 의 교정이
   아직 안 걸린 상태였다. **하필 안내를 보려고 치는 명령에서 죽었다.**

진입점을 새로 만들 때마다 되살아나므로 여기서 막는다.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / "installer" / "mcp_launcher.py"


def 파이프로_실행(args: list[str]) -> subprocess.CompletedProcess:
    """PYTHONIOENCODING 을 지우고 파이프로 받는다 — 실제로 죽던 조건 그대로."""
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    env.pop("PYTHONIOENCODING", None)
    return subprocess.run(
        args, capture_output=True, cwd=ROOT, env=env, timeout=90
    )


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_MCP_진입점_도움말이_안_죽는다(flag):
    r = 파이프로_실행([sys.executable, str(LAUNCHER), flag])
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    assert b"seojae-mcp" in r.stdout


def test_CLI_도움말이_안_죽는다():
    r = 파이프로_실행([sys.executable, "-m", "seojae.cli", "--help"])
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")


def test_연결_목록이_안_죽는다():
    """표에 한글이 잔뜩 들어간다. 설치 직후 사람이 제일 먼저 칠 만한 명령이다."""
    r = 파이프로_실행([sys.executable, "-m", "seojae.cli", "mcp-list"])
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")


def test_진입점이_전부_인코딩을_교정한다():
    """새 진입점을 만들면서 빠뜨리는 것을 막는다. 세 번 겪었다."""
    for path in (ROOT / "src" / "seojae" / "cli.py", LAUNCHER):
        source = path.read_text(encoding="utf-8")
        assert 'reconfigure(encoding="utf-8"' in source, f"{path.name} 에 교정이 없다"


class Test도움말이_거짓말하지_않는다:
    """`--commands` 가 보여주는 명령은 실제로 실행돼야 한다.

    `ui` 를 보여주면서 정작 실행하면 서재 폴더 이름으로 넘겨버렸다.
    도움말에 있는데 안 되는 것이 제일 나쁘다.
    """

    def _launcher(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("mcp_launcher", LAUNCHER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_CLI_명령을_전부_알고_있다(self):
        launcher = self._launcher()
        names = launcher.cli_commands()
        # 실제로 있는 것들. 하나라도 빠지면 그 명령이 서재 폴더로 오인된다.
        for expected in ("ui", "status", "readings", "serve", "mcp-list"):
            assert expected in names, f"{expected} 를 넘기지 못한다"

    def test_별칭도_전부_실재하는_명령이다(self):
        launcher = self._launcher()
        names = launcher.cli_commands()
        for alias, real in launcher.ALIASES.items():
            assert real in names, f"별칭 {alias} 이 없는 명령({real})을 가리킨다"

    def test_안내문에_적은_명령이_실제로_있다(self):
        """USAGE 에 적어둔 것과 실제가 어긋나는 것을 막는다."""
        launcher = self._launcher()
        names = launcher.cli_commands() | set(launcher.ALIASES)
        for word in ("mcp-list", "register", "unregister"):
            assert word in launcher.USAGE, f"안내문에 {word} 가 없다"
            assert word in names, f"안내문의 {word} 를 실행할 수 없다"
