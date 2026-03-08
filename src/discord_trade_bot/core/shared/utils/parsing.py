from typing import Any


def safe_float(value: Any) -> float | None:
    """Safely convert value to float, handling various formats.

    Args:
        value: Value to convert (can be int, float, str, or None).

    Returns:
        Float value or None if conversion fails.

    Examples:
        >>> safe_float("123.45")
        123.45
        >>> safe_float("$1,234.56")
        1234.56
        >>> safe_float("100 USDT")
        100.0
        >>> safe_float("invalid")
        None
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "")
    s = s.replace("$", "")
    s = s.replace("USDT", "")
    try:
        return float(s)
    except Exception:
        return None
