import logging
from datetime import UTC, datetime
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
from discord_trade_bot.core.application.signal.use_cases.update import (
    HandleSignalUpdateUseCase,
)
from discord_trade_bot.core.application.trading.dto import TradeSettingsDTO
from discord_trade_bot.core.application.trading.interfaces import (
    ExchangeRegistryProtocol,
)
from discord_trade_bot.core.application.trading.use_cases import OpenPositionUseCase
from discord_trade_bot.core.domain.entities.position import ActivePositionEntity
from discord_trade_bot.core.domain.services.parser import SignalParserService
from discord_trade_bot.core.domain.value_objects.trading import PositionStatus, TradeSide
from discord_trade_bot.main.config.app import AppConfig

logger = logging.getLogger(__name__)


@final
class ProcessSignalUseCase:
    """Use case for processing trading signals from Discord channels.

    This use case handles the complete workflow of receiving a trading signal,
    validating it, checking for duplicates, and opening positions on exchanges.
    It acts as the main orchestrator for signal-to-trade conversion.

    Attributes:
        _exchange_gateway: Gateway for exchange operations.
        _notification_gateway: Gateway for sending notifications.
        _state_repository: Repository for position state management.
        _open_position_use_case: Use case for opening positions.
        _config: Application configuration.
        _parser: Service for parsing signal text.
    """

    def __init__(
        self,
        exchange_registry: ExchangeRegistryProtocol,
        notification_gateway: NotificationGatewayProtocol,
        state_repository: StateRepositoryProtocol,
        open_position_use_case: OpenPositionUseCase,
        config: AppConfig,
    ):
        self._exchange_registry = exchange_registry
        self._notification_gateway = notification_gateway
        self._state_repository = state_repository
        self._open_position_use_case = open_position_use_case
        self._config = config
        self._parser = SignalParserService()
        self._handle_signal_update_use_case = HandleSignalUpdateUseCase(
            exchange_registry=exchange_registry,
            notification_gateway=notification_gateway,
            state_repository=state_repository,
            config=config,
        )

    async def execute(self, dto: ProcessSignalDTO) -> SignalProcessingResultDTO:
        """Process a trading signal and open a position if valid.

        This method performs the following steps:
        1. Parse the signal text to extract trading parameters
        2. Validate the signal has required fields (symbol, side)
        3. Check for duplicate positions on the same exchange
        4. Open a new position if all checks pass
        5. Save position state for tracking

        Args:
            dto: Data transfer object containing channel ID, message ID, and signal text.

        Returns:
            Result indicating success/failure and relevant details.

        Note:
            Duplicate positions are prevented per symbol per exchange. The same symbol
            can be traded on different exchanges simultaneously.
        """
        sig = self._parser.parse(dto.channel_id, dto.message_id, dto.text)
        if not sig.is_signal or not sig.symbol or not sig.side:
            return SignalProcessingResultDTO(success=False, message_id=dto.message_id, reason="Invalid signal")

        # Decision logic: is it a primary signal or an update?
        if sig.signal_type == "signal_update":
            # Handle signal update (edited message with new SL/TP)
            logger.info(f"Processing signal update for {sig.symbol}")
            return await self._handle_signal_update_use_case.execute(sig, dto)

        if sig.signal_type == "primary_signal":
            # Get source config
            watch_sources = self._config.yaml.discord.watch_sources
            source_cfg = next((s for s in watch_sources if str(s.channel_id) == str(dto.channel_id)), None)

            if not source_cfg:
                logger.warning(f"Unknown channel {dto.channel_id}")
                return SignalProcessingResultDTO(success=False, message_id=dto.message_id, reason="Unknown channel")

            # Check for duplicate position on the same exchange (in local database)
            existing_positions = await self._state_repository.get_open_positions_by_symbol_and_exchange(symbol=sig.symbol, exchange=source_cfg.exchange)

            if existing_positions:
                # Check if this is an edited message (same message_id as existing position)
                for existing_pos in existing_positions:
                    if existing_pos.message_id == dto.message_id:
                        # This is an edited message, treat as signal update
                        logger.info(f"Detected edited message for {sig.symbol} (message_id: {dto.message_id}), processing as update")
                        return await self._handle_signal_update_use_case.execute(sig, dto)

                # Position found in DB - check if it's actually open on exchange
                existing_pos = existing_positions[0]
                exchange = self._exchange_registry.get_exchange(source_cfg.exchange)

                try:
                    position_on_exchange = await exchange.get_position(sig.symbol)

                    # Check if position is actually open on exchange
                    if exchange.is_position_open(position_on_exchange, existing_pos.side):
                        # Position is OPEN on exchange - block duplicate, DO NOT modify DB
                        warning_msg = (
                            f"⚠️ Position for {sig.symbol} is already open on {source_cfg.exchange}\nEntry: {existing_pos.entry_price}\nQty: {existing_pos.qty}\nNew signal ignored."
                        )
                        logger.warning(f"Duplicate position detected: {sig.symbol} on {source_cfg.exchange}")
                        await self._notification_gateway.send_message(warning_msg)

                        return SignalProcessingResultDTO(success=False, message_id=dto.message_id, reason=f"Duplicate position: {sig.symbol} already open on {source_cfg.exchange}")
                    else:
                        # Position is CLOSED on exchange but exists in DB - allow new position, DO NOT modify DB
                        logger.info(
                            f"📊 Position {sig.symbol} found in DB (status: {existing_pos.status}, ID: {existing_pos.id}) "
                            f"but NOT open on exchange. Allowing new position to be opened."
                        )
                        # Continue to open new position (don't return here, don't modify DB)

                except Exception as e:
                    logger.error(f"Failed to check position on exchange for {sig.symbol}: {e}. Blocking signal for safety.")
                    # If check fails, block signal (safe default)
                    return SignalProcessingResultDTO(success=False, message_id=dto.message_id, reason=f"Failed to verify position status on exchange: {sig.symbol}")

            # Check for position on exchange (not just in database)
            # This catches manually opened positions or database sync issues
            exchange = self._exchange_registry.get_exchange(source_cfg.exchange)

            try:
                position_on_exchange = await exchange.get_position(sig.symbol)

                if exchange.is_position_open(position_on_exchange, sig.side):
                    # Position exists on exchange but not in DB
                    warning_msg = (
                        f"⚠️ Position for {sig.symbol} {sig.side.value} already exists on {source_cfg.exchange} "
                        f"but not found in local database.\n"
                        f"This may indicate:\n"
                        f"• Manual position opened via exchange UI\n"
                        f"• Database synchronization issue\n"
                        f"New signal ignored."
                    )
                    logger.warning(f"Position exists on exchange but not in DB: {sig.symbol} {sig.side.value}")
                    await self._notification_gateway.send_message(warning_msg)

                    return SignalProcessingResultDTO(success=False, message_id=dto.message_id, reason=f"Position already exists on exchange: {sig.symbol}")

                # Check for opposite side position (hedging check)
                opposite_side = TradeSide.SHORT if sig.side == TradeSide.LONG else TradeSide.LONG
                if exchange.is_position_open(position_on_exchange, opposite_side):
                    # Opposite position exists - sync DB and allow new position
                    logger.warning(f"Opposite position ({opposite_side.value}) exists for {sig.symbol} on {source_cfg.exchange}. Checking if it's tracked in database...")

                    # Check if opposite position is in DB
                    opposite_positions = await self._state_repository.get_open_positions_by_symbol_and_exchange(symbol=sig.symbol, exchange=source_cfg.exchange)

                    # Sync any opposite positions in DB
                    for opp_pos in opposite_positions:
                        if opp_pos.side == opposite_side:
                            logger.warning(f"Opposite position {sig.symbol} {opposite_side.value} found in DB but closed on exchange. Synchronizing database...")
                            opp_pos.status = PositionStatus.CLOSED
                            await self._state_repository.save_position(opp_pos)
                            logger.info(f"Database synchronized: Opposite position {sig.symbol} {opposite_side.value} marked as CLOSED.")

                    # Allow opening new position in opposite direction
                    logger.info(f"Proceeding to open {sig.side.value} position for {sig.symbol}")
                    # Continue to open new position (don't return here)

            except Exception as e:
                logger.warning(f"Failed to check position on exchange for {sig.symbol}: {e}. Proceeding with caution.")
                # Continue anyway - will be caught by opening.py final check

            # Check for pending entry orders
            try:
                open_orders = await exchange.list_open_orders(sig.symbol)
                entry_orders = [
                    order
                    for order in open_orders
                    if not order.get("reduceOnly", False)  # Not a closing order
                ]

                if entry_orders:
                    warning_msg = (
                        f"⚠️ Pending entry order(s) found for {sig.symbol} on {source_cfg.exchange}\nCount: {len(entry_orders)}\nNew signal ignored to avoid duplicate entries."
                    )
                    logger.warning(f"Pending entry orders found for {sig.symbol}: {len(entry_orders)}")
                    await self._notification_gateway.send_message(warning_msg)

                    return SignalProcessingResultDTO(success=False, message_id=dto.message_id, reason=f"Pending entry orders exist: {sig.symbol}")
            except Exception as e:
                logger.warning(f"Failed to check open orders for {sig.symbol}: {e}. Proceeding with caution.")
                # Continue anyway - will be caught by opening.py final check

            logger.info(f"Opening position: {sig.symbol} {sig.side} [Leverage: {sig.leverage}] [Entry price: {sig.entry_price}]")

            # Convert tp_distribution or tp_distributions to the new format
            tp_distributions_dict: dict[int, list[dict[str, Any]]] = {}

            # Check if new format exists
            if source_cfg.tp_distributions:
                tp_distributions_dict = {k: [tp.model_dump() for tp in v] for k, v in source_cfg.tp_distributions.items()}
            # Fallback to old format for backward compatibility
            # elif source_cfg.tp_distribution:
            #     # Convert old format to new format: use length as key
            #     num_tps = len(source_cfg.tp_distribution)
            #     tp_distributions_dict = {num_tps: [tp.model_dump() for tp in source_cfg.tp_distribution]}

            settings = TradeSettingsDTO(
                exchange=source_cfg.exchange,
                fixed_leverage=source_cfg.fixed_leverage,
                position_size_pct=source_cfg.position_size_pct,
                default_sl_percent=source_cfg.default_sl_percent,
                tp_distribution=tp_distributions_dict,
            )
            res = await self._open_position_use_case.execute(sig, settings)
            if not res.success:
                logger.error(f"❌ Error opening trade: {res.reason}")
            else:
                # Extract and Save Position State
                entry_order_id = str(res.order.get("orderId", "")) if res.order else ""
                sl_tp_res = res.sl_tp_res or {}
                sl_order = sl_tp_res.get("stop_loss")
                # Binance Futures returns algoId for conditional orders (SL/TP)
                sl_order_id = str(sl_order.get("algoId") or sl_order.get("orderId") or "") if sl_order else None

                tp_order_ids = {}
                for i, tp_order in enumerate(sl_tp_res.get("take_profits", [])):
                    # Binance Futures returns algoId for conditional orders
                    order_id = tp_order.get("algoId") or tp_order.get("orderId")
                    if order_id and i < len(sig.take_profits):
                        tp_price = float(sig.take_profits[i])
                        tp_order_ids[str(order_id)] = tp_price
                # Determine if position needs to wait for signal updates
                # If signal has no SL/TP, mark position as waiting for updates
                needs_signal_stop_update = sig.stop_loss is None and res.final_sl is None
                needs_signal_tp_update = not sig.take_profits

                position_status = PositionStatus.WAITING_UPDATE if (needs_signal_stop_update or needs_signal_tp_update) else PositionStatus.OPEN

                position = ActivePositionEntity(
                    symbol=sig.symbol,
                    source_id=dto.source_id,
                    message_id=dto.message_id,
                    exchange=source_cfg.exchange,
                    side=sig.side,
                    qty=res.qty,
                    entry_price=res.entry_price,
                    stop_loss=res.final_sl,
                    is_default_sl=res.is_default_sl,
                    take_profits=sig.take_profits,
                    order_id=entry_order_id,
                    sl_order_id=sl_order_id,
                    tp_order_ids=tp_order_ids,
                    # Initialize tracking fields for breakeven calculation
                    remaining_qty=res.qty,  # Initially equals full quantity
                    closed_qty=0.0,
                    realized_pnl_usdt=0.0,
                    # Signal update tracking fields
                    status=position_status,
                    message_hash=sig.message_hash,
                    needs_signal_stop_update=needs_signal_stop_update,
                    needs_signal_tp_update=needs_signal_tp_update,
                    temporary_stop=res.final_sl if needs_signal_stop_update else None,
                )

                # Save it
                await self._state_repository.save_position(position)

                if position_status == PositionStatus.WAITING_UPDATE:
                    logger.info(f"✅ Position {sig.symbol} saved with status WAITING_UPDATE (needs_stop={needs_signal_stop_update}, needs_tp={needs_signal_tp_update})")
                else:
                    logger.info(f"✅ Position {sig.symbol} saved to SQLite DB for tracking.")
        else:
            logger.info(f"INFO This is an update or not a primary signal (type: {sig.signal_type}). Symbol: {sig.symbol}")

        return SignalProcessingResultDTO(success=True, message_id=dto.message_id, symbol=sig.symbol)
