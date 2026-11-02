"""Single place where percent-vs-fraction risk settings are normalised."""
from decimal import Decimal
from typing import Union

Number = Union[int, float, str, Decimal]


def exposure_pct_to_fraction(value: Number) -> Decimal:
    """
    Normalise an exposure limit to a fraction of the reference balance.

    The YAML files use both forms (0.50 and 50.0 for 50%), so values in (0, 1]
    are taken as fractions and values in (1, 100] as percentages. A value of
    exactly 1 therefore means 100%. Anything else raises ValueError.
    """
    dec = Decimal(str(value))
    if dec <= 0 or dec > 100:
        raise ValueError(f"exposure limit must be in (0, 100], got {dec}")
    return dec if dec <= 1 else dec / Decimal("100")


def pct_to_fraction(value: Number) -> float:
    """Convert a setting that is always expressed in percent (3.0 = 3%) to a fraction."""
    return float(Decimal(str(value)) / Decimal("100"))
