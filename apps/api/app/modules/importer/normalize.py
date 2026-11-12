"""Cleaning of spreadsheet text: names, numbers, units and totals rows."""

import re
import unicodedata
from decimal import Decimal, InvalidOperation

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
# Harakat, superscript alef and tatweel.
_MARKS = re.compile("[ً-ٰٟـ]")
_CURRENCY = re.compile(r"\b(?:egp|le)\b|ج\.?\s?م\.?|جنيه|جنية|£", re.IGNORECASE)


def normalize_name(text: str) -> str:
    """A comparison key: no diacritics, unified letter variants, one case, one space."""
    value = unicodedata.normalize("NFKC", text).translate(_ARABIC_DIGITS)
    value = _MARKS.sub("", value)
    for old, new in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ى", "ي"), ("ة", "ه")):
        value = value.replace(old, new)
    return " ".join(value.lower().split())


def parse_number(text: str) -> Decimal | None:
    """A number from sheet text. ``None`` for blank; ``ValueError`` for text that is not one."""
    value = text.translate(_ARABIC_DIGITS).replace("٫", ".").replace("٬", ",")
    value = _CURRENCY.sub("", value)
    value = "".join(value.split())
    if value == "":
        return None
    if re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", value):
        value = value.replace(",", "")
    elif re.fullmatch(r"-?\d+,\d{1,2}", value):
        value = value.replace(",", ".")
    elif not re.fullmatch(r"-?\d+(\.\d+)?", value):
        raise ValueError(f"not a number: {text!r}")
    try:
        return Decimal(value)
    except InvalidOperation as exc:  # pragma: no cover - the patterns above guard this
        raise ValueError(f"not a number: {text!r}") from exc


_UNIT_ALIASES: dict[str, tuple[str, ...]] = {
    "piece": ("قطعة", "حبة", "عدد", "وحدة", "pcs", "pc", "piece", "unit"),
    "kilogram": ("كيلو", "كجم", "كغم", "كيلوجرام", "كيلوغرام", "kg", "kgs", "kilo"),
    "gram": ("جرام", "جم", "غرام", "g", "gm", "gram"),
    "liter": ("لتر", "ل", "litre", "liter", "l", "lt"),
    "milliliter": ("مل", "ملل", "ملليلتر", "ml"),
    "bag": ("شيكارة", "شكارة", "كيس", "bag"),
    "bottle": ("زجاجة", "ازازة", "قنينة", "bottle"),
    "box": ("كرتونة", "كرتون", "صندوق", "box", "carton"),
    "pack": ("عبوة", "علبة", "باكت", "pack", "packet"),
}
_UNIT_BY_ALIAS = {
    normalize_name(alias): code for code, aliases in _UNIT_ALIASES.items() for alias in aliases
}


def resolve_unit(text: str) -> str | None:
    """The unit code a sheet's unit text means, or ``None`` when unknown."""
    return _UNIT_BY_ALIAS.get(normalize_name(text))


_TOTAL_WORDS = frozenset(
    normalize_name(word)
    for word in (
        "الإجمالي",
        "إجمالي",
        "اجمالي",
        "المجموع",
        "مجموع",
        "المجموع الكلي",
        "الإجمالي الكلي",
        "المجموع الإجمالي",
        "total",
        "grand total",
        "sum",
    )
)


def is_total_row(name: str) -> bool:
    """A totals row says only «الإجمالي» or «Total» where the product name would be."""
    return normalize_name(name) in _TOTAL_WORDS
