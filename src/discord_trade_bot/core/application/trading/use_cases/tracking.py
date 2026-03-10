import logging
from asyncio import Lock
from collections import defaultdict
from typing import Any, final

from discord_trade_bot.core.application.common.interfaces.notification import NotificationGatewayProtocol
from discord_trade_bot.core.application.common.interfaces.repository import StateRepositoryProtocol
from discord_trade_bot.core.application.trading.interfaces import ExchangeRegistryProtocol
from discord_trade_bot.core.domain.value_objects.trading import PositionStatus

logger = logging.getLogger(__name__)


@final
class ProcessTrackerEventUseCase:
    """Use case for processing exchange WebSocket events and updating position state.

    This use case listens to order execution events from exchanges (via WebSocket)
    and updates position state accordingly. It handles take-profit hits, stop-loss
    execution, and automatic breakeven management.

    Attributes:
        _exchange_registry: Registry for accessing exchange adapters.
        _state_repository: Repository for position state management.
        _notification_gateway: Gateway for sending notifications.
        _position_locks: Per-position locks to prevent race conditions.
    """

    def __init__(
        self,
        exchange_registry: ExchangeRegistryProtocol,
        state_repository: StateRepositoryProtocol,
        notification_gateway: NotificationGatewayProtocol,
    ):
        self._exchange_registry = exchange_registry
        self._state_repository = state_repository
        self._notification_gateway = notification_gateway
        self._position_locks: dict[str, Lock] = defaultdict(Lock)

    async def execute(self, event: dict[str, Any]) -> None:
        """Process a WebSocket event and update position state.

        This method performs the following:
        1. Extract order information from the event
        2. Find matching open positions by symbol
        3. Lock the position to prevent concurrent updates
        4. Check if the order is a TP or SL execution
        5. Update position state and move SL to breakeven if needed
        6. Close position if all TPs are hit or SL is triggered

        Args:
            event: WebSocket event dictionary containing order execution data.

        Note:
            Uses per-position locks to ensure thread-safe updates when multiple
            events arrive simultaneously for the same position.
        """
        order_info = event.get("o", {})
        order_id = str(order_info.get("i", ""))
        symbol = order_info.get("s", "")
        active_positions = await self._state_repository.get_open_positions()

        # Filter positions by symbol first (in memory, no DB query)
        matching_positions = [p for p in active_positions if p.symbol == symbol and p.id]

        if not matching_positions:
            logger.debug(f"No open positions found for {symbol}")
            return

        for position in matching_positions:
            position_id = position.id
            if not position_id:  # Extra safety check for type checker
                continue

            # Lock this specific position to prevent race conditions
            async with self._position_locks[position_id]:
                # Re-fetch only THIS position inside lock to get latest state
                position = await self._state_repository.get_position_by_id(position_id)
                if not position or position.status != PositionStatus.OPEN:
                    continue

                # Check for Take Profit execution
                if order_id in position.tp_order_ids:
                    tp_price = position.tp_order_ids.get(order_id, "Unknown")
                    logger.info(f"🎯 [USE CASE] Take profit {tp_price} reached for {symbol}!")
                    if not position.breakeven_applied:
                        await self._move_sl_to_breakeven(position)
                    position.tp_index_hit += 1
                    if position.tp_index_hit >= len(position.take_profits):
                        logger.info(f"DONE [USE CASE] All TPs for {symbol} reached. Position closed.")
                        position.status = PositionStatus.CLOSED
                    await self._state_repository.save_position(position)
                    break
                # Check for Stop Loss execution
                elif order_id == str(position.sl_order_id):
                    logger.info(f"🛑 [USE CASE] Stop Loss filled for {symbol}. Position closed.")
                    position.status = PositionStatus.CLOSED
                    await self._state_repository.save_position(position)
                    break

    async def _move_sl_to_breakeven(self, position) -> None:
        symbol = position.symbol
        old_sl_id = position.sl_order_id
        entry_price = position.entry_price
        side = position.side
        exchange_name = position.exchange
        exchange = self._exchange_registry.get_exchange(exchange_name)
        logger.info(f"🛡️ [USE CASE] Moving Stop Loss to breakeven ({entry_price}) for {symbol}...")
        if old_sl_id:
            try:
                await exchange.cancel_order(symbol, old_sl_id)
            except Exception as e:
                logger.warning(f"WARN Could not cancel old SL {old_sl_id}: {e}")
        try:
            res = await exchange.place_stop_market_order(symbol=symbol, side=side, stop_price=entry_price)
            new_sl_id = str(res.get("orderId"))

            position.sl_order_id = new_sl_id
            position.breakeven_applied = True
            position.break_even_price = entry_price
            msg = f"🛡️ **{symbol}**: Stop loss successfully moved to breakeven at {entry_price}!"
            logger.info(msg)
            await self._notification_gateway.send_message(msg)
        except Exception as e:
            err_msg = f"❌ Error moving SL to breakeven for {symbol}: {e}"
            logger.error(err_msg)
            await self._notification_gateway.send_message(err_msg)
            raise e
