"""Tests for core.application.signal.use_cases.processing module."""

from unittest.mock import AsyncMock, Mock

import pytest

from discord_trade_bot.core.application.signal.dto import (
    ProcessSignalDTO,
    SignalProcessingResultDTO,
)
from discord_trade_bot.core.application.signal.use_cases.processing import (
    ProcessSignalUseCase,
)
from discord_trade_bot.core.application.trading.dto import TradeSettingsDTO
from discord_trade_bot.core.domain.entities.position import ActivePositionEntity
from discord_trade_bot.core.domain.value_objects.trading import TradeSide
from discord_trade_bot.main.config.yaml.discord import (
    Source,
    DiscordYamlConfig,
    TpDistribution,
)


@pytest.fixture
def mock_config():
    """Create a mock AppConfig."""
    config = Mock()
    config.yaml = Mock()
    config.yaml.discord = DiscordYamlConfig(
        watch_sources=[
            Source(
                source_id="test_source",
                channel_id=123,
                exchange="binance",
                fixed_leverage=20,
                free_balance_pct=10.0,
                position_size_pct=5.0,
                default_sl_percent=4.0,
                tp_distributions={
                    3: [
                        TpDistribution(label="TP1", close_pct=33.33),
                        TpDistribution(label="TP2", close_pct=33.33),
                        TpDistribution(label="TP3", close_pct=33.34),
                    ]
                },
            )
        ]
    )
    return config


@pytest.fixture
def mock_open_position_use_case():
    """Create a mock OpenPositionUseCase."""
    use_case = AsyncMock()
    use_case.execute = AsyncMock(
        return_value=Mock(
            success=True,
            qty=0.1,
            entry_price=50000.0,
            final_sl=48000.0,
            order={"orderId": "entry_123"},
            sl_tp_res={
                "stop_loss": {"orderId": "sl_123"},
                "take_profits": [
                    {"orderId": "tp_1"},
                    {"orderId": "tp_2"},
                    {"orderId": "tp_3"},
                ],
            },
        )
    )
    return use_case


@pytest.fixture
def process_signal_use_case(
    mock_exchange_registry,
    mock_notification_gateway,
    mock_repository,
    mock_open_position_use_case,
    mock_config,
):
    """Create ProcessSignalUseCase instance with mocked dependencies."""
    return ProcessSignalUseCase(
        exchange_registry=mock_exchange_registry,
        notification_gateway=mock_notification_gateway,
        state_repository=mock_repository,
        open_position_use_case=mock_open_position_use_case,
        config=mock_config,
    )


class TestProcessSignalUseCase:
    """Test ProcessSignalUseCase."""

    @pytest.mark.asyncio
    async def test_process_valid_signal_success(
        self,
        process_signal_use_case,
        mock_repository,
        mock_open_position_use_case,
    ):
        """Test processing a valid signal successfully opens a position."""
        dto = ProcessSignalDTO(
            source_id="test_source_1",
            channel_id="123",  # Match the channel_id in mock_config
            message_id="msg_456",
            text="""
            BTCUSDT LONG
            Entry: 50000
            Stop Loss: 48000
            TP1: 51000
            TP2: 52000
            TP3: 53000
            Leverage: 20x
            """,
        )

        # No existing positions
        mock_repository.get_open_positions_by_symbol_and_exchange.return_value = []

        result = await process_signal_use_case.execute(dto)

        assert result.success is True
        assert result.message_id == "msg_456"
        assert result.symbol == "BTCUSDT"

        # Verify position was saved
        mock_repository.save_position.assert_called_once()
        saved_position = mock_repository.save_position.call_args[0][0]
        assert isinstance(saved_position, ActivePositionEntity)
        assert saved_position.symbol == "BTCUSDT"
        assert saved_position.side == TradeSide.LONG
        assert saved_position.exchange == "binance"

    @pytest.mark.asyncio
    async def test_process_invalid_signal(self, process_signal_use_case):
        """Test processing an invalid signal returns failure."""
        dto = ProcessSignalDTO(
            source_id="test_source_1",
            channel_id="123",
            message_id="msg_456",
            text="Just a random message without trading info",
        )

        result = await process_signal_use_case.execute(dto)

        assert result.success is False
        assert result.message_id == "msg_456"
        assert result.reason == "Invalid signal"

    @pytest.mark.asyncio
    async def test_process_signal_without_symbol(self, process_signal_use_case):
        """Test processing a signal without symbol returns failure."""
        dto = ProcessSignalDTO(
            source_id="test_source_1",
            channel_id="123",
            message_id="msg_456",
            text="LONG Entry: 50000",
        )

        result = await process_signal_use_case.execute(dto)

        assert result.success is False
        assert result.reason == "Invalid signal"

    @pytest.mark.asyncio
    async def test_process_signal_without_side(self, process_signal_use_case):
        """Test processing a signal without side returns failure."""
        dto = ProcessSignalDTO(
            source_id="test_source_1",
            channel_id="123",
            message_id="msg_456",
            text="BTCUSDT Entry: 50000",
        )

        result = await process_signal_use_case.execute(dto)

        assert result.success is False
        assert result.reason == "Invalid signal"

    @pytest.mark.asyncio
    async def test_duplicate_position_detection(
        self,
        process_signal_use_case,
        mock_repository,
        mock_notification_gateway,
        sample_position,
    ):
        """Test that duplicate positions are detected and prevented."""
        dto = ProcessSignalDTO(
            source_id="test_source_1",
            channel_id="123",
            message_id="msg_456",
            text="""
            BTCUSDT LONG
            Entry: 50000
            Stop Loss: 48000
            TP1: 51000
            """,
        )

        # Return existing position
        mock_repository.get_open_positions_by_symbol_and_exchange.return_value = [sample_position]

        result = await process_signal_use_case.execute(dto)

        assert result.success is False
        assert "Duplicate position" in result.reason
        assert "BTCUSDT" in result.reason

        # Verify warning notification was sent
        mock_notification_gateway.send_message.assert_called_once()
        warning_msg = mock_notification_gateway.send_message.call_args[0][0]
        assert "already open" in warning_msg

    @pytest.mark.asyncio
    async def test_unknown_channel(self, process_signal_use_case):
        """Test processing signal from unknown channel returns failure."""
        dto = ProcessSignalDTO(
            source_id="test_source_1",
            channel_id="unknown_channel_999",
            message_id="msg_456",
            text="""
            BTCUSDT LONG
            Entry: 50000
            """,
        )

        result = await process_signal_use_case.execute(dto)

        assert result.success is False
        assert result.reason == "Unknown channel"

    @pytest.mark.asyncio
    async def test_open_position_failure(
        self,
        process_signal_use_case,
        mock_repository,
        mock_open_position_use_case,
    ):
        """Test handling of position opening failure."""
        dto = ProcessSignalDTO(
            source_id="test_source_1",
            channel_id="123",
            message_id="msg_456",
            text="""
            BTCUSDT LONG
            Entry: 50000
            Stop Loss: 48000
            TP1: 51000
            """,
        )

        # No existing positions
        mock_repository.get_open_positions_by_symbol_and_exchange.return_value = []

        # Mock position opening failure
        mock_open_position_use_case.execute.return_value = Mock(
            success=False,
            reason="Insufficient balance",
        )

        result = await process_signal_use_case.execute(dto)

        # Signal processing succeeds but position opening fails
        assert result.success is True  # Signal was valid

        # Position should not be saved
        mock_repository.save_position.assert_not_called()

    @pytest.mark.asyncio
    async def test_short_signal_processing(
        self,
        process_signal_use_case,
        mock_repository,
        mock_open_position_use_case,
    ):
        """Test processing a SHORT signal."""
        dto = ProcessSignalDTO(
            source_id="test_source_1",
            channel_id="123",
            message_id="msg_789",
            text="""
            ETHUSDT SHORT
            Entry: 3000
            Stop Loss: 3100
            TP1: 2950
            TP2: 2900
            """,
        )

        mock_repository.get_open_positions_by_symbol_and_exchange.return_value = []

        result = await process_signal_use_case.execute(dto)

        assert result.success is True
        assert result.symbol == "ETHUSDT"

        # Verify position was saved with SHORT side
        mock_repository.save_position.assert_called_once()
        saved_position = mock_repository.save_position.call_args[0][0]
        assert saved_position.side == TradeSide.SHORT

    @pytest.mark.asyncio
    async def test_signal_update_not_processed(
        self,
        process_signal_use_case,
        mock_repository,
    ):
        """Test that signal updates are not processed as new positions."""
        dto = ProcessSignalDTO(
            source_id="test_source_1",
            channel_id="123",
            message_id="msg_456",
            text="""
            BTCUSDT
            TP1 HIT ✅
            """,
        )

        result = await process_signal_use_case.execute(dto)

        # Signal update is not a valid signal (no side), so it returns failure
        assert result.success is False
        assert result.reason == "Invalid signal"
        mock_repository.save_position.assert_not_called()

    @pytest.mark.asyncio
    async def test_position_state_saved_correctly(
        self,
        process_signal_use_case,
        mock_repository,
    ):
        """Test that position state is saved with correct data."""
        dto = ProcessSignalDTO(
            source_id="test_source_1",
            channel_id="123",
            message_id="msg_456",
            text="""
            BTCUSDT LONG
            Entry: 50000
            Stop Loss: 48000
            TP1: 51000
            TP2: 52000
            TP3: 53000
            """,
        )

        mock_repository.get_open_positions_by_symbol_and_exchange.return_value = []

        await process_signal_use_case.execute(dto)

        # Verify saved position has all required fields
        mock_repository.save_position.assert_called_once()
        saved_position = mock_repository.save_position.call_args[0][0]

        assert saved_position.symbol == "BTCUSDT"
        assert saved_position.source_id == "test_source_1"
        assert saved_position.message_id == "msg_456"
        assert saved_position.exchange == "binance"
        assert saved_position.side == TradeSide.LONG
        assert saved_position.qty == 0.1
        assert saved_position.entry_price == 50000.0
        assert saved_position.stop_loss == 48000.0
        assert saved_position.take_profits == [51000.0, 52000.0, 53000.0]
        assert saved_position.order_id == "entry_123"
        assert saved_position.sl_order_id == "sl_123"
        assert len(saved_position.tp_order_ids) == 3

    @pytest.mark.asyncio
    async def test_trade_settings_passed_correctly(
        self,
        process_signal_use_case,
        mock_repository,
        mock_open_position_use_case,
    ):
        """Test that trade settings are passed correctly to OpenPositionUseCase."""
        dto = ProcessSignalDTO(
            source_id="test_source_1",
            channel_id="123",
            message_id="msg_456",
            text="""
            BTCUSDT LONG
            Entry: 50000
            Stop Loss: 48000
            TP1: 51000
            """,
        )

        mock_repository.get_open_positions_by_symbol_and_exchange.return_value = []

        await process_signal_use_case.execute(dto)

        # Verify OpenPositionUseCase was called with correct settings
        mock_open_position_use_case.execute.assert_called_once()
        call_args = mock_open_position_use_case.execute.call_args
        settings = call_args[0][1]

        assert isinstance(settings, TradeSettingsDTO)
        assert settings.exchange == "binance"
        assert settings.fixed_leverage == 20
        assert settings.free_balance_pct == 10.0
        assert settings.default_sl_percent == 4.0
        # tp_distribution is now a dict[int, list[dict]]
        assert isinstance(settings.tp_distribution, dict)
        assert 3 in settings.tp_distribution
        assert len(settings.tp_distribution[3]) == 3
