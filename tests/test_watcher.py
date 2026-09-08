"""파일 감시 증분 색인.

3단계의 완료 기준은 "파일을 넣으면 자동 반영"이다.
이벤트를 그대로 믿으면 안 되는 두 경우(디바운스, 잠긴 파일)를 함께 확인한다.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from seojae.index import collection_of, forget_one, index_one, index_root, open_db
from seojae.paths import INBOX_DIRNAME
from seojae.search import list_collections, list_documents, search
from seojae.watcher import ShelfWatcher, _is_watchable

# 테스트에서는 짧게. 실제 기본값은 1초.
DEBOUNCE = 0.15
TIMEOUT = 15.0


@pytest.fixture
def live(shelf: Path):
    """감시자가 붙어 도는 서재."""
    conn = open_db(shelf, check_same_thread=False)
    index_root(shelf, conn)
    lock = threading.Lock()

    watcher = ShelfWatcher(shelf, conn, lock, debounce=DEBOUNCE)
    watcher.start()
    try:
        yield shelf, conn, lock, watcher
    finally:
        watcher.stop()
        conn.close()


def wait_until(predicate, timeout: float = TIMEOUT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def doc_paths(conn, lock) -> set[str]:
    with lock:
        return {d.path for d in list_documents(conn)}


# ── 파일 하나 단위 색인 ────────────────────────────────────────────────────


def test_collection_of(shelf: Path) -> None:
    assert collection_of(shelf, shelf / "업무규정" / "휴가규정.md") == ("업무규정", False)
    assert collection_of(shelf, shelf / "업무규정" / "경비" / "a.md") == ("업무규정", False)
    assert collection_of(shelf, shelf / INBOX_DIRNAME / "메모.md") == (INBOX_DIRNAME, True)
    # 루트 직속 파일도 미분류로 본다
    assert collection_of(shelf, shelf / "떠돌이.md") == (INBOX_DIRNAME, True)


def test_index_one_adds_document(shelf: Path) -> None:
    conn = open_db(shelf)
    index_root(shelf, conn)
    before = len(list_documents(conn))

    new_file = shelf / "업무규정" / "복리후생.md"
    new_file.write_text("# 복리후생\n\n## 경조사비\n결혼 50만원을 지급한다.\n", encoding="utf-8")
    stats = index_one(shelf, conn, new_file)

    assert stats.indexed == 1
    assert len(list_documents(conn)) == before + 1
    assert search(conn, "경조사비 결혼")
    conn.close()


def test_index_one_creates_collection_when_new(shelf: Path) -> None:
    conn = open_db(shelf)
    index_root(shelf, conn)

    new_dir = shelf / "새책장"
    new_dir.mkdir()
    new_file = new_dir / "문서.md"
    new_file.write_text("# 새 문서\n내용이 있다.\n", encoding="utf-8")
    index_one(shelf, conn, new_file)

    assert "새책장" in {c.dirname for c in list_collections(conn)}
    conn.close()


def test_index_one_refreshes_collection_description(shelf: Path) -> None:
    """README를 고치면 책장 설명(=Claude의 라우팅 근거)이 따라 바뀐다."""
    conn = open_db(shelf)
    index_root(shelf, conn)

    readme = shelf / "업무규정" / "README.md"
    readme.write_text(
        "---\nname: 업무규정\ndescription: 새로 쓴 설명. 복리후생 질문에 사용.\n---\n\n# 업무규정\n",
        encoding="utf-8",
    )
    index_one(shelf, conn, readme)

    info = next(c for c in list_collections(conn) if c.dirname == "업무규정")
    assert "복리후생" in info.description
    conn.close()


def test_forget_one(shelf: Path) -> None:
    conn = open_db(shelf)
    index_root(shelf, conn)
    target = shelf / "업무규정" / "출장지침.md"

    assert forget_one(shelf, conn, target) is True
    assert not any(d.path.endswith("출장지침.md") for d in list_documents(conn))
    assert forget_one(shelf, conn, target) is False  # 두 번째는 지울 게 없다
    conn.close()


def test_index_one_ignores_unsupported(shelf: Path) -> None:
    conn = open_db(shelf)
    index_root(shelf, conn)
    junk = shelf / "업무규정" / "압축.zip"
    junk.write_bytes(b"PK fake archive")

    assert index_one(shelf, conn, junk).indexed == 0
    conn.close()


# ── 감시 대상 판정 ─────────────────────────────────────────────────────────


def test_is_watchable(shelf: Path) -> None:
    assert _is_watchable(shelf, shelf / "업무규정" / "휴가규정.md")
    assert not _is_watchable(shelf, shelf / "업무규정" / "압축.zip")
    assert not _is_watchable(shelf, shelf / ".seojae" / "index.db")
    assert not _is_watchable(shelf, shelf / ".숨김" / "a.md")
    assert not _is_watchable(shelf, shelf.parent / "바깥" / "a.md")


# ── 실제 감시 ──────────────────────────────────────────────────────────────


def test_new_file_is_indexed_automatically(live) -> None:
    shelf, conn, lock, _ = live

    (shelf / "업무규정" / "복리후생.md").write_text(
        "# 복리후생\n\n## 경조사비\n결혼 축의금 50만원을 지급한다.\n", encoding="utf-8"
    )

    assert wait_until(lambda: any("복리후생" in p for p in doc_paths(conn, lock))), (
        "새 파일이 자동 색인돼야 한다"
    )
    with lock:
        hits = search(conn, "경조사비 축의금")
    assert hits
    assert hits[0].source.endswith("복리후생.md")


def test_deleted_file_disappears_from_index(live) -> None:
    shelf, conn, lock, _ = live
    target = shelf / "업무규정" / "출장지침.md"
    assert any("출장지침" in p for p in doc_paths(conn, lock))

    target.unlink()

    assert wait_until(lambda: not any("출장지침" in p for p in doc_paths(conn, lock))), (
        "지운 파일은 색인에서 빠져야 한다"
    )
    with lock:
        assert not search(conn, "숙박비 실비 정산")


def test_edited_file_is_reindexed(live) -> None:
    shelf, conn, lock, _ = live
    target = shelf / "업무규정" / "휴가규정.md"
    assert _search(conn, lock, "병가 진단서"), "고치기 전에는 옛 내용이 잡힌다"

    target.write_text(
        "# 휴가 규정\n\n## 사바티컬\n10년 근속 시 사바티컬 30일을 부여한다.\n", encoding="utf-8"
    )

    # 새 내용이 들어왔는지로 기다린다. "휴가" 같은 말로 기다리면 옛 색인으로도
    # 조건이 만족돼서, 재색인이 끝나기 전에 다음 단언으로 넘어간다.
    assert wait_until(lambda: bool(_search(conn, lock, "사바티컬"))), "수정이 반영돼야 한다"
    assert not _search(conn, lock, "병가 진단서"), "옛 내용은 사라져야 한다"


def test_new_collection_folder_is_picked_up(live) -> None:
    shelf, conn, lock, _ = live

    new_dir = shelf / "개발가이드"
    new_dir.mkdir()
    (new_dir / "README.md").write_text(
        "---\nname: 개발가이드\ndescription: 코딩 규약. 네이밍 질문에 사용.\n---\n\n# 개발가이드\n",
        encoding="utf-8",
    )
    (new_dir / "컨벤션.md").write_text(
        "# 컨벤션\n\n## 네이밍\n클래스는 파스칼케이스를 쓴다.\n", encoding="utf-8"
    )

    assert wait_until(
        lambda: bool(_search(conn, lock, "파스칼케이스", collection="개발가이드"))
    ), "새 폴더가 책장으로 잡히고 그 안의 문서가 검색돼야 한다"

    with lock:
        info = next(c for c in list_collections(conn) if c.dirname == "개발가이드")
    assert "네이밍" in info.description  # README의 description이 라우팅 근거로 들어온다


def test_inbox_file_stays_out_of_results(live) -> None:
    shelf, conn, lock, _ = live

    (shelf / INBOX_DIRNAME / "새메모.md").write_text(
        "# 미분류 메모\n\n사바티컬 관련 낙서.\n", encoding="utf-8"
    )

    assert wait_until(lambda: any("새메모" in p for p in doc_paths(conn, lock)))
    with lock:
        assert not search(conn, "사바티컬")  # 기본 검색에서는 빠진다
        assert search(conn, "사바티컬", include_inbox=True)


def _search(conn, lock, query, **kwargs):
    with lock:
        return search(conn, query, **kwargs)


# ── 디바운스 ───────────────────────────────────────────────────────────────


def test_debounce_collapses_rapid_events(shelf: Path) -> None:
    """에디터가 저장 한 번에 이벤트를 여러 개 뱉어도 한 번만 처리한다."""
    conn = open_db(shelf, check_same_thread=False)
    index_root(shelf, conn)
    watcher = ShelfWatcher(shelf, conn, threading.Lock(), debounce=0.3)

    target = shelf / "업무규정" / "휴가규정.md"
    target.write_text("# 휴가 규정\n\n## 사바티컬\n30일을 부여한다.\n", encoding="utf-8")
    for _ in range(5):
        watcher.mark_changed(target)

    assert watcher.process_due() == 0  # 아직 잠잠해지지 않았다
    time.sleep(0.35)
    assert watcher.process_due() == 1  # 여러 이벤트가 한 번으로 합쳐진다
    assert watcher.process_due() == 0  # 남은 일이 없다
    assert search(conn, "사바티컬")
    conn.close()


def test_file_deleted_before_processing(shelf: Path) -> None:
    """디바운스 사이에 지워져도 터지지 않는다."""
    conn = open_db(shelf, check_same_thread=False)
    index_root(shelf, conn)
    watcher = ShelfWatcher(shelf, conn, threading.Lock(), debounce=0.0)

    ghost = shelf / "업무규정" / "잠깐있던파일.md"
    ghost.write_text("# 임시\n", encoding="utf-8")
    watcher.mark_changed(ghost)
    ghost.unlink()

    watcher.process_due()  # 예외 없이 지나가야 한다
    assert not any(d.path.endswith("잠깐있던파일.md") for d in list_documents(conn))
    conn.close()
