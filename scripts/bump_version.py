"""버전을 한 번에 올린다.

버전의 유일한 출처는 `src/seojae/__init__.py` 다. pyproject.toml 은 hatchling 으로
거기를 읽으므로 어긋날 수 없다.

문제는 파이썬을 읽지 못하는 두 곳이다.

    mcpb/manifest.json     JSON
    installer/seojae.iss   Inno Setup 전처리기

이 둘은 숫자를 그대로 들고 있을 수밖에 없다. 그래서 손으로 네 번 고치는 대신
이 스크립트가 한 번에 고치고, `tests/test_version.py` 가 어긋나면 잡는다.

    python scripts/bump_version.py 0.2.0
    python scripts/bump_version.py --check      # 고치지 않고 확인만

버전을 올린 뒤에는 실행 파일과 설치 파일을 다시 만들어야 한다. 설치 파일 이름에
버전이 들어가므로(`seojae-setup-0.2.0.exe`) 안 만들면 옛날 파일이 남는다.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

INIT = ROOT / "src" / "seojae" / "__init__.py"
MANIFEST = ROOT / "mcpb" / "manifest.json"
ISS = ROOT / "installer" / "seojae.iss"

_INIT_PATTERN = re.compile(r'^__version__ = "([^"]+)"$', re.MULTILINE)
_ISS_PATTERN = re.compile(r'^#define AppVersion "([^"]+)"$', re.MULTILINE)

VERSION_FORMAT = re.compile(r"^\d+\.\d+\.\d+$")


def current() -> dict[str, str]:
    """지금 각 파일이 들고 있는 버전. 어긋나 있으면 여기서 드러난다."""
    found: dict[str, str] = {}

    match = _INIT_PATTERN.search(INIT.read_text(encoding="utf-8"))
    found["src/seojae/__init__.py"] = match.group(1) if match else "?"

    if MANIFEST.is_file():
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        found["mcpb/manifest.json"] = data.get("version", "?")

    if ISS.is_file():
        match = _ISS_PATTERN.search(ISS.read_text(encoding="utf-8"))
        found["installer/seojae.iss"] = match.group(1) if match else "?"

    return found


def write(version: str) -> None:
    text = INIT.read_text(encoding="utf-8")
    INIT.write_text(
        _INIT_PATTERN.sub(f'__version__ = "{version}"', text, count=1), encoding="utf-8"
    )

    if MANIFEST.is_file():
        # 줄 순서를 지키려고 json.dump 대신 그 줄만 바꾼다. 통째로 다시 쓰면
        # 사람이 정렬해둔 순서가 흐트러져 diff가 커진다.
        text = MANIFEST.read_text(encoding="utf-8")
        text = re.sub(r'("version":\s*)"[^"]+"', rf'\1"{version}"', text, count=1)
        MANIFEST.write_text(text, encoding="utf-8")

    if ISS.is_file():
        text = ISS.read_text(encoding="utf-8")
        ISS.write_text(
            _ISS_PATTERN.sub(f'#define AppVersion "{version}"', text, count=1),
            encoding="utf-8",
        )


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help"}:
        print(__doc__)
        return 0

    found = current()

    if argv[0] == "--check":
        for path, version in found.items():
            print(f"  {version:10} {path}")
        if len(set(found.values())) == 1:
            print("\n전부 같다.")
            return 0
        print("\n어긋나 있다. `python scripts/bump_version.py <버전>` 으로 맞춰라.")
        return 1

    version = argv[0]
    if not VERSION_FORMAT.match(version):
        print(f"버전 형식이 아니다: {version} (예: 0.2.0)", file=sys.stderr)
        return 2

    write(version)
    for path, was in found.items():
        print(f"  {was} → {version}  {path}")
    print("\n실행 파일과 설치 파일을 다시 만들어야 한다:")
    print("  .venv/Scripts/pyinstaller.exe installer/seojae.spec --noconfirm --distpath dist/app")
    print("  ISCC.exe installer/seojae.iss")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
