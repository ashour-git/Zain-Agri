"""Egyptian pounds to two decimals, rounded half-up like a shop counter."""

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)
