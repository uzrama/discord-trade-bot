import logging
from asyncio import Lock
from collections import defaultdict
from typing import Any, final

from discord_trade_bot.core.application.common.interfaces.notification import NotificationGatewayProtocol
from discord_trade_bot.core.application.common.interfaces.repository import StateRepositoryProtocol
from discord_trade_bot.core.application.trading.interfaces import ExchangeGatewayProtocol, ExchangeRegistryProtocol
from discord_trade_bot.core.domain.entities.position import ActivePositionEntity
from discord_trade_bot.core.domain.services.breakeven_calculator import calculate_realized_pnl
from discord_trade_bot.core.domain.value_objects.trading import BreakevenMoveResult, PositionStatus, TPDistributionRow, TradeSide
from discord_trade_bot.main.config.app import AppConfig

logger = logging.getLogger(__name__)


@final
class ProcessTrackerEventUseCase:
    """Use case for processing exchange WebSocket events and updating position state.

    This use case listens to order execution events from exchanges (via WebSocket)
    and updates position state accordingly. It handles take-profit hits, stop-loss
    execution, and automatic breakeven management with fee-adjusted calculations.

    Attributes:
        _exchange_registry: Registry for accessing exchange adapters.
        _state_repository: Repository for position state management.
        _notification_gateway: Gateway for sending notifications.
        _config: Application configuration including fees.
        _position_locks: Per-position locks to prevent race conditions.
    """

    def __init__(
        self,
        exchange_registry: ExchangeRegistryProtocol,
        state_repository: StateRepositoryProtocol,
        notification_gateway: NotificationGatewayProtocol,
        config: AppConfig,
    ):
        self._exchange_registry = exchange_registry
        self._state_repository = state_repository
        self._notification_gateway = notification_gateway
        self._config = config
        self._position_locks: dict[str, Lock] = defaultdict(Lock)

    async def execute(self, event: dict[str, Any]) -> None:
        """Process a WebSocket event and update position state.

        This method performs the following:
        1. Extract order information from the event
        2. Check if this is a pending entry fill
        3. Find matching open positions by symbol
        4. Lock the position to prevent concurrent updates
        5. Check if the order is a TP or SL execution
        6. Update position state and move SL to breakeven if needed
        7. Close position if all TPs are hit or SL is triggered
        8. Check pending entries for SL hit

        Args:
            event: WebSocket event dictionary containing order execution data.

        Note:
            Uses per-position locks to ensure thread-safe updates when multiple
            events arrive simultaneously for the same position.
        """
        order_info = event.get("o", {})
        order_id = str(order_info.get("i", ""))
        symbol = order_info.get("s", "")
        status = order_info.get("X", "")

        logger.info(f"WebSocket event for {symbol}: order_id={order_id}, status={status}, event_type={event.get('e')}")

        # Check if this is a pending entry fill
        if status == "FILLED":
            await self._handle_pending_entry_fill(event)

        # Check if this is a pending entry cancellation/expiration
        if status in {"CANCELED", "CANCELLED", "EXPIRED", "REJECTED"}:
            await self._handle_pending_entry_cancellation(event)

        # Check pending entries for SL hit (price monitoring)
        await self._check_pending_entries_sl_hit(symbol)

        # Continue with existing logic for active positions
        # For conditional orders (TP/SL), Binance uses 'si' (algoId), otherwise 'i' (orderId)
        order_id = str(order_info.get("si") or order_info.get("i", ""))
        active_positions = await self._state_repository.get_open_positions()

        # Filter positions by symbol first (in memory, no DB query)
        matching_positions = [p for p in active_positions if p.symbol == symbol and p.id]

        if not matching_positions:
            logger.debug(f"No open positions found for {symbol}")
            return

        for position in matching_positions:
            position_id = position.id
            if not position_id:  # Extra safety check for type checker
                continue

            # Lock this specific position to prevent race conditions
            async with self._position_locks[position_id]:
                # Re-fetch only THIS position inside lock to get latest state
                position = await self._state_repository.get_position_by_id(position_id)
                if not position or position.status != PositionStatus.OPEN:
                    continue
                # Check for Take Profit execution
                if order_id in position.tp_order_ids:
                    tp_price = position.tp_order_ids.get(order_id, 0.0)
                    logger.info(f"🎯 [USE CASE] Take profit {tp_price} reached for {symbol}!")

                    # Calculate TP quantity based on distribution
                    # For the last TP: close entire remaining quantity to avoid rounding issues
                    is_last_tp = position.tp_index_hit == len(position.take_profits) - 1

                    if is_last_tp:
                        # Last TP: close all remaining quantity
                        tp_qty = position.remaining_qty
                        logger.info(f"📊 [USE CASE] Last TP - closing entire remaining quantity: {tp_qty:.8f}")
                    elif position.tp_index_hit < len(position.tp_distribution):
                        tp_pct = position.tp_distribution[position.tp_index_hit].close_pct
                        tp_qty = position.qty * (tp_pct / 100.0)
                    else:
                        # Fallback: equal distribution
                        tp_qty = position.qty / len(position.take_profits)

                    # Calculate realized PnL for this TP
                    realized_pnl = calculate_realized_pnl(
                        entry_price=position.entry_price,
                        exit_price=float(tp_price),
                        qty_closed=tp_qty,
                        side=position.side,
                    )

                    # Update position state
                    position.closed_qty += tp_qty
                    position.remaining_qty = position.qty - position.closed_qty
                    position.realized_pnl_usdt += realized_pnl

                    logger.info(
                        f"📊 [USE CASE] TP{position.tp_index_hit + 1} stats: "
                        f"closed_qty={tp_qty:.2f}, remaining_qty={position.remaining_qty:.2f}, "
                        f"realized_pnl={realized_pnl:.2f} USDT (total: {position.realized_pnl_usdt:.2f} USDT)"
                    )

                    # Move SL to breakeven after first TP if not already done
                    if not position.breakeven_applied:
                        await self._move_sl_to_breakeven(position)

                    position.tp_index_hit += 1

                    # Check if position is closed first
                    if position.tp_index_hit >= len(position.take_profits):
                        logger.info(f"DONE [USE CASE] All TPs for {symbol} reached. Position closed.")
                        position.status = PositionStatus.CLOSED
                    # Move SL to TP1 after third TP is hit (only if more TPs remain)
                    elif position.tp_index_hit == 3 and len(position.take_profits) > 3:
                        await self._move_sl_to_tp1(position)

                    await self._state_repository.save_position(position)
                    break
                # Check for Stop Loss execution
                elif order_id == str(position.sl_order_id):
                    logger.info(f"🛑 [USE CASE] Stop Loss filled for {symbol}. Position closed.")

                    # Get exchange to cancel remaining TP orders
                    exchange = self._exchange_registry.get_exchange(position.exchange)
                    await self._cancel_remaining_tp_orders(position, exchange)

                    # Cancel all orders for the symbol from exchange
                    await self._cancel_all_orders_for_symbol_from_exchange(symbol, exchange)

                    position.status = PositionStatus.CLOSED
                    await self._state_repository.save_position(position)
                    break

    def _get_position_size(self, position_info: dict[str, Any]) -> float:
        """
        Get position size from exchange data.

        Supports both Binance and Bybit formats.

        Args:
            position_info: Position data from exchange

        Returns:
            Absolute position size (always positive)
        """
        if not position_info:
            return 0.0

        # Binance format: {"positionAmt": "0.001", ...}
        if "positionAmt" in position_info:
            return abs(float(position_info.get("positionAmt", 0)))

        # Bybit format: {"size": "0.001", "side": "Buy", ...}
        if "size" in position_info:
            return float(position_info.get("size", 0))

        logger.warning(f"⚠️ Unknown position format: {position_info}")
        return 0.0

    async def _move_sl_to_breakeven(self, position: ActivePositionEntity) -> BreakevenMoveResult:
        """Move SL to breakeven (entry price) with fallback strategies.

        This method implements a three-tier strategy:
        1. Try entry price adjusted for fees (true breakeven)
        2. Fallback: Try default_sl_percent from current price
        3. Emergency: Close entire position with market order

        Args:
            position: Active position entity

        Returns:
            Result of the breakeven move attempt
        """
        symbol = position.symbol
        exchange_name = position.exchange
        exchange = self._exchange_registry.get_exchange(exchange_name)

        # Get source config for default_sl_percent
        source_config = self._get_source_config(position.source_id)
        if not source_config:
            logger.error(f"Cannot move SL: source config not found for {position.source_id}")
            position.breakeven_applied = True
            return BreakevenMoveResult.POSITION_ALREADY_CLOSED

        # Check if position still exists on exchange
        try:
            position_info = await exchange.get_position(symbol)

            # Use helper method to get position size (supports both Binance and Bybit)
            position_amt = self._get_position_size(position_info)

            if position_amt < 0.0001:
                logger.warning(f"⚠️ Position for {symbol} is already closed or too small ({position_amt})")
                position.breakeven_applied = True
                return BreakevenMoveResult.POSITION_ALREADY_CLOSED

            logger.info(f"✅ Position confirmed for {symbol}: {position_amt} units")
        except Exception as e:
            logger.warning(f"Could not check position for {symbol}: {e}")

        # Get current market price
        try:
            current_price = await exchange.get_last_price(symbol)
        except Exception as e:
            logger.error(f"Could not get current price for {symbol}: {e}")
            position.breakeven_applied = True
            return BreakevenMoveResult.POSITION_ALREADY_CLOSED

        # ============================================================
        # ATTEMPT 1: SL at entry price (breakeven with fee adjustment)
        # ============================================================

        be_price = self._calculate_entry_based_sl(position)

        logger.info(
            f"🛡️ [USE CASE] Moving Stop Loss to entry price (breakeven) for {symbol}...\n"
            f"  Entry: {position.entry_price:.8f}\n"
            f"  SL (Entry + fees): {be_price:.8f}\n"
            f"  Current price: {current_price:.8f}\n"
            f"  Remaining qty: {position.remaining_qty:.2f}\n"
            f"  Realized PnL: {position.realized_pnl_usdt:.2f} USDT"
        )

        # Check if distance is valid
        if self._is_sl_distance_valid(be_price, current_price, position.side):
            if await self._try_move_sl(position, exchange, be_price, "entry_breakeven"):
                msg = f"🛡️ **{symbol}**: Stop loss moved to breakeven (entry price)!\n  Entry: {position.entry_price:.8f}\n  SL: {be_price:.8f}\n  Remaining: {position.remaining_qty:.2f}"
                logger.info(msg)
                await self._notification_gateway.send_message(msg)
                return BreakevenMoveResult.SUCCESS
        else:
            logger.warning(f"⚠️ Entry-based SL {be_price:.8f} too close to market {current_price:.8f}, trying fallback...")

        # ============================================================
        # ATTEMPT 2: Fallback to default_sl_percent from current price
        # ============================================================

        default_sl_pct = source_config.default_sl_percent / 100.0

        if position.side == TradeSide.LONG:
            fallback_sl = current_price * (1 - default_sl_pct)
        else:  # SHORT
            fallback_sl = current_price * (1 + default_sl_pct)

        logger.info(
            f"🔄 [FALLBACK] Attempting SL with default_sl_percent for {symbol}\n"
            f"  Current price: {current_price:.8f}\n"
            f"  default_sl_percent: {source_config.default_sl_percent}%\n"
            f"  Fallback SL: {fallback_sl:.8f}"
        )

        # Check if distance is valid
        if self._is_sl_distance_valid(fallback_sl, current_price, position.side):
            if await self._try_move_sl(position, exchange, fallback_sl, f"fallback_{source_config.default_sl_percent}%"):
                msg = (
                    f"⚠️ **{symbol}**: SL moved using fallback strategy!\n"
                    f"  Method: {source_config.default_sl_percent}% from current price\n"
                    f"  SL Price: {fallback_sl:.8f}\n"
                    f"  Reason: Calculated BE too close to market (high volatility)"
                )
                logger.warning(msg)
                await self._notification_gateway.send_message(msg)
                return BreakevenMoveResult.SUCCESS_FALLBACK
        else:
            logger.error(f"❌ Fallback SL {fallback_sl:.8f} also too close to market {current_price:.8f}, emergency close required!")

        # ============================================================
        # ATTEMPT 3: Emergency - Close entire position
        # ============================================================

        logger.error(f"🚨 [EMERGENCY] All SL move attempts failed for {symbol}, closing position...")

        try:
            await self._close_position_market(position, exchange)

            msg = (
                f"🚨 **{symbol}**: Position closed (EMERGENCY)\n"
                f"  Reason: Extreme volatility - unable to set protective SL\n"
                f"  Closed qty: {position.remaining_qty:.2f}\n"
                f"  Realized PnL: {position.realized_pnl_usdt:.2f} USDT"
            )
            logger.error(msg)
            await self._notification_gateway.send_message(msg)

            return BreakevenMoveResult.POSITION_CLOSED

        except Exception as e:
            logger.critical(f"💀 CRITICAL: Failed to close position {symbol}: {e}")
            position.breakeven_applied = True  # Mark to avoid infinite retry

            msg = f"💀 **{symbol}**: CRITICAL - Failed to close position: {e}"
            await self._notification_gateway.send_message(msg)

            return BreakevenMoveResult.POSITION_CLOSED

    def _is_sl_distance_valid(self, sl_price: float, current_price: float, side: TradeSide, min_distance_pct: float = 0.3) -> bool:
        """Check if SL price is far enough from current market price.

        Args:
            sl_price: Proposed stop loss price
            current_price: Current market price
            side: Position side (LONG or SHORT)
            min_distance_pct: Minimum distance in percentage (default: 0.3%)

        Returns:
            True if distance is valid, False otherwise
        """
        distance_pct = abs(sl_price - current_price) / current_price * 100

        # Check minimum distance
        if distance_pct < min_distance_pct:
            logger.debug(f"SL distance {distance_pct:.3f}% < {min_distance_pct}% (too close to market)")
            return False

        # Check direction (SL must be below market for LONG, above for SHORT)
        if side == TradeSide.LONG and sl_price >= current_price:
            logger.debug(f"SL {sl_price} >= current {current_price} for LONG (wrong direction)")
            return False

        if side == TradeSide.SHORT and sl_price <= current_price:
            logger.debug(f"SL {sl_price} <= current {current_price} for SHORT (wrong direction)")
            return False

        return True

    async def _try_move_sl(self, position: ActivePositionEntity, exchange: ExchangeGatewayProtocol, stop_price: float, reason: str) -> bool:
        """Try to move SL to specified price.

        Args:
            position: Active position entity
            exchange: Exchange gateway
            stop_price: New stop loss price
            reason: Reason for this attempt (for logging)

        Returns:
            True if successful, False otherwise
        """
        symbol = position.symbol

        try:
            # Get symbol info for precision
            symbol_info = await exchange.get_symbol_info(symbol)
            price_precision = symbol_info.get("price_precision", 8)
            qty_precision = symbol_info.get("qty_precision", 3)

            # Round price and quantity to exchange precision
            stop_price_rounded = self._round_price(stop_price, price_precision)
            self._round_quantity(position.remaining_qty, qty_precision)

            logger.debug(f"Rounding for {symbol}: stop_price {stop_price:.8f} -> {stop_price_rounded:.8f}")

            # Cancel old SL if exists
            if position.sl_order_id:
                try:
                    await exchange.cancel_order(symbol, position.sl_order_id)
                    logger.debug(f"✅ Cancelled old SL {position.sl_order_id}")
                except Exception as e:
                    logger.debug(f"Could not cancel old SL {position.sl_order_id}: {e}")

            # Create new SL with qty=None for full position close
            # This avoids issues with quantity calculation and ensures entire position is closed
            res = await exchange.place_stop_market_order(
                symbol=symbol,
                side=position.side,
                stop_price=stop_price_rounded,
                qty=None,  # Full position close
            )

            new_sl_id = str(res.get("algoId") or res.get("orderId") or "")
            position.sl_order_id = new_sl_id
            position.breakeven_applied = True
            position.break_even_price = stop_price_rounded

            logger.info(f"✅ SL moved to {stop_price_rounded:.8f} ({reason}) for {symbol}, new SL ID: {new_sl_id}")
            return True

        except Exception as e:
            logger.warning(f"Failed to move SL ({reason}): {e}")
            return False

    async def _cancel_remaining_tp_orders(self, position: ActivePositionEntity, exchange: ExchangeGatewayProtocol) -> None:
        """Cancel all remaining TP orders after SL hit or position close.

        This method uses a two-step approach:
        1. Try to cancel by known TP order IDs (if available)
        2. Fallback: Cancel all orders for the symbol (guarantees cleanup)

        Args:
            position: Active position entity
            exchange: Exchange gateway
        """
        symbol = position.symbol

        # Step 1: Cancel by known TP order IDs
        tp_order_ids = position.tp_order_ids or {}
        if tp_order_ids:
            cancelled_count = 0
            for tp_order_id, tp_price in tp_order_ids.items():
                try:
                    await exchange.cancel_order(symbol, tp_order_id)
                    cancelled_count += 1
                    logger.info(f"✅ Cancelled TP order {tp_order_id} (price={tp_price:.8f}) for {symbol}")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to cancel TP order {tp_order_id}: {e}")

            logger.info(f"🗑️ Cancelled {cancelled_count}/{len(tp_order_ids)} TP orders for {symbol}")
        else:
            logger.debug(f"No TP order IDs stored for {symbol}, will use fallback")

        # Step 2: Fallback - cancel all orders for the symbol (guarantees cleanup)
        try:
            await exchange.cancel_all_orders(symbol)
            logger.info(f"✅ Cancelled all remaining orders for {symbol} (fallback)")
        except Exception as e:
            logger.warning(f"⚠️ Failed to cancel all orders for {symbol}: {e}")

    async def _cancel_all_orders_for_symbol_from_exchange(self, symbol: str, exchange: ExchangeGatewayProtocol) -> None:
        """Cancel all open orders for symbol directly from exchange after SL trigger.

        This method uses a direct exchange approach:
        1. Cancel all orders for the symbol via exchange API
        2. Clean up pending entry from database (if exists)

        Args:
            symbol: Trading pair symbol
            exchange: Exchange gateway
        """
        logger.info(f"🗑️ [SL TRIGGER] Cancelling all orders for {symbol} from exchange")

        # Step 1: Cancel all orders for the symbol
        try:
            await exchange.cancel_all_orders(symbol)
            logger.info(f"✅ Cancelled all orders for {symbol}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to cancel all orders for {symbol}: {e}")

        # Step 2: Clean up pending entry from database (if exists)
        try:
            pending_entry = await self._state_repository.get_pending_entry_by_symbol(symbol)
            if pending_entry:
                await self._state_repository.delete_pending_entry(symbol)
                logger.info(f"✅ Removed pending entry for {symbol} from database")
            else:
                logger.debug(f"No pending entry found in database for {symbol}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to clean up pending entry for {symbol}: {e}")

    async def _close_position_market(self, position: ActivePositionEntity, exchange: ExchangeGatewayProtocol) -> None:
        """Close position with market order (emergency).

        Args:
            position: Active position entity
            exchange: Exchange gateway
        """
        symbol = position.symbol

        # Cancel all TP orders before closing position
        await self._cancel_remaining_tp_orders(position, exchange)

        close_side = TradeSide.SHORT if position.side == TradeSide.LONG else TradeSide.LONG

        # Get symbol info for precision
        symbol_info = await exchange.get_symbol_info(symbol)
        qty_precision = symbol_info.get("qty_precision", 3)

        # Round quantity to exchange precision
        qty_rounded = self._round_quantity(position.remaining_qty, qty_precision)

        logger.warning(f"🚨 Emergency closing position {symbol}: remaining_qty={qty_rounded:.8f}")

        # Close position with market order
        await exchange.place_market_order(symbol=symbol, side=close_side, qty=qty_rounded, reduce_only=True)

        position.status = PositionStatus.CLOSED
        position.breakeven_applied = True
        await self._state_repository.save_position(position)

        logger.info(f"✅ Position {symbol} closed successfully (emergency)")

    def _round_quantity(self, qty: float, precision: int) -> float:
        """Round quantity to exchange precision.

        Args:
            qty: Quantity to round
            precision: Number of decimal places

        Returns:
            Rounded quantity
        """
        return round(qty, precision)

    def _round_price(self, price: float, precision: int) -> float:
        """Round price to exchange precision.

        Args:
            price: Price to round
            precision: Number of decimal places

        Returns:
            Rounded price
        """
        return round(price, precision)

    def _calculate_entry_based_sl(self, position: ActivePositionEntity) -> float:
        """Calculate SL price at entry level accounting for fees.

        This places the stop loss at the entry price, adjusted for fees to ensure
        that if the SL is hit, the overall trade breaks even (accounting for fees).

        Args:
            position: Active position entity

        Returns:
            SL price at entry level (adjusted for fees)
        """
        entry_price = position.entry_price
        fee_rate = self._config.fees.get_break_even_fee_rate()

        # Calculate fees for closing remaining position at entry level
        remaining_notional = position.remaining_qty * entry_price
        fees_for_close = remaining_notional * fee_rate

        # Adjust SL from entry to account for fees
        fee_per_unit = fees_for_close / position.remaining_qty

        if position.side == TradeSide.LONG:
            # For LONG: SL slightly above entry to cover fees
            return entry_price + fee_per_unit
        else:  # SHORT
            # For SHORT: SL slightly below entry to cover fees
            return entry_price - fee_per_unit

    async def _move_sl_to_tp1(self, position: ActivePositionEntity) -> None:
        """Move SL to TP1 level after TP3 is hit.

        This method moves the stop loss to the TP1 level (adjusted for fees)
        after the third take profit has been executed, locking in more profit.

        Args:
            position: Active position entity
        """
        symbol = position.symbol
        exchange_name = position.exchange
        exchange = self._exchange_registry.get_exchange(exchange_name)

        # Check if TP1 exists
        if not position.take_profits or len(position.take_profits) < 1:
            logger.warning(f"⚠️ Cannot move SL to TP1 for {symbol}: no TP1 defined")
            return

        tp1_price = position.take_profits[0]
        fee_rate = self._config.fees.get_break_even_fee_rate()

        # Calculate fees for closing remaining position at TP1 level
        remaining_notional = position.remaining_qty * tp1_price
        fees_for_close = remaining_notional * fee_rate
        fee_per_unit = fees_for_close / position.remaining_qty

        # Adjust SL from TP1 to account for fees
        if position.side == TradeSide.LONG:
            # For LONG: SL slightly below TP1 to cover fees
            sl_price = tp1_price - fee_per_unit
        else:  # SHORT
            # For SHORT: SL slightly above TP1 to cover fees
            sl_price = tp1_price + fee_per_unit

        # Get current market price for validation
        try:
            current_price = await exchange.get_last_price(symbol)
        except Exception as e:
            logger.error(f"Could not get current price for {symbol}: {e}")
            return

        logger.info(
            f"🛡️ [USE CASE] Moving Stop Loss to TP1 level after TP3 for {symbol}...\n"
            f"  TP1: {tp1_price:.8f}\n"
            f"  SL (TP1 - fees): {sl_price:.8f}\n"
            f"  Current price: {current_price:.8f}\n"
            f"  Remaining qty: {position.remaining_qty:.2f}"
        )

        # Check if distance is valid
        if self._is_sl_distance_valid(sl_price, current_price, position.side):
            if await self._try_move_sl(position, exchange, sl_price, "tp1_after_tp3"):
                msg = f"🛡️ **{symbol}**: Stop loss moved to TP1 level (after TP3)!\n  TP1: {tp1_price:.8f}\n  SL: {sl_price:.8f}\n  Remaining: {position.remaining_qty:.2f}"
                logger.info(msg)
                await self._notification_gateway.send_message(msg)
            else:
                logger.warning(f"⚠️ Failed to move SL to TP1 for {symbol} after TP3")
        else:
            logger.warning(f"⚠️ TP1-based SL {sl_price:.8f} too close to market {current_price:.8f} after TP3 for {symbol}, keeping current SL")

    def _get_source_config(self, source_id: str):
        """Get source configuration by source_id.

        Args:
            source_id: Source identifier

        Returns:
            Source configuration or None if not found
        """
        for source in self._config.yaml.discord.watch_sources:
            if source.source_id == source_id:
                return source

        logger.warning(f"Source config not found for {source_id}")
        return None

    def _convert_tp_distribution(self, tp_dist: list[TPDistributionRow]) -> dict[int, list[dict[str, Any]]]:
        """Convert TPDistributionRow list to dict format for exchange adapter.

        Args:
            tp_dist: List of TPDistributionRow objects

        Returns:
            Dictionary mapping number of TPs to distribution list
        """
        if not tp_dist:
            return {}

        num_tps = len(tp_dist)
        return {num_tps: [{"label": row.label, "close_pct": row.close_pct} for row in tp_dist]}

    async def _handle_pending_entry_fill(self, event: dict[str, Any]) -> None:
        """Handle limit order fill for pending entries.

        When a pending limit order is filled:
        1. Check if this order_id matches a pending entry
        2. Wait for position to be confirmed on exchange
        3. Place SL/TP orders
        4. Send notification
        5. Delete pending entry (position is now active)

        Args:
            event: WebSocket event dictionary
        """
        order_info = event.get("o", {})
        order_id = str(order_info.get("i", ""))
        symbol = order_info.get("s", "")

        # Check if this is a pending entry
        pending_entry = await self._state_repository.get_pending_entry_by_symbol(symbol)

        if not pending_entry or pending_entry.order_id != order_id:
            return  # Not a pending entry, skip

        logger.info(f"🎯 Pending limit order filled for {symbol}!")

        # Get exchange adapter
        exchange = self._exchange_registry.get_exchange(pending_entry.exchange)

        # Wait for position to be confirmed (similar to market orders)
        logger.info(f"⏳ Waiting for position {symbol} to be confirmed after limit fill...")
        position_ready = await exchange.wait_for_position_ready(
            symbol=symbol,
            side=pending_entry.side,
            timeout=10.0,
        )

        if not position_ready:
            # Critical error: position not confirmed
            error_msg = f"Position {symbol} not confirmed after limit fill. SL/TP NOT placed - MANUAL INTERVENTION REQUIRED!"
            logger.critical(f"🚨 {error_msg}")
            await self._notification_gateway.send_message(f"🚨 CRITICAL: {error_msg}")
            return

        # Place missing orders if needed
        sl_tp_res = {}

        # Check if all orders are already placed
        if pending_entry.sl_tp_attached and pending_entry.sl_order_id and pending_entry.tp_order_ids:
            # All orders already placed, nothing to do
            logger.info(f"✅ SL/TP already active for {symbol} (placed with limit order)")

            # Build notification message
            side_str = "LONG" if pending_entry.side == TradeSide.LONG else "SHORT"
            message = f"✅ Limit order FILLED for {side_str} on {symbol}\n"
            message += f"Entry Price: {pending_entry.entry_price}\n"
            message += f"Qty: {pending_entry.qty}\n"

            if pending_entry.stop_loss:
                message += f"✅ SL: {pending_entry.stop_loss} (already active)\n"

            if pending_entry.take_profits:
                tp_count = len(pending_entry.tp_order_ids)
                tp_expected = len(pending_entry.take_profits)
                message += f"✅ TP: {tp_count}/{tp_expected} targets (already active)"

            await self._notification_gateway.send_message(message)

        elif pending_entry.stop_loss or pending_entry.take_profits:
            # Some orders missing, place them now
            try:
                tp_distribution = self._convert_tp_distribution(pending_entry.tp_distribution)

                # Determine what needs to be placed
                need_sl = pending_entry.stop_loss and not pending_entry.sl_order_id
                need_tp = pending_entry.take_profits and not pending_entry.tp_order_ids

                if need_sl and need_tp:
                    logger.info(f"📊 Placing missing SL/TP orders for {symbol}")
                    sl_tp_res = await exchange.place_sl_tp_orders(
                        symbol=symbol,
                        side=pending_entry.side,
                        stop_loss=pending_entry.stop_loss,
                        take_profits=pending_entry.take_profits,
                        qty=pending_entry.qty,
                        tp_distribution=tp_distribution,
                    )
                elif need_sl:
                    logger.info(f"📊 Placing missing SL order for {symbol}")
                    sl_tp_res = await exchange.place_sl_tp_orders(
                        symbol=symbol,
                        side=pending_entry.side,
                        stop_loss=pending_entry.stop_loss,
                        take_profits=[],
                        qty=pending_entry.qty,
                        tp_distribution=tp_distribution,
                    )
                elif need_tp:
                    logger.info(f"📊 Placing missing TP orders for {symbol}")
                    sl_tp_res = await exchange.place_sl_tp_orders(
                        symbol=symbol,
                        side=pending_entry.side,
                        stop_loss=None,
                        take_profits=pending_entry.take_profits,
                        qty=pending_entry.qty,
                        tp_distribution=tp_distribution,
                    )

                logger.info(f"✅ Missing orders placed for {symbol} after limit fill")

                # Build notification message
                side_str = "LONG" if pending_entry.side == TradeSide.LONG else "SHORT"
                message = f"✅ Limit order FILLED for {side_str} on {symbol}\n"
                message += f"Entry Price: {pending_entry.entry_price}\n"
                message += f"Qty: {pending_entry.qty}\n"

                if pending_entry.stop_loss:
                    if pending_entry.sl_order_id:
                        message += f"✅ SL: {pending_entry.stop_loss} (already active)\n"
                    elif sl_tp_res.get("stop_loss"):
                        message += f"✅ SL: {pending_entry.stop_loss}\n"
                    else:
                        message += "⚠️ SL: Failed to place\n"

                if pending_entry.take_profits:
                    already_placed = len(pending_entry.tp_order_ids)
                    newly_placed = len(sl_tp_res.get("take_profits", []))
                    total_placed = already_placed + newly_placed
                    tp_expected = len(pending_entry.take_profits)

                    if total_placed == tp_expected:
                        message += f"✅ TP: {total_placed}/{tp_expected} targets"
                    elif total_placed > 0:
                        message += f"⚠️ TP: {total_placed}/{tp_expected} targets"
                    else:
                        message += f"❌ TP: 0/{tp_expected} targets"

                await self._notification_gateway.send_message(message)

            except Exception as e:
                logger.error(f"❌ Failed to place missing orders after limit fill for {symbol}: {e}", exc_info=True)
                await self._notification_gateway.send_message(f"⚠️ Limit filled for {symbol} but order placement failed: {e}")

        # Delete pending entry (position is now active and will be tracked normally)
        await self._state_repository.delete_pending_entry(symbol)
        logger.info(f"✅ Pending entry for {symbol} processed and removed")

    async def _handle_pending_entry_cancellation(self, event: dict[str, Any]) -> None:
        """Handle limit order cancellation/expiration for pending entries.

        When a pending limit order is cancelled or expires:
        1. Check if this order_id matches a pending entry
        2. Cancel the protective SL order if it was placed
        3. Send notification
        4. Delete pending entry

        Args:
            event: WebSocket event dictionary
        """
        order_info = event.get("o", {})
        order_id = str(order_info.get("i", ""))
        symbol = order_info.get("s", "")
        status = order_info.get("X", "")

        # Check if this is a pending entry
        pending_entry = await self._state_repository.get_pending_entry_by_symbol(symbol)

        if not pending_entry or pending_entry.order_id != order_id:
            return  # Not a pending entry, skip

        logger.info(f"🚫 Pending limit order {status} for {symbol}")

        # Get exchange adapter
        exchange = self._exchange_registry.get_exchange(pending_entry.exchange)

        # Cancel protective SL and TP orders if they were placed
        cancelled_orders = []

        # Cancel SL order
        if pending_entry.sl_order_id:
            try:
                logger.info(f"🗑️ Cancelling protective SL order {pending_entry.sl_order_id} for {symbol}")
                await exchange.cancel_order(symbol, pending_entry.sl_order_id)
                cancelled_orders.append("SL")
                logger.info(f"✅ Protective SL order cancelled for {symbol}")
            except Exception as e:
                logger.error(f"⚠️ Failed to cancel protective SL for {symbol}: {e}")

        # Cancel all TP orders
        if pending_entry.tp_order_ids:
            for i, tp_order_id in enumerate(pending_entry.tp_order_ids, start=1):
                try:
                    logger.info(f"🗑️ Cancelling protective TP{i} order {tp_order_id} for {symbol}")
                    await exchange.cancel_order(symbol, tp_order_id)
                    cancelled_orders.append(f"TP{i}")
                    logger.info(f"✅ Protective TP{i} order cancelled for {symbol}")
                except Exception as e:
                    logger.error(f"⚠️ Failed to cancel protective TP{i} for {symbol}: {e}")

        # Send notification
        side_str = "LONG" if pending_entry.side == TradeSide.LONG else "SHORT"
        message = f"🚫 Limit order {status} for {side_str} on {symbol}\n"
        message += f"Entry Price: {pending_entry.entry_price}\n"
        message += f"Qty: {pending_entry.qty}"

        if cancelled_orders:
            message += f"\n✅ Cancelled: {', '.join(cancelled_orders)}"

        await self._notification_gateway.send_message(message)

        # Delete pending entry
        await self._state_repository.delete_pending_entry(symbol)
        logger.info(f"✅ Cancelled pending entry for {symbol} removed")

    async def _check_pending_entries_sl_hit(self, symbol: str) -> None:
        """Check if pending entries have their SL hit by current price.

        This method monitors pending limit orders and cancels them if the current
        market price touches the stop loss level before the limit order is filled.

        Args:
            symbol: Trading pair symbol to check
        """
        # Get pending entry for this symbol
        pending_entry = await self._state_repository.get_pending_entry_by_symbol(symbol)

        if not pending_entry:
            return  # No pending entry for this symbol

        # Skip if no stop loss defined
        if not pending_entry.stop_loss:
            return

        # Get exchange adapter
        exchange = self._exchange_registry.get_exchange(pending_entry.exchange)

        # Get current market price
        try:
            current_price = await exchange.get_last_price(symbol)
        except Exception as e:
            logger.warning(f"⚠️ Could not get current price for {symbol} to check pending SL: {e}")
            return

        # Check if SL is hit based on side
        sl_hit = False

        if pending_entry.side == TradeSide.LONG:
            # For LONG: SL hit if current price <= stop loss
            if current_price <= pending_entry.stop_loss:
                sl_hit = True
                logger.warning(f"🛑 [PENDING SL HIT] LONG limit order for {symbol}: current price {current_price:.8f} <= SL {pending_entry.stop_loss:.8f}")
        else:  # SHORT
            # For SHORT: SL hit if current price >= stop loss
            if current_price >= pending_entry.stop_loss:
                sl_hit = True
                logger.warning(f"🛑 [PENDING SL HIT] SHORT limit order for {symbol}: current price {current_price:.8f} >= SL {pending_entry.stop_loss:.8f}")

        if not sl_hit:
            return  # SL not hit, nothing to do

        # SL is hit - cancel limit order and protective orders
        logger.info(f"🚫 Cancelling pending limit order for {symbol} due to SL hit")

        # Cancel the limit order
        try:
            await exchange.cancel_order(symbol, pending_entry.order_id)
            logger.info(f"✅ Cancelled limit order {pending_entry.order_id} for {symbol}")
        except Exception as e:
            logger.error(f"⚠️ Failed to cancel limit order {pending_entry.order_id} for {symbol}: {e}")

        # Cancel protective SL order if exists
        if pending_entry.sl_order_id:
            try:
                await exchange.cancel_order(symbol, pending_entry.sl_order_id)
                logger.info(f"✅ Cancelled protective SL order {pending_entry.sl_order_id} for {symbol}")
            except Exception as e:
                logger.error(f"⚠️ Failed to cancel protective SL for {symbol}: {e}")

        # Cancel all protective TP orders
        if pending_entry.tp_order_ids:
            for i, tp_order_id in enumerate(pending_entry.tp_order_ids, start=1):
                try:
                    await exchange.cancel_order(symbol, tp_order_id)
                    logger.info(f"✅ Cancelled protective TP{i} order {tp_order_id} for {symbol}")
                except Exception as e:
                    logger.error(f"⚠️ Failed to cancel protective TP{i} for {symbol}: {e}")

        # Send notification
        side_str = "LONG" if pending_entry.side == TradeSide.LONG else "SHORT"
        message = (
            f"🛑 **{symbol}**: Limit order cancelled - SL hit before entry!\n"
            f"Side: {side_str}\n"
            f"Entry Price: {pending_entry.entry_price:.8f}\n"
            f"Stop Loss: {pending_entry.stop_loss:.8f}\n"
            f"Current Price: {current_price:.8f}\n"
            f"Reason: Price touched SL level before limit order filled"
        )
        await self._notification_gateway.send_message(message)

        # Delete pending entry from database
        await self._state_repository.delete_pending_entry(symbol)
        logger.info(f"✅ Pending entry for {symbol} removed due to SL hit")
