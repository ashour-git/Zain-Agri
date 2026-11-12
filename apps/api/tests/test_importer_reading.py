"""Reading a product sheet and cleaning its cells."""

from decimal import Decimal
from io import BytesIO

import pytest
from openpyxl import Workbook

from app.core.errors import UnprocessableError
from app.modules.importer.normalize import (
    is_total_row,
    normalize_name,
    parse_number,
    resolve_unit,
)
from app.modules.importer.parser import find_header_row, read_sheet


def _xlsx(
    rows: list[list[object]],
    title: str = "Sheet1",
    extra: dict[str, list[list[object]]] | None = None,
) -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = title
    for row in rows:
        sheet.append(row)
    for name, data in (extra or {}).items():
        other = book.create_sheet(name)
        for row in data:
            other.append(row)
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def test_reads_an_arabic_sheet_as_text() -> None:
    content = _xlsx([["الصنف", "السعر", "الكمية"], ["يوريا", 12.5, 40], ["بذور خيار", 30, 7.0]])

    data = read_sheet(content, "مخزون.xlsx")

    assert data.rows == [
        ["الصنف", "السعر", "الكمية"],
        ["يوريا", "12.5", "40"],
        ["بذور خيار", "30", "7"],
    ]
    assert data.sheet == "Sheet1"


def test_float_noise_is_not_shown() -> None:
    data = read_sheet(_xlsx([["x"], [0.1 + 0.2]]), "a.xlsx")

    assert data.rows[1] == ["0.3"]


def test_title_rows_above_the_header_are_found() -> None:
    content = _xlsx(
        [
            ["جرد مؤسسة زين - نوفمبر"],
            [],
            ["الصنف", "الوحدة", "الرصيد"],
            ["يوريا", "شيكارة", 12],
        ]
    )

    data = read_sheet(content, "a.xlsx")

    assert find_header_row(data.rows) == 2


def test_header_is_the_first_row_when_there_is_no_title() -> None:
    assert find_header_row([["a", "b"], ["1", "2"]]) == 0


def test_formulas_are_never_evaluated() -> None:
    content = _xlsx([["الصنف", "الكمية"], ["يوريا", "=1+1"]])

    data = read_sheet(content, "a.xlsx")

    # openpyxl writes no saved value for a formula, so the reader sees nothing.
    assert data.rows[1] == ["يوريا", ""]


def test_a_named_sheet_can_be_chosen() -> None:
    content = _xlsx([["ملاحظات"]], extra={"المنتجات": [["الصنف"], ["يوريا"]]})

    data = read_sheet(content, "a.xlsx", sheet="المنتجات")

    assert data.sheet_names == ["Sheet1", "المنتجات"]
    assert data.rows == [["الصنف"], ["يوريا"]]


def test_an_unknown_sheet_is_refused() -> None:
    with pytest.raises(UnprocessableError, match="Sheet not found"):
        read_sheet(_xlsx([["a"]]), "a.xlsx", sheet="غير موجودة")


@pytest.mark.parametrize("encoding", ["utf-8-sig", "cp1256"])
def test_csv_in_either_arabic_encoding(encoding: str) -> None:
    text = "الصنف,السعر\nيوريا,12\n"

    data = read_sheet(text.encode(encoding), "a.csv")

    assert data.rows == [["الصنف", "السعر"], ["يوريا", "12"]]


def test_csv_with_semicolons() -> None:
    data = read_sheet("الصنف;السعر\nيوريا;12\n".encode("utf-8-sig"), "a.csv")

    assert data.rows[1] == ["يوريا", "12"]


def test_old_xls_files_are_refused_with_a_hint() -> None:
    with pytest.raises(UnprocessableError, match="xls"):
        read_sheet(b"whatever", "old.xls")


def test_a_renamed_non_spreadsheet_is_refused() -> None:
    with pytest.raises(UnprocessableError, match="Could not read"):
        read_sheet(b"this is not a zip file", "fake.xlsx")


def test_unknown_extension_is_refused() -> None:
    with pytest.raises(UnprocessableError, match="Unsupported"):
        read_sheet(b"x", "notes.pdf")


def test_an_empty_sheet_is_refused() -> None:
    with pytest.raises(UnprocessableError, match="empty"):
        read_sheet(_xlsx([[]]), "a.xlsx")


def test_oversized_files_are_refused() -> None:
    with pytest.raises(UnprocessableError, match="too large"):
        read_sheet(b"x" * (4 * 1024 * 1024 + 1), "a.csv")


def test_blank_rows_between_data_are_kept_so_row_numbers_stay_true() -> None:
    data = read_sheet(_xlsx([["الصنف"], ["يوريا"], [], ["بذور"]]), "a.xlsx")

    # Every row is padded to one width, so a blank row is one empty cell.
    assert data.rows == [["الصنف"], ["يوريا"], [""], ["بذور"]]


# --- cleaning ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("12", Decimal("12")),
        ("12.50", Decimal("12.50")),
        ("1,250", Decimal("1250")),
        ("1,250.75", Decimal("1250.75")),
        ("12,5", Decimal("12.5")),
        ("١٢٥٠", Decimal("1250")),
        ("١٬٢٥٠٫٥٠ ج.م", Decimal("1250.50")),
        ("45 جنيه", Decimal("45")),
        ("EGP 99", Decimal("99")),
        (" 7 ", Decimal("7")),
        ("-3", Decimal("-3")),
        ("", None),
        ("   ", None),
    ],
)
def test_numbers(raw: str, expected: Decimal | None) -> None:
    assert parse_number(raw) == expected


@pytest.mark.parametrize("raw", ["abc", "12 كيلو", "1.2.3", "--5"])
def test_text_that_is_not_a_number_is_refused(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_number(raw)


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("كيلو", "kilogram"),
        ("كيلُو", "kilogram"),
        ("كجم", "kilogram"),
        ("KG", "kilogram"),
        ("شيكارة", "bag"),
        ("شكارة", "bag"),
        ("لتر", "liter"),
        ("ل", "liter"),
        ("جرام", "gram"),
        ("مل", "milliliter"),
        ("زجاجة", "bottle"),
        ("ازازة", "bottle"),
        ("كرتونة", "box"),
        ("كرتون", "box"),
        ("عبوة", "pack"),
        ("قطعة", "piece"),
        ("حبة", "piece"),
        ("pcs", "piece"),
    ],
)
def test_unit_names(raw: str, code: str) -> None:
    assert resolve_unit(raw) == code


def test_unknown_unit_is_none() -> None:
    assert resolve_unit("قنطار") is None
    assert resolve_unit("") is None


def test_names_compare_without_diacritics_or_letter_variants() -> None:
    assert normalize_name("أَسمدة  عضوية") == normalize_name("اسمده عضويه")
    assert normalize_name("Urea 46%") == normalize_name("urea   46%")


@pytest.mark.parametrize(
    "raw", ["الإجمالي", "المجموع", "اجمالي", "Total", "TOTAL", "المجموع الكلي"]
)
def test_totals_rows_are_recognised(raw: str) -> None:
    assert is_total_row(raw) is True


def test_a_product_called_total_something_is_not_a_totals_row() -> None:
    assert is_total_row("يوريا") is False
    assert is_total_row("سماد توتال بلس") is False
