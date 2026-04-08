import asyncio
import logging
import uuid
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
from discord_trade_bot.main.config.yaml.discord import ExchangeSettings, Source

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

    async def _check_duplicate_for_exchange(
        self,
        sig,
        exchange_name: str,
        existing_positions: list[Any],
    ) -> tuple[bool, str | None]:
        """
        Check if position already exists for given exchange.

        Returns:
            (should_skip, reason) - True if should skip opening, with optional reason
        """
        if not existing_positions:
            return False, None

        existing_pos = existing_positions[0]
        exchange = self._exchange_registry.get_exchange(exchange_name)

        try:
            position_on_exchange = await exchange.get_position(sig.symbol)

            if exchange.is_position_open(position_on_exchange, existing_pos.side):
                # Position is OPEN on exchange - skip
                warning_msg = f"⚠️ Position for {sig.symbol} is already open on {exchange_name}\nEntry: {existing_pos.entry_price}\nQty: {existing_pos.qty}\nSkipping this exchange."
                logger.warning(f"Duplicate position detected: {sig.symbol} on {exchange_name}")
                await self._notification_gateway.send_message(warning_msg)
                return True, f"Duplicate position on {exchange_name}"
            else:
                # Position is CLOSED on exchange but exists in DB - allow
                logger.info(f"📊 Position {sig.symbol} found in DB for {exchange_name} but NOT open on exchange. Allowing new position.")
                return False, None

        except Exception as e:
            logger.error(f"Failed to check position on {exchange_name} for {sig.symbol}: {e}")
            return True, f"Failed to verify position on {exchange_name}"

    async def _open_position_on_exchange(
        self,
        sig,
        dto: ProcessSignalDTO,
        source_cfg: Source,
        exchange_cfg: ExchangeSettings,
    ) -> dict[str, Any]:
        """
        Open position on a single exchange.

        Returns dict with:
            - success: bool
            - exchange: str
            - reason: str | None
            - position_data: dict | None (if successful)
        """
        exchange_name = exchange_cfg.name

        try:
            # Check for duplicate in DB
            existing_positions = await self._state_repository.get_open_positions_by_symbol_and_exchange(symbol=sig.symbol, exchange=exchange_name)

            # Check if duplicate exists
            should_skip, reason = await self._check_duplicate_for_exchange(sig, exchange_name, existing_positions)
            if should_skip:
                return {"success": False, "exchange": exchange_name, "reason": reason}

            # Check for position on exchange (not in DB)
            exchange = self._exchange_registry.get_exchange(exchange_name)
            position_on_exchange = await exchange.get_position(sig.symbol)

            if exchange.is_position_open(position_on_exchange, sig.side):
                warning_msg = f"⚠️ Position for {sig.symbol} {sig.side.value} already exists on {exchange_name} but not in database. Skipping this exchange."
                logger.warning(f"Position exists on {exchange_name} but not in DB: {sig.symbol}")
                await self._notification_gateway.send_message(warning_msg)
                return {"success": False, "exchange": exchange_name, "reason": "Position exists on exchange"}

            # Check for opposite side position
            opposite_side = TradeSide.SHORT if sig.side == TradeSide.LONG else TradeSide.LONG
            if exchange.is_position_open(position_on_exchange, opposite_side):
                logger.warning(f"Opposite position exists for {sig.symbol} on {exchange_name}")
                # Check if tracked in DB
                opposite_positions = await self._state_repository.get_open_positions_by_symbol_and_exchange(symbol=sig.symbol, exchange=exchange_name)
                # Continue anyway (allow hedging or let opening.py handle it)

            # Check for pending entry orders
            try:
                open_orders = await exchange.list_open_orders(sig.symbol)
                entry_orders = [order for order in open_orders if not order.get("reduceOnly", False)]

                if entry_orders:
                    warning_msg = f"⚠️ Pending entry order(s) found for {sig.symbol} on {exchange_name}\nCount: {len(entry_orders)}\nSkipping this exchange."
                    logger.warning(f"Pending entry orders for {sig.symbol} on {exchange_name}: {len(entry_orders)}")
                    await self._notification_gateway.send_message(warning_msg)
                    return {"success": False, "exchange": exchange_name, "reason": "Pending entry orders exist"}
            except Exception as e:
                logger.warning(f"Failed to check open orders for {sig.symbol} on {exchange_name}: {e}")

            # Open position
            logger.info(f"Opening position on {exchange_name}: {sig.symbol} {sig.side} [Leverage: {sig.leverage}]")

            tp_distributions_dict: dict[int, list[dict[str, Any]]] = {}
            if source_cfg.tp_distributions:
                tp_distributions_dict = {k: [tp.model_dump() for tp in v] for k, v in source_cfg.tp_distributions.items()}

            settings = TradeSettingsDTO(
                exchange=exchange_name,
                fixed_leverage=source_cfg.fixed_leverage,
                position_size_pct=exchange_cfg.position_size_pct,
                default_sl_percent=source_cfg.default_sl_percent,
                tp_distribution=tp_distributions_dict,
            )

            res = await self._open_position_use_case.execute(sig, settings)

            if not res.success:
                logger.error(f"❌ Error opening trade on {exchange_name}: {res.reason}")
                return {"success": False, "exchange": exchange_name, "reason": res.reason}

            # Extract position data
            entry_order_id = str(res.order.get("orderId", "")) if res.order else ""
            sl_tp_res = res.sl_tp_res or {}
            sl_order = sl_tp_res.get("stop_loss")
            sl_order_id = str(sl_order.get("algoId") or sl_order.get("orderId") or "") if sl_order else None

            tp_order_ids = {}
            for i, tp_order in enumerate(sl_tp_res.get("take_profits", [])):
                order_id = tp_order.get("algoId") or tp_order.get("orderId")
                if order_id and i < len(sig.take_profits):
                    tp_price = float(sig.take_profits[i])
                    tp_order_ids[str(order_id)] = tp_price

            # Determine if position needs to wait for signal updates
            needs_signal_stop_update = sig.stop_loss is None
            needs_signal_tp_update = not sig.take_profits

            position_status = PositionStatus.WAITING_UPDATE if (needs_signal_stop_update or needs_signal_tp_update) else PositionStatus.OPEN

            # Save position state
            position = ActivePositionEntity(
                symbol=sig.symbol,
                source_id=dto.source_id,
                message_id=dto.message_id,
                exchange=exchange_name,
                side=sig.side,
                qty=res.qty,
                entry_price=res.entry_price,
                stop_loss=res.final_sl,
                is_default_sl=res.is_default_sl,
                take_profits=sig.take_profits,
                order_id=entry_order_id,
                sl_order_id=sl_order_id,
                tp_order_ids=tp_order_ids,
                remaining_qty=res.qty,
                closed_qty=0.0,
                realized_pnl_usdt=0.0,
                status=position_status,
                message_hash=sig.message_hash,
                needs_signal_stop_update=needs_signal_stop_update,
                needs_signal_tp_update=needs_signal_tp_update,
                temporary_stop=res.final_sl if needs_signal_stop_update else None,
            )

            await self._state_repository.save_position(position)

            logger.info(f"✅ Position opened on {exchange_name}: {sig.symbol} {sig.side}")

            return {
                "success": True,
                "exchange": exchange_name,
                "position_data": position,
                "pending": res.pending,
            }

        except Exception as e:
            logger.error(f"❌ Unexpected error opening position on {exchange_name}: {e}", exc_info=True)
            return {"success": False, "exchange": exchange_name, "reason": str(e)}

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

            # Check for duplicate positions across all configured exchanges
            existing_positions_by_exchange: dict[str, list[Any]] = {}
            for exchange_cfg in source_cfg.exchanges:
                positions = await self._state_repository.get_open_positions_by_symbol_and_exchange(symbol=sig.symbol, exchange=exchange_cfg.name)
                if positions:
                    existing_positions_by_exchange[exchange_cfg.name] = positions

            # Check if this is an edited message across any exchange
            for exchange_name, positions in existing_positions_by_exchange.items():
                for existing_pos in positions:
                    if existing_pos.message_id == dto.message_id:
                        logger.info(f"Detected edited message for {sig.symbol} on {exchange_name} (message_id: {dto.message_id})")
                        return await self._handle_signal_update_use_case.execute(sig, dto)

            # Open positions on all exchanges in parallel
            logger.info(f"Opening position: {sig.symbol} {sig.side} [Leverage: {sig.leverage}] [Entry: {sig.entry_price}]")
            logger.info(f"Will attempt to open on {len(source_cfg.exchanges)} exchange(s): {[ex.name for ex in source_cfg.exchanges]}")

            tasks = [self._open_position_on_exchange(sig, dto, source_cfg, exchange_cfg) for exchange_cfg in source_cfg.exchanges]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process results
            successful_exchanges = []
            failed_exchanges = []

            for i, result in enumerate(results):
                exchange_name = source_cfg.exchanges[i].name

                if isinstance(result, Exception):
                    logger.error(f"❌ Exception opening position on {exchange_name}: {result}")
                    failed_exchanges.append({"exchange": exchange_name, "reason": str(result)})
                elif isinstance(result, dict) and result.get("success"):
                    successful_exchanges.append(result)
                    logger.info(f"✅ Successfully opened position on {exchange_name}")
                elif isinstance(result, dict):
                    failed_exchanges.append(result)
                    logger.warning(f"⚠️ Failed to open position on {exchange_name}: {result.get('reason')}")

            # Send summary notification
            if successful_exchanges:
                summary_msg = f"✅ Position opened for {sig.symbol} {sig.side.value}\n"
                summary_msg += f"Successful: {len(successful_exchanges)}/{len(source_cfg.exchanges)} exchanges\n"
                summary_msg += f"Exchanges: {', '.join([r['exchange'] for r in successful_exchanges])}"

                if failed_exchanges:
                    summary_msg += f"\n\n⚠️ Failed on: {', '.join([r['exchange'] for r in failed_exchanges])}"

                await self._notification_gateway.send_message(summary_msg)

                return SignalProcessingResultDTO(success=True, message_id=dto.message_id, reason=f"Opened on {len(successful_exchanges)} exchange(s)")
            else:
                error_msg = f"❌ Failed to open position for {sig.symbol} on all exchanges\n"
                error_msg += "\n".join([f"• {r['exchange']}: {r.get('reason', 'Unknown')}" for r in failed_exchanges])

                await self._notification_gateway.send_message(error_msg)

                return SignalProcessingResultDTO(success=False, message_id=dto.message_id, reason="Failed on all exchanges")
        else:
            logger.info(f"INFO This is an update or not a primary signal (type: {sig.signal_type}). Symbol: {sig.symbol}")

        return SignalProcessingResultDTO(success=True, message_id=dto.message_id, symbol=sig.symbol)
