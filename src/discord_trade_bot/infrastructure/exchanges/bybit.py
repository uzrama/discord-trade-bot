import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, cast, final, override

from pybit.unified_trading import HTTP, WebSocket

from discord_trade_bot.core.domain.services.tp_calculator import calculate_tp_quantities
from discord_trade_bot.core.domain.value_objects.trading import TradeSide
from discord_trade_bot.infrastructure.exchanges.base import BaseExchangeAdapter

logger = logging.getLogger(__name__)


@final
class BybitFuturesAdapter(BaseExchangeAdapter):
    def __init__(self, api_key: str, api_secret: str, testnet: bool = False, demo: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet  # Store testnet parameter for WebSocket
        self.demo = demo  # Store demo parameter for HTTP and WebSocket
        self.session = HTTP(demo=self.demo, testnet=testnet, api_key=self.api_key, api_secret=self.api_secret, recv_window=5000)
        self._ws: WebSocket | None = None
        self._stop_event = asyncio.Event()
        self._symbol_info_cache: dict[str, dict[str, Any]] = {}  # Cache for symbol info

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

    @staticmethod
    def _floor_to_step(value: float, step: float) -> float:
        """Round down value to the nearest step.

        Args:
            value: Value to round
            step: Step size

        Returns:
            Rounded value

        Examples:
            >>> _floor_to_step(8838.8, 1.0)
            8838.0
            >>> _floor_to_step(0.123456, 0.001)
            0.123
        """
        if step <= 0:
            return float(value)
        import math

        # Use round to avoid floating point precision issues
        result = math.floor(float(value) / step) * step
        # Determine precision from step
        if step >= 1:
            return round(result, 0)
        else:
            decimals = len(str(step).split(".")[-1].rstrip("0"))
            return round(result, decimals)

    async def _get_cached_symbol_info(self, symbol: str) -> dict[str, Any]:
        """Get symbol info with caching.

        Args:
            symbol: Trading symbol

        Returns:
            Symbol info dict with qty_precision, price_precision, min_qty, qty_step, tick_size
        """
        if symbol in self._symbol_info_cache:
            return self._symbol_info_cache[symbol]

        # Fetch from exchange
        info = await self.get_symbol_info(symbol)
        self._symbol_info_cache[symbol] = info
        return info

    async def _format_quantity_for_symbol(self, symbol: str, qty: float, reduce_only: bool = False) -> str:
        """Format quantity according to symbol's qtyStep requirement.

        Args:
            symbol: Trading symbol
            qty: Quantity to format
            reduce_only: If True, skip minOrderQty check

        Returns:
            Formatted quantity string
        """
        symbol_info = await self._get_cached_symbol_info(symbol)
        qty_step = symbol_info.get("qty_step", 0.001)
        min_qty = symbol_info.get("min_qty", 0.001)
        qty_precision = symbol_info.get("qty_precision", 3)

        # Normalize to qtyStep
        if qty_step > 0:
            qty = self._floor_to_step(qty, qty_step)

        # Check minimum (only for opening orders)
        if not reduce_only and min_qty > 0 and qty < min_qty:
            qty = min_qty
            if qty_step > 0:
                qty = self._floor_to_step(qty, qty_step)

        # Format based on precision
        if qty_step >= 1:
            # Integer quantities (like SIRENUSDT with qtyStep=1)
            return str(int(qty))
        else:
            # Decimal quantities (like BTCUSDT with qtyStep=0.001)
            return f"{qty:.{qty_precision}f}".rstrip("0").rstrip(".")

    async def _format_price_for_symbol(self, symbol: str, price: float) -> str:
        """Format price according to symbol's tickSize requirement.

        Args:
            symbol: Trading symbol
            price: Price to format

        Returns:
            Formatted price string
        """
        symbol_info = await self._get_cached_symbol_info(symbol)
        tick_size = symbol_info.get("tick_size", 0.01)
        price_precision = symbol_info.get("price_precision", 2)

        # Normalize to tickSize
        if tick_size > 0:
            price = self._floor_to_step(price, tick_size)

        # Format based on precision
        return f"{price:.{price_precision}f}".rstrip("0").rstrip(".")

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
            qty=await self._format_quantity_for_symbol(symbol, qty, reduce_only),
            reduceOnly=reduce_only,
            positionIdx=0,
        )
        return {"orderId": resp["result"]["orderId"]}

    @override
    async def place_limit_order(self, symbol: str, side: TradeSide, qty: float, price: float, reduce_only: bool = False) -> dict[str, Any]:
        # Format qty and price
        formatted_qty = await self._format_quantity_for_symbol(symbol, qty, reduce_only)
        formatted_price = await self._format_price_for_symbol(symbol, price)

        # Log order details
        logger.info(f"[Bybit] Placing limit order: symbol={symbol}, side={side.value}, qty_input={qty:.2f}, qty_formatted={formatted_qty}, price={formatted_price}")

        resp = await self._run_in_thread(
            self.session.place_order,
            category="linear",
            symbol=symbol,
            side="Buy" if side == TradeSide.LONG else "Sell",
            orderType="Limit",
            price=formatted_price,
            qty=formatted_qty,
            reduceOnly=reduce_only,
            timeInForce="GTC",
            positionIdx=0,
        )

        order_id = resp["result"]["orderId"]
        logger.info(f"[Bybit] Limit order placed successfully: order_id={order_id}, symbol={symbol}")

        return {"orderId": order_id}

    @override
    async def place_stop_market_order(self, symbol: str, side: TradeSide, stop_price: float, qty: float | None = None) -> dict[str, Any]:
        close_side = "Sell" if side == TradeSide.LONG else "Buy"
        trigger_direction = 2 if side == TradeSide.LONG else 1  # 1: rise, 2: fall

        # If qty is None, use "0" to close entire position
        # Otherwise format the specific quantity
        if qty is None:
            qty_str = "0"
        else:
            qty_str = await self._format_quantity_for_symbol(symbol, qty, reduce_only=True)

        resp = await self._run_in_thread(
            self.session.place_order,
            category="linear",
            symbol=symbol,
            side=close_side,
            orderType="Market",
            qty=qty_str,
            triggerPrice=await self._format_price_for_symbol(symbol, stop_price),
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
    async def list_open_orders(self, symbol: str) -> list[dict[str, Any]]:
        """List all open orders for a symbol."""
        resp = await self._run_in_thread(
            self.session.get_open_orders,
            category="linear",
            symbol=symbol,
        )
        orders = resp.get("result", {}).get("list", [])
        return orders

    @override
    async def place_sl_tp_orders(
        self, symbol: str, side: TradeSide, stop_loss: float | None, take_profits: list[float], qty: float, tp_distribution: dict[int, list[dict[str, Any]]]
    ) -> dict[str, Any]:
        results: dict[str, Any] = {"stop_loss": None, "take_profits": []}
        if stop_loss:
            try:
                # Get current price for logging
                try:
                    current_price = await self.get_last_price(symbol)
                except Exception:
                    current_price = None

                res = await self.place_stop_market_order(symbol, side, stop_loss)
                results["stop_loss"] = res

                # Log success with details
                if current_price:
                    abs((stop_loss - current_price) / current_price) * 100
                    logger.info(f"✅ Bybit SL order placed successfully for {symbol}")
                else:
                    logger.info(f"✅ Bybit SL order placed for {symbol}: Order ID {res.get('orderId', 'N/A')}, SL=${stop_loss:,.2f}")
            except Exception as e:
                logger.error(f"❌ Bybit SL error for {symbol}: {e}", exc_info=True)
        if take_profits:
            # Calculate TP quantities using configured distribution
            tp_quantities = calculate_tp_quantities(total_qty=qty, num_tps=len(take_profits), tp_distributions=tp_distribution)

            for i, (tp, tp_qty) in enumerate(zip(take_profits, tp_quantities)):
                close_side = "Sell" if side == TradeSide.LONG else "Buy"
                trigger_direction = 1 if side == TradeSide.LONG else 2

                try:
                    # Use smart formatting based on symbol's qtyStep
                    qty_str = await self._format_quantity_for_symbol(symbol, tp_qty, reduce_only=True)
                    price_str = await self._format_price_for_symbol(symbol, tp)

                    res = await self._run_in_thread(
                        self.session.place_order,
                        category="linear",
                        symbol=symbol,
                        side=close_side,
                        orderType="Market",
                        qty=qty_str,
                        triggerPrice=price_str,
                        triggerBy="MarkPrice",
                        triggerDirection=trigger_direction,
                        reduceOnly=True,
                        closeOnTrigger=True,
                        positionIdx=0,
                    )
                    results["take_profits"].append({"orderId": res["result"]["orderId"]})
                    logger.info(f"✅ TP{i + 1} placed at {price_str} with qty {qty_str} for {symbol}")
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
            logger.info(f"📡 Connecting to Bybit WebSocket (testnet={self.testnet}) via pybit...")
            self._ws = WebSocket(testnet=False, demo=self.demo, channel_type="private", api_key=self.api_key, api_secret=self.api_secret)

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
            price_filter = rows[0].get("priceFilter", {})
            qty_step = float(lot_size_filter.get("qtyStep", "0.01"))
            tick_size = float(price_filter.get("tickSize", "0.01"))
            max_order_qty = float(lot_size_filter.get("maxOrderQty", "1000000"))

            return {
                "qty_precision": len(str(qty_step).split(".")[-1]),
                "price_precision": len(str(tick_size).split(".")[-1]),
                "min_qty": float(lot_size_filter.get("minOrderQty", "0.01")),
                "qty_step": qty_step,
                "tick_size": tick_size,
                "max_order_qty": max_order_qty,
            }
        return {
            "qty_precision": 2,
            "price_precision": 2,
            "min_qty": 1.0,
            "qty_step": 0.01,
            "tick_size": 0.01,
            "max_order_qty": 1000000.0,
        }

    async def get_order_status(self, symbol: str, order_id: str) -> dict[str, Any]:
        """Get order status from Bybit.

        Args:
            symbol: Trading pair symbol
            order_id: Order ID to check

        Returns:
            Order information including status (New, Filled, PartiallyFilled, Cancelled, etc.)
        """
        resp = await self._run_in_thread(
            self.session.get_open_orders,
            category="linear",
            symbol=symbol,
            orderId=order_id,
        )
        orders = resp.get("result", {}).get("list", [])
        if orders:
            return orders[0]

        # If not in open orders, check order history
        resp = await self._run_in_thread(
            self.session.get_order_history,
            category="linear",
            symbol=symbol,
            orderId=order_id,
        )
        orders = resp.get("result", {}).get("list", [])
        if orders:
            return orders[0]

        return {"orderId": order_id, "orderStatus": "NOT_FOUND"}

    async def close(self) -> None:
        pass
