"""정리 축 — 파일을 실제로 옮기는 코드.

여기서 버그가 나면 사용자의 문서가 사라진다. 안전 규칙 셋을 집중적으로 확인한다.
  1. 루트 밖으로 나가지 않는다
  2. 무엇도 덮어쓰지 않는다
  3. 전부 되돌릴 수 있다
"""

from __future__ import annotations

from pathlib import Path

import pytest

from seojae.index import index_root, open_db
from seojae.organize import (
    OrganizeError,
    create_collection,
    delete_collection_if_empty,
    describe_collection,
    file_document,
    inbox_count,
    list_inbox,
    list_moves,
    rename_collection,
    undo_last,
    write_collection_readme,
)
from seojae.paths import INBOX_DIRNAME, OutsideRootError
from seojae.search import list_collections, list_documents, search


@pytest.fixture
def shelf_db(shelf: Path):
    conn = open_db(shelf)
    index_root(shelf, conn)
    yield shelf, conn
    conn.close()


def inbox_id(conn, root, filename: str) -> int:
    return next(i.id for i in list_inbox(conn, root) if i.filename == filename)


# ── 인박스 ────────────────────────────────────────────────────────────────


def test_list_inbox_gives_excerpt(shelf_db) -> None:
    root, conn = shelf_db
    items = list_inbox(conn, root)

    assert len(items) == 1
    item = items[0]
    assert item.filename == "미분류메모.md"
    assert "연차" in item.excerpt  # 분류를 판단할 재료가 들어 있다
    assert item.size > 0


def test_inbox_count(shelf_db) -> None:
    root, conn = shelf_db
    assert inbox_count(conn) == 1


def test_root_level_file_counts_as_inbox(shelf_db) -> None:
    root, conn = shelf_db
    (root / "떠돌이문서.md").write_text("# 떠돌이\n루트에 던져둔 파일.\n", encoding="utf-8")
    index_root(root, conn)

    assert "떠돌이문서.md" in {i.filename for i in list_inbox(conn, root)}


# ── 파일 이동 ─────────────────────────────────────────────────────────────


def test_file_document_moves_and_reindexes(shelf_db) -> None:
    root, conn = shelf_db
    doc_id = inbox_id(conn, root, "미분류메모.md")

    result = file_document(conn, root, doc_id, "업무규정")

    assert result.collection == "업무규정"
    assert not (root / INBOX_DIRNAME / "미분류메모.md").exists()
    assert (root / "업무규정" / "미분류메모.md").is_file()
    assert inbox_count(conn) == 0

    # 옮긴 뒤에는 기본 검색에 잡힌다 (인박스일 때는 빠져 있었다)
    hits = search(conn, "낙서")
    assert hits
    assert hits[0].source == "업무규정/미분류메모.md"


def test_file_document_renames(shelf_db) -> None:
    root, conn = shelf_db
    doc_id = inbox_id(conn, root, "미분류메모.md")

    result = file_document(conn, root, doc_id, "업무규정", new_name="연차메모.md")

    assert result.dst == "업무규정/연차메모.md"
    assert (root / "업무규정" / "연차메모.md").is_file()


def test_file_document_keeps_extension(shelf_db) -> None:
    """확장자를 바꾸면 파서가 달라진다. 원본 확장자를 지킨다."""
    root, conn = shelf_db
    doc_id = inbox_id(conn, root, "미분류메모.md")

    result = file_document(conn, root, doc_id, "업무규정", new_name="메모.txt")
    assert result.dst.endswith(".md")


def test_file_document_never_overwrites(shelf_db) -> None:
    root, conn = shelf_db
    doc_id = inbox_id(conn, root, "미분류메모.md")
    original = (root / "업무규정" / "휴가규정.md").read_text(encoding="utf-8")

    result = file_document(conn, root, doc_id, "업무규정", new_name="휴가규정.md")

    assert result.renamed
    assert result.dst == "업무규정/휴가규정 (2).md"
    assert (root / "업무규정" / "휴가규정.md").read_text(encoding="utf-8") == original


def test_file_document_requires_flag_for_new_collection(shelf_db) -> None:
    root, conn = shelf_db
    doc_id = inbox_id(conn, root, "미분류메모.md")

    with pytest.raises(OrganizeError) as e:
        file_document(conn, root, doc_id, "새책장")
    assert "create_collection" in str(e.value)
    assert "업무규정" in str(e.value)  # 있는 책장을 알려준다
    assert not (root / "새책장").exists()


def test_file_document_creates_collection_when_allowed(shelf_db) -> None:
    root, conn = shelf_db
    doc_id = inbox_id(conn, root, "미분류메모.md")

    result = file_document(conn, root, doc_id, "메모함", create_collection=True)

    assert result.created_collection
    assert (root / "메모함" / "미분류메모.md").is_file()
    assert "메모함" in {c.dirname for c in list_collections(conn)}


@pytest.mark.parametrize(
    "bad",
    ["..", "../바깥", "..\\바깥", "업무규정/하위", "_inbox", ".seojae", ".숨김", "  "],
)
def test_file_document_rejects_unsafe_collection(shelf_db, bad: str) -> None:
    root, conn = shelf_db
    doc_id = inbox_id(conn, root, "미분류메모.md")

    with pytest.raises((OrganizeError, OutsideRootError)):
        file_document(conn, root, doc_id, bad, create_collection=True)

    assert (root / INBOX_DIRNAME / "미분류메모.md").is_file()  # 원본은 그대로다


@pytest.mark.parametrize("bad", ["../탈출.md", "하위/파일.md", "이름<>.md"])
def test_file_document_rejects_unsafe_filename(shelf_db, bad: str) -> None:
    root, conn = shelf_db
    doc_id = inbox_id(conn, root, "미분류메모.md")

    with pytest.raises(OrganizeError):
        file_document(conn, root, doc_id, "업무규정", new_name=bad)


def test_file_document_unknown_id(shelf_db) -> None:
    root, conn = shelf_db
    with pytest.raises(OrganizeError):
        file_document(conn, root, 99999, "업무규정")


# ── 되돌리기 ──────────────────────────────────────────────────────────────


def test_undo_move(shelf_db) -> None:
    root, conn = shelf_db
    doc_id = inbox_id(conn, root, "미분류메모.md")
    file_document(conn, root, doc_id, "업무규정")

    message = undo_last(conn, root)

    assert "되돌렸다" in message
    assert (root / INBOX_DIRNAME / "미분류메모.md").is_file()
    assert not (root / "업무규정" / "미분류메모.md").exists()
    assert inbox_count(conn) == 1
    assert not search(conn, "낙서")  # 다시 인박스라 기본 검색에서 빠진다


def test_undo_removes_collection_it_created(shelf_db) -> None:
    root, conn = shelf_db
    doc_id = inbox_id(conn, root, "미분류메모.md")
    file_document(conn, root, doc_id, "메모함", create_collection=True)

    undo_last(conn, root)

    assert not (root / "메모함").exists()  # 우리가 만든 빈 폴더는 치운다


def test_undo_keeps_collection_that_has_other_files(shelf_db) -> None:
    root, conn = shelf_db
    doc_id = inbox_id(conn, root, "미분류메모.md")
    file_document(conn, root, doc_id, "메모함", create_collection=True)
    (root / "메모함" / "남의파일.md").write_text("# 남의 것\n", encoding="utf-8")

    undo_last(conn, root)

    assert (root / "메모함" / "남의파일.md").is_file()  # 남의 파일을 지우면 안 된다


def test_undo_twice_walks_back(shelf_db) -> None:
    root, conn = shelf_db
    (root / INBOX_DIRNAME / "둘째.md").write_text("# 둘째\n내용\n", encoding="utf-8")
    index_root(root, conn)

    file_document(conn, root, inbox_id(conn, root, "미분류메모.md"), "업무규정")
    file_document(conn, root, inbox_id(conn, root, "둘째.md"), "업무규정")

    undo_last(conn, root)
    assert (root / INBOX_DIRNAME / "둘째.md").is_file()
    undo_last(conn, root)
    assert (root / INBOX_DIRNAME / "미분류메모.md").is_file()

    with pytest.raises(OrganizeError):
        undo_last(conn, root)


def test_undo_with_nothing_to_undo(shelf_db) -> None:
    root, conn = shelf_db
    with pytest.raises(OrganizeError):
        undo_last(conn, root)


def test_moves_are_logged(shelf_db) -> None:
    root, conn = shelf_db
    doc_id = inbox_id(conn, root, "미분류메모.md")
    file_document(conn, root, doc_id, "업무규정")

    records = list_moves(conn)
    assert len(records) == 1
    assert records[0]["kind"] == "move"
    assert records[0]["undone"] is False

    undo_last(conn, root)
    assert list_moves(conn)[0]["undone"] is True


# ── 책장 설명 ─────────────────────────────────────────────────────────────


def test_describe_collection_gives_material(shelf_db) -> None:
    root, conn = shelf_db
    material = describe_collection(conn, root, "업무규정")

    assert material.document_count == 3
    assert material.has_readme
    titles = {d["title"] for d in material.documents}
    assert "휴가 규정" in titles

    doc = next(d for d in material.documents if d["title"] == "휴가 규정")
    assert any("연차" in h for h in doc["headings"])  # 헤딩이 설명 재료가 된다
    assert material.frequent_terms


def test_describe_missing_collection(shelf_db) -> None:
    root, conn = shelf_db
    with pytest.raises(OrganizeError):
        describe_collection(conn, root, "없는책장")


def test_write_readme_preserves_body_and_backs_up(shelf_db) -> None:
    root, conn = shelf_db
    readme = root / "업무규정" / "README.md"
    before = readme.read_text(encoding="utf-8")

    write_collection_readme(
        conn, root, "업무규정", "업무규정", "새 설명. 휴가·경비 질문에 쓴다.", ["규정"]
    )

    after = readme.read_text(encoding="utf-8")
    assert "새 설명" in after
    assert "휴가규정.md" in after  # 프론트매터 아래 본문은 그대로 남는다

    backups = list((root / ".seojae" / "backups").glob("*.md"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == before


def test_write_readme_updates_routing_description(shelf_db) -> None:
    root, conn = shelf_db
    write_collection_readme(conn, root, "업무규정", "업무규정", "복리후생 질문에 쓴다.")

    info = next(c for c in list_collections(conn) if c.dirname == "업무규정")
    assert "복리후생" in info.description


def test_write_readme_creates_when_absent(shelf_db) -> None:
    root, conn = shelf_db
    new_dir = root / "새책장"
    new_dir.mkdir()
    (new_dir / "문서.md").write_text("# 문서\n내용\n", encoding="utf-8")
    index_root(root, conn)

    path = write_collection_readme(conn, root, "새책장", "새책장", "새 책장 설명이다.")

    assert path == "새책장/README.md"
    assert (new_dir / "README.md").is_file()


def test_write_readme_rejects_empty_description(shelf_db) -> None:
    root, conn = shelf_db
    with pytest.raises(OrganizeError):
        write_collection_readme(conn, root, "업무규정", "업무규정", "   ")


def test_undo_readme_restores_previous(shelf_db) -> None:
    root, conn = shelf_db
    readme = root / "업무규정" / "README.md"
    before = readme.read_text(encoding="utf-8")

    write_collection_readme(conn, root, "업무규정", "업무규정", "덮어쓴 설명이다.")
    assert "덮어쓴 설명" in readme.read_text(encoding="utf-8")

    undo_last(conn, root)
    assert readme.read_text(encoding="utf-8") == before


def test_undo_readme_deletes_one_we_created(shelf_db) -> None:
    root, conn = shelf_db
    new_dir = root / "새책장"
    new_dir.mkdir()
    (new_dir / "문서.md").write_text("# 문서\n내용\n", encoding="utf-8")
    index_root(root, conn)
    write_collection_readme(conn, root, "새책장", "새책장", "새 책장 설명이다.")

    undo_last(conn, root)

    assert not (new_dir / "README.md").exists()  # 원래 없던 파일은 지운다
    assert (new_dir / "문서.md").is_file()  # 다른 파일은 건드리지 않는다


def test_readme_move_is_indexed_after_write(shelf_db) -> None:
    """README 본문도 검색 대상이다 (SPEC 6절)."""
    root, conn = shelf_db
    write_collection_readme(
        conn, root, "업무규정", "업무규정", "사규 안내. 근태 질문에 쓴다.", ["사규"]
    )

    paths = {d.path for d in list_documents(conn)}
    assert "업무규정/README.md" in paths


def test_excerpt_is_not_just_the_title(shelf_db) -> None:
    """마크다운은 H1이 혼자 한 청크가 되기 쉽다. 제목만 주면 분류를 판단할 수 없다."""
    root, conn = shelf_db
    (root / INBOX_DIRNAME / "제목먼저.md").write_text(
        "# 회의록\n\n## 안건\n출장비 정액을 3만원에서 3만5천원으로 올린다.\n",
        encoding="utf-8",
    )
    index_root(root, conn)

    item = next(i for i in list_inbox(conn, root) if i.filename == "제목먼저.md")
    assert "출장비" in item.excerpt, "제목 다음 내용까지 발췌에 들어와야 한다"


def test_readme_frontmatter_date_is_unquoted(shelf_db) -> None:
    root, conn = shelf_db
    write_collection_readme(conn, root, "업무규정", "업무규정", "사규 안내. 근태 질문에 쓴다.")

    text = (root / "업무규정" / "README.md").read_text(encoding="utf-8")
    assert "updated: '" not in text and 'updated: "' not in text


# ── 책장 만들기·이름 바꾸기 ───────────────────────────────────────────────


def test_create_collection(shelf_db) -> None:
    root, conn = shelf_db
    name = create_collection(conn, root, "개발가이드", "코딩 규약. 네이밍 질문에 사용.")

    assert name == "개발가이드"
    assert (root / "개발가이드").is_dir()
    assert (root / "개발가이드" / "README.md").is_file()

    info = next(c for c in list_collections(conn) if c.dirname == "개발가이드")
    assert "네이밍" in info.description


def test_create_collection_without_description(shelf_db) -> None:
    root, conn = shelf_db
    create_collection(conn, root, "메모함")
    assert (root / "메모함").is_dir()
    assert not (root / "메모함" / "README.md").exists()


def test_create_collection_rejects_duplicate(shelf_db) -> None:
    root, conn = shelf_db
    with pytest.raises(OrganizeError):
        create_collection(conn, root, "업무규정")


@pytest.mark.parametrize("bad", ["..", "하위/폴더", "_inbox", ".숨김", "  "])
def test_create_collection_rejects_unsafe(shelf_db, bad: str) -> None:
    root, conn = shelf_db
    with pytest.raises((OrganizeError, OutsideRootError)):
        create_collection(conn, root, bad)


def test_rename_collection(shelf_db) -> None:
    root, conn = shelf_db
    rename_collection(conn, root, "업무규정", "사규")

    assert (root / "사규").is_dir()
    assert not (root / "업무규정").exists()
    assert "사규" in {c.dirname for c in list_collections(conn)}
    assert "업무규정" not in {c.dirname for c in list_collections(conn)}


def test_rename_keeps_index_without_reparsing(shelf_db) -> None:
    """폴더만 바뀌었으니 다시 읽지 않는다. 경로만 고쳐도 검색이 유지돼야 한다."""
    root, conn = shelf_db
    before = len(list_documents(conn, collection="업무규정"))

    rename_collection(conn, root, "업무규정", "사규")

    docs = list_documents(conn, collection="사규")
    assert len(docs) == before
    assert all(d.path.startswith("사규/") for d in docs)

    hits = search(conn, "연차 휴가", collection="사규")
    assert hits
    assert hits[0].source.startswith("사규/")


def test_rename_rejects_existing_name(shelf_db) -> None:
    root, conn = shelf_db
    create_collection(conn, root, "메모함")
    with pytest.raises(OrganizeError):
        rename_collection(conn, root, "업무규정", "메모함")


def test_undo_create_collection(shelf_db) -> None:
    root, conn = shelf_db
    create_collection(conn, root, "메모함")

    undo_last(conn, root)
    assert not (root / "메모함").exists()


def test_undo_create_refuses_when_files_arrived(shelf_db) -> None:
    """되돌리는 사이에 파일이 들어왔으면 지우지 않는다."""
    root, conn = shelf_db
    create_collection(conn, root, "메모함")
    (root / "메모함" / "누군가의파일.md").write_text("# 남의 것\n", encoding="utf-8")

    with pytest.raises(OrganizeError):
        undo_last(conn, root)
    assert (root / "메모함" / "누군가의파일.md").is_file()


def test_undo_rename_collection(shelf_db) -> None:
    root, conn = shelf_db
    rename_collection(conn, root, "업무규정", "사규")

    undo_last(conn, root)

    assert (root / "업무규정").is_dir()
    assert not (root / "사규").exists()
    assert search(conn, "연차 휴가", collection="업무규정")


def test_delete_empty_collection(shelf_db) -> None:
    root, conn = shelf_db
    create_collection(conn, root, "메모함", "임시 메모.")
    delete_collection_if_empty(conn, root, "메모함")

    assert not (root / "메모함").exists()
    assert "메모함" not in {c.dirname for c in list_collections(conn)}


def test_delete_collection_refuses_when_not_empty(shelf_db) -> None:
    root, conn = shelf_db
    with pytest.raises(OrganizeError) as e:
        delete_collection_if_empty(conn, root, "업무규정")
    assert "남아 있다" in str(e.value)
    assert (root / "업무규정").is_dir()
