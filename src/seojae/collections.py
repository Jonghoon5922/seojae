"""컬렉션 정의.

루트 직속 폴더 하나가 컬렉션 하나. 정의는 그 폴더의 README.md 프론트매터가 갖는다.
description은 "어떤 질문에 이 컬렉션을 써야 하는지"이고, Claude의 라우팅 근거가 된다.
README가 없으면 폴더명·파일명·헤딩으로 임시 설명을 만든다(동작은 항상 되게).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .parsers.markdown import strip_frontmatter
from .parsers.plain import read_text
from .paths import INBOX_DIRNAME, walk_files

README_NAMES = ("README.md", "readme.md", "Readme.md", "README.markdown")

_HEADING_RE = re.compile(r"^#{1,3}\s+(.+?)\s*#*$", re.MULTILINE)


@dataclass
class CollectionInfo:
    dirname: str  # 폴더명 = 컬렉션 id
    name: str
    description: str
    tags: list[str] = field(default_factory=list)
    updated: str = ""
    has_readme: bool = False
    body: str = ""  # README 본문 (검색 대상, 약간 가중)
    readme_path: Path | None = None

    @property
    def is_inbox(self) -> bool:
        return self.dirname == INBOX_DIRNAME


def find_readme(directory: Path) -> Path | None:
    for name in README_NAMES:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


def _auto_description(directory: Path, root: Path, limit: int = 12) -> str:
    """README가 없을 때 쓰는 임시 설명. 파일명과 상위 헤딩을 모은다."""
    names: list[str] = []
    headings: list[str] = []
    for path in walk_files(directory, root):
        if len(names) < limit:
            names.append(path.stem)
        if path.suffix.lower() in {".md", ".markdown"} and len(headings) < limit:
            try:
                for m in _HEADING_RE.finditer(read_text(path)):
                    headings.append(m.group(1).strip())
                    if len(headings) >= limit:
                        break
            except OSError:
                continue

    parts = [f"{directory.name} 폴더의 문서 모음"]
    if names:
        parts.append("파일: " + ", ".join(names[:limit]))
    if headings:
        parts.append("주제: " + ", ".join(headings[:limit]))
    parts.append("(README.md가 없어 자동 생성한 설명. 정확한 라우팅을 원하면 README.md를 추가할 것)")
    return " / ".join(parts)


def load_collection(directory: Path, root: Path) -> CollectionInfo:
    readme = find_readme(directory)
    if readme is None:
        return CollectionInfo(
            dirname=directory.name,
            name=directory.name,
            description=_auto_description(directory, root),
            has_readme=False,
        )

    raw = read_text(readme)
    front_raw, body = strip_frontmatter(raw)

    meta: dict = {}
    if front_raw:
        try:
            loaded = yaml.safe_load(front_raw)
            if isinstance(loaded, dict):
                meta = loaded
        except yaml.YAMLError:
            meta = {}

    tags = meta.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    tags = [str(t) for t in tags]

    description = str(meta.get("description") or "").strip()
    if not description:
        description = _auto_description(directory, root)

    updated = meta.get("updated")

    return CollectionInfo(
        dirname=directory.name,
        name=str(meta.get("name") or directory.name).strip(),
        description=description,
        tags=tags,
        updated=str(updated) if updated else "",
        has_readme=True,
        body=body.strip(),
        readme_path=readme,
    )
