import logging
from typing import final

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
from discord_trade_bot.core.application.trading.dto import TradeSettingsDTO
from discord_trade_bot.core.application.trading.interfaces import (
    ExchangeGatewayProtocol,
)
from discord_trade_bot.core.application.trading.use_cases import OpenPositionUseCase
from discord_trade_bot.core.domain.entities.position import ActivePositionEntity
from discord_trade_bot.core.domain.services.parser import SignalParserService
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
        exchange_gateway: ExchangeGatewayProtocol,
        notification_gateway: NotificationGatewayProtocol,
        state_repository: StateRepositoryProtocol,
        open_position_use_case: OpenPositionUseCase,
        config: AppConfig,
    ):
        self._exchange_gateway = exchange_gateway
        self._notification_gateway = notification_gateway
        self._state_repository = state_repository
        self._open_position_use_case = open_position_use_case
        self._config = config
        self._parser = SignalParserService()

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
        # Decision logic: is it a primary signal?
        if sig.signal_type == "primary_signal":
            # Get source config
            watch_sources = self._config.yaml.discord.watch_sources
            source_cfg = next((s for s in watch_sources if str(s.channel_id) == str(dto.channel_id)), None)

            if not source_cfg:
                logger.warning(f"Unknown channel {dto.channel_id}")
                return SignalProcessingResultDTO(success=False, message_id=dto.message_id, reason="Unknown channel")

            # Check for duplicate position on the same exchange
            existing_positions = await self._state_repository.get_open_positions_by_symbol_and_exchange(symbol=sig.symbol, exchange=source_cfg.exchange)

            if existing_positions:
                # Position already open, ignore new signal
                existing_pos = existing_positions[0]
                warning_msg = (
                    f"⚠️ Position for {sig.symbol} is already open on {source_cfg.exchange}\nEntry: {existing_pos.entry_price}\nQty: {existing_pos.qty}\nNew signal ignored."
                )
                logger.warning(f"Duplicate position detected: {sig.symbol} on {source_cfg.exchange}")
                await self._notification_gateway.send_message(warning_msg)

                return SignalProcessingResultDTO(success=False, message_id=dto.message_id, reason=f"Duplicate position: {sig.symbol} already open on {source_cfg.exchange}")

            logger.info(f"Opening position: {sig.symbol} {sig.side} [Leverage: {sig.leverage}] [Entry price: {sig.entry_price}]")
            settings = TradeSettingsDTO(
                exchange=source_cfg.exchange,
                fixed_leverage=source_cfg.fixed_leverage,
                free_balance_pct=source_cfg.free_balance_pct,
                default_sl_percent=source_cfg.default_sl_percent,
                tp_distribution=[tp.model_dump() for tp in source_cfg.tp_distribution],
            )
            res = await self._open_position_use_case.execute(sig, settings)
            if not res.success:
                logger.error(f"❌ Error opening trade: {res.reason}")
            else:
                # Extract and Save Position State
                entry_order_id = str(res.order.get("orderId", "")) if res.order else ""
                sl_tp_res = res.sl_tp_res or {}
                sl_order = sl_tp_res.get("stop_loss")
                sl_order_id = str(sl_order.get("orderId", "")) if sl_order else None

                tp_order_ids = {}
                for i, tp_order in enumerate(sl_tp_res.get("take_profits", [])):
                    if "orderId" in tp_order and i < len(sig.take_profits):
                        tp_price = float(sig.take_profits[i])
                        tp_order_ids[str(tp_order["orderId"])] = tp_price

                position = ActivePositionEntity(
                    symbol=sig.symbol,
                    source_id=dto.channel_id,
                    message_id=dto.message_id,
                    exchange=source_cfg.exchange,
                    side=sig.side,
                    qty=res.qty,
                    entry_price=res.entry_price,
                    stop_loss=res.final_sl,
                    take_profits=sig.take_profits,
                    order_id=entry_order_id,
                    sl_order_id=sl_order_id,
                    tp_order_ids=tp_order_ids,
                )

                # Save it
                await self._state_repository.save_position(position)
                logger.info(f"✅ Position {sig.symbol} saved to SQLite DB for tracking.")
        else:
            logger.info(f"INFO This is an update or not a primary signal (type: {sig.signal_type}). Symbol: {sig.symbol}")

        return SignalProcessingResultDTO(success=True, message_id=dto.message_id, symbol=sig.symbol)
