"""Reading a spreadsheet into rows of text.

Only saved values are read: ``data_only=True`` means a formula cell yields
the number Excel stored, never the formula, and nothing is calculated here.
"""

import csv
import io
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from app.core.errors import UnprocessableError
from app.modules.importer.normalize import parse_number

MAX_BYTES = 4 * 1024 * 1024
# Rows scanned in a sheet before giving up (blank rows included).
MAX_SCAN_ROWS = 10_000
HEADER_SEARCH_ROWS = 15

TOO_LARGE = "The file is too large"
TOO_MANY_ROWS = "The file has too many rows"
UNSUPPORTED = "Unsupported file type"
OLD_XLS = "Old Excel files (xls) are not supported"
UNREADABLE = "Could not read this file"
EMPTY = "The file is empty"
NO_SHEET = "Sheet not found"


@dataclass(frozen=True)
class SheetData:
    sheet_names: list[str]
    sheet: str
    # One list per sheet row, blank rows included, so row n is ``rows[n - 1]``.
    rows: list[list[str]]


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "نعم" if value else "لا"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.6f}".rstrip("0").rstrip(".")
    if isinstance(value, datetime | date):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    return str(value).strip()


def _finish(rows: list[list[str]]) -> list[list[str]]:
    """Drop trailing blank rows and columns; refuse a sheet with nothing in it."""
    while rows and not any(rows[-1]):
        rows.pop()
    if not rows:
        raise UnprocessableError(EMPTY)
    width = max((index + 1 for row in rows for index, cell in enumerate(row) if cell), default=0)
    return [row[:width] + [""] * (width - len(row[:width])) for row in rows]


def _read_xlsx(content: bytes, sheet: str | None) -> SheetData:
    if not content.startswith(b"PK"):
        raise UnprocessableError(UNREADABLE)
    try:
        book = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except (zipfile.BadZipFile, KeyError, ValueError, OSError, InvalidFileException) as exc:
        raise UnprocessableError(UNREADABLE) from exc
    try:
        names = list(book.sheetnames)
        chosen = sheet if sheet is not None else names[0]
        if chosen not in names:
            raise UnprocessableError(NO_SHEET)
        rows: list[list[str]] = []
        for index, raw in enumerate(book[chosen].iter_rows(values_only=True)):
            if index >= MAX_SCAN_ROWS:
                raise UnprocessableError(TOO_MANY_ROWS)
            rows.append([_cell_text(cell) for cell in raw])
    except (zipfile.BadZipFile, KeyError, ValueError, OSError) as exc:
        raise UnprocessableError(UNREADABLE) from exc
    finally:
        book.close()
    return SheetData(sheet_names=names, sheet=chosen, rows=_finish(rows))


def _decode(content: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1256"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise UnprocessableError(UNREADABLE)  # pragma: no cover - cp1256 decodes any byte


def _read_csv(content: bytes) -> SheetData:
    text = _decode(content)
    first_line = text.split("\n", 1)[0]
    delimiter = max((",", ";", "\t"), key=first_line.count)
    rows: list[list[str]] = []
    for index, raw in enumerate(csv.reader(io.StringIO(text), delimiter=delimiter)):
        if index >= MAX_SCAN_ROWS:
            raise UnprocessableError(TOO_MANY_ROWS)
        rows.append([cell.strip() for cell in raw])
    return SheetData(sheet_names=["csv"], sheet="csv", rows=_finish(rows))


def read_sheet(content: bytes, filename: str, sheet: str | None = None) -> SheetData:
    if len(content) > MAX_BYTES:
        raise UnprocessableError(TOO_LARGE)
    extension = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if extension == "xls":
        raise UnprocessableError(OLD_XLS)
    if extension == "csv":
        return _read_csv(content)
    if extension in ("xlsx", "xlsm"):
        return _read_xlsx(content, sheet)
    raise UnprocessableError(UNSUPPORTED)


def _is_number(text: str) -> bool:
    try:
        return parse_number(text) is not None
    except ValueError:
        return False


def find_header_row(rows: list[list[str]]) -> int:
    """Index of the header: the first near-fullest row of text among the first rows.

    Title rows above it usually hold one merged cell, so they score low; the
    header is the first row with about as many text cells as any other.
    """
    scores = [
        sum(1 for cell in row if cell and not _is_number(cell)) for row in rows[:HEADER_SEARCH_ROWS]
    ]
    best = max(scores, default=0)
    if best < 2:
        return 0
    threshold = max(2, best - 1)
    return next(index for index, score in enumerate(scores) if score >= threshold)
