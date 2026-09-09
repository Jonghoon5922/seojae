"""대출 기록 — 누가 언제 왜 무엇을 꺼내 갔는지.

도서관의 대출 카드에 해당한다. 다른 점은 빌려가는 쪽이 사람이 아니라 Claude라는 것.

| 칸 | 담기는 것 | 어디서 오나 |
|---|---|---|
| 누가 | `Claude Desktop`, `Claude Code`, `앱` | MCP `initialize` 의 clientInfo |
| 언제 | 시각 | 서버 시계 |
| 왜 | `"연차 휴가 며칠"` | 검색어 그 자체 |
| 무엇을 | 건네준 문서 경로 | 검색 결과 |

**"왜"가 검색어인 이유.** 이 코드는 LLM을 부르지 않으므로 Claude에게 의도를 물어볼
길이 없다. 대신 어떤 말로 찾았는지는 그대로 남는다. 사서 입장에서 그것이 "왜 빌려
갔는지"에 가장 가까운 기록이다.

기록이 쌓이면 서재를 고칠 재료가 된다.

- **빈손 기록**(hits=0) — 서재에 없는 주제이거나 말이 어긋난 것. 뭘 더 채울지 알려준다
- **한 번도 안 나온 문서** — 정리 대상
- **자주 열린 책장** — 그 책장 설명이 잘 쓰였다는 뜻

기록하다 실패해도 검색은 계속되어야 한다. 대출 카드를 못 쓴다고 책을 안 빌려주지는
않는다. 그래서 이 파일의 쓰기는 전부 예외를 삼킨다.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

#: 기록이 무한정 쌓이지 않게 한다. 넘으면 오래된 것부터 지운다.
KEEP_ROWS = 5_000
_PRUNE_EVERY = 200

#: 사람에게 보여줄 이름. 클라이언트가 밝히는 이름은 기계용이라 그대로 두면 읽기 나쁘다.
_CLIENT_LABELS = {
    "claude-ai": "Claude Desktop",
    "claude-code": "Claude Code",
    "cline": "Cline",
    "continue": "Continue",
}

UNKNOWN_CLIENT = "알 수 없음"
APP_CLIENT = "앱"


@dataclass(frozen=True)
class Reading:
    id: int
    ts: str
    client: str
    tool: str
    query: str
    collection: str
    hits: int
    docs: list[str]
    note: str


def label_client(name: str | None, version: str | None = None) -> str:
    """클라이언트가 밝힌 이름을 사람이 읽을 이름으로."""
    if not name:
        return UNKNOWN_CLIENT
    label = _CLIENT_LABELS.get(name.lower(), name)
    return f"{label} {version}" if version else label


def record(
    conn: sqlite3.Connection,
    *,
    tool: str,
    client: str = UNKNOWN_CLIENT,
    query: str = "",
    collection: str = "",
    hits: int = 0,
    docs: list[str] | None = None,
    note: str = "",
) -> None:
    """한 건 적는다. 실패해도 조용히 넘어간다 — 기록 때문에 검색이 죽으면 안 된다."""
    try:
        cur = conn.execute(
            "INSERT INTO readings(ts, client, tool, query, collection, hits, docs, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now().isoformat(timespec="seconds"),
                client,
                tool,
                query,
                collection,
                hits,
                "\n".join(docs or []),
                note,
            ),
        )
        if cur.lastrowid and cur.lastrowid % _PRUNE_EVERY == 0:
            _prune(conn)
        conn.commit()
    except sqlite3.DatabaseError:
        pass


def _prune(conn: sqlite3.Connection) -> None:
    conn.execute(
        "DELETE FROM readings WHERE id <= "
        "(SELECT MAX(id) FROM readings) - ?",
        (KEEP_ROWS,),
    )


def _row(row: sqlite3.Row) -> Reading:
    return Reading(
        id=row["id"],
        ts=row["ts"],
        client=row["client"],
        tool=row["tool"],
        query=row["query"],
        collection=row["collection"],
        hits=row["hits"],
        docs=[d for d in row["docs"].split("\n") if d],
        note=row["note"],
    )


#: 헛걸음의 정의. hits=0 만으로는 안 잡힌다 — BM25는 단어 하나만 걸려도 뭔가를
#: 돌려주므로 "블록체인 합의 알고리즘" 같은 엉뚱한 검색도 결과가 3건 나온다.
#: 진짜 신호는 재검색 힌트다. 이 서재가 쓰지 않는 말이 섞였을 때만 붙는다.
_WASTED = "query <> '' AND (hits = 0 OR note <> '')"


def readings(
    conn: sqlite3.Connection, limit: int = 100, only_empty: bool = False
) -> list[Reading]:
    """최근 기록. `only_empty` 면 헛걸음만 — 서재에 뭘 채울지 보여준다."""
    where = f"WHERE {_WASTED}" if only_empty else ""
    rows = conn.execute(
        f"SELECT * FROM readings {where} ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [_row(r) for r in rows]


def unread_documents(conn: sqlite3.Connection, limit: int = 50) -> list[str]:
    """한 번도 건네진 적 없는 문서. 아무도 안 찾은 책이다.

    미분류는 세지 않는다. 아직 책장에 안 꽂힌 것을 "안 읽힌 책"이라 부를 수 없다.
    """
    from .paths import INBOX_DIRNAME

    given = set()
    for row in conn.execute("SELECT docs FROM readings WHERE docs <> ''"):
        given.update(d for d in row["docs"].split(chr(10)) if d)

    rows = conn.execute(
        "SELECT path FROM documents WHERE status = 'ok' AND collection <> ? ORDER BY path",
        (INBOX_DIRNAME,),
    ).fetchall()
    return [r["path"] for r in rows if r["path"] not in given][:limit]


def summary(conn: sqlite3.Connection) -> dict:
    """기록 요약. 기록 화면 위에 한 줄로 보여준다."""
    row = conn.execute(
        "SELECT COUNT(*) AS total, "
        f"SUM(CASE WHEN {_WASTED} THEN 1 ELSE 0 END) AS empty, "
        "MIN(ts) AS since FROM readings"
    ).fetchone()
    clients = conn.execute(
        "SELECT client, COUNT(*) AS n FROM readings GROUP BY client ORDER BY n DESC"
    ).fetchall()
    return {
        "total": row["total"] or 0,
        "empty": row["empty"] or 0,
        "since": row["since"] or "",
        "clients": [{"name": c["client"], "count": c["n"]} for c in clients],
    }
