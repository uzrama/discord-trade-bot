import asyncio
import logging
from asyncio import Lock
from collections import defaultdict
from typing import Any, final

from discord_trade_bot.core.application.common.interfaces.notification import NotificationGatewayProtocol
from discord_trade_bot.core.application.common.interfaces.repository import StateRepositoryProtocol
from discord_trade_bot.core.application.trading.interfaces import ExchangeGatewayProtocol, ExchangeRegistryProtocol
from discord_trade_bot.core.domain.entities.position import ActivePositionEntity
from discord_trade_bot.core.domain.services.breakeven_calculator import calculate_breakeven_price, calculate_realized_pnl
from discord_trade_bot.core.domain.value_objects.trading import BreakevenMoveResult, PositionStatus, TradeSide
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

        logger.warning(f"WebSocket event for {symbol}: order_id={order_id}, status={status}, event_type={event.get('e')}")
        # Check if this is a protective TP trigger for pending entry
        # Strategy: Check if there's a limit order on exchange (means position not opened yet)
        if status == "Rejected":
            try:
                # Get exchange (composite will use default exchange)
                exchange = self._exchange_registry.get_exchange("composite")

                # Get all open orders for this symbol from exchange (with retry)
                open_orders = await self._get_open_orders_with_retry(exchange, symbol, max_retries=3)
                # Check if there's a limit order (pending entry not filled yet)
                limit_orders = [order for order in open_orders if order.get("orderType") == "Limit" and order.get("stopOrderType") == ""]
                if limit_orders:
                    # Cancel ALL orders for this symbol (limit + all protective orders)
                    logger.info(f"🚫 Cancelling all orders for {symbol}")
                    await exchange.cancel_all_orders(symbol)
                    logger.info(f"✅ All orders cancelled for {symbol}")

                    # Delete pending entry from database
                    await self._state_repository.delete_pending_entry(symbol)
                    logger.info(f"✅ Pending entry removed for {symbol} after protective TP trigger")

                    return  # Stop further processing - don't treat as active position TP

            except Exception as e:
                logger.warning(f"⚠️ Failed to check open orders for {symbol}: {e}")
                # Continue to active position logic if check fails

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
                # position = await self._state_repository.get_position_by_id(position_id)
                if not position:
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

                        # Cancel remaining orders (SL, reentry, etc.)
                        exchange = self._exchange_registry.get_exchange(position.exchange)
                        await self._cancel_all_position_orders(position, exchange)

                        position.status = PositionStatus.CLOSED
                    # Move SL to TP1 after third TP is hit (only if more TPs remain)
                    elif position.tp_index_hit == 3 and len(position.take_profits) > 3:
                        await self._move_sl_to_tp1(position)

                    await self._state_repository.save_position(position)
                    break
                # Check for Stop Loss execution
                elif order_id == str(position.sl_order_id):
                    logger.info(f"🛑 [USE CASE] Stop Loss filled for {symbol}. Position closed.")

                    # Get exchange to cancel all position orders (TP, reentry, etc.)
                    exchange = self._exchange_registry.get_exchange(position.exchange)
                    await self._cancel_all_position_orders(position, exchange)

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

        position_info = await exchange.get_position(symbol)
        # Check if position still exists on exchange
        try:
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

        breakeven_price = float(position_info["breakEvenPrice"])
        logger.info(
            f"🛡️ [USE CASE] Moving Stop Loss to entry price (breakeven) for {symbol}...\n"
            f"  Entry: {position.entry_price:.8f}\n"
            f"  SL (Entry + fees): {breakeven_price:.8f}\n"
            f"  Current price: {current_price:.8f}\n"
            f"  Remaining qty: {position.remaining_qty:.2f}\n"
            f"  Realized PnL: {position.realized_pnl_usdt:.2f} USDT"
        )

        # Check if distance is valid
        breakeven_price = float(position_info["breakEvenPrice"])
        if await self._try_move_sl(position, exchange, breakeven_price, "entry_breakeven"):
            msg = f"🛡️ **{symbol}**: Stop loss moved to breakeven (entry price)!\n  Entry: {position.entry_price:.8f}\n  SL: {breakeven_price:.8f}\n  Remaining: {position.remaining_qty:.2f}"
            logger.info(msg)
            return BreakevenMoveResult.SUCCESS

        # ============================================================
        # ATTEMPT 2: Emergency - Close entire position
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

    async def _cancel_all_position_orders(self, position: ActivePositionEntity, exchange: ExchangeGatewayProtocol) -> None:
        """Cancel all orders related to position: TP, reentry, and any other orders.

        This method uses a three-step approach:
        1. Cancel TP orders by known order IDs
        2. Cancel reentry order if exists
        3. Fallback: Cancel all orders for the symbol (guarantees cleanup)

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

        # Step 2: Cancel reentry order if exists
        if position.reentry_order_id:
            try:
                await exchange.cancel_order(symbol, position.reentry_order_id)
                logger.info(f"✅ Cancelled reentry order {position.reentry_order_id} for {symbol}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to cancel reentry order {position.reentry_order_id}: {e}")

        # Step 3: Fallback - cancel all orders for the symbol (guarantees cleanup)
        try:
            await exchange.cancel_all_orders(symbol)
            logger.info(f"✅ Cancelled all remaining orders for {symbol} (fallback)")
        except Exception as e:
            logger.warning(f"⚠️ Failed to cancel all orders for {symbol}: {e}")

    async def _cancel_all_orders_for_symbol_from_exchange(self, symbol: str, exchange: ExchangeGatewayProtocol) -> None:
        """Cancel all open orders for symbol directly from exchange after SL trigger.

        This method ensures complete cleanup:
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
                logger.info(f"✅ Removed pending entry for {symbol} (had limit order, protective SL/TP)")
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

        close_side = TradeSide.SHORT if position.side == TradeSide.LONG else TradeSide.LONG

        # Close position with market order
        await exchange.place_market_order(symbol=symbol, side=close_side, qty=0, reduce_only=True)

        # Cancel all position orders
        await self._cancel_all_position_orders(position, exchange)

        logger.warning(f"🚨 Emergency closing position {symbol}")

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
        if await self._try_move_sl(position, exchange, sl_price, "tp1_after_tp3"):
            msg = f"🛡️ **{symbol}**: Stop loss moved to TP1 level (after TP3)!\n  TP1: {tp1_price:.8f}\n  SL: {sl_price:.8f}\n  Remaining: {position.remaining_qty:.2f}"
            logger.info(msg)
            await self._notification_gateway.send_message(msg)
        else:
            logger.warning(f"⚠️ Failed to move SL to TP1 for {symbol} after TP3")

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

    async def _get_open_orders_with_retry(
        self,
        exchange: ExchangeGatewayProtocol,
        symbol: str,
        max_retries: int = 3,
        initial_delay: float = 0.5,
    ) -> list[dict[str, Any]]:
        """Get open orders from exchange with retry logic.

        Args:
            exchange: Exchange gateway
            symbol: Trading pair symbol
            max_retries: Maximum number of retry attempts (default: 3)
            initial_delay: Initial delay between retries in seconds (default: 0.5s)

        Returns:
            List of open orders

        Raises:
            Exception: If all retries fail
        """
        for attempt in range(max_retries):
            try:
                orders = await exchange.list_open_orders(symbol)

                if attempt > 0:
                    logger.info(f"✅ Successfully fetched open orders for {symbol} on attempt {attempt + 1}/{max_retries}")

                return orders

            except Exception as e:
                if attempt < max_retries - 1:
                    delay = initial_delay * (2**attempt)  # Exponential backoff
                    logger.warning(f"⚠️ Failed to fetch open orders for {symbol}, retrying in {delay:.2f}s (attempt {attempt + 1}/{max_retries}): {e}")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"❌ Failed to fetch open orders for {symbol} after {max_retries} attempts: {e}")
                    raise

        return []
