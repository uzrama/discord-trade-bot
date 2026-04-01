import asyncio
import logging
from typing import Any, final

from discord_trade_bot.core.application.common.interfaces.notification import NotificationGatewayProtocol
from discord_trade_bot.core.application.common.interfaces.repository import StateRepositoryProtocol
from discord_trade_bot.core.application.trading.dto import OpenPositionResultDTO, TradeSettingsDTO
from discord_trade_bot.core.application.trading.interfaces import ExchangeGatewayProtocol, ExchangeRegistryProtocol
from discord_trade_bot.core.domain.entities.pending_entry import PendingEntryEntity
from discord_trade_bot.core.domain.entities.signal import ParsedSignalEntity
from discord_trade_bot.core.domain.services.entry_order_decider import OrderType, decide_entry_order
from discord_trade_bot.core.domain.value_objects.trading import TPDistributionRow, TradeSide

logger = logging.getLogger(__name__)


@final
class OpenPositionUseCase:
    def __init__(
        self,
        exchange_registry: ExchangeRegistryProtocol,
        notification_gateway: NotificationGatewayProtocol,
        state_repository: StateRepositoryProtocol,
    ):
        self._exchange_registry = exchange_registry
        self._notification_gateway = notification_gateway
        self._state_repository = state_repository

    async def execute(self, sig: ParsedSignalEntity, settings: TradeSettingsDTO) -> OpenPositionResultDTO:
        symbol = sig.symbol
        if not symbol:
            return OpenPositionResultDTO(success=False, reason="No symbol")

        side = sig.side
        if not side:
            return OpenPositionResultDTO(success=False, reason="No side")

        # Resolve the specific exchange adapter from composite if possible
        exchange_name = settings.exchange

        exchange = self._exchange_registry.get_exchange(exchange_name)

        # 1. Get symbol info
        try:
            await exchange.get_symbol_info(symbol)
        except Exception as e:
            return OpenPositionResultDTO(success=False, reason=f"Failed to get symbol info for {symbol}: {e}")

        # 2. Resolve leverage
        leverage = await self._resolve_leverage(settings)
        try:
            await exchange.set_leverage(symbol, leverage)
        except Exception as e:
            return OpenPositionResultDTO(success=False, reason=f"Failed to set leverage: {e}")

        # 3. Get market price
        try:
            market_price = await exchange.get_last_price(symbol)
        except Exception as e:
            return OpenPositionResultDTO(success=False, reason=f"Failed to get price for {symbol}: {e}")

        # 4. Decide order type (market vs limit)
        decision = decide_entry_order(
            entry_mode=sig.entry_mode,
            entry_price=sig.entry_price,
            market_price=market_price,
            side=side,
        )

        if decision.order_type == OrderType.SKIP:
            return OpenPositionResultDTO(success=False, reason=f"Entry skipped: {decision.reason}")

        logger.info(f"Entry decision for {symbol}: {decision.order_type} (reason: {decision.reason}, limit_price: {decision.limit_price})")

        # 5. Compute qty and notional using market_price (same as bot_fixed)
        # IMPORTANT: Always use market_price for qty calculation, regardless of order type.
        # This matches bot_fixed behavior where qty = notional / market_price.
        # The configured percent is interpreted as the margin portion of the currently
        # available balance. Final position notional is that margin multiplied by leverage.
        qty, notional_value = await self._compute_qty(exchange, symbol, market_price, leverage, settings)
        if qty <= 0:
            return OpenPositionResultDTO(success=False, reason="Invalid qty (0 or negative). Check balance and settings.")

        # 6. Validate minimum notional value (Bybit requires min 5 USDT)
        min_notional = 5.0  # USDT minimum for Bybit

        if notional_value < min_notional:
            error_msg = (
                f"Cannot open position for {symbol}: notional value too low. "
                f"Calculated: {notional_value:.4f} USDT < minimum {min_notional} USDT. "
                f"Increase free_balance_pct in config (current: {settings.free_balance_pct}%) or skip this signal."
            )
            logger.warning(f"⚠️ {error_msg}")
            return OpenPositionResultDTO(success=False, reason=error_msg)

        logger.info(f"✅ Notional value check passed for {symbol}: {notional_value:.2f} USDT (min: {min_notional} USDT)")

        # 7. Branch based on order type
        if decision.order_type == OrderType.MARKET:
            return await self._execute_market_entry(
                exchange=exchange,
                sig=sig,
                settings=settings,
                qty=qty,
                market_price=market_price,
                exchange_name=exchange_name,
            )
        else:  # LIMIT
            return await self._execute_limit_entry(
                exchange=exchange,
                sig=sig,
                settings=settings,
                qty=qty,
                limit_price=decision.limit_price,
                exchange_name=exchange_name,
            )

    async def _execute_market_entry(
        self,
        exchange: ExchangeGatewayProtocol,
        sig: ParsedSignalEntity,
        settings: TradeSettingsDTO,
        qty: float,
        market_price: float,
        exchange_name: str,
    ) -> OpenPositionResultDTO:
        """Execute market order entry (immediate fill)."""
        # Type narrowing - these are already validated in execute()
        assert sig.symbol is not None
        assert sig.side is not None

        symbol: str = sig.symbol
        side: TradeSide = sig.side

        # Place market order
        try:
            order_res = await exchange.place_market_order(symbol=symbol, side=side, qty=qty)
        except Exception as e:
            return OpenPositionResultDTO(success=False, reason=f"Failed to place market order: {e}")

        # Wait for position to be confirmed on exchange
        logger.info(f"⏳ Waiting for position {symbol} to be established...")
        position_ready = await exchange.wait_for_position_ready(
            symbol=symbol,
            side=side,
            timeout=10.0,
            check_interval=0.5,
        )

        if not position_ready:
            # Critical error: position not confirmed
            error_msg = f"Position {symbol} not confirmed after 10s. SL/TP NOT placed - MANUAL INTERVENTION REQUIRED!"
            logger.critical(f"🚨 {error_msg}")
            await self._notification_gateway.send_message(f"🚨 CRITICAL: {error_msg}")

            # Return partial success (order placed but without SL/TP)
            return OpenPositionResultDTO(
                success=True,
                order=order_res,
                sl_tp_res={},
                qty=qty,
                entry_price=market_price,
                final_sl=None,
                exchange_name=exchange_name,
                pending=False,
            )

        # Calculate SL
        final_sl = self._calculate_stop_loss(
            signal_sl=sig.stop_loss,
            market_price=market_price,
            side=side,
            default_sl_pct=settings.default_sl_percent,
        )

        # Place SL/TP with retry logic (position is now guaranteed to exist)
        sl_tp_res = {}
        if final_sl or sig.take_profits:
            sl_tp_res = await self._place_sl_tp_with_retry(
                exchange=exchange,
                symbol=symbol,
                side=side,
                stop_loss=final_sl,
                take_profits=sig.take_profits,
                qty=qty,
                tp_distribution=settings.tp_distribution,
            )

        # Build notification message
        message = f"🚀 Opened {side} on {symbol} ({exchange_name})\nType: MARKET\nQty: {qty}\nPrice: {market_price}"

        # Add SL status
        if final_sl:
            if sl_tp_res.get("stop_loss"):
                message += f"\n✅ SL: {final_sl}"
            else:
                message += "\n⚠️ SL: Failed to place"

        # Add TP status
        if sig.take_profits:
            tp_placed = len(sl_tp_res.get("take_profits", []))
            tp_expected = len(sig.take_profits)
            if tp_placed == tp_expected:
                message += f"\n✅ TP: {tp_placed}/{tp_expected} placed"
            elif tp_placed > 0:
                message += f"\n⚠️ TP: Only {tp_placed}/{tp_expected} placed"
            else:
                message += f"\n❌ TP: 0/{tp_expected} placed (qty too small?)"

        await self._notification_gateway.send_message(message)

        return OpenPositionResultDTO(
            success=True,
            order=order_res,
            sl_tp_res=sl_tp_res,
            qty=qty,
            entry_price=market_price,
            final_sl=final_sl,
            exchange_name=exchange_name,
            pending=False,
        )

    async def _execute_limit_entry(
        self,
        exchange: ExchangeGatewayProtocol,
        sig: ParsedSignalEntity,
        settings: TradeSettingsDTO,
        qty: float,
        limit_price: float | None,
        exchange_name: str,
    ) -> OpenPositionResultDTO:
        """Execute limit order entry (pending fill)."""
        # Type narrowing - these are already validated in execute()
        assert sig.symbol is not None
        assert sig.side is not None
        assert limit_price is not None

        symbol: str = sig.symbol
        side: TradeSide = sig.side

        # Place limit order
        try:
            order_res = await exchange.place_limit_order(symbol=symbol, side=side, qty=qty, price=limit_price)
        except Exception as e:
            return OpenPositionResultDTO(success=False, reason=f"Failed to place limit order: {e}")

        order_id = str(order_res.get("orderId", ""))

        # Calculate SL
        final_sl = self._calculate_stop_loss(
            signal_sl=sig.stop_loss,
            market_price=limit_price,  # Use limit price as reference
            side=side,
            default_sl_pct=settings.default_sl_percent,
        )

        # Place SL + TP immediately for maximum protection
        # These are conditional orders that only trigger if position exists
        sl_tp_res: dict[str, Any] = {"stop_loss": None, "take_profits": []}
        sl_order_id = None
        tp_order_ids: list[str] = []

        if final_sl or sig.take_profits:
            try:
                logger.info(f"🛡️ Placing protective SL/TP orders for pending limit order on {symbol}")
                sl_tp_res = await self._place_sl_tp_with_retry(
                    exchange=exchange,
                    symbol=symbol,
                    side=side,
                    stop_loss=final_sl,
                    take_profits=sig.take_profits,
                    qty=qty,
                    tp_distribution=settings.tp_distribution,
                )

                # Extract order IDs
                if sl_tp_res.get("stop_loss"):
                    sl_order_id = str(sl_tp_res["stop_loss"].get("orderId", ""))
                    logger.info(f"✅ Protective SL placed for {symbol} (Order ID: {sl_order_id})")

                tp_order_ids = [str(tp.get("orderId", "")) for tp in sl_tp_res.get("take_profits", []) if tp.get("orderId")]
                if tp_order_ids:
                    logger.info(f"✅ {len(tp_order_ids)} protective TP orders placed for {symbol}")

            except Exception as e:
                logger.error(f"❌ Failed to place protective SL/TP for {symbol}: {e}")
                # Continue anyway - will retry after fill if needed

        logger.info(f"⏳ Limit order placed for {symbol}. SL/TP are active and waiting for position.")

        # Convert tp_distribution to TPDistributionRow list
        tp_dist_rows = []
        if settings.tp_distribution and sig.take_profits:
            num_tps = len(sig.take_profits)
            if num_tps in settings.tp_distribution:
                for tp_dict in settings.tp_distribution[num_tps]:
                    tp_dist_rows.append(TPDistributionRow(label=tp_dict["label"], close_pct=tp_dict["close_pct"]))

        # Save to pending entries
        pending_entry = PendingEntryEntity(
            symbol=symbol,
            source_id=sig.source_id,
            message_id=sig.message_id,
            exchange=exchange_name,
            side=side,
            qty=qty,
            entry_price=limit_price,
            order_id=order_id,
            stop_loss=final_sl,
            take_profits=sig.take_profits,
            tp_distribution=tp_dist_rows,
            status="pending",
            sl_tp_attached=bool(sl_order_id and tp_order_ids),  # True if both SL and TP placed
            sl_order_id=sl_order_id,  # Store SL order ID for potential cancellation
            tp_order_ids=tp_order_ids,  # Store TP order IDs for potential cancellation
        )

        await self._state_repository.save_pending_entry(pending_entry)

        # Build notification message
        message = f"📋 Limit order placed for {side} on {symbol} ({exchange_name})\nType: LIMIT\nQty: {qty}\nLimit Price: {limit_price}"

        # Add SL/TP info
        if final_sl:
            if sl_order_id:
                message += f"\n✅ SL: {final_sl} (already active)"
            else:
                message += f"\n⚠️ SL: {final_sl} (failed to place)"

        # Add TP status
        if sig.take_profits:
            tp_expected = len(sig.take_profits)
            tp_placed = len(tp_order_ids)
            if tp_placed == tp_expected:
                message += f"\n✅ TP: {tp_placed}/{tp_expected} targets (already active)"
            elif tp_placed > 0:
                message += f"\n⚠️ TP: {tp_placed}/{tp_expected} targets (will retry missing after fill)"
            else:
                message += f"\n⚠️ TP: 0/{tp_expected} targets (will place after fill)"

        message += "\n⏳ Waiting for limit order to fill..."

        await self._notification_gateway.send_message(message)

        return OpenPositionResultDTO(
            success=True,
            order=order_res,
            sl_tp_res=sl_tp_res,
            qty=qty,
            entry_price=limit_price,
            final_sl=final_sl,
            exchange_name=exchange_name,
            pending=True,
        )

    async def _resolve_leverage(self, settings: TradeSettingsDTO) -> int:
        return settings.fixed_leverage

    async def _compute_qty(self, exchange: ExchangeGatewayProtocol, symbol: str, price: float, leverage: int, settings: TradeSettingsDTO) -> tuple[float, float]:
        """Calculate position quantity and notional value.

        Returns:
            tuple[float, float]: (qty, notional_value)
        """
        try:
            symbol_info = await exchange.get_symbol_info(symbol)
            qty_precision = symbol_info.get("qty_precision", 3)
            min_qty = symbol_info.get("min_qty", 0.001)

            balance = await exchange.get_balance()
            size_pct = settings.free_balance_pct
            margin = balance * (size_pct / 100.0)
            notional = margin * leverage
            qty = notional / price

            logger.info(
                f"[Position Sizing] {symbol}: "
                f"balance={balance:.2f} USDT, "
                f"free_balance_pct={size_pct}%, "
                f"margin={margin:.2f} USDT, "
                f"leverage={leverage}x, "
                f"notional={notional:.2f} USDT, "
                f"price={price:.8f}, "
                f"qty_raw={qty:.8f}"
            )

            qty = round(qty, qty_precision)

            if qty < min_qty:
                logger.warning(f"Calculated qty {qty} is less than min_qty {min_qty}, using min_qty")
                qty = min_qty

            logger.info(f"[Position Sizing] {symbol}: final qty={qty:.8f}, notional={notional:.2f} USDT (after rounding and min_qty check)")

            return qty, notional
        except Exception as e:
            logger.error(f"Failed to compute qty: balance query failed or calculation error. Price={price}, Leverage={leverage}, Error: {e}")
            return 0.0, 0.0

    def _calculate_stop_loss(self, signal_sl: float | None, market_price: float, side: TradeSide, default_sl_pct: float | None) -> float | None:
        if signal_sl is not None:
            return signal_sl
        if default_sl_pct is not None:
            if side == TradeSide.LONG:
                final_sl = market_price * (1 - default_sl_pct / 100.0)
            else:
                final_sl = market_price * (1 + default_sl_pct / 100.0)
            return round(final_sl, 8)
        return None

    async def _place_sl_tp_with_retry(
        self,
        exchange: ExchangeGatewayProtocol,
        symbol: str,
        side: TradeSide,
        stop_loss: float | None,
        take_profits: list[float],
        qty: float,
        tp_distribution: dict[int, list[dict[str, Any]]],
        max_retries: int = 5,
        initial_delay: float = 0.5,
    ) -> dict[str, Any]:
        """Place SL/TP orders with retry logic.

        Args:
            exchange: Exchange adapter to use
            symbol: Trading symbol
            side: Trade side (LONG/SHORT)
            stop_loss: Stop loss price (optional)
            take_profits: List of take profit prices
            qty: Position quantity
            tp_distribution: TP distribution configuration
            max_retries: Maximum number of retry attempts (default: 5)
            initial_delay: Initial delay between retries in seconds (default: 0.5s)

        Returns:
            Dictionary with stop_loss and take_profits order results
        """

        for attempt in range(max_retries):
            try:
                result = await exchange.place_sl_tp_orders(
                    symbol=symbol,
                    side=side,
                    stop_loss=stop_loss,
                    take_profits=take_profits,
                    qty=qty,
                    tp_distribution=tp_distribution,
                )

                if attempt > 0:
                    logger.info(f"✅ SL/TP placement succeeded on attempt {attempt + 1}/{max_retries} for {symbol}")

                return result

            except Exception as e:
                error_str = str(e).lower()

                # Check if it's a "position not available" error
                if "position" in error_str and ("not" in error_str or "available" in error_str or "tif" in error_str):
                    if attempt < max_retries - 1:
                        delay = initial_delay * (2**attempt)  # Exponential backoff
                        logger.warning(f"⚠️ Position not ready for {symbol}, retrying in {delay:.2f}s (attempt {attempt + 1}/{max_retries})")
                        await asyncio.sleep(delay)
                        continue
                    else:
                        logger.error(f"❌ Failed to place SL/TP for {symbol} after {max_retries} attempts: {e}")
                else:
                    # Different error, don't retry
                    logger.error(f"❌ Non-retryable error placing SL/TP for {symbol}: {e}")
                    break

        # All retries failed, return empty result
        return {"stop_loss": None, "take_profits": []}
