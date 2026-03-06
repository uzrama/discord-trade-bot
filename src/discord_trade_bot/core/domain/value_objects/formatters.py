from discord_trade_bot.core.shared.utils.parsing import safe_float


def format_quantity(qty: float, precision: int = 6) -> str:
    """Format quantity for exchange API (remove trailing zeros).

    Args:
        qty: Quantity to format.
        precision: Number of decimal places (default: 6).

    Returns:
        Formatted quantity string without trailing zeros.

    Examples:
        >>> format_quantity(1.500000)
        '1.5'
        >>> format_quantity(0.123456)
        '0.123456'
        >>> format_quantity(10.0)
        '10'
    """
    return f"{qty:.{precision}f}".rstrip("0").rstrip(".")


def format_price(price: float, precision: int = 8) -> str:
    """Format price for exchange API (remove trailing zeros).

    Args:
        price: Price to format.
        precision: Number of decimal places (default: 8).

    Returns:
        Formatted price string without trailing zeros.

    Examples:
        >>> format_price(50000.12000000)
        '50000.12'
        >>> format_price(0.00012340)
        '0.0001234'
    """
    return f"{price:.{precision}f}".rstrip("0").rstrip(".")


def dedupe_float_levels(values: list[float], precision: int = 12) -> list[float]:
    """Remove duplicate float values from list based on precision.

    Args:
        values: List of float values to deduplicate.
        precision: Number of decimal places for comparison (default: 12).

    Returns:
        List of unique float values preserving order.

    Examples:
        >>> dedupe_float_levels([1.0, 1.0000000001, 2.0])
        [1.0, 2.0]
        >>> dedupe_float_levels([100.5, 200.3, 100.5])
        [100.5, 200.3]
    """
    out: list[float] = []
    seen = set()
    for value in values or []:
        fv = safe_float(value)
        if fv is None:
            continue
        key = round(float(fv), precision)
        if key in seen:
            continue
        seen.add(key)
        out.append(float(fv))
    return out
