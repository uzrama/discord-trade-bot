def pct(n: float, d: float) -> float:
    """Calculate percentage.

    Args:
        n: Numerator.
        d: Denominator.

    Returns:
        Percentage value (0-100 scale).

    Examples:
        >>> pct(50, 100)
        50.0
        >>> pct(25, 200)
        12.5
        >>> pct(10, 0)
        0.0
    """
    if not d:
        return 0.0
    return (n / d) * 100.0


def calc_realized_pnl_for_partial(entry_price: float, exit_price: float, qty_closed: float, side: str) -> float:
    """Calculate realized PnL for partial position close.

    Args:
        entry_price: Entry price of the position.
        exit_price: Exit price for the closed portion.
        qty_closed: Quantity being closed.
        side: Position side ("long" or "short").

    Returns:
        Realized profit/loss in quote currency.

    Examples:
        >>> calc_realized_pnl_for_partial(100.0, 110.0, 1.0, "long")
        10.0
        >>> calc_realized_pnl_for_partial(100.0, 90.0, 1.0, "short")
        10.0
    """
    if side == "long":
        return (exit_price - entry_price) * qty_closed
    return (entry_price - exit_price) * qty_closed
