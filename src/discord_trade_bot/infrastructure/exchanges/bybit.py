import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, cast, final, override

from pybit.unified_trading import HTTP, WebSocket

from discord_trade_bot.core.domain.value_objects.formatters import format_price, format_quantity
from discord_trade_bot.core.domain.value_objects.trading import TradeSide
from discord_trade_bot.infrastructure.exchanges.base import BaseExchangeAdapter

logger = logging.getLogger(__name__)


@final
class BybitFuturesAdapter(BaseExchangeAdapter):
    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.session = HTTP(testnet=testnet, api_key=self.api_key, api_secret=self.api_secret, recv_window=5000)
        self._ws: WebSocket | None = None
        self._stop_event = asyncio.Event()

    @property
    @override
    def name(self) -> str:
        return "bybit"

    @override
    async def close(self):
        if self._ws:
            self._ws.exit()
        self._stop_event.set()

    # Helper method to run synchronous pybit functions without blocking Event Loop
    async def _run_in_thread(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

    @override
    async def get_last_price(self, symbol: str) -> float:
        resp = await self._run_in_thread(self.session.get_tickers, category="linear", symbol=symbol)
        rows = resp.get("result", {}).get("list", [])
        if not rows:
            raise RuntimeError(f"Bybit get_last_price empty for {symbol}")
        return float(rows[0]["lastPrice"])

    @override
    async def get_balance(self) -> float:
        resp = await self._run_in_thread(self.session.get_wallet_balance, accountType="UNIFIED", coin="USDT")
        list_data = resp.get("result", {}).get("list", [])
        if not list_data:
            return 0.0

        for coin_data in list_data[0].get("coin", []):
            if coin_data.get("coin") == "USDT":
                return float(coin_data.get("availableToWithdraw") or coin_data.get("walletBalance") or 0.0)
        return 0.0

    @override
    async def set_leverage(self, symbol: str, leverage: int) -> dict[str, Any]:
        try:
            return await self._run_in_thread(self.session.set_leverage, category="linear", symbol=symbol, buyLeverage=str(leverage), sellLeverage=str(leverage))
        except Exception as e:
            if "110043" in str(e):  # Bybit Error: Leverage not modified
                return {"msg": "leverage not modified"}
            raise

    @override
    async def place_market_order(self, symbol: str, side: TradeSide, qty: float, reduce_only: bool = False) -> dict[str, Any]:
        resp = await self._run_in_thread(
            self.session.place_order,
            category="linear",
            symbol=symbol,
            side="Buy" if side == TradeSide.LONG else "Sell",
            orderType="Market",
            qty=format_quantity(qty),
            reduceOnly=reduce_only,
            positionIdx=0,
        )
        return {"orderId": resp["result"]["orderId"]}

    @override
    async def place_limit_order(self, symbol: str, side: TradeSide, qty: float, price: float, reduce_only: bool = False) -> dict[str, Any]:
        resp = await self._run_in_thread(
            self.session.place_order,
            category="linear",
            symbol=symbol,
            side="Buy" if side == TradeSide.LONG else "Sell",
            orderType="Limit",
            price=format_price(price),
            qty=format_quantity(qty),
            reduceOnly=reduce_only,
            timeInForce="GTC",
            positionIdx=0,
        )
        return {"orderId": resp["result"]["orderId"]}

    @override
    async def place_stop_market_order(self, symbol: str, side: TradeSide, stop_price: float) -> dict[str, Any]:
        close_side = "Sell" if side == TradeSide.LONG else "Buy"
        trigger_direction = 2 if side == TradeSide.LONG else 1  # 1: rise, 2: fall
        resp = await self._run_in_thread(
            self.session.place_order,
            category="linear",
            symbol=symbol,
            side=close_side,
            orderType="Market",
            qty="0",  # With reduceOnly and closeOnTrigger for the whole volume
            triggerPrice=format_price(stop_price),
            triggerBy="MarkPrice",
            triggerDirection=trigger_direction,
            reduceOnly=True,
            closeOnTrigger=True,
            positionIdx=0,
        )
        return {"orderId": resp["result"]["orderId"]}

    @override
    async def cancel_order(self, symbol: str, order_id: str | int) -> dict[str, Any]:
        return await self._run_in_thread(self.session.cancel_order, category="linear", symbol=symbol, orderId=str(order_id))

    @override
    async def get_position(self, symbol: str) -> dict[str, Any]:
        resp = await self._run_in_thread(self.session.get_positions, category="linear", symbol=symbol)
        rows = resp.get("result", {}).get("list", [])
        return rows[0] if rows else {}

    @override
    async def cancel_all_orders(self, symbol: str) -> dict[str, Any]:
        return await self._run_in_thread(self.session.cancel_all_orders, category="linear", symbol=symbol)

    @override
    async def place_sl_tp_orders(
        self, symbol: str, side: TradeSide, stop_loss: float | None, take_profits: list[float], qty: float, tp_distribution: list[dict[str, Any]]
    ) -> dict[str, Any]:
        results: dict[str, Any] = {"stop_loss": None, "take_profits": []}
        if stop_loss:
            try:
                res = await self.place_stop_market_order(symbol, side, stop_loss)
                results["stop_loss"] = res
            except Exception as e:
                logger.error(f"Bybit SL error for {symbol}: {e}")
        if take_profits:
            each_qty = qty / len(take_profits)

            # Round qty to integer if needed (Bybit often requires whole numbers for altcoins)
            each_qty_rounded = round(each_qty, 0)

            for i, tp in enumerate(take_profits):
                close_side = "Sell" if side == TradeSide.LONG else "Buy"
                trigger_direction = 1 if side == TradeSide.LONG else 2
                try:
                    # Format quantity as integer string if it's a whole number
                    if each_qty_rounded == int(each_qty_rounded):
                        qty_str = str(int(each_qty_rounded))
                    else:
                        qty_str = format_quantity(each_qty_rounded)

                    res = await self._run_in_thread(
                        self.session.place_order,
                        category="linear",
                        symbol=symbol,
                        side=close_side,
                        orderType="Market",
                        qty=qty_str,
                        triggerPrice=format_price(tp),
                        triggerBy="MarkPrice",
                        triggerDirection=trigger_direction,
                        reduceOnly=True,
                        closeOnTrigger=True,
                        positionIdx=0,
                    )
                    results["take_profits"].append({"orderId": res["result"]["orderId"]})
                    logger.info(f"✅ TP{i + 1} placed at {format_price(tp)} with qty {qty_str} for {symbol}")
                except Exception as e:
                    logger.error(f"❌ Bybit TP{i + 1} error for {symbol} at {tp}: {e}")
        return results

    @override
    async def listen_user_stream(self, on_update_callback: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        """Listen to Bybit user data stream for order updates.

        Handles WebSocket connection errors gracefully and provides detailed error messages.
        """
        loop = asyncio.get_running_loop()

        def handle_order_msg(msg: dict[str, Any]):
            """Handle order messages from Bybit WebSocket."""
            try:
                data = msg.get("data", [])
                for order in data:
                    status = order.get("orderStatus")
                    # Map to format expected by Tracker (like Binance)
                    adapted_event = {
                        "e": "ORDER_TRADE_UPDATE",
                        "o": {"i": order.get("orderId"), "X": "FILLED" if status == "Filled" else status, "s": order.get("symbol")},
                    }
                    # Safely pass event to our Event Loop
                    asyncio.run_coroutine_threadsafe(cast(Coroutine[Any, Any, None], on_update_callback(adapted_event)), loop)
            except Exception as e:
                logger.error(f"❌ Error handling Bybit order message: {e}")

        try:
            logger.info("📡 Connecting to Bybit WebSocket via pybit...")
            self._ws = WebSocket(testnet=False, channel_type="private", api_key=self.api_key, api_secret=self.api_secret)

            # Subscribe to order events
            self._ws.order_stream(callback=handle_order_msg)
            logger.info("✅ Bybit WebSocket connected successfully")

            # Keep method active for Tracker to continue working
            await self._stop_event.wait()

        except Exception as e:
            error_msg = str(e).lower()
            if "not authorized" in error_msg or "unauthorized" in error_msg:
                logger.error("❌ Bybit WebSocket authorization failed. Please check your API keys and permissions.")
                logger.error("   Required permissions: Read, Trade, WebSocket")
            elif "connection" in error_msg:
                logger.error(f"❌ Bybit WebSocket connection failed: {e}")
            else:
                logger.error(f"❌ Bybit WebSocket error: {e}")
            raise

    async def get_symbol_info(self, symbol: str) -> dict[str, Any]:
        resp = await self._run_in_thread(self.session.get_instruments_info, category="linear", symbol=symbol)
        rows = resp.get("result", {}).get("list", [])
        if rows:
            lot_size_filter = rows[0].get("lotSizeFilter", {})
            return {
                "qty_precision": len(str(float(lot_size_filter.get("qtyStep", "0.01"))).split(".")[-1]),
                "price_precision": len(str(float(rows[0].get("priceFilter", {}).get("tickSize", "0.01"))).split(".")[-1]),
                "min_qty": float(lot_size_filter.get("minOrderQty", "0.01")),
            }
        return {"qty_precision": 2, "price_precision": 2, "min_qty": 1.0}
