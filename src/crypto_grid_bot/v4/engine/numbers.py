"""The one Decimal context of the V4 engine and the exact Decimal/Fraction converters.

All Decimal arithmetic runs under ``CONTEXT`` (60 digits, round half to even), as V3 section
4 to 6 compute. The ledger keeps exact ``Fraction`` amounts, so the two converters never
round: ``to_fraction`` reads a Decimal's exact value, and ``to_decimal`` returns a Fraction
as a Decimal only when that Decimal is the same number.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Context, Decimal
from fractions import Fraction

CONTEXT = Context(prec=60, rounding=ROUND_HALF_EVEN)


def to_fraction(value: Decimal) -> Fraction:
    """The exact value of a finite Decimal. Refuses anything else (a float included)."""
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"a finite Decimal is required, got {value!r}")
    return Fraction(value)


def to_decimal(value: Fraction) -> Decimal:
    """The exact Decimal of a Fraction, or a ``ValueError`` if no finite Decimal equals it.

    A Fraction in lowest terms terminates in base 10 exactly when its denominator has no
    prime factor besides 2 and 5. The digits are built from integers and never pass through
    the Decimal context, so a value with more than ``CONTEXT.prec`` digits stays exact.
    """
    if not isinstance(value, Fraction):
        raise ValueError(f"a Fraction is required, got {value!r}")
    denominator = value.denominator
    twos = fives = 0
    rest = denominator
    while rest % 2 == 0:
        rest //= 2
        twos += 1
    while rest % 5 == 0:
        rest //= 5
        fives += 1
    if rest != 1:
        raise ValueError(f"{value} has no terminating decimal form")
    places = max(twos, fives)
    scaled = value.numerator * (10**places // denominator)
    return Decimal(f"{scaled}E-{places}")
