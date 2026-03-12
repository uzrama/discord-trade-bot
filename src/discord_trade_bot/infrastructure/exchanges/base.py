from abc import ABC, abstractmethod
from typing import Any, override

from discord_trade_bot.core.application.trading.interfaces import (
    ExchangeGatewayProtocol,
)
from discord_trade_bot.core.domain.value_objects.trading import TradeSide


class BaseExchangeAdapter(ExchangeGatewayProtocol, ABC):
    @override
    async def close(self):
        pass

    @abstractmethod
    async def get_symbol_info(self, symbol: str) -> dict[str, Any]:
        """Get symbol trading rules (precision, min qty, etc.)"""
        ...

    async def close_position_market(self, symbol: str, side: TradeSide, qty: float) -> dict[str, Any]:
        close_side = TradeSide.SHORT if side == TradeSide.LONG else TradeSide.LONG
        return await self.place_market_order(symbol, close_side, qty, reduce_only=True)
