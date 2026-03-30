"""Domain service for calculating breakeven prices and realized PnL.

This module provides functions to calculate the true breakeven price
accounting for fees and partial position closures, as well as realized
profit/loss from partial exits.
"""

from typing import TYPE_CHECKING

from discord_trade_bot.core.domain.value_objects.trading import TradeSide

if TYPE_CHECKING:
    from discord_trade_bot.main.config.yaml.fee import FeesConfig


def calculate_breakeven_price(
    entry_price: float,
    side: TradeSide,
    qty_total: float,
    qty_remaining: float,
    realized_pnl_gross: float,
    fees_config: FeesConfig,
) -> float | None:
    """Calculate the breakeven price accounting for fees and realized PnL.

    This function calculates the price at which the remaining position
    would break even, considering:
    - Fees paid on entry for the full position
    - Realized PnL from partial closures
    - Fees that will be paid on exit for the remaining position

    The formula ensures that closing the remaining position at the breakeven
    price results in zero total profit/loss after all fees.

    Args:
        entry_price: Original entry price for the position
        side: Position side (LONG or SHORT)
        qty_total: Total initial position quantity
        qty_remaining: Remaining position quantity after partial closures
        realized_pnl_gross: Gross realized PnL from partial closures (before fees)
        fees_config: Fee configuration for the exchange

    Returns:
        Breakeven price, or None if calculation is not possible

    Example:
        >>> fees = FeesConfig(maker=0.0002, taker=0.00055, break_even_fee_mode="taker", break_even_extra_buffer=0.0)
        >>> # Entered 100 BTC @ 50000, closed 30 BTC @ 51000 (profit: 30000 USDT)
        >>> be_price = calculate_breakeven_price(
        ...     entry_price=50000.0,
        ...     side=TradeSide.LONG,
        ...     qty_total=100.0,
        ...     qty_remaining=70.0,
        ...     realized_pnl_gross=30000.0,
        ...     fees_config=fees,
        ... )
        >>> # BE price will be lower than entry due to realized profit
    """
    if qty_remaining <= 0 or entry_price <= 0 or qty_total <= 0:
        return None

    fee = fees_config.get_break_even_fee_rate()

    # Fees paid on entry for the full position
    entry_notional = qty_total * entry_price
    fees_paid = entry_notional * fee

    # Realized PnL after subtracting entry fees
    realized_after_fees = realized_pnl_gross - fees_paid

    # Calculate breakeven price accounting for exit fees
    if side == TradeSide.LONG:
        # For LONG: BE = (remaining_qty * entry - realized_after_fees) / (remaining_qty * (1 - fee))
        denom = qty_remaining * max(1e-12, (1.0 - fee))
        return (qty_remaining * entry_price - realized_after_fees) / denom
    else:  # SHORT
        # For SHORT: BE = (realized_after_fees + remaining_qty * entry) / (remaining_qty * (1 + fee))
        denom = qty_remaining * (1.0 + fee)
        return (realized_after_fees + qty_remaining * entry_price) / max(1e-12, denom)


def calculate_realized_pnl(
    entry_price: float,
    exit_price: float,
    qty_closed: float,
    side: TradeSide,
) -> float:
    """Calculate realized PnL for a partial position closure.

    This calculates the gross profit/loss from closing part of a position,
    before accounting for fees.

    Args:
        entry_price: Original entry price
        exit_price: Price at which the position was partially closed
        qty_closed: Quantity that was closed
        side: Position side (LONG or SHORT)

    Returns:
        Realized PnL in quote currency (e.g., USDT)

    Example:
        >>> # Closed 30 BTC from a LONG position: entry 50000, exit 51000
        >>> pnl = calculate_realized_pnl(50000.0, 51000.0, 30.0, TradeSide.LONG)
        >>> pnl
        30000.0  # (51000 - 50000) * 30
    """
    if side == TradeSide.LONG:
        return (exit_price - entry_price) * qty_closed
    else:  # SHORT
        return (entry_price - exit_price) * qty_closed
