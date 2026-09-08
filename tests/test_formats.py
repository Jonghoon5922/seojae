"""형식별 파서.

새 형식을 추가하면 여기에 "실제 파일을 만들어 읽어보는" 테스트를 하나 더한다.
파서는 남의 파일을 다루므로, 깨진 입력에도 죽지 않고 실패로 남아야 한다.
"""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

import pytest

from seojae.parsers import (
    SUPPORTED_EXTS,
    ParseError,
    describe_formats,
    parse_file,
    parser_for,
)
from seojae.tokenizer import tokenize


# ── 등록기 ────────────────────────────────────────────────────────────────


def test_registry_is_the_only_source_of_extensions() -> None:
    """paths 가 따로 목록을 들고 있으면 한쪽만 고쳐 조용히 안 잡힌다."""
    from seojae.paths import SUPPORTED_EXTS as from_paths

    assert from_paths is SUPPORTED_EXTS


def test_core_formats_registered() -> None:
    for ext in (".md", ".txt", ".pdf", ".docx", ".hwpx", ".xlsx", ".csv", ".pptx", ".java"):
        assert parser_for(ext) is not None, f"{ext} 파서가 없다"


def test_describe_formats_is_human_readable() -> None:
    labels = [label for label, _ in describe_formats()]
    assert "한글 문서 (hwpx)" in labels
    assert "Excel 문서" in labels


def test_unknown_extension_raises(tmp_path: Path) -> None:
    junk = tmp_path / "압축.zip"
    junk.write_bytes(b"PK fake archive")
    with pytest.raises(ParseError):
        parse_file(junk)


# ── 소스 코드 ─────────────────────────────────────────────────────────────

JAVA = """package bxm.dbli.bil;

import java.util.List;

public class UserService {

    public String getUserName(long userId) {
        return repository.findName(userId);
    }

    private void updateLastLogin(long userId) {
        repository.touch(userId);
    }
}
"""


def test_java_is_chunked_by_declaration(tmp_path: Path) -> None:
    path = tmp_path / "UserService.java"
    path.write_text(JAVA, encoding="utf-8")

    doc = parse_file(path)
    locations = [b.location for b in doc.blocks]

    # 선언 이름과 줄 번호가 출처에 들어간다
    assert any("UserService" in loc for loc in locations)
    assert all("L" in loc for loc in locations)


def test_camel_case_is_searchable_as_words() -> None:
    """getUserName 을 "user name" 으로 찾을 수 있어야 한다."""
    tokens = tokenize("public String getUserName(long userId)")

    assert "getusername" in tokens  # 원형도 남는다
    assert "user" in tokens
    assert "name" in tokens
    assert "get" not in tokens  # 흔한 접두사는 뺀다


def test_snake_and_kebab_split() -> None:
    tokens = tokenize("max_retry_count 와 data-source-url")
    for word in ("max", "retry", "count", "data", "source", "url"):
        assert word in tokens, word


def test_consecutive_capitals_stay_together() -> None:
    tokens = tokenize("HTTPServer 설정")
    assert "http" in tokens
    assert "server" in tokens


def test_sql_file(tmp_path: Path) -> None:
    path = tmp_path / "쿼리.sql"
    path.write_text(
        "CREATE TABLE 계약 (\n  증권번호 VARCHAR(12)\n);\n\n"
        "SELECT 증권번호 FROM 계약 WHERE 상태 = '유효';\n",
        encoding="utf-8",
    )
    doc = parse_file(path)
    assert doc.blocks
    assert any("계약" in b.text for b in doc.blocks)


def test_huge_text_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "거대로그.log"
    path.write_text("x" * (6 * 1024 * 1024), encoding="utf-8")
    with pytest.raises(ParseError):
        parse_file(path)


# ── 표 ────────────────────────────────────────────────────────────────────


def test_csv_repeats_header_in_every_chunk(tmp_path: Path) -> None:
    """헤더가 없으면 '2026-03-15 | 승인 | 3500000' 이 무슨 뜻인지 알 수 없다."""
    path = tmp_path / "정산.csv"
    rows = [["일자", "상태", "금액"]] + [
        [f"2026-03-{d:02d}", "승인", str(d * 100000)] for d in range(1, 31)
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(rows)

    doc = parse_file(path)

    assert len(doc.blocks) > 1, "30행이면 여러 덩어리로 갈라져야 한다"
    for block in doc.blocks:
        assert "일자 | 상태 | 금액" in block.text, "덩어리마다 헤더가 붙어야 한다"
    assert any("행" in b.location for b in doc.blocks)


def test_tsv_uses_tab(tmp_path: Path) -> None:
    path = tmp_path / "표.tsv"
    path.write_text("이름\t부서\n홍길동\t총무\n", encoding="utf-8")
    doc = parse_file(path)
    assert "홍길동 | 총무" in doc.blocks[0].text


def test_xlsx_sheets_and_headers(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")

    path = tmp_path / "장부.xlsx"
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "정산"
    sheet.append(["일자", "상태", "금액"])
    for d in range(1, 40):
        sheet.append([f"2026-03-{d:02d}", "승인", d * 1000])

    second = book.create_sheet("메모")
    second.append(["항목", "내용"])
    second.append(["비고", "사바티컬 검토"])
    book.save(path)

    doc = parse_file(path)
    locations = [b.location for b in doc.blocks]

    assert any(loc.startswith("정산") for loc in locations)
    assert any(loc.startswith("메모") for loc in locations)
    assert any("행" in loc for loc in locations)
    assert all("일자 | 상태 | 금액" in b.text for b in doc.blocks if b.location.startswith("정산"))
    assert any("사바티컬" in b.text for b in doc.blocks)


def test_broken_xlsx_fails_cleanly(tmp_path: Path) -> None:
    path = tmp_path / "깨진.xlsx"
    path.write_bytes("이건 xlsx가 아니다".encode("utf-8"))
    with pytest.raises(ParseError):
        parse_file(path)


# ── hwpx ──────────────────────────────────────────────────────────────────


def _make_hwpx(path: Path, body: str) -> None:
    """최소한의 hwpx (zip + Contents/section0.xml)."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("Contents/section0.xml", body)


HWPX_BODY = """<?xml version="1.0" encoding="UTF-8"?>
<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"
        xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">
  <hp:p><hp:run><hp:t>휴가 규정</hp:t></hp:run></hp:p>
  <hp:p><hp:run><hp:t>연차는 15일을 부여한다.</hp:t></hp:run></hp:p>
  <hp:tbl>
    <hp:tr>
      <hp:tc><hp:p><hp:run><hp:t>구분</hp:t></hp:run></hp:p></hp:tc>
      <hp:tc><hp:p><hp:run><hp:t>일수</hp:t></hp:run></hp:p></hp:tc>
    </hp:tr>
    <hp:tr>
      <hp:tc><hp:p><hp:run><hp:t>연차</hp:t></hp:run></hp:p></hp:tc>
      <hp:tc><hp:p><hp:run><hp:t>15</hp:t></hp:run></hp:p></hp:tc>
    </hp:tr>
  </hp:tbl>
</hs:sec>
"""


def test_hwpx_reads_paragraphs_and_tables(tmp_path: Path) -> None:
    path = tmp_path / "휴가규정.hwpx"
    _make_hwpx(path, HWPX_BODY)

    doc = parse_file(path)
    text = "\n".join(b.text for b in doc.blocks)

    assert "연차는 15일을 부여한다." in text
    assert "구분 | 일수" in text, "표를 빠뜨리면 안 된다"
    assert doc.title == "휴가 규정"


def test_hwpx_table_text_is_not_duplicated(tmp_path: Path) -> None:
    """표 안의 문단이 두 번 들어가면 검색 결과가 중복된다."""
    path = tmp_path / "휴가규정.hwpx"
    _make_hwpx(path, HWPX_BODY)

    text = "\n".join(b.text for b in parse_file(path).blocks)
    assert text.count("구분") == 1


def test_broken_hwpx_fails_cleanly(tmp_path: Path) -> None:
    path = tmp_path / "깨진.hwpx"
    path.write_bytes(b"not a zip")
    with pytest.raises(ParseError):
        parse_file(path)


def test_hwpx_without_section_fails_cleanly(tmp_path: Path) -> None:
    path = tmp_path / "빈.hwpx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/hwp+zip")
    with pytest.raises(ParseError):
        parse_file(path)


# ── pptx ──────────────────────────────────────────────────────────────────


def test_pptx_slides_and_notes(tmp_path: Path) -> None:
    pptx = pytest.importorskip("pptx")

    path = tmp_path / "발표.pptx"
    deck = pptx.Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[1])
    slide.shapes.title.text = "전환 일정"
    slide.placeholders[1].text = "9월 착수, 12월 종료"
    slide.notes_slide.notes_text_frame.text = "예비 기간 2주 포함"
    deck.save(path)

    doc = parse_file(path)
    text = "\n".join(b.text for b in doc.blocks)

    assert "전환 일정" in text
    assert "9월 착수" in text
    assert "예비 기간" in text, "발표자 노트도 읽어야 한다"
    assert doc.blocks[0].location.startswith("슬라이드 1")


# ── HTML ──────────────────────────────────────────────────────────────────


def test_html_strips_script_and_keeps_headings(tmp_path: Path) -> None:
    path = tmp_path / "안내.html"
    path.write_text(
        "<html><head><title>사내 안내</title>"
        "<style>body{color:red}</style></head><body>"
        "<h1>휴가</h1><p>연차는 15일이다.</p>"
        "<script>alert('무시해야 한다')</script>"
        "<h2>병가</h2><p>진단서를 낸다.</p>"
        "</body></html>",
        encoding="utf-8",
    )

    doc = parse_file(path)
    text = "\n".join(b.text for b in doc.blocks)

    assert "연차는 15일이다." in text
    assert "진단서를 낸다." in text
    assert "alert" not in text and "color:red" not in text
    assert any("병가" in b.location for b in doc.blocks)


# ── 색인 폭발 방지 ────────────────────────────────────────────────────────


def test_build_dirs_are_skipped(tmp_path: Path) -> None:
    """소스 폴더를 통째로 넣어도 node_modules 가 색인을 잡아먹지 않아야 한다."""
    from seojae.paths import walk_files

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "App.java").write_text("public class App {}", encoding="utf-8")
    for junk in ("node_modules", "target", ".venv", "__pycache__"):
        d = tmp_path / junk
        d.mkdir()
        (d / "쓰레기.js").write_text("x", encoding="utf-8")

    found = {p.name for p in walk_files(tmp_path, tmp_path)}
    assert found == {"App.java"}


# ── 이미지 ────────────────────────────────────────────────────────────────


def _tiny_png() -> bytes:
    """1x1 투명 PNG (base64 디코딩한 최소 이미지)."""
    import base64

    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
        "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    )


def test_image_is_searchable_by_filename(tmp_path: Path) -> None:
    """OCR은 하지 않는다. 파일명만으로도 찾을 수 있어야 한다."""
    path = tmp_path / "전환_흐름도-v2.png"
    path.write_bytes(_tiny_png())

    doc = parse_file(path)
    text = doc.blocks[0].text

    assert "전환_흐름도-v2.png" in text
    assert "전환 흐름도 v2" in text  # 구분자를 띄어 검색에 걸리게
    assert "get_document" in text  # 어떻게 열어보는지 알려준다


def test_image_helpers() -> None:
    from seojae.parsers.image import is_image, mime_type

    assert is_image("설계도.png")
    assert is_image("사진.JPG")
    assert not is_image("문서.pdf")
    assert mime_type("설계도.png") == "image/png"
    assert mime_type("사진.jpg") == "image/jpeg"


def test_huge_image_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "거대.png"
    path.write_bytes(b"\x00" * (21 * 1024 * 1024))
    with pytest.raises(ParseError):
        parse_file(path)
