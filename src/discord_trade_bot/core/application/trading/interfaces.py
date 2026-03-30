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
    async def place_stop_market_order(
        self,
        symbol: str,
        side: TradeSide,
        stop_price: float,
        qty: float | None = None,
    ) -> dict[str, Any]:
        """Place a stop market order.

        Args:
            symbol: Trading pair symbol
            side: Position side (LONG or SHORT)
            stop_price: Stop trigger price
            qty: Optional quantity. If None, uses closePosition=true

        Returns:
            Order response from exchange
        """
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
        tp_distribution: dict[int, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        pass

    @abstractmethod
    async def listen_user_stream(self, on_update_callback: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        pass

    @abstractmethod
    async def get_symbol_info(self, symbol: str) -> dict[str, Any]:
        pass

    @abstractmethod
    async def list_open_orders(self, symbol: str) -> list[dict[str, Any]]:
        """List all open orders for a symbol.

        Args:
            symbol: Trading pair symbol

        Returns:
            List of open orders with at least 'orderId' field
        """
        pass

    @abstractmethod
    async def get_order_status(self, symbol: str, order_id: str) -> dict[str, Any]:
        """Get order status from exchange.

        Args:
            symbol: Trading pair symbol
            order_id: Order ID to check

        Returns:
            Order information including status (NEW, FILLED, CANCELLED, etc.)
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        pass

    @abstractmethod
    def is_position_open(self, position: dict[str, Any], side: TradeSide) -> bool:
        """Check if position is open based on exchange data.

        Args:
            position: Position data from exchange
            side: Expected position side

        Returns:
            True if position is open in the correct direction
        """
        pass

    @abstractmethod
    async def wait_for_position_ready(
        self,
        symbol: str,
        side: TradeSide,
        timeout: float = 10.0,
        check_interval: float = 0.5,
    ) -> bool:
        """Wait for position to appear on exchange after order fill.

        Args:
            symbol: Trading symbol
            side: Position side (LONG/SHORT)
            timeout: Maximum wait time in seconds
            check_interval: Interval between checks in seconds

        Returns:
            True if position found, False if timeout
        """
        pass


class ExchangeRegistryProtocol(ABC):
    @abstractmethod
    def get_exchange(self, name: str) -> ExchangeGatewayProtocol:
        pass
