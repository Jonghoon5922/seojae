"""루트 경계와 경로 안전 규칙.

서재는 실행 시 지정한 루트 폴더 1개 바깥을 어떤 경우에도 읽거나 쓰지 않는다.
경로를 다루는 코드는 반드시 이 모듈을 거친다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from .parsers import SUPPORTED_EXTS  # noqa: F401  (등록기가 유일한 출처다)

INBOX_DIRNAME = "_inbox"
DATA_DIRNAME = ".seojae"
DB_FILENAME = "index.db"

# 소스 폴더를 통째로 넣으면 색인이 터진다. 이름만 보고 통째로 건너뛴다.
SKIP_DIRNAMES = frozenset(
    {
        "node_modules", "bower_components", "vendor",
        "venv", ".venv", "env", "__pycache__", ".mypy_cache", ".pytest_cache",
        "target", "build", "dist", "out", "bin", "obj",
        ".gradle", ".idea", ".vscode", ".terraform",
        "coverage", ".next", ".nuxt", ".svelte-kit",
    }
)

# 컬렉션으로 취급하지 않는 루트 직속 폴더
RESERVED_DIRNAMES = {INBOX_DIRNAME, DATA_DIRNAME}


class OutsideRootError(Exception):
    """루트 밖 경로에 접근하려 할 때."""


def resolve_root(root: str | Path) -> Path:
    p = Path(root).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"루트 폴더가 없다: {p}")
    if not p.is_dir():
        raise NotADirectoryError(f"루트는 폴더여야 한다: {p}")
    return p


def data_dir(root: Path) -> Path:
    return root / DATA_DIRNAME


def db_path(root: Path) -> Path:
    return data_dir(root) / DB_FILENAME


def inbox_dir(root: Path) -> Path:
    return root / INBOX_DIRNAME


def is_inside(root: Path, path: Path) -> bool:
    """path가 root 안에 있는지. 심볼릭 링크를 푼 실제 경로로 판단한다."""
    try:
        resolved = path.resolve()
    except OSError:
        return False
    return resolved == root or root in resolved.parents


def ensure_inside(root: Path, path: Path) -> Path:
    """루트 안이면 해석된 경로를 돌려주고, 밖이면 거부한다."""
    resolved = Path(path).expanduser()
    if not resolved.is_absolute():
        resolved = root / resolved
    if not is_inside(root, resolved):
        raise OutsideRootError(f"루트 밖 경로는 다루지 않는다: {path}")
    return resolved.resolve()


def is_hidden(path: Path) -> bool:
    return path.name.startswith(".")


def collection_dirs(root: Path) -> list[Path]:
    """루트 직속 하위 폴더 = 컬렉션. 예약 폴더와 숨김 폴더는 제외."""
    out = []
    for p in sorted(root.iterdir()):
        if not p.is_dir():
            continue
        if p.name in RESERVED_DIRNAMES or is_hidden(p):
            continue
        if p.is_symlink() and not is_inside(root, p):
            continue
        out.append(p)
    return out


def walk_files(base: Path, root: Path) -> Iterator[Path]:
    """base 아래 색인 대상 파일을 순회한다. 숨김·루트 밖 링크는 건너뛴다."""
    if not base.is_dir():
        return
    for p in sorted(base.iterdir()):
        if is_hidden(p):
            continue
        if p.is_symlink() and not is_inside(root, p):
            continue
        if p.is_dir():
            if p.name in SKIP_DIRNAMES:
                continue  # node_modules, target, .venv …
            yield from walk_files(p, root)
        elif p.suffix.lower() in SUPPORTED_EXTS:
            yield p


def rel(root: Path, path: Path) -> str:
    """DB에 저장하는 루트 기준 상대 경로 (구분자는 /로 통일).

    양쪽 다 resolve한다. 루트만 8.3 단축 경로(`NB-240~1`)거나 링크면
    한쪽만 풀렸을 때 relative_to가 터진다.
    """
    return path.resolve().relative_to(root.resolve()).as_posix()


def inbox_files(root: Path) -> list[Path]:
    """미분류 파일: _inbox 아래 전부 + 루트 직속 파일."""
    files = list(walk_files(inbox_dir(root), root))
    for p in sorted(root.iterdir()):
        if p.is_file() and not is_hidden(p) and p.suffix.lower() in SUPPORTED_EXTS:
            files.append(p)
    return files
