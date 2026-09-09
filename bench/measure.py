"""서재가 있을 때와 없을 때, Claude 앞에 놓이는 맥락의 크기를 잰다.

    python bench/measure.py testdata/seojae

**이 코드는 LLM을 부르지 않는다.** 그래서 "Claude가 실제로 쓴 토큰"은 잴 수 없다.
대신 잴 수 있는 것이 있다 — **Claude 앞에 놓이는 글자 수**다. 답을 만들려면
그만큼은 읽어야 하므로, 이것이 토큰의 하한이자 가장 정직한 대리 지표다.

세 가지를 나란히 잰다.

    검색만        search 가 돌려준 청크들          싸고 좁다
    검색 + 펼침   그 문서들을 get_document 로 전부  실제로는 이 중간 어딘가다
    서재 없이     답이 든 파일들의 전문             비교 기준

**"서재 없이"는 서재 없는 쪽에 유리하게 잡았다.** 어느 파일을 열어야 하는지 이미
안다고 가정하기 때문이다. 실제로는 578건 중에서 그 파일을 찾는 비용이 더 든다.
그러니 여기 나오는 배수는 실제보다 **작다**.

시나리오는 `bench/scenarios.yaml` 에 있다. 네가 실제로 물어볼 말을 적어라.
지어낸 질문으로 재면 지어낸 숫자가 나온다.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from seojae.index import open_db  # noqa: E402
from seojae.search import (  # noqa: E402
    document_total,
    get_document,
    search,
    search_hint,
    term_document_counts,
)

#: 글자 → 토큰 어림. Claude의 토크나이저는 공개돼 있지 않으므로 추정이다.
#: 한글은 토큰을 많이 먹고 영문·기호는 덜 먹는다. 배수를 볼 때는 어차피
#: 분자·분모에 같은 규칙이 걸리므로 영향이 거의 없다.
KOREAN_CHARS_PER_TOKEN = 1.5
OTHER_CHARS_PER_TOKEN = 4.0


def estimate_tokens(text: str) -> int:
    korean = sum(1 for c in text if "가" <= c <= "힣")
    other = len(text) - korean
    return round(korean / KOREAN_CHARS_PER_TOKEN + other / OTHER_CHARS_PER_TOKEN)


def _shelf_tokens(total_chars: int, sample: str) -> int:
    """서재 전체의 토큰 어림. 전문을 다 들고 세면 메모리를 크게 먹으므로
    표본에서 글자당 토큰 비율만 구해 곱한다."""
    if not sample:
        return 0
    return round(total_chars * estimate_tokens(sample) / len(sample))


def _tool_mix(conn) -> dict:
    """대출 기록에서 실제 사용 비율을 읽는다.

    **이 숫자가 위 두 극단 사이의 어디쯤인지 말해준다.** 검색만으로 끝났으면
    절감이 크고, 매번 문서를 펼쳤으면 절감이 없다. 기록이 없으면 알 수 없다.
    """
    try:
        rows = conn.execute(
            "SELECT tool, COUNT(*) AS n FROM readings GROUP BY tool"
        ).fetchall()
    except Exception:
        return {}
    counts = {r["tool"]: r["n"] for r in rows}
    searches = counts.get("search", 0)
    expands = counts.get("get_document", 0)
    return {
        "searches": searches,
        "expands": expands,
        "expand_rate": round(expands / searches, 2) if searches else None,
    }


@dataclass
class Measured:
    ask: str
    hits: int
    hint: bool
    search_chars: int = 0
    expanded_chars: int = 0
    whole_file_chars: int = 0
    documents: int = 0
    problems: list[str] = field(default_factory=list)
    gap: str = ""  # 알려진 구멍. 실패로 세지 않되 눈에는 띄게 둔다

    @property
    def saving(self) -> float:
        """검색만 했을 때 몇 배 아꼈나. 파일을 못 찾으면 의미 없으므로 0."""
        return self.whole_file_chars / self.search_chars if self.search_chars else 0.0

    @property
    def saving_expanded(self) -> float:
        """문서까지 펼쳤을 때. 이쪽이 실제에 가깝다."""
        return self.whole_file_chars / self.expanded_chars if self.expanded_chars else 0.0


def measure_one(conn, scenario: dict, collection: str | None) -> Measured:
    ask = scenario["ask"]
    hits = search(conn, ask, collection=collection, top_k=5)
    counts = term_document_counts(conn, ask, collection)
    hint = search_hint(conn, ask, hits, collection, counts=counts)

    m = Measured(ask=ask, hits=len(hits), hint=bool(hint))

    # 검색만 — 청크 본문 + 출처. 출처도 Claude가 읽는 글자다
    m.search_chars = sum(len(h.text) + len(h.source) + len(h.location) for h in hits)

    # 검색 + 펼침 / 서재 없이 — 같은 문서 집합을 두 방식으로
    doc_ids = {h.doc_id for h in hits}
    m.documents = len(doc_ids)
    for doc_id in doc_ids:
        doc = get_document(conn, doc_id)
        if doc is None:
            continue
        full = sum(len(s["text"]) for s in doc["sections"])
        m.whole_file_chars += full
    # 펼쳤을 때는 검색 결과 + 문서 전문을 둘 다 본 셈이다
    m.expanded_chars = m.search_chars + m.whole_file_chars

    m.gap = scenario.get("known_gap", "")

    expect = scenario.get("expect") or {}
    if "min_hits" in expect and m.hits < expect["min_hits"]:
        m.problems.append(f"결과 {m.hits}건 (최소 {expect['min_hits']}건이어야 함)")
    if "hint" in expect and m.hint != expect["hint"]:
        m.problems.append(
            "힌트가 떠야 하는데 안 떴다" if expect["hint"] else "힌트가 뜨면 안 되는데 떴다"
        )
    for needle in expect.get("sources", []):
        if not any(needle in h.source for h in hits):
            m.problems.append(f"결과에 '{needle}' 가 없다")

    return m


def run(root: Path, scenarios_path: Path) -> dict:
    spec = yaml.safe_load(scenarios_path.read_text(encoding="utf-8"))
    collection = spec.get("shelf")
    conn = open_db(root)

    results = [measure_one(conn, s, collection) for s in spec["scenarios"]]

    # 서재를 통째로 읽는다면 — 다른 극단. 검색이 없을 때의 상한선이다.
    whole_shelf = conn.execute(
        "SELECT SUM(LENGTH(text)) AS n FROM chunks c "
        "JOIN documents d ON d.id = c.doc_id WHERE d.status = 'ok' AND d.is_inbox = 0"
    ).fetchone()["n"] or 0
    sample = "".join(
        r["text"]
        for r in conn.execute(
            "SELECT text FROM chunks ORDER BY id LIMIT 400"
        ).fetchall()
    )
    mix = _tool_mix(conn)
    total_docs = document_total(conn, collection)
    conn.close()

    # 헛걸음은 평균에서 뺀다. 틀린 답을 싸게 얻은 것은 절감이 아니다.
    answered = [m for m in results if m.hits and not m.hint and not m.gap]
    return {
        "when": datetime.now().isoformat(timespec="seconds"),
        "root": str(root),
        "shelf": collection,
        "document_count": total_docs,
        "whole_shelf_chars": whole_shelf,
        # 전문을 다 들고 어림하면 메모리를 크게 먹는다. 비율만 표본으로 재서 곱한다.
        "whole_shelf_tokens": _shelf_tokens(whole_shelf, sample),
        "scenarios": [asdict(m) for m in results],
        "problems": sum(len(m.problems) for m in results),
        "counted": len(answered),
        "tool_mix": mix,
        "average_saving": (
            sum(m.saving for m in answered) / len(answered) if answered else 0.0
        ),
        "average_saving_expanded": (
            sum(m.saving_expanded for m in answered) / len(answered) if answered else 0.0
        ),
    }


def report(data: dict) -> str:
    lines = [
        f"# 측정 — {data['when'][:16].replace('T', ' ')}",
        "",
        f"서재 `{data['root']}` · 문서 {data['document_count']:,}건 "
        f"· 책장 `{data['shelf'] or '전체'}`",
        "",
        "## 질문마다",
        "",
        "| 질문 | 결과 | 검색만 | 그 파일 전문 | 절감 | |",
        "|---|---:|---:|---:|---:|:--|",
    ]
    for s in data["scenarios"]:
        saving = (
            f"{s['whole_file_chars'] / s['search_chars']:.0f}배"
            if s["search_chars"]
            else "-"
        )
        note = ""
        if s["problems"]:
            note = "**어긋남**"
        elif s["gap"]:
            note = "알려진 구멍"
        elif s["hint"]:
            note = "헛걸음 (평균 제외)"
        lines.append(
            f"| {s['ask']} | {s['hits']} | {s['search_chars']:,} | "
            f"{s['whole_file_chars']:,} | {saving} | {note} |"
        )

    lines += [
        "",
        "글자 수다. `검색만` 은 청크 본문과 출처를 합한 것, `그 파일 전문` 은",
        "그 청크가 든 파일들을 통째로 읽었을 때.",
        "",
        f"**검색만으로 끝났을 때 평균 {data['average_saving']:.1f}배** "
        f"({data['counted']}개 질문. 헛걸음과 알려진 구멍은 뺐다.)",
        "",
        "## 두 극단과 그 사이",
        "",
        "| | Claude가 읽는 양 |",
        "|---|---|",
        f"| 서재 전체를 읽는다면 | {data['whole_shelf_chars']:,}자 "
        f"(어림 {data['whole_shelf_tokens']:,} 토큰) |",
        "| 답이 든 파일만 읽는다면 | 위 표의 `그 파일 전문` |",
        "| 검색 결과만 읽는다면 | 위 표의 `검색만` |",
        "",
        "**문서를 펼치면(`get_document`) 절감은 사라진다.** 검색 결과를 읽고 그 문서를",
        "통째로 다시 읽으면 오히려 검색한 만큼 더 든다. 그러니 실제 절감은",
        "**Claude가 얼마나 자주 펼치느냐**에 달렸다.",
        "",
    ]

    mix = data.get("tool_mix") or {}
    if mix.get("searches"):
        rate = mix["expand_rate"]
        lines += [
            f"대출 기록으로는 검색 {mix['searches']}회에 펼침 {mix['expands']}회 "
            f"(검색 1회당 {rate}번 펼침).",
            "",
        ]
    else:
        lines += [
            "아직 대출 기록이 없어 실제 비율을 모른다. Claude에게 몇 번 물어본 뒤",
            "다시 재면 이 자리에 실제 비율이 나온다.",
            "",
        ]

    gaps = [(s["ask"], s["gap"]) for s in data["scenarios"] if s["gap"]]
    if gaps:
        lines += ["## 알려진 구멍", "", "고쳐야 할 것이 아니라, 아직 못 고친 것이다.", ""]
        lines += [f"- **{ask}** — {why}" for ask, why in gaps]
        lines += [""]

    problems = [(s["ask"], p) for s in data["scenarios"] for p in s["problems"]]
    if problems:
        lines += ["## 어긋난 것", ""]
        lines += [f"- **{ask}** — {p}" for ask, p in problems]
    else:
        lines += ["기대와 어긋난 것 없음."]
    return "\n".join(lines) + "\n"



def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 0

    root = Path(argv[0])
    if not root.is_dir():
        print(f"그런 폴더가 없다: {root}", file=sys.stderr)
        return 1

    here = Path(__file__).resolve().parent
    data = run(root, here / "scenarios.yaml")

    out_dir = here / "results"
    out_dir.mkdir(exist_ok=True)
    stamp = data["when"].replace(":", "").replace("-", "")
    (out_dir / f"{stamp}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    text = report(data)
    (out_dir / "최근.md").write_text(text, encoding="utf-8")
    print(text)

    return 1 if data["problems"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
