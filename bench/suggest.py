"""서재를 보고 시나리오 뼈대를 만든다.

    python bench/suggest.py "C:/Users/.../Documents/서재" > bench/scenarios.yaml

**도구가 네 질문을 대신 지어낼 수는 없다.** 앞서 그렇게 해봤다가 `001 조회 dbio`
같은 것이 나왔다 — 자주 나오는 낱말을 이어 붙였을 뿐 아무도 그렇게 묻지 않는다.

그래서 이 도구가 하는 일은 셋이다.

1. **책장 설명(README)에서 주제를 뽑는다.** 거기엔 "이 책장이 어떤 질문에 쓰이는지"가
   사람 말로 적혀 있다. 쉼표로 끊으면 그대로 질문 후보가 된다.
2. **그 후보가 실제로 찾히는지 미리 확인한다.** 안 찾히면 표시해둔다 —
   **설명이 약속한 것을 서재가 실제로는 안 갖고 있다는 뜻**이라 그 자체가 발견이다.
3. **서재가 쓰는 낱말을 주석으로 붙인다.** 네가 질문을 쓸 때 이 어휘 안에서 써야
   찾힌다. 서재에 없는 말로 물으면 헛걸음이 된다.

나머지(대조군, 형식)는 채워준다. **질문은 네가 고쳐라.**
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from seojae.index import open_db  # noqa: E402
from seojae.search import (  # noqa: E402
    collection_terms,
    list_collections,
    search,
    search_hint,
    term_document_counts,
)

#: 어느 서재에도 없을 법한 말. 헛걸음이 제대로 잡히는지 보는 대조군이다.
#: 서재 주제와 겹치면 바꿔라.
CONTROLS = [
    ("블록체인 합의 알고리즘", "이 서재와 아무 상관 없는 주제"),
    ("김치찌개 끓이는 법", "한 낱말도 안 겹칠 때"),
]

#: 설명 끝에 붙는 상투구. 주제가 아니므로 떼어낸다.
_TAIL = re.compile(r"\s*(질문에 사용|에 사용|을 다룬다|를 다룬다|입니다|이다)\.?\s*$")
_SPLIT = re.compile(r"[,·、]|\s+및\s+|\s+그리고\s+")


def topics(description: str) -> list[str]:
    """책장 설명에서 질문 후보를 뽑는다."""
    out: list[str] = []
    for sentence in description.split("."):
        for piece in _SPLIT.split(sentence):
            piece = _TAIL.sub("", piece).strip()
            # 너무 짧으면 낱말 하나라 질문이 안 되고, 너무 길면 문장이다
            if 3 <= len(piece) <= 30 and piece not in out:
                out.append(piece)
    return out


def check(conn, ask: str, collection: str) -> tuple[int, bool]:
    """이 질문이 실제로 찾히는지. (결과 수, 힌트 떴는지)"""
    hits = search(conn, ask, collection=collection, top_k=5)
    counts = term_document_counts(conn, ask, collection)
    return len(hits), bool(search_hint(conn, ask, hits, collection, counts=counts))


def suggest(root: Path) -> str:
    conn = open_db(root)
    shelves = [c for c in list_collections(conn, include_inbox=False) if c.doc_count]

    out = [
        "# 테스트 시나리오",
        "#",
        "# bench/suggest.py 가 만든 뼈대다. **질문은 네가 고쳐라.**",
        "# 책장 설명에서 뽑은 주제라 그럴듯해 보여도, 네가 실제로 물어볼 말은 아닐 수 있다.",
        "#",
        f"# 서재: {root}",
        "",
    ]

    if not shelves:
        out += [
            "# 책장에 꽂힌 문서가 없다. 문서를 넣고 색인한 뒤 다시 돌려라.",
            "#   seojae reindex <폴더>",
            "",
            "scenarios: []",
        ]
        conn.close()
        return "\n".join(out)

    biggest = max(shelves, key=lambda c: c.doc_count)
    out += [
        f"shelf: {biggest.dirname}   # 가장 큰 책장. 다른 책장을 재려면 바꿔라",
        "",
        "scenarios:",
    ]

    무설명 = []
    for shelf in shelves:
        found = topics(shelf.description)
        terms = collection_terms(conn, shelf.dirname, limit=20)

        out += ["", f"  # ── {shelf.dirname} ({shelf.doc_count}건) ──"]
        if terms:
            out += [f"  # 이 책장이 쓰는 말: {', '.join(terms[:15])}"]
            out += ["  # 질문은 이 어휘 안에서 써야 찾힌다."]

        if not found:
            무설명.append(shelf.dirname)
            out += [
                "  #",
                "  # 책장 설명이 비어 있거나 짧아서 주제를 못 뽑았다.",
                "  # README.md 의 description 을 채우면 여기가 채워진다.",
            ]
            continue

        for topic in found[:4]:
            hits, hint = check(conn, topic, shelf.dirname)
            out += ["", f"  - ask: {topic}"]
            if hint or hits == 0:
                out += [
                    "    why: |",
                    "      책장 설명에는 있는데 **실제로는 안 찾힌다**"
                    f" (결과 {hits}건{', 힌트 뜸' if hint else ''}).",
                    "      설명이 약속한 것을 서재가 안 갖고 있거나, 다른 말로 적혀 있다.",
                    "      설명을 고치든 문서를 채우든 해야 한다.",
                    "    known_gap: 책장 설명과 실제 내용이 어긋남",
                ]
            else:
                out += [
                    f"    why: 책장 설명에 있는 주제. 지금 {hits}건 찾힌다",
                    "    expect:",
                    f"      min_hits: {min(hits, 3)}",
                    "      hint: false",
                ]

    out += ["", "", "  # ── 헛걸음이어야 하는 것 (대조군) ──"]
    for ask, why in CONTROLS:
        hits, hint = check(conn, ask, biggest.dirname)
        out += ["", f"  - ask: {ask}", f"    why: {why}"]
        if hint:
            out += ["    expect:", "      hint: true"]
        else:
            out += [
                "    # 힌트가 안 뜬다. 이 서재와 낱말이 겹친다는 뜻이니 다른 말로 바꿔라.",
                "    expect:",
                "      hint: true",
            ]

    out += [
        "",
        "",
        "  # ── 네 질문 ──",
        "  # 실제로 Claude에게 물어볼 말을 여기 적어라. 위 어휘 목록을 보고 쓰면 잘 찾힌다.",
        "  #",
        "  # - ask: 물어볼 말",
        "  #   why: 왜 이걸 재는지. 나중의 내가 읽는다",
        "  #   expect:",
        "  #     min_hits: 3",
        "  #     hint: false",
        "  #     sources: [규정.md]",
        "",
    ]
    if 무설명:
        out += [
            f"# 설명이 비어 있는 책장: {', '.join(무설명)}",
            "# Claude에게 '○○ 책장 설명 써줘'라고 하면 채워준다.",
            "",
        ]

    conn.close()
    return "\n".join(out)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 0
    root = Path(argv[0])
    if not root.is_dir():
        print(f"그런 폴더가 없다: {root}", file=sys.stderr)
        return 1
    print(suggest(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
