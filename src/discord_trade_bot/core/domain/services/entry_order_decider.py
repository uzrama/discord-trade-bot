"""Domain service for deciding entry order type (market vs limit).

This module provides logic to determine whether to use a market or limit order
for entering a position based on the signal's entry mode, entry price, and
current market price.
"""

from dataclasses import dataclass
from enum import StrEnum

from discord_trade_bot.core.domain.value_objects.trading import EntryMode, TradeSide


class OrderType(StrEnum):
    """Type of order to place for entry."""

    MARKET = "market"
    LIMIT = "limit"
    SKIP = "skip"


@dataclass(frozen=True, slots=True)
class EntryOrderDecision:
    """Decision about which order type to use for entry.

    Attributes:
        order_type: Type of order (market, limit, or skip)
        limit_price: Price for limit order (None for market orders)
        reason: Human-readable reason for the decision
    """

    order_type: OrderType
    limit_price: float | None
    reason: str


def decide_entry_order(
    entry_mode: EntryMode | None,
    entry_price: float | None,
    market_price: float,
    side: TradeSide,
    stop_loss: float | None = None,
) -> EntryOrderDecision:
    """Decide whether to use market or limit order for entry.

    Logic:
    - LONG: if market_price <= entry_price → check SL, then market or skip
    - SHORT: if market_price >= entry_price → check SL, then market or skip
    - If stop_loss exists and already hit → skip entry
    - CMP with entry_price: applies same logic as above
    - CMP without entry_price: always market
    - No entry_mode or invalid: skip

    Args:
        entry_mode: Entry mode from signal (CMP or EXACT_PRICE)
        entry_price: Entry price from signal (can be None for CMP)
        market_price: Current market price
        side: Trade side (LONG or SHORT)
        stop_loss: Stop loss price from signal (optional)

    Returns:
        EntryOrderDecision with order type, limit price, and reason

    Examples:
        >>> # LONG, market above entry → limit
        >>> decide_entry_order(EntryMode.EXACT_PRICE, 50000.0, 51000.0, TradeSide.LONG)
        EntryOrderDecision(order_type=OrderType.LIMIT, limit_price=50000.0, reason='buy_limit_above_entry')

        >>> # LONG, market below entry → market
        >>> decide_entry_order(EntryMode.EXACT_PRICE, 50000.0, 49000.0, TradeSide.LONG)
        EntryOrderDecision(order_type=OrderType.MARKET, limit_price=None, reason='market_buy_below_or_equal_entry')

        >>> # CMP without entry price → market
        >>> decide_entry_order(EntryMode.CMP, None, 50000.0, TradeSide.LONG)
        EntryOrderDecision(order_type=OrderType.MARKET, limit_price=None, reason='cmp_market_entry_no_reference')
    """
    # Validate inputs
    if not side or side not in (TradeSide.LONG, TradeSide.SHORT):
        return EntryOrderDecision(
            order_type=OrderType.SKIP,
            limit_price=None,
            reason="invalid_side",
        )

    if market_price <= 0:
        return EntryOrderDecision(
            order_type=OrderType.SKIP,
            limit_price=None,
            reason="invalid_market_price",
        )
    # Handle CMP mode
    if entry_mode == EntryMode.CMP:
        # CMP with reference price
        if entry_price is not None and entry_price > 0:
            if side == TradeSide.LONG:
                if market_price <= entry_price:
                    # Check if stop loss already hit
                    if stop_loss is not None and market_price <= stop_loss:
                        return EntryOrderDecision(
                            order_type=OrderType.SKIP,
                            limit_price=None,
                            reason=f"stop_loss_already_hit (Entry: {entry_price:.2f}, SL: {stop_loss:.2f}, Market: {market_price:.2f})",
                        )
                    return EntryOrderDecision(
                        order_type=OrderType.MARKET,
                        limit_price=None,
                        reason="cmp_market_buy_below_or_equal_reference",
                    )
                return EntryOrderDecision(
                    order_type=OrderType.LIMIT,
                    limit_price=float(entry_price),
                    reason="cmp_buy_limit_above_reference",
                )
            else:  # SHORT
                if market_price >= entry_price:
                    # Check if stop loss already hit
                    if stop_loss is not None and market_price >= stop_loss:
                        return EntryOrderDecision(
                            order_type=OrderType.SKIP,
                            limit_price=None,
                            reason=f"stop_loss_already_hit (Entry: {entry_price:.2f}, SL: {stop_loss:.2f}, Market: {market_price:.2f})",
                        )
                    return EntryOrderDecision(
                        order_type=OrderType.MARKET,
                        limit_price=None,
                        reason="cmp_market_sell_above_or_equal_reference",
                    )
                return EntryOrderDecision(
                    order_type=OrderType.LIMIT,
                    limit_price=float(entry_price),
                    reason="cmp_sell_limit_below_reference",
                )

        # CMP without reference price → always market
        return EntryOrderDecision(
            order_type=OrderType.MARKET,
            limit_price=None,
            reason="cmp_market_entry_no_reference",
        )

    # Handle EXACT_PRICE mode
    if entry_mode == EntryMode.EXACT_PRICE:
        if entry_price is None or entry_price <= 0:
            return EntryOrderDecision(
                order_type=OrderType.SKIP,
                limit_price=None,
                reason="exact_price_mode_but_no_entry_price",
            )

        if side == TradeSide.LONG:
            if market_price <= entry_price:
                # Check if stop loss already hit
                if stop_loss is not None and market_price <= stop_loss:
                    return EntryOrderDecision(
                        order_type=OrderType.SKIP,
                        limit_price=None,
                        reason=f"stop_loss_already_hit (Entry: {entry_price:.2f}, SL: {stop_loss:.2f}, Market: {market_price:.2f})",
                    )
                return EntryOrderDecision(
                    order_type=OrderType.MARKET,
                    limit_price=None,
                    reason="market_buy_below_or_equal_entry",
                )
            return EntryOrderDecision(
                order_type=OrderType.LIMIT,
                limit_price=float(entry_price),
                reason="buy_limit_above_entry",
            )
        else:  # SHORT
            if market_price >= entry_price:
                # Check if stop loss already hit
                if stop_loss is not None and market_price >= stop_loss:
                    return EntryOrderDecision(
                        order_type=OrderType.SKIP,
                        limit_price=None,
                        reason=f"stop_loss_already_hit (Entry: {entry_price:.2f}, SL: {stop_loss:.2f}, Market: {market_price:.2f})",
                    )
                return EntryOrderDecision(
                    order_type=OrderType.MARKET,
                    limit_price=None,
                    reason="market_sell_above_or_equal_entry",
                )
            return EntryOrderDecision(
                order_type=OrderType.LIMIT,
                limit_price=float(entry_price),
                reason="sell_limit_below_entry",
            )

    # No valid entry mode
    return EntryOrderDecision(
        order_type=OrderType.SKIP,
        limit_price=None,
        reason="invalid_entry_mode",
    )
