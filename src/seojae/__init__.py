"""서재 (Seojae) — 로컬 RAG MCP 서버."""

#: 이 프로젝트 버전의 **유일한 출처**다.
#:
#: pyproject.toml 은 hatchling 으로 여기를 읽는다(어긋날 수 없다).
#: 파이썬을 읽지 못하는 두 곳(mcpb/manifest.json, installer/seojae.iss)은
#: `python scripts/bump_version.py <새 버전>` 이 같이 고치고,
#: tests/test_version.py 가 어긋나면 잡는다.
__version__ = "0.2.0"
