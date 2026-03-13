import asyncio
import logging
from typing import Any, final, override

from binance import AsyncClient, BinanceSocketManager

from discord_trade_bot.core.domain.value_objects.formatters import format_price, format_quantity
from discord_trade_bot.core.domain.value_objects.trading import TradeSide
from discord_trade_bot.infrastructure.exchanges.base import BaseExchangeAdapter

logger = logging.getLogger(__name__)


@final
class BinanceFuturesAdapter(BaseExchangeAdapter):
    """Adapter for Binance Futures exchange operations.

    This adapter provides a unified interface for interacting with Binance Futures API,
    including placing orders, managing positions, and listening to user data streams.
    Supports both testnet and production environments.

    Attributes:
        api_key: Binance API key for authentication.
        api_secret: Binance API secret for authentication.
        testnet: Whether to use testnet (True) or production (False).
        _client: Cached AsyncClient instance for API calls.
    """

    @property
    @override
    def name(self) -> str:
        return "binance"

    def __init__(self, api_key: str, api_secret: str, testnet: bool = True):
        """Initialize Binance Futures adapter.

        Args:
            api_key: Binance API key.
            api_secret: Binance API secret.
            testnet: Use testnet if True, production if False. Defaults to True.
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self._client: AsyncClient | None = None

    async def _get_client(self) -> AsyncClient:
        """Get or create AsyncClient instance.

        Returns:
            Initialized AsyncClient for Binance API calls.
        """
        if self._client is None:
            self._client = await AsyncClient.create(
                api_key=self.api_key,
                api_secret=self.api_secret,
                testnet=self.testnet,
            )
        return self._client

    def _format_number(self, value: float, precision: int) -> str:
        """Format a number to string with correct precision.

        Args:
            value: Number to format.
            precision: Decimal precision (0 for integers).

        Returns:
            Formatted string representation.
        """
        rounded = round(value, precision)
        return str(int(rounded)) if precision == 0 else str(rounded)

    def _validate_sl_distance(self, stop_loss: float, current_price: float, side: TradeSide, min_distance_pct: float = 0.3) -> bool:
        """Validate stop-loss is far enough from current price.

        Args:
            stop_loss: Stop-loss price.
            current_price: Current market price.
            side: Position side.
            min_distance_pct: Minimum distance percentage.

        Returns:
            True if valid, False otherwise.
        """
        if side == TradeSide.LONG:
            min_sl_price = current_price * (1 - min_distance_pct / 100)
            if stop_loss >= min_sl_price:
                logger.warning(f"SL {stop_loss} too close to current price {current_price} (min: {min_sl_price}), skipping SL order")
                return False
        else:  # SHORT
            max_sl_price = current_price * (1 + min_distance_pct / 100)
            if stop_loss <= max_sl_price:
                logger.warning(f"SL {stop_loss} too close to current price {current_price} (max: {max_sl_price}), skipping SL order")
                return False
        return True

    def _validate_tp_price(self, tp: float, current_price: float, side: TradeSide, tp_index: int) -> bool:
        """Validate take-profit price is in correct direction.

        Args:
            tp: Take-profit price.
            current_price: Current market price.
            side: Position side.
            tp_index: TP index for logging (1-based).

        Returns:
            True if valid, False otherwise.
        """
        if side == TradeSide.LONG and tp <= current_price:
            logger.warning(f"⚠️ TP{tp_index} at {tp} is below/equal current price {current_price} for LONG. Skipping.")
            return False
        elif side == TradeSide.SHORT and tp >= current_price:
            logger.warning(f"⚠️ TP{tp_index} at {tp} is above/equal current price {current_price} for SHORT. Skipping.")
            return False
        return True

    @override
    async def close(self):
        """Close the API client connection."""
        if self._client:
            await self._client.close_connection()
            self._client = None

    @override
    async def get_last_price(self, symbol: str) -> float:
        """Get the current market price for a symbol.

        Args:
            symbol: Trading pair symbol (e.g., 'BTCUSDT').

        Returns:
            Current market price as float.
        """
        client = await self._get_client()
        res = await client.futures_symbol_ticker(symbol=symbol)
        return float(res["price"])

    @override
    async def get_balance(self) -> float:
        client = await self._get_client()
        res = await client.futures_account_balance()
        for row in res:
            if row.get("asset") == "USDT":
                return float(row.get("availableBalance", 0.0))
        return 0.0

    @override
    async def place_market_order(self, symbol: str, side: TradeSide, qty: float, reduce_only: bool = False) -> dict[str, Any]:
        client = await self._get_client()
        side_val = "BUY" if side == TradeSide.LONG else "SELL"
        res = await client.futures_create_order(
            symbol=symbol,
            side=side_val,
            type="MARKET",
            quantity=format_quantity(qty),
            reduceOnly="true" if reduce_only else "false",
        )
        return res

    @override
    async def place_limit_order(
        self,
        symbol: str,
        side: TradeSide,
        qty: float,
        price: float,
        reduce_only: bool = False,
    ) -> dict[str, Any]:
        client = await self._get_client()
        side_val = "BUY" if side == TradeSide.LONG else "SELL"
        res = await client.futures_create_order(
            symbol=symbol,
            side=side_val,
            type="LIMIT",
            timeInForce="GTC",
            quantity=format_quantity(qty),
            price=format_price(price),
            reduceOnly="true" if reduce_only else "false",
        )
        return res

    @override
    async def place_stop_market_order(self, symbol: str, side: TradeSide, stop_price: float) -> dict[str, Any]:
        client = await self._get_client()
        side_val = "BUY" if side == TradeSide.LONG else "SELL"
        res = await client.futures_create_order(
            symbol=symbol,
            side=side_val,
            type="STOP_MARKET",
            stopPrice=format_price(stop_price),
            closePosition="true",
            workingType="MARK_PRICE",
        )
        return res

    @override
    async def cancel_order(self, symbol: str, order_id: str | int) -> dict[str, Any]:
        client = await self._get_client()
        res = await client.futures_cancel_order(symbol=symbol, orderId=order_id)
        return res

    @override
    async def get_position(self, symbol: str) -> dict[str, Any]:
        client = await self._get_client()
        res = await client.futures_position_information(symbol=symbol)
        if isinstance(res, list) and len(res) > 0:
            return res[0]
        return {}

    @override
    async def cancel_all_orders(self, symbol: str) -> dict[str, Any]:
        client = await self._get_client()
        res = await client.futures_cancel_all_open_orders(symbol=symbol)
        return res

    @override
    async def set_leverage(self, symbol: str, leverage: int) -> dict[str, Any]:
        client = await self._get_client()
        res = await client.futures_change_leverage(symbol=symbol, leverage=leverage)
        return res

    @override
    async def listen_user_stream(self, on_update_callback):
        """Listen to Binance user data stream for order updates.

        Automatically reconnects on connection errors with exponential backoff.
        """
        client = await self._get_client()
        bm = BinanceSocketManager(client)

        logger.info("📡 Connecting to Binance WebSocket (User Data Stream)...")
        retry_count = 0
        max_retries = 5

        while True:
            try:
                async with bm.futures_user_socket() as stream:
                    logger.info("✅ Binance WebSocket connected successfully")
                    retry_count = 0  # Reset retry count on successful connection

                    while True:
                        res = await stream.recv()
                        if res:
                            await on_update_callback(res)

            except Exception as e:
                retry_count += 1
                error_msg = str(e).lower()

                if "api" in error_msg and ("key" in error_msg or "signature" in error_msg):
                    logger.error("❌ Binance WebSocket authorization failed. Please check your API keys.")
                    logger.error("   Required permissions: Enable Futures, Enable Reading")
                    raise  # Don't retry on auth errors
                elif retry_count >= max_retries:
                    logger.error(f"❌ Binance WebSocket failed after {max_retries} retries. Giving up.")
                    raise
                else:
                    backoff_time = min(5 * retry_count, 30)  # Max 30 seconds
                    logger.warning(f"⚠️ Binance WebSocket error: {e}")
                    logger.info(f"🔄 Reconnecting in {backoff_time}s... (attempt {retry_count}/{max_retries})")
                    await asyncio.sleep(backoff_time)

    @override
    async def place_sl_tp_orders(
        self, symbol: str, side: TradeSide, stop_loss: float | None, take_profits: list[float], qty: float, tp_distribution: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Place stop-loss and take-profit orders for a position.

        This method places conditional orders for risk management. Stop-loss uses
        closePosition=true to close the entire position. Take-profits are split
        equally across all TP levels.

        Args:
            symbol: Trading pair symbol (e.g., 'BTCUSDT').
            side: Position side (LONG or SHORT).
            stop_loss: Stop-loss price, or None to skip.
            take_profits: List of take-profit prices.
            qty: Total position quantity to split across TPs.
            tp_distribution: Distribution configuration (currently unused).

        Returns:
            Dictionary with 'stop_loss' and 'take_profits' order responses.

        Note:
            - SL must be at least 0.3% away from current price
            - Each TP quantity must meet minimum quantity requirements
            - If quantity is too small to split, all TPs are skipped
        """
        client = await self._get_client()
        results: dict[str, Any] = {"stop_loss": None, "take_profits": []}
        close_side = "SELL" if side == TradeSide.LONG else "BUY"

        if stop_loss:
            try:
                current_price = await self.get_last_price(symbol)

                if self._validate_sl_distance(stop_loss, current_price, side):
                    res = await client.futures_create_order(
                        symbol=symbol, side=close_side, type="STOP_MARKET", stopPrice=format_price(stop_loss), closePosition="true", workingType="MARK_PRICE"
                    )
                    results["stop_loss"] = res
            except Exception as e:
                logger.error(f"Error placing SL for {symbol}: {e}")

        if take_profits:
            # Get current price for validation
            try:
                current_price = await self.get_last_price(symbol)
                logger.info(f"Current price for {symbol}: {current_price}, placing {len(take_profits)} TP orders")
            except Exception as e:
                logger.warning(f"Could not get current price for {symbol}: {e}")
                current_price = None

            # Get symbol precision
            try:
                symbol_info = await self.get_symbol_info(symbol)
                price_precision = symbol_info.get("price_precision", 3)
                qty_precision = symbol_info.get("qty_precision", 3)
                min_qty = symbol_info.get("min_qty", 1.0)
                logger.info(f"Symbol info for {symbol}: price_precision={price_precision}, qty_precision={qty_precision}, min_qty={min_qty}")
            except Exception as e:
                logger.warning(f"Could not get symbol info for {symbol}: {e}. Using defaults.")
                price_precision = 3
                qty_precision = 2
                min_qty = 1.0

            each_qty = qty / len(take_profits)

            # Check if each TP qty meets minimum requirement
            if each_qty < min_qty:
                logger.warning(f"Each TP qty {each_qty:.6f} is less than min_qty {min_qty}. Cannot split {qty} into {len(take_profits)} TPs. Skipping TP orders.")
                return results

            for i, tp in enumerate(take_profits):
                try:
                    # Validate TP price against current price
                    if current_price and not self._validate_tp_price(tp, current_price, side, i + 1):
                        continue

                    # Round and format
                    tp_rounded = round(tp, price_precision)
                    qty_str = self._format_number(each_qty, qty_precision)
                    tp_str = self._format_number(tp_rounded, price_precision)

                    logger.debug(f"TP{i + 1}: {tp} → {tp_str} (precision={price_precision}), qty={qty_str}")

                    res = await client.futures_create_order(
                        symbol=symbol,
                        side=close_side,
                        type="TAKE_PROFIT_MARKET",
                        stopPrice=tp_str,
                        quantity=qty_str,
                        reduceOnly="true",
                        workingType="MARK_PRICE",
                    )
                    results["take_profits"].append(res)
                    logger.info(f"✅ TP{i + 1} placed at {tp_str} with qty {qty_str} for {symbol}")
                    logger.debug(f"TP{i + 1} Binance response: {res}")
                except Exception as e:
                    logger.error(f"❌ Error placing TP{i + 1} at {tp} for {symbol}: {e}")

        return results

    @override
    async def get_symbol_info(self, symbol: str) -> dict[str, Any]:
        client = await self._get_client()
        info = await client.futures_exchange_info()
        for s in info["symbols"]:
            if s["symbol"] == symbol:
                # Extract quantityPrecision
                qty_precision = s.get("quantityPrecision", 3)
                price_precision = s.get("pricePrecision", 8)
                return {
                    "qty_precision": qty_precision,
                    "price_precision": price_precision,
                    "min_qty": float(s["filters"][1]["minQty"]),  # LOT_SIZE filter
                }
        return {"qty_precision": 3, "price_precision": 8, "min_qty": 0.001}
