"""첫 실행 안내.

설치하고 아이콘을 처음 눌렀을 때 뭘 해야 하는지 말해주는 화면이다.
**책장에 문서가 하나라도 꽂히면 저절로 사라진다** — 그래서 "다시 보지 않기"가 없다.
그 판단이 어긋나면 안내가 영영 남거나 첫 실행에 아예 안 뜬다.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from seojae.bootstrap import EXAMPLE_SHELF, make_skeleton
from seojae.index import index_root, open_db
from seojae.paths import INBOX_DIRNAME
from seojae.search import shelved_total
from seojae.web import create_app


@pytest.fixture
def 빈서재(tmp_path):
    """첫 실행에 만들어지는 그대로의 서재. 골격만 있고 문서는 없다."""
    make_skeleton(tmp_path)
    conn = open_db(tmp_path, check_same_thread=False)
    index_root(tmp_path, conn)
    with TestClient(create_app(tmp_path, conn, threading.Lock())) as c:
        yield c, tmp_path, conn
    conn.close()


class Test빈_서재_판정:
    def test_골격만_있으면_0이다(self, 빈서재):
        """예시책장/README.md 와 _미분류/안내문이 세어지면 안내가 바로 사라진다."""
        _, _, conn = 빈서재
        assert shelved_total(conn) == 0

    def test_그래도_문서는_잡혀_있다(self, 빈서재):
        """0인 것은 '꽂힌 문서'가 없다는 뜻이지 색인이 비었다는 뜻이 아니다."""
        c, _, _ = 빈서재
        assert c.get("/api/status").json()["document_count"] > 0

    def test_문서_하나가_꽂히면_1이_된다(self, 빈서재):
        c, root, conn = 빈서재
        shelf = root / "업무규정"
        shelf.mkdir()
        (shelf / "취업규칙.md").write_text("# 취업규칙\n연차는 15일이다.\n", encoding="utf-8")
        index_root(root, conn)

        assert shelved_total(conn) == 1
        assert c.get("/api/status").json()["shelved_count"] == 1

    def test_미분류에_넣는_것으로는_안_된다(self, 빈서재):
        """아직 책장에 안 꽂혔으므로 안내는 계속 떠 있어야 한다."""
        c, root, conn = 빈서재
        (root / INBOX_DIRNAME / "던져둔것.md").write_text("# 메모\n", encoding="utf-8")
        index_root(root, conn)

        assert c.get("/api/status").json()["shelved_count"] == 0

    def test_README만_써도_안_된다(self, 빈서재):
        """책장 설명을 쓴 것은 문서를 꽂은 것이 아니다."""
        c, root, conn = 빈서재
        (root / EXAMPLE_SHELF / "README.md").write_text(
            "---\nname: 예시책장\ndescription: 고쳐 썼다\n---\n\n# 예시책장\n본문\n",
            encoding="utf-8",
        )
        index_root(root, conn)

        assert c.get("/api/status").json()["shelved_count"] == 0


class Test안내가_쓰는_값:
    def test_상태에_전부_실려_온다(self, 빈서재):
        c, root, _ = 빈서재
        s = c.get("/api/status").json()

        assert s["shelved_count"] == 0
        assert s["root"] == str(root)
        assert s["inbox_dirname"] == INBOX_DIRNAME
        assert s["format_count"] > 0
        assert s["extension_count"] >= s["format_count"]
        assert isinstance(s["claude_registered"], bool)

    def test_형식_수를_문서에_적지_않고_센다(self, 빈서재):
        """숫자를 화면에 박아두면 형식을 늘릴 때마다 어긋난다."""
        from seojae.parsers import describe_formats, supported_extensions

        c, _, _ = 빈서재
        s = c.get("/api/status").json()
        assert s["format_count"] == len(describe_formats())
        assert s["extension_count"] == len(supported_extensions())


class Test서재_폴더_열기:
    def test_루트를_연다(self, 빈서재, monkeypatch):
        c, root, _ = 빈서재
        열린것 = []
        monkeypatch.setattr("seojae.web._open_in_file_manager", 열린것.append)

        r = c.post("/api/open-root")
        assert r.status_code == 200
        assert 열린것 == [root]

    def test_경로를_인자로_받지_않는다(self, 빈서재, monkeypatch):
        """받으면 로컬 서버가 아무 폴더나 여는 수단이 된다."""
        c, root, _ = 빈서재
        열린것 = []
        monkeypatch.setattr("seojae.web._open_in_file_manager", 열린것.append)

        c.post("/api/open-root", json={"path": "C:/Windows"})
        assert 열린것 == [root]

    def test_다른_사이트에서_오면_막힌다(self, 빈서재):
        c, _, _ = 빈서재
        r = c.post("/api/open-root", headers={"Origin": "https://evil.example.com"})
        assert r.status_code == 403

    def test_열지_못하면_오류를_알린다(self, 빈서재, monkeypatch):
        def 실패(_):
            raise OSError("탐색기가 없다")

        c, _, _ = 빈서재
        monkeypatch.setattr("seojae.web._open_in_file_manager", 실패)
        assert "error" in c.post("/api/open-root").json()
