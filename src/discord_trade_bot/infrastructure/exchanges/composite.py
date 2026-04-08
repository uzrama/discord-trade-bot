import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, final, override

from discord_trade_bot.core.application.trading.interfaces import ExchangeGatewayProtocol, ExchangeRegistryProtocol
from discord_trade_bot.core.domain.value_objects.trading import TradeSide

logger = logging.getLogger(__name__)


@final
class CompositeExchangeGateway(ExchangeGatewayProtocol, ExchangeRegistryProtocol):
    def __init__(self, exchanges: dict[str, ExchangeGatewayProtocol]):
        self._exchanges = exchanges

    @override
    def get_exchange(self, name: str) -> ExchangeGatewayProtocol:
        adapter = self._exchanges.get(name)
        if not adapter:
            if not self._exchanges:
                raise RuntimeError("No exchange adapters configured")
            return next(iter(self._exchanges.values()))
        return adapter

    def _get_default_exchange(self) -> ExchangeGatewayProtocol:
        """Get the first available exchange adapter."""
        if not self._exchanges:
            raise RuntimeError("No exchange adapters configured")
        return next(iter(self._exchanges.values()))

    @property
    @override
    def name(self) -> str:
        return "composite"

    @override
    async def get_last_price(self, symbol: str) -> float:
        # This is ambiguous in composite, we probably shouldn't call it on composite directly
        return await self._get_default_exchange().get_last_price(symbol)

    @override
    async def get_balance(self) -> float:
        return await self._get_default_exchange().get_balance()

    @override
    async def place_market_order(self, symbol: str, side: TradeSide, qty: float, reduce_only: bool = False) -> dict[str, Any]:
        return await self._get_default_exchange().place_market_order(symbol, side, qty, reduce_only)

    @override
    async def place_limit_order(self, symbol: str, side: TradeSide, qty: float, price: float, reduce_only: bool = False) -> dict[str, Any]:
        return await self._get_default_exchange().place_limit_order(symbol, side, qty, price, reduce_only)

    @override
    async def place_stop_market_order(self, symbol: str, side: TradeSide, stop_price: float, qty: float | None = None) -> dict[str, Any]:
        return await self._get_default_exchange().place_stop_market_order(symbol, side, stop_price, qty)

    @override
    async def cancel_order(self, symbol: str, order_id: str | int) -> dict[str, Any]:
        return await self._get_default_exchange().cancel_order(symbol, order_id)

    @override
    async def get_position(self, symbol: str) -> dict[str, Any]:
        return await self._get_default_exchange().get_position(symbol)

    @override
    async def cancel_all_orders(self, symbol: str) -> dict[str, Any]:
        return await self._get_default_exchange().cancel_all_orders(symbol)

    @override
    async def set_leverage(self, symbol: str, leverage: int) -> dict[str, Any]:
        return await self._get_default_exchange().set_leverage(symbol, leverage)

    @override
    async def place_sl_tp_orders(
        self, symbol: str, side: TradeSide, stop_loss: float | None, take_profits: list[float], qty: float, tp_distribution: dict[int, list[dict[str, Any]]]
    ) -> dict[str, Any]:
        return await self._get_default_exchange().place_sl_tp_orders(symbol, side, stop_loss, take_profits, qty, tp_distribution)

    @override
    async def get_symbol_info(self, symbol: str) -> dict[str, Any]:
        return await self._get_default_exchange().get_symbol_info(symbol)

    @override
    async def list_open_orders(self, symbol: str) -> list[dict[str, Any]]:
        return await self._get_default_exchange().list_open_orders(symbol)

    @override
    async def get_order_status(self, symbol: str, order_id: str) -> dict[str, Any]:
        return await self._get_default_exchange().get_order_status(symbol, order_id)

    @override
    def is_position_open(self, position: dict[str, Any], side: TradeSide) -> bool:
        return self._get_default_exchange().is_position_open(position, side)

    @override
    async def wait_for_position_ready(
        self,
        symbol: str,
        side: TradeSide,
        timeout: float = 10.0,
        check_interval: float = 0.5,
    ) -> bool:
        return await self._get_default_exchange().wait_for_position_ready(symbol, side, timeout, check_interval)

    @override
    async def close(self):
        for adapter in self._exchanges.values():
            await adapter.close()

    @override
    async def listen_user_stream(self, on_update_callback: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        """Start WebSocket streams for all configured exchanges.

        Each exchange stream runs independently. If one fails, others continue running.
        """
        if not self._exchanges:
            logger.error("❌ No exchanges configured for WebSocket tracking")
            raise RuntimeError("No exchanges available for WebSocket tracking")

        async def safe_listen(name: str, adapter: ExchangeGatewayProtocol) -> None:
            """Wrapper to handle individual exchange stream errors gracefully."""
            try:
                await adapter.listen_user_stream(on_update_callback)
            except Exception as e:
                logger.error(f"❌ WebSocket stream failed for {name}: {e}")

        # Start all streams concurrently with error isolation
        tasks = [safe_listen(name, adapter) for name, adapter in self._exchanges.items()]
        await asyncio.gather(*tasks, return_exceptions=True)
