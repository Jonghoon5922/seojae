"""표 파서 (xlsx, csv, tsv).

표는 "문서"가 아니라서 그대로 넣으면 검색이 무의미해진다. 두 가지를 지킨다.

1. **행 묶음 단위로 자른다.** 시트 하나를 한 덩어리로 넣으면 어느 행이 걸렸는지
   알 수 없고, 한 행씩 자르면 조각이 너무 잘아 BM25가 힘을 못 쓴다.
2. **헤더를 각 덩어리에 다시 붙인다.** 이게 없으면
   "2026-03-15 | 승인 | 3,500,000" 같은 청크가 무슨 컬럼인지 알 수 없다.

출처는 "Sheet1 · 2-25행" 처럼 남겨서, 사람이 엑셀에서 바로 찾아갈 수 있게 한다.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from .base import Block, ParsedDoc, ParseError, register
from .plain import read_text

# 한 덩어리에 담을 데이터 행 수
ROWS_PER_BLOCK = 25

# 이보다 많은 행은 읽지 않는다 (수십만 행짜리 시트로부터 색인을 보호한다)
MAX_ROWS = 20_000


def _clean(value) -> str:
    if value is None:
        return ""
    return str(value).strip().replace("\n", " ")


def _is_empty(row: list[str]) -> bool:
    return not any(cell for cell in row)


def _blocks_from_rows(
    rows: list[list[str]], sheet: str, first_row_number: int = 1
) -> list[Block]:
    """헤더를 뗀 뒤 행을 묶어서 블록으로. 각 블록에 헤더를 다시 붙인다."""
    rows = [r for r in rows if not _is_empty(r)]
    if not rows:
        return []

    header = rows[0]
    header_line = " | ".join(header)
    body = rows[1:]

    if not body:  # 헤더만 있는 시트
        return [Block(text=header_line, location=sheet, group=sheet)]

    blocks: list[Block] = []
    for start in range(0, len(body), ROWS_PER_BLOCK):
        window = body[start : start + ROWS_PER_BLOCK]
        # 엑셀에서 보이는 행 번호로 알려준다 (헤더가 1행)
        begin = first_row_number + 1 + start
        end = begin + len(window) - 1
        location = f"{sheet} · {begin}-{end}행"

        lines = [header_line, "-" * 8]
        lines += [" | ".join(row) for row in window]
        blocks.append(Block(text="\n".join(lines), location=location, group=location))

    return blocks


@register(".xlsx", ".xlsm", label="Excel 문서")
def parse_xlsx(path: Path) -> ParsedDoc:
    try:
        from openpyxl import load_workbook

        # read_only 로 열어야 큰 파일에서 메모리가 터지지 않는다.
        # data_only 는 수식 대신 계산된 값을 준다 — 검색에는 값이 필요하다.
        book = load_workbook(path, read_only=True, data_only=True)
    except Exception as e:
        raise ParseError(f"Excel을 열지 못했다: {e}") from e

    blocks: list[Block] = []
    try:
        for sheet in book.worksheets:
            rows: list[list[str]] = []
            for index, raw in enumerate(sheet.iter_rows(values_only=True)):
                if index >= MAX_ROWS:
                    break
                rows.append([_clean(cell) for cell in raw])
            blocks.extend(_blocks_from_rows(rows, sheet.title))
    finally:
        book.close()

    if not blocks:
        raise ParseError("Excel에서 읽어낸 내용이 없다.")

    return ParsedDoc(title=path.stem, blocks=blocks, pages=len(book.sheetnames))


@register(".csv", ".tsv", label="표 (csv, tsv)")
def parse_csv(path: Path) -> ParsedDoc:
    try:
        text = read_text(path)
    except OSError as e:
        raise ParseError(str(e)) from e

    delimiter = "\t" if path.suffix.lower() == ".tsv" else _sniff(text)
    try:
        rows = [
            [_clean(cell) for cell in row]
            for row in csv.reader(io.StringIO(text), delimiter=delimiter)
        ][:MAX_ROWS]
    except csv.Error as e:
        raise ParseError(f"표를 읽지 못했다: {e}") from e

    blocks = _blocks_from_rows(rows, path.stem)
    if not blocks:
        raise ParseError("표에서 읽어낸 내용이 없다.")

    return ParsedDoc(title=path.stem, blocks=blocks)


def _sniff(text: str) -> str:
    """구분자를 추측한다. 안 되면 쉼표."""
    sample = "\n".join(text.splitlines()[:5])
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","
