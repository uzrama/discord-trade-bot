from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any

from discord_trade_bot.core.domain.value_objects.trading import TradeSide


class ExchangeGatewayProtocol(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    async def get_last_price(self, symbol: str) -> float:
        pass

    @abstractmethod
    async def get_balance(self) -> float:
        pass

    @abstractmethod
    async def place_market_order(self, symbol: str, side: TradeSide, qty: float, reduce_only: bool = False) -> dict[str, Any]:
        pass

    @abstractmethod
    async def place_limit_order(
        self,
        symbol: str,
        side: TradeSide,
        qty: float,
        price: float,
        reduce_only: bool = False,
    ) -> dict[str, Any]:
        pass

    @abstractmethod
    async def place_stop_market_order(self, symbol: str, side: TradeSide, stop_price: float) -> dict[str, Any]:
        pass

    @abstractmethod
    async def cancel_order(self, symbol: str, order_id: str | int) -> dict[str, Any]:
        pass

    @abstractmethod
    async def get_position(self, symbol: str) -> dict[str, Any]:
        pass

    @abstractmethod
    async def cancel_all_orders(self, symbol: str) -> dict[str, Any]:
        pass

    @abstractmethod
    async def set_leverage(self, symbol: str, leverage: int) -> dict[str, Any]:
        pass

    @abstractmethod
    async def place_sl_tp_orders(  # noqa: PLR0913
        self,
        symbol: str,
        side: TradeSide,
        stop_loss: float | None,
        take_profits: list[float],
        qty: float,
        tp_distribution: list[dict[str, Any]],
    ) -> dict[str, Any]:
        pass

    @abstractmethod
    async def listen_user_stream(self, on_update_callback: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        pass

    @abstractmethod
    async def get_symbol_info(self, symbol: str) -> dict[str, Any]:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass


class ExchangeRegistryProtocol(ABC):
    @abstractmethod
    def get_exchange(self, name: str) -> ExchangeGatewayProtocol:
        pass
