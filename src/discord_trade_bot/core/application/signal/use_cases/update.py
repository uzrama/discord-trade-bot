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

        # Find positions waiting for updates across all configured exchanges
        all_positions = []
        for exchange_cfg in source_cfg.exchanges:
            positions = await self._state_repository.get_open_positions_by_symbol_and_exchange(symbol=sig.symbol, exchange=exchange_cfg.name)
            all_positions.extend(positions)

        target_position = None
        for pos in all_positions:
            if pos.message_id == dto.message_id:
                # For WAITING_UPDATE: always allow update
                if pos.status == PositionStatus.WAITING_UPDATE:
                    target_position = pos
                    break
                # For OPEN with default SL: allow update if signal has new SL
                elif pos.status == PositionStatus.OPEN and pos.is_default_sl and sig.stop_loss is not None:
                    target_position = pos
                    break
                # For OPEN with full SL/TP: select it to check if we should ignore
                elif pos.status == PositionStatus.OPEN:
                    target_position = pos
                    break

        if not target_position:
            logger.info(f"No position found for update: {sig.symbol} (message_id: {dto.message_id})")
            return SignalProcessingResultDTO(
                success=False,
                message_id=dto.message_id,
                reason="No position found for update",
            )

        # Check if position already has full SL/TP and is not waiting for updates
        if target_position.status == PositionStatus.OPEN:
            if not target_position.needs_signal_stop_update and not target_position.needs_signal_tp_update:
                logger.info(
                    f"✋ Position {sig.symbol} already has full SL/TP (status: OPEN, "
                    f"needs_stop_update: False, needs_tp_update: False). "
                    f"Ignoring signal update from message {dto.message_id}."
                )
                return SignalProcessingResultDTO(
                    success=False,
                    message_id=dto.message_id,
                    symbol=sig.symbol,
                    reason="Position already has full SL/TP, not waiting for updates",
                )

        # Check if we got new SL/TP data
        # For SL: check if signal has SL AND it's different from current SL
        # For TP: check if signal has TPs AND position is waiting for TP update

        # For OPEN with default SL: accept any SL from signal (replaces default)
        if target_position.status == PositionStatus.OPEN and target_position.is_default_sl:
            got_new_stop = sig.stop_loss is not None
        else:
            # For WAITING_UPDATE or OPEN with real SL: check if SL changed
            got_new_stop = sig.stop_loss is not None and sig.stop_loss != target_position.stop_loss

        # For TP: check based on status
        if target_position.status == PositionStatus.WAITING_UPDATE:
            got_new_tps = bool(sig.take_profits) and target_position.needs_signal_tp_update
        else:  # OPEN
            # For OPEN: check if TP list changed
            got_new_tps = bool(sig.take_profits) and sig.take_profits != target_position.take_profits

        if not got_new_stop and not got_new_tps:
            logger.info(
                f"Signal update for {sig.symbol} but no new SL/TP data "
                f"(status={target_position.status}, is_default_sl={target_position.is_default_sl}, "
                f"current_sl={target_position.stop_loss}, new_sl={sig.stop_loss}, "
                f"current_tps={target_position.take_profits}, new_tps={sig.take_profits})"
            )
            return SignalProcessingResultDTO(
                success=False,
                message_id=dto.message_id,
                reason="No new SL/TP data in update",
            )

        logger.info(
            f"Processing signal update for {sig.symbol}: "
            f"position_status={target_position.status}, "
            f"got_new_stop={got_new_stop} (old={target_position.stop_loss}, new={sig.stop_loss}), "
            f"got_new_tps={got_new_tps} (old={target_position.take_profits}, new={sig.take_profits})"
        )

        # Track if SL was default before update (for notification)
        was_default = target_position.is_default_sl

        # Update position with new SL/TP
        if got_new_stop:
            old_sl = target_position.stop_loss

            target_position.stop_loss = sig.stop_loss
            target_position.is_default_sl = False  # Now SL is from signal, not default
            target_position.needs_signal_stop_update = False
            target_position.temporary_stop = None

            if was_default:
                logger.info(f"Replaced default SL with signal SL for {sig.symbol}: {old_sl} (default) → {sig.stop_loss} (from signal)")
            else:
                logger.info(f"Updated SL for {sig.symbol}: {old_sl} → {sig.stop_loss}")

        if got_new_tps:
            target_position.take_profits = sig.take_profits
            target_position.needs_signal_tp_update = False

            # Update TP distribution
            tp_distributions_dict: dict[int, list[dict[str, Any]]] = {}
            if source_cfg.tp_distributions:
                tp_distributions_dict = {k: [tp.model_dump() for tp in v] for k, v in source_cfg.tp_distributions.items()}

            num_tps = len(sig.take_profits)
            if num_tps in tp_distributions_dict:
                from discord_trade_bot.core.domain.value_objects.trading import TPDistributionRow

                target_position.tp_distribution = [TPDistributionRow(label=tp["label"], close_pct=tp["close_pct"]) for tp in tp_distributions_dict[num_tps]]

            logger.info(f"Updated TPs for {sig.symbol}: {sig.take_profits}")

        # Update message hash
        target_position.message_hash = sig.message_hash

        # Rebuild position risk orders (cancel old SL/TP and place new ones)
        # Use the exchange from the position itself (not from source_cfg)
        exchange = self._exchange_registry.get_exchange(target_position.exchange)

        try:
            # Prepare keep_order_ids (entry order should be kept if it exists)
            keep_order_ids = set()
            if target_position.order_id:
                keep_order_ids.add(str(target_position.order_id))

            # Rebuild risk orders (cancel old SL/TP, place new ones)
            sl_tp_res = await self._rebuild_position_risk_orders(
                exchange=exchange,
                symbol=sig.symbol,
                side=target_position.side,
                stop_loss=target_position.stop_loss,
                take_profits=target_position.take_profits,
                qty=target_position.remaining_qty or target_position.qty,
                tp_distribution={len(target_position.take_profits): [{"label": tp.label, "close_pct": tp.close_pct} for tp in target_position.tp_distribution]}
                if target_position.tp_distribution
                else {},
                keep_order_ids=keep_order_ids,
            )

            # Update order IDs
            sl_order = sl_tp_res.get("stop_loss")
            if sl_order:
                target_position.sl_order_id = str(sl_order.get("algoId") or sl_order.get("orderId") or "")

            tp_order_ids = {}
            for i, tp_order in enumerate(sl_tp_res.get("take_profits", [])):
                order_id = tp_order.get("algoId") or tp_order.get("orderId")
                if order_id and i < len(target_position.take_profits):
                    tp_price = float(target_position.take_profits[i])
                    tp_order_ids[str(order_id)] = tp_price
            target_position.tp_order_ids = tp_order_ids

            logger.info(f"✅ Rebuilt SL/TP for {sig.symbol}: SL={target_position.stop_loss}, TPs={target_position.take_profits}")

        except Exception as e:
            logger.error(f"❌ Failed to rebuild SL/TP for {sig.symbol}: {e}")
            await self._notification_gateway.send_message(f"⚠️ Failed to rebuild SL/TP for {sig.symbol}: {e}")
            return SignalProcessingResultDTO(success=False, message_id=dto.message_id, reason=f"Failed to rebuild SL/TP: {e}")

        # Update status to OPEN only if it was WAITING_UPDATE
        if target_position.status == PositionStatus.WAITING_UPDATE:
            target_position.status = PositionStatus.OPEN
            logger.info(f"Position status changed from WAITING_UPDATE to OPEN for {sig.symbol}")
        # If already OPEN, keep it OPEN (just updated SL/TP)

        # Save updated position
        await self._state_repository.save_position(target_position)

        # Send notification
        if target_position.status == PositionStatus.OPEN and got_new_stop and was_default:
            # Replaced default SL with signal SL
            message = f"✅ Replaced default SL with signal SL for {sig.symbol}\n🛡 Stop Loss: {target_position.stop_loss}"
        elif got_new_stop and got_new_tps:
            message = f"✅ Updated {sig.symbol} with SL/TP from signal edit"
            if target_position.stop_loss:
                message += f"\n🛡 Stop Loss: {target_position.stop_loss}"
            if target_position.take_profits:
                message += f"\n🎯 Take Profits: {', '.join(str(tp) for tp in target_position.take_profits)}"
        elif got_new_stop:
            message = f"✅ Updated SL for {sig.symbol}\n🛡 Stop Loss: {target_position.stop_loss}"
        else:  # got_new_tps
            message = f"✅ Updated TPs for {sig.symbol}\n🎯 Take Profits: {', '.join(str(tp) for tp in target_position.take_profits)}"

        await self._notification_gateway.send_message(message)

        return SignalProcessingResultDTO(success=True, message_id=dto.message_id, reason="Signal update processed")
