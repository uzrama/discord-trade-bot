import logging
from typing import final

from discord_trade_bot.core.domain.entities.signal import ParsedSignalEntity
from discord_trade_bot.core.domain.value_objects.trading import TradeSide

from discord_trade_bot.core.application.common.interfaces.notification import NotificationGatewayProtocol
from discord_trade_bot.core.application.trading.dto import OpenPositionResultDTO, TradeSettingsDTO
from discord_trade_bot.core.application.trading.interfaces import ExchangeGatewayProtocol, ExchangeRegistryProtocol

logger = logging.getLogger(__name__)


@final
class OpenPositionUseCase:
    def __init__(
        self,
        exchange_registry: ExchangeRegistryProtocol,
        notification_gateway: NotificationGatewayProtocol,
    ):
        self._exchange_registry = exchange_registry
        self._notification_gateway = notification_gateway

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

        # 1. Resolve leverage
        leverage = await self._resolve_leverage(settings)
        try:
            await exchange.set_leverage(symbol, leverage)
        except Exception as e:
            return OpenPositionResultDTO(success=False, reason=f"Failed to set leverage: {e}")

        # 2. Get market price and compute qty
        try:
            market_price = await exchange.get_last_price(symbol)
        except Exception as e:
            return OpenPositionResultDTO(success=False, reason=f"Failed to get price for {symbol}: {e}")
        qty = await self._compute_qty(exchange, symbol, market_price, leverage, settings)
        if qty <= 0:
            return OpenPositionResultDTO(success=False, reason="Invalid qty (0 or negative). Check balance and settings.")

        # 3. Place Order
        try:
            order_res = await exchange.place_market_order(symbol=symbol, side=side, qty=qty)
        except Exception as e:
            return OpenPositionResultDTO(success=False, reason=f"Failed to place entry order: {e}")

        # Wait for entry order to fill before placing SL/TP
        import asyncio

        logger.info(f"Waiting 1.5s for entry order to fill for {symbol}...")
        await asyncio.sleep(1.5)

        # 4. Resolve Default SL (if missing)
        final_sl = self._calculate_stop_loss(
            signal_sl=sig.stop_loss,
            market_price=market_price,
            side=side,
            default_sl_pct=settings.default_sl_percent,
        )

        # 5. Place SL/TP
        sl_tp_res = {}
        if final_sl or sig.take_profits:
            sl_tp_res = await exchange.place_sl_tp_orders(
                symbol=symbol, side=side, stop_loss=final_sl, take_profits=sig.take_profits, qty=qty, tp_distribution=settings.tp_distribution
            )

        # Build notification message with actual SL/TP status
        message = f"🚀 Opened {side} on {symbol} ({exchange_name})\nQty: {qty}\nPrice: {market_price}"

        # Add SL status
        if final_sl:
            if sl_tp_res.get("stop_loss"):
                message += f"\n✅ SL: {final_sl}"
            else:
                message += f"\n⚠️ SL: Failed to place"

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
        )

    async def _resolve_leverage(self, settings: TradeSettingsDTO) -> int:
        return settings.fixed_leverage

    async def _compute_qty(self, exchange: ExchangeGatewayProtocol, symbol: str, price: float, leverage: int, settings: TradeSettingsDTO) -> float:
        try:
            symbol_info = await exchange.get_symbol_info(symbol)
            qty_precision = symbol_info.get("qty_precision", 3)
            min_qty = symbol_info.get("min_qty", 0.001)

            balance = await exchange.get_balance()
            size_pct = settings.free_balance_pct
            margin = balance * (size_pct / 100.0)
            notional = margin * leverage
            qty = notional / price

            qty = round(qty, qty_precision)

            if qty < min_qty:
                logger.warning(f"Calculated qty {qty} is less than min_qty {min_qty}, using min_qty")
                qty = min_qty

            return qty
        except Exception as e:
            logger.error(f"Failed to compute qty: balance query failed or calculation error. Price={price}, Leverage={leverage}, Error: {e}")
            return 0.0

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
