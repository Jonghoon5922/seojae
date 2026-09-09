"""대출 기록 — 누가 언제 왜 무엇을 꺼내 갔는지."""

from __future__ import annotations

import pytest

from seojae import ledger
from seojae.index import open_db
from seojae.paths import INBOX_DIRNAME


@pytest.fixture
def conn(tmp_path):
    c = open_db(tmp_path)
    yield c
    c.close()


def test_한_건_적고_읽는다(conn):
    ledger.record(
        conn,
        tool="search",
        client="Claude Desktop",
        query="연차 휴가",
        collection="업무규정",
        hits=3,
        docs=["업무규정/취업규칙.md", "업무규정/휴가.md"],
    )
    (r,) = ledger.readings(conn)
    assert r.client == "Claude Desktop"
    assert r.query == "연차 휴가"
    assert r.docs == ["업무규정/취업규칙.md", "업무규정/휴가.md"]
    assert r.hits == 3


def test_최근_것이_먼저_온다(conn):
    for q in ("첫째", "둘째", "셋째"):
        ledger.record(conn, tool="search", query=q)
    assert [r.query for r in ledger.readings(conn)] == ["셋째", "둘째", "첫째"]


def test_기록이_실패해도_예외를_안_던진다(conn):
    """대출 카드를 못 쓴다고 책을 안 빌려주지는 않는다."""
    conn.execute("DROP TABLE readings")
    ledger.record(conn, tool="search", query="아무거나")  # 터지면 실패


class Test헛걸음:
    """hits=0 만으로는 헛걸음이 안 잡힌다. BM25는 단어 하나만 걸려도 뭔가를 돌려준다."""

    def test_결과가_있어도_힌트가_붙으면_헛걸음(self, conn):
        ledger.record(
            conn, tool="search", query="블록체인 합의", hits=3,
            note="이 서재가 쓰지 않는 말: 블록체인, 합의",
        )
        assert [r.query for r in ledger.readings(conn, only_empty=True)] == ["블록체인 합의"]

    def test_결과가_없어도_헛걸음(self, conn):
        ledger.record(conn, tool="search", query="아무것도 없는 말", hits=0)
        assert len(ledger.readings(conn, only_empty=True)) == 1

    def test_잘_찾은_것은_헛걸음이_아니다(self, conn):
        ledger.record(conn, tool="search", query="예외 처리", hits=3, note="")
        assert ledger.readings(conn, only_empty=True) == []

    def test_검색어가_없는_기록은_세지_않는다(self, conn):
        """책장을 열어본 것은 헛걸음일 수 없다. 찾던 말이 없으니까."""
        ledger.record(conn, tool="get_collection_guide", collection="업무규정", hits=0)
        assert ledger.readings(conn, only_empty=True) == []


class Test안_꺼내진_문서:
    def _문서(self, conn, path, collection):
        conn.execute(
            "INSERT INTO documents(path, collection, title, status, mtime, size, hash, "
            "indexed_at, pages, terms) VALUES (?, ?, ?, 'ok', 0, 0, '', '', 0, '')",
            (path, collection, path),
        )
        conn.commit()

    def test_건네준_적_없는_것만_돌려준다(self, conn):
        self._문서(conn, "책장/읽힌.md", "책장")
        self._문서(conn, "책장/안읽힌.md", "책장")
        ledger.record(conn, tool="search", query="x", hits=1, docs=["책장/읽힌.md"])

        assert ledger.unread_documents(conn) == ["책장/안읽힌.md"]

    def test_미분류는_세지_않는다(self, conn):
        """아직 책장에 안 꽂힌 것을 '안 읽힌 책'이라 부를 수 없다."""
        self._문서(conn, f"{INBOX_DIRNAME}/던져둔것.md", INBOX_DIRNAME)
        self._문서(conn, "책장/문서.md", "책장")

        assert ledger.unread_documents(conn) == ["책장/문서.md"]


class Test클라이언트_이름:
    @pytest.mark.parametrize(
        "raw, version, expected",
        [
            ("claude-ai", "0.14.2", "Claude Desktop 0.14.2"),
            ("claude-code", None, "Claude Code"),
            ("낯선도구", "1.0", "낯선도구 1.0"),
            (None, None, ledger.UNKNOWN_CLIENT),
            ("", None, ledger.UNKNOWN_CLIENT),
        ],
    )
    def test_읽을_수_있는_이름으로(self, raw, version, expected):
        assert ledger.label_client(raw, version) == expected


def test_요약(conn):
    ledger.record(conn, tool="search", client="Claude Desktop", query="찾음", hits=2)
    ledger.record(conn, tool="search", client="Claude Desktop", query="못찾음", hits=0)
    ledger.record(conn, tool="search", client=ledger.APP_CLIENT, query="앱에서", hits=1)

    s = ledger.summary(conn)
    assert s["total"] == 3
    assert s["empty"] == 1
    assert s["clients"][0] == {"name": "Claude Desktop", "count": 2}


def test_무한정_쌓이지_않는다(conn, monkeypatch):
    monkeypatch.setattr(ledger, "KEEP_ROWS", 10)
    monkeypatch.setattr(ledger, "_PRUNE_EVERY", 5)
    for i in range(40):
        ledger.record(conn, tool="search", query=f"검색{i}")

    남은수 = conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
    assert 남은수 <= 15  # 가지치기 주기 때문에 정확히 10은 아니다
    # 최근 것은 살아 있어야 한다
    assert ledger.readings(conn, limit=1)[0].query == "검색39"
