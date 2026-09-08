"""CLI. init은 사용자가 처음 만나는 명령이라 실수해도 파괴적이면 안 된다."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from seojae.cli import app
from seojae.paths import INBOX_DIRNAME

runner = CliRunner()


def test_init_creates_skeleton(tmp_path: Path) -> None:
    root = tmp_path / "내서재"
    result = runner.invoke(app, ["init", str(root)])

    assert result.exit_code == 0
    assert root.is_dir()
    assert (root / INBOX_DIRNAME).is_dir()
    assert (root / "예시책장" / "README.md").is_file()

    readme = (root / "예시책장" / "README.md").read_text(encoding="utf-8")
    assert readme.startswith("---")
    assert "description:" in readme


def test_init_never_overwrites(tmp_path: Path) -> None:
    """이미 쓰던 폴더에 init을 다시 해도 내용이 날아가면 안 된다."""
    root = tmp_path / "내서재"
    (root / "예시책장").mkdir(parents=True)
    keep = root / "예시책장" / "README.md"
    keep.write_text("---\nname: 내가쓴것\ndescription: 건드리지 마라\n---\n", encoding="utf-8")

    result = runner.invoke(app, ["init", str(root)])

    assert result.exit_code == 0
    assert "내가쓴것" in keep.read_text(encoding="utf-8")


def test_init_rejects_file_path(tmp_path: Path) -> None:
    target = tmp_path / "파일.txt"
    target.write_text("x", encoding="utf-8")

    result = runner.invoke(app, ["init", str(target)])
    assert result.exit_code == 1


def test_init_then_reindex_works(tmp_path: Path) -> None:
    """init 직후 바로 색인이 돌아야 한다 (빈 책장이어도 터지지 않게)."""
    root = tmp_path / "내서재"
    runner.invoke(app, ["init", str(root)])

    result = runner.invoke(app, ["reindex", str(root), "--quiet"])
    assert result.exit_code == 0
    assert "색인 완료" in result.output


def test_status_on_missing_root(tmp_path: Path) -> None:
    result = runner.invoke(app, ["status", str(tmp_path / "없는폴더")])
    assert result.exit_code == 1


def test_search_reports_no_results(tmp_path: Path) -> None:
    root = tmp_path / "내서재"
    runner.invoke(app, ["init", str(root)])
    runner.invoke(app, ["reindex", str(root), "--quiet"])

    result = runner.invoke(app, ["search", str(root), "존재하지않는단어열두개"])
    assert result.exit_code == 0
    assert "결과 없음" in result.output
