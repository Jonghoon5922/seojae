"""버전이 네 곳에서 어긋나지 않게 지킨다.

버전의 유일한 출처는 `src/seojae/__init__.py` 다. pyproject.toml 은 hatchling 이
거기를 읽으므로 어긋날 수 없다. 문제는 파이썬을 못 읽는 두 곳이다.

    mcpb/manifest.json     JSON
    installer/seojae.iss   Inno Setup 전처리기

이 둘은 숫자를 그대로 들고 있을 수밖에 없어서, 손으로 올리다 보면 언젠가 하나를
빠뜨린다. 그때 이 테스트가 잡는다. 고치는 방법은 한 줄이다.

    python scripts/bump_version.py 0.2.0
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import bump_version  # noqa: E402

from seojae import __version__  # noqa: E402


def test_모든_파일이_같은_버전을_들고_있다():
    found = bump_version.current()
    assert len(set(found.values())) == 1, (
        "버전이 어긋났다:\n"
        + "\n".join(f"  {v:10} {p}" for p, v in found.items())
        + "\n\n  python scripts/bump_version.py <버전>"
    )


def test_패키지_버전이_그_값이다():
    assert bump_version.current()["src/seojae/__init__.py"] == __version__


def test_pyproject_는_숫자를_들고_있지_않다():
    """들고 있으면 그것부터 어긋난다. hatchling 이 __init__.py 를 읽어야 한다."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in text
    assert 'path = "src/seojae/__init__.py"' in text


@pytest.mark.parametrize("bad", ["0.2", "v0.2.0", "0.2.0-rc1", "이상한거", ""])
def test_형식이_아니면_거부한다(bad, capsys):
    assert bump_version.main([bad]) == 2


def test_check_는_고치지_않는다():
    before = bump_version.INIT.read_text(encoding="utf-8")
    bump_version.main(["--check"])
    assert bump_version.INIT.read_text(encoding="utf-8") == before
