import logging
from typing import Any, final

from discord_trade_bot.core.application.common.interfaces.notification import (
    NotificationGatewayProtocol,
)
from discord_trade_bot.core.application.common.interfaces.repository import (
    StateRepositoryProtocol,
)
from discord_trade_bot.core.application.signal.dto import (
    ProcessSignalDTO,
    SignalProcessingResultDTO,
)
from discord_trade_bot.core.application.trading.interfaces import (
    ExchangeGatewayProtocol,
    ExchangeRegistryProtocol,
)
from discord_trade_bot.core.domain.entities.signal import ParsedSignalEntity
from discord_trade_bot.core.domain.value_objects.trading import PositionStatus, TradeSide
from discord_trade_bot.main.config.app import AppConfig

logger = logging.getLogger(__name__)


@final
class HandleSignalUpdateUseCase:
    """Use case for handling signal updates (edited messages with new SL/TP).

    This use case handles the workflow when a Discord message is edited to add
    or update stop loss and take profit levels for an already opened position.

    Attributes:
        _exchange_registry: Registry for exchange adapters.
        _notification_gateway: Gateway for sending notifications.
        _state_repository: Repository for position state management.
        _config: Application configuration.
    """

    def __init__(
        self,
        exchange_registry: ExchangeRegistryProtocol,
        notification_gateway: NotificationGatewayProtocol,
        state_repository: StateRepositoryProtocol,
        config: AppConfig,
    ):
        self._exchange_registry = exchange_registry
        self._notification_gateway = notification_gateway
        self._state_repository = state_repository
        self._config = config

    async def _rebuild_position_risk_orders(
        self,
        exchange: ExchangeGatewayProtocol,
        symbol: str,
        side: TradeSide,
        stop_loss: float | None,
        take_profits: list[float],
        qty: float,
        tp_distribution: dict[int, list[dict[str, Any]]],
        keep_order_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        """Rebuild position risk orders (SL/TP) by cancelling old ones and placing new ones.

        This method:
        1. Gets all open orders for the symbol
        2. Cancels all orders except those in keep_order_ids
        3. Places new SL/TP orders

        Args:
            exchange: Exchange gateway
            symbol: Trading symbol
            side: Position side
            stop_loss: Stop loss price
            take_profits: List of take profit prices
            qty: Position quantity
            tp_distribution: TP distribution configuration
            keep_order_ids: Set of order IDs to keep (e.g., entry order)

        Returns:
            Result from place_sl_tp_orders
        """
        keep_ids = keep_order_ids or set()

        # 1. Get all open orders
        try:
            open_orders = await exchange.list_open_orders(symbol)
        except Exception as e:
            logger.warning(f"Failed to list open orders for {symbol}: {e}")
            open_orders = []

        # 2. Cancel all orders except those in keep_ids
        cancelled_orders = []
        for order in open_orders:
            order_id = str(order.get("orderId") or order.get("order_id") or order.get("id") or "")
            if not order_id:
                continue

            if order_id in keep_ids:
                logger.info(f"Keeping order {order_id} for {symbol}")
                continue

            try:
                await exchange.cancel_order(symbol, order_id)
                cancelled_orders.append(order_id)
                logger.info(f"Cancelled order {order_id} for {symbol}")
            except Exception as e:
                logger.warning(f"Failed to cancel order {order_id} for {symbol}: {e}")

        if cancelled_orders:
            logger.info(f"Cancelled {len(cancelled_orders)} orders for {symbol}: {cancelled_orders}")

        # 3. Place new SL/TP orders
        sl_tp_res = await exchange.place_sl_tp_orders(
            symbol=symbol,
            side=side,
            stop_loss=stop_loss,
            take_profits=take_profits,
            qty=qty,
            tp_distribution=tp_distribution,
        )

        return sl_tp_res

    async def execute(self, sig: ParsedSignalEntity, dto: ProcessSignalDTO) -> SignalProcessingResultDTO:
        """Handle signal update for an existing position.

        This method:
        1. Finds the position waiting for updates (status = WAITING_UPDATE)
        2. Checks if new SL/TP data is available in the signal
        3. Adds SL/TP orders to the existing position
        4. Updates position status to OPEN

        Args:
            sig: Parsed signal entity with updated SL/TP data.
            dto: Data transfer object containing channel ID and message ID.

        Returns:
            Result indicating success/failure and relevant details.
        """
        if not sig.symbol:
            return SignalProcessingResultDTO(success=False, message_id=dto.message_id, reason="No symbol in update")

        # Get source config
        watch_sources = self._config.yaml.discord.watch_sources
        source_cfg = next((s for s in watch_sources if str(s.channel_id) == str(dto.channel_id)), None)

        if not source_cfg:
            logger.warning(f"Unknown channel {dto.channel_id}")
            return SignalProcessingResultDTO(success=False, message_id=dto.message_id, reason="Unknown channel")

        # Find position waiting for updates
        positions = await self._state_repository.get_open_positions_by_symbol_and_exchange(symbol=sig.symbol, exchange=source_cfg.exchange)

        waiting_position = None
        for pos in positions:
            if pos.status == PositionStatus.WAITING_UPDATE and pos.message_id == dto.message_id:
                waiting_position = pos
                break

        if not waiting_position:
            logger.info(f"No position waiting for update: {sig.symbol} on {source_cfg.exchange}")
            return SignalProcessingResultDTO(
                success=False,
                message_id=dto.message_id,
                reason="No position waiting for update",
            )

        # Check if we got new SL/TP data
        # For SL: check if signal has SL AND it's different from current SL
        # For TP: check if signal has TPs AND position is waiting for TP update
        got_new_stop = sig.stop_loss is not None and sig.stop_loss != waiting_position.stop_loss
        got_new_tps = bool(sig.take_profits) and waiting_position.needs_signal_tp_update

        if not got_new_stop and not got_new_tps:
            logger.info(
                f"Signal update for {sig.symbol} but no new SL/TP data (needs_stop={waiting_position.needs_signal_stop_update}, needs_tp={waiting_position.needs_signal_tp_update})"
            )
            return SignalProcessingResultDTO(
                success=False,
                message_id=dto.message_id,
                reason="No new SL/TP data in update",
            )

        logger.info(f"Processing signal update for {sig.symbol}: got_new_stop={got_new_stop}, got_new_tps={got_new_tps}")

        # Update position with new SL/TP
        if got_new_stop:
            waiting_position.stop_loss = sig.stop_loss
            waiting_position.needs_signal_stop_update = False
            waiting_position.temporary_stop = None
            logger.info(f"Updated SL for {sig.symbol}: {sig.stop_loss}")

        if got_new_tps:
            waiting_position.take_profits = sig.take_profits
            waiting_position.needs_signal_tp_update = False

            # Update TP distribution
            tp_distributions_dict: dict[int, list[dict[str, Any]]] = {}
            if source_cfg.tp_distributions:
                tp_distributions_dict = {k: [tp.model_dump() for tp in v] for k, v in source_cfg.tp_distributions.items()}

            num_tps = len(sig.take_profits)
            if num_tps in tp_distributions_dict:
                from discord_trade_bot.core.domain.value_objects.trading import TPDistributionRow

                waiting_position.tp_distribution = [TPDistributionRow(label=tp["label"], close_pct=tp["close_pct"]) for tp in tp_distributions_dict[num_tps]]

            logger.info(f"Updated TPs for {sig.symbol}: {sig.take_profits}")

        # Update message hash
        waiting_position.message_hash = sig.message_hash

        # Rebuild position risk orders (cancel old SL/TP and place new ones)
        exchange = self._exchange_registry.get_exchange(source_cfg.exchange)

        try:
            # Prepare keep_order_ids (entry order should be kept if it exists)
            keep_order_ids = set()
            if waiting_position.order_id:
                keep_order_ids.add(str(waiting_position.order_id))

            # Rebuild risk orders (cancel old SL/TP, place new ones)
            sl_tp_res = await self._rebuild_position_risk_orders(
                exchange=exchange,
                symbol=sig.symbol,
                side=waiting_position.side,
                stop_loss=waiting_position.stop_loss,
                take_profits=waiting_position.take_profits,
                qty=waiting_position.remaining_qty or waiting_position.qty,
                tp_distribution={len(waiting_position.take_profits): [{"label": tp.label, "close_pct": tp.close_pct} for tp in waiting_position.tp_distribution]}
                if waiting_position.tp_distribution
                else {},
                keep_order_ids=keep_order_ids,
            )

            # Update order IDs
            sl_order = sl_tp_res.get("stop_loss")
            if sl_order:
                waiting_position.sl_order_id = str(sl_order.get("algoId") or sl_order.get("orderId") or "")

            tp_order_ids = {}
            for i, tp_order in enumerate(sl_tp_res.get("take_profits", [])):
                order_id = tp_order.get("algoId") or tp_order.get("orderId")
                if order_id and i < len(waiting_position.take_profits):
                    tp_price = float(waiting_position.take_profits[i])
                    tp_order_ids[str(order_id)] = tp_price
            waiting_position.tp_order_ids = tp_order_ids

            logger.info(f"✅ Rebuilt SL/TP for {sig.symbol}: SL={waiting_position.stop_loss}, TPs={waiting_position.take_profits}")

        except Exception as e:
            logger.error(f"❌ Failed to rebuild SL/TP for {sig.symbol}: {e}")
            await self._notification_gateway.send_message(f"⚠️ Failed to rebuild SL/TP for {sig.symbol}: {e}")
            return SignalProcessingResultDTO(success=False, message_id=dto.message_id, reason=f"Failed to rebuild SL/TP: {e}")

        # Update status to OPEN (no longer waiting for updates)
        waiting_position.status = PositionStatus.OPEN

        # Save updated position
        await self._state_repository.save_position(waiting_position)

        # Send notification
        message = f"✅ Updated {sig.symbol} with SL/TP from signal edit"
        if waiting_position.stop_loss:
            message += f"\nSL: {waiting_position.stop_loss}"
        if waiting_position.take_profits:
            message += f"\nTPs: {', '.join(str(tp) for tp in waiting_position.take_profits)}"

        await self._notification_gateway.send_message(message)

        return SignalProcessingResultDTO(success=True, message_id=dto.message_id, reason="Signal update processed")
