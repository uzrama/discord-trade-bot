from abc import ABC, abstractmethod
from typing import Any

from discord_trade_bot.core.domain.entities.position import ActivePositionEntity


class StateRepositoryProtocol(ABC):
    """Protocol for managing position state persistence.

    This protocol defines the interface for storing and retrieving trading positions
    from persistent storage. Implementations should handle serialization, deserialization,
    and querying of position data.
    """

    @abstractmethod
    async def get_open_positions(self) -> list[ActivePositionEntity]:
        """Retrieve all open positions.

        Returns:
            List of all currently open positions across all exchanges and symbols.
        """
        pass

    @abstractmethod
    async def get_position_by_id(self, position_id: str) -> ActivePositionEntity | None:
        """Retrieve a specific position by its ID.

        Args:
            position_id: Unique identifier of the position.

        Returns:
            The position if found and still open, None otherwise.
        """
        pass

    @abstractmethod
    async def get_open_positions_by_symbol_and_exchange(self, symbol: str, exchange: str) -> list[ActivePositionEntity]:
        """Retrieve open positions filtered by symbol and exchange.

        This method is used to check for duplicate positions before opening a new one.

        Args:
            symbol: Trading pair symbol (e.g., 'BTCUSDT').
            exchange: Exchange name (e.g., 'binance', 'bybit').

        Returns:
            List of open positions matching the symbol and exchange.
        """
        pass

    @abstractmethod
    async def save_position(self, position: ActivePositionEntity) -> None:
        """Save or update a position.

        If the position doesn't have an ID, one will be generated. If it exists,
        the position will be updated with the new data.

        Args:
            position: Position entity to save or update.
        """
        pass

    @abstractmethod
    async def append_trade_log(self, trade_data: dict[str, Any]) -> None:
        """Append a trade event to the trade log.

        Args:
            trade_data: Dictionary containing trade event information.
        """
        pass
