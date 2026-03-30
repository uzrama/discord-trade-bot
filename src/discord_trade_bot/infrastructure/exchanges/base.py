import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, override

from discord_trade_bot.core.application.trading.interfaces import (
    ExchangeGatewayProtocol,
)
from discord_trade_bot.core.domain.value_objects.trading import TradeSide

logger = logging.getLogger(__name__)


class BaseExchangeAdapter(ExchangeGatewayProtocol, ABC):
    @override
    async def close(self):
        pass

    @abstractmethod
    async def get_symbol_info(self, symbol: str) -> dict[str, Any]:
        """Get symbol trading rules (precision, min qty, etc.)"""
        ...

    @abstractmethod
    async def get_position(self, symbol: str) -> dict[str, Any]:
        """Get current position for symbol"""
        ...

    async def close_position_market(self, symbol: str, side: TradeSide, qty: float) -> dict[str, Any]:
        close_side = TradeSide.SHORT if side == TradeSide.LONG else TradeSide.LONG
        return await self.place_market_order(symbol, close_side, qty, reduce_only=True)

    def is_position_open(self, position: dict[str, Any], side: TradeSide) -> bool:
        """Check if position is open based on exchange data.

        Supports both Binance and Bybit formats.

        Args:
            position: Position data from exchange
            side: Expected position side

        Returns:
            True if position is open in the correct direction
        """
        if not position:
            return False

        # Binance format: {"positionAmt": "0.001", ...}
        if "positionAmt" in position:
            position_amt = float(position.get("positionAmt", 0))

            if side == TradeSide.LONG:
                return position_amt > 0
            else:  # SHORT
                return position_amt < 0

        # Bybit format: {"size": "0.001", "side": "Buy", ...}
        if "size" in position:
            size = float(position.get("size", 0))
            position_side = position.get("side", "").lower()

            if size <= 0:
                return False

            if side == TradeSide.LONG:
                return position_side == "buy"
            else:  # SHORT
                return position_side == "sell"

        # Unknown format
        logger.warning(f"⚠️ Unknown position format: {position}")
        return False

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
            timeout: Maximum wait time in seconds (default: 10s)
            check_interval: Interval between checks in seconds (default: 0.5s)

        Returns:
            True if position found, False if timeout
        """
        import time

        start_time = time.time()
        attempts = 0

        while True:
            attempts += 1
            elapsed = time.time() - start_time

            # Check timeout
            if elapsed >= timeout:
                logger.error(f"❌ Timeout waiting for position {symbol} after {timeout}s ({attempts} attempts)")
                return False

            try:
                # Get position information
                position = await self.get_position(symbol)

                # Check if position is open
                if self.is_position_open(position, side):
                    logger.info(f"✅ Position {symbol} confirmed after {elapsed:.2f}s ({attempts} attempts)")
                    return True

                # Log every 2 seconds
                if attempts % 4 == 0:  # Every 2s at 0.5s interval
                    logger.info(f"⏳ Waiting for position {symbol}... ({elapsed:.1f}s elapsed)")

            except Exception as e:
                logger.warning(f"⚠️ Error checking position {symbol}: {e}")

            # Wait before next check
            await asyncio.sleep(check_interval)
