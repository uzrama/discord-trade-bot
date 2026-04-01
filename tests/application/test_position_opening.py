"""Tests for core.application.trading.use_cases.opening module."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from discord_trade_bot.core.application.trading.dto import (
    OpenPositionResultDTO,
    TradeSettingsDTO,
)
from discord_trade_bot.core.application.trading.use_cases.opening import (
    OpenPositionUseCase,
)
from discord_trade_bot.core.domain.entities.signal import ParsedSignalEntity
from discord_trade_bot.core.domain.value_objects.trading import EntryMode, TradeSide


@pytest.fixture
def mock_exchange_registry():
    """Create a mock exchange registry."""
    registry = Mock()
    exchange = AsyncMock()
    exchange.name = "binance"
    exchange.set_leverage = AsyncMock(return_value={"leverage": 20})
    exchange.get_last_price = AsyncMock(return_value=50000.0)
    exchange.get_balance = AsyncMock(return_value=1000.0)
    exchange.get_symbol_info = AsyncMock(
        return_value={
            "qty_precision": 3,
            "price_precision": 2,
            "min_qty": 0.001,
        }
    )
    exchange.place_market_order = AsyncMock(return_value={"orderId": "entry_123", "status": "FILLED"})
    exchange.get_position = AsyncMock(return_value={"positionAmt": "0", "entryPrice": "0"})  # No position initially
    exchange.wait_for_position_ready = AsyncMock(return_value=True)
    exchange.is_position_open = Mock(return_value=False)  # No position initially
    exchange.place_sl_tp_orders = AsyncMock(
        return_value={
            "stop_loss": {"orderId": "sl_123"},
            "take_profits": [
                {"orderId": "tp_1"},
                {"orderId": "tp_2"},
                {"orderId": "tp_3"},
            ],
        }
    )
    registry.get_exchange = Mock(return_value=exchange)
    return registry


@pytest.fixture
def open_position_use_case(mock_exchange_registry, mock_notification_gateway):
    """Create OpenPositionUseCase instance with mocked dependencies."""
    mock_state_repository = Mock()
    return OpenPositionUseCase(
        exchange_registry=mock_exchange_registry,
        notification_gateway=mock_notification_gateway,
        state_repository=mock_state_repository,
    )


@pytest.fixture
def trade_settings():
    """Create sample trade settings."""
    return TradeSettingsDTO(
        exchange="binance",
        fixed_leverage=20,
        free_balance_pct=10.0,
        position_size_pct=5.0,
        default_sl_percent=4.0,
        tp_distribution=[
            {"label": "TP1", "close_pct": 33.33},
            {"label": "TP2", "close_pct": 33.33},
            {"label": "TP3", "close_pct": 33.34},
        ],
    )


@pytest.fixture
def long_signal():
    """Create a LONG signal."""
    return ParsedSignalEntity(
        source_id="channel_123",
        message_id="msg_456",
        message_hash="hash_123",
        message_text="BTCUSDT LONG",
        symbol="BTCUSDT",
        side=TradeSide.LONG,
        entry_price=50000.0,
        entry_mode=EntryMode.EXACT_PRICE,
        stop_loss=48000.0,
        take_profits=[51000.0, 52000.0, 53000.0],
        leverage=20,
        is_signal=True,
    )


@pytest.fixture
def short_signal():
    """Create a SHORT signal."""
    return ParsedSignalEntity(
        source_id="channel_123",
        message_id="msg_789",
        message_hash="hash_789",
        message_text="ETHUSDT SHORT",
        symbol="ETHUSDT",
        side=TradeSide.SHORT,
        entry_price=3000.0,
        entry_mode=EntryMode.EXACT_PRICE,
        stop_loss=3100.0,
        take_profits=[2950.0, 2900.0, 2850.0],
        leverage=10,
        is_signal=True,
    )


class TestOpenPositionUseCase:
    """Test OpenPositionUseCase."""

    @pytest.mark.asyncio
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_open_long_position_success(
        self,
        mock_sleep,
        open_position_use_case,
        long_signal,
        trade_settings,
        mock_notification_gateway,
    ):
        """Test successfully opening a LONG position."""
        result = await open_position_use_case.execute(long_signal, trade_settings)

        assert result.success is True
        assert result.qty > 0
        assert result.entry_price == 50000.0
        assert result.final_sl == 48000.0
        assert result.exchange_name == "binance"
        assert result.order is not None
        assert result.sl_tp_res is not None

        # Verify notification was sent
        mock_notification_gateway.send_message.assert_called_once()
        message = mock_notification_gateway.send_message.call_args[0][0]
        assert "opened long" in message.lower()
        assert "btcusdt" in message.lower()

    @pytest.mark.asyncio
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_open_short_position_success(
        self,
        mock_sleep,
        open_position_use_case,
        short_signal,
        trade_settings,
        mock_notification_gateway,
        mock_exchange_registry,
    ):
        """Test successfully opening a SHORT position."""
        exchange = mock_exchange_registry.get_exchange("binance")
        # Mock SHORT position (negative positionAmt)
        exchange.get_position.return_value = {"positionAmt": "-0.001", "entryPrice": "3000.0"}

        result = await open_position_use_case.execute(short_signal, trade_settings)

        assert result.success is True
        assert result.qty > 0
        assert result.entry_price == 50000.0
        assert result.final_sl == 3100.0

        # Verify notification was sent
        mock_notification_gateway.send_message.assert_called_once()
        message = mock_notification_gateway.send_message.call_args[0][0]
        assert "opened short" in message.lower()
        assert "ethusdt" in message.lower()

    @pytest.mark.asyncio
    async def test_signal_without_symbol(self, open_position_use_case, trade_settings):
        """Test that signal without symbol returns failure."""
        signal = ParsedSignalEntity(
            source_id="channel_123",
            message_id="msg_456",
            message_hash="hash_123",
            message_text="LONG",
            symbol=None,
            side=TradeSide.LONG,
        )

        result = await open_position_use_case.execute(signal, trade_settings)

        assert result.success is False
        assert result.reason == "No symbol"

    @pytest.mark.asyncio
    async def test_signal_without_side(self, open_position_use_case, trade_settings):
        """Test that signal without side returns failure."""
        signal = ParsedSignalEntity(
            source_id="channel_123",
            message_id="msg_456",
            message_hash="hash_123",
            message_text="BTCUSDT",
            symbol="BTCUSDT",
            side=None,
        )

        result = await open_position_use_case.execute(signal, trade_settings)

        assert result.success is False
        assert result.reason == "No side"

    @pytest.mark.asyncio
    async def test_leverage_setting_failure(
        self,
        open_position_use_case,
        long_signal,
        trade_settings,
        mock_exchange_registry,
    ):
        """Test handling of leverage setting failure."""
        exchange = mock_exchange_registry.get_exchange("binance")
        exchange.set_leverage.side_effect = Exception("Leverage error")

        result = await open_position_use_case.execute(long_signal, trade_settings)

        assert result.success is False
        assert "Failed to set leverage" in result.reason

    @pytest.mark.asyncio
    async def test_price_fetch_failure(
        self,
        open_position_use_case,
        long_signal,
        trade_settings,
        mock_exchange_registry,
    ):
        """Test handling of price fetch failure."""
        exchange = mock_exchange_registry.get_exchange("binance")
        exchange.get_last_price.side_effect = Exception("Price fetch error")

        result = await open_position_use_case.execute(long_signal, trade_settings)

        assert result.success is False
        assert "Failed to get price" in result.reason

    @pytest.mark.asyncio
    async def test_order_placement_failure(
        self,
        open_position_use_case,
        long_signal,
        trade_settings,
        mock_exchange_registry,
    ):
        """Test handling of order placement failure."""
        exchange = mock_exchange_registry.get_exchange("binance")
        exchange.place_market_order.side_effect = Exception("Order placement error")

        result = await open_position_use_case.execute(long_signal, trade_settings)

        assert result.success is False
        assert "Failed to place market order" in result.reason

    @pytest.mark.asyncio
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_qty_calculation(
        self,
        mock_sleep,
        open_position_use_case,
        long_signal,
        trade_settings,
        mock_exchange_registry,
    ):
        """Test quantity calculation based on balance and leverage."""
        exchange = mock_exchange_registry.get_exchange("binance")
        exchange.get_balance.return_value = 1000.0  # $1000 balance
        exchange.get_last_price.return_value = 50000.0  # BTC at $50k

        result = await open_position_use_case.execute(long_signal, trade_settings)

        assert result.success is True
        # Two-step calculation:
        # Step 1: free_balance = balance * free_balance_pct = 1000 * 0.1 = 100 USDT
        # Step 2: margin = free_balance * position_size_pct = 100 * 0.05 = 5 USDT
        # Notional: margin * leverage = 5 * 20 = 100 USDT
        # Qty: notional / price = 100 / 50000 = 0.002
        assert result.qty == 0.002

    @pytest.mark.asyncio
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_min_qty_enforcement(
        self,
        mock_sleep,
        open_position_use_case,
        long_signal,
        trade_settings,
        mock_exchange_registry,
    ):
        """Test that minimum quantity is enforced."""
        exchange = mock_exchange_registry.get_exchange("binance")
        exchange.get_balance.return_value = 1000.0  # Increased balance to meet min notional
        exchange.get_symbol_info.return_value = {
            "qty_precision": 3,
            "price_precision": 2,
            "min_qty": 0.001,
        }

        result = await open_position_use_case.execute(long_signal, trade_settings)

        assert result.success is True
        assert result.qty >= 0.001  # Should use min_qty

    @pytest.mark.asyncio
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_default_sl_calculation_long(
        self,
        mock_sleep,
        open_position_use_case,
        trade_settings,
        mock_exchange_registry,
    ):
        """Test default stop loss calculation for LONG position."""
        signal = ParsedSignalEntity(
            source_id="channel_123",
            message_id="msg_456",
            message_hash="hash_123",
            message_text="BTCUSDT LONG",
            symbol="BTCUSDT",
            side=TradeSide.LONG,
            entry_mode=EntryMode.CMP,
            stop_loss=None,  # No SL in signal
            is_signal=True,
        )

        exchange = mock_exchange_registry.get_exchange("binance")
        exchange.get_last_price.return_value = 50000.0

        result = await open_position_use_case.execute(signal, trade_settings)

        assert result.success is True
        # Default SL: 50000 * (1 - 0.04) = 48000
        assert result.final_sl == 48000.0

    @pytest.mark.asyncio
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_default_sl_calculation_short(
        self,
        mock_sleep,
        open_position_use_case,
        trade_settings,
        mock_exchange_registry,
    ):
        """Test default stop loss calculation for SHORT position."""
        signal = ParsedSignalEntity(
            source_id="channel_123",
            message_id="msg_456",
            message_hash="hash_123",
            message_text="BTCUSDT SHORT",
            symbol="BTCUSDT",
            side=TradeSide.SHORT,
            entry_mode=EntryMode.CMP,
            stop_loss=None,  # No SL in signal
            is_signal=True,
        )

        exchange = mock_exchange_registry.get_exchange("binance")
        exchange.get_last_price.return_value = 50000.0
        # Mock SHORT position (negative positionAmt)
        exchange.get_position.return_value = {"positionAmt": "-0.001", "entryPrice": "50000.0"}

        result = await open_position_use_case.execute(signal, trade_settings)

        assert result.success is True
        # Default SL: 50000 * (1 + 0.04) = 52000
        assert result.final_sl == 52000.0

    @pytest.mark.asyncio
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_signal_sl_overrides_default(
        self,
        mock_sleep,
        open_position_use_case,
        long_signal,
        trade_settings,
    ):
        """Test that signal SL overrides default SL."""
        result = await open_position_use_case.execute(long_signal, trade_settings)

        assert result.success is True
        assert result.final_sl == 48000.0  # From signal, not calculated

    @pytest.mark.asyncio
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_sl_tp_placement(
        self,
        mock_sleep,
        open_position_use_case,
        long_signal,
        trade_settings,
        mock_exchange_registry,
    ):
        """Test that SL/TP orders are placed correctly."""
        exchange = mock_exchange_registry.get_exchange("binance")

        result = await open_position_use_case.execute(long_signal, trade_settings)

        assert result.success is True

        # Verify SL/TP orders were placed
        exchange.place_sl_tp_orders.assert_called_once()
        call_args = exchange.place_sl_tp_orders.call_args
        assert call_args.kwargs["symbol"] == "BTCUSDT"
        assert call_args.kwargs["side"] == TradeSide.LONG
        assert call_args.kwargs["stop_loss"] == 48000.0
        assert call_args.kwargs["take_profits"] == [51000.0, 52000.0, 53000.0]

    @pytest.mark.asyncio
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_notification_includes_sl_tp_status(
        self,
        mock_sleep,
        open_position_use_case,
        long_signal,
        trade_settings,
        mock_notification_gateway,
    ):
        """Test that notification includes SL/TP placement status."""
        result = await open_position_use_case.execute(long_signal, trade_settings)

        assert result.success is True

        message = mock_notification_gateway.send_message.call_args[0][0]
        assert "SL:" in message
        assert "TP:" in message
        assert "✅" in message  # Success indicators

    @pytest.mark.asyncio
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_partial_tp_placement_warning(
        self,
        mock_sleep,
        open_position_use_case,
        long_signal,
        trade_settings,
        mock_exchange_registry,
        mock_notification_gateway,
    ):
        """Test warning when only some TP orders are placed."""
        exchange = mock_exchange_registry.get_exchange("binance")
        exchange.place_sl_tp_orders.return_value = {
            "stop_loss": {"orderId": "sl_123"},
            "take_profits": [
                {"orderId": "tp_1"},
                # Only 1 TP placed instead of 3
            ],
        }

        result = await open_position_use_case.execute(long_signal, trade_settings)

        assert result.success is True

        message = mock_notification_gateway.send_message.call_args[0][0]
        assert "⚠️" in message  # Warning indicator
        assert "1/3" in message  # Shows partial placement

    @pytest.mark.asyncio
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_waits_for_position_confirmation(
        self,
        mock_sleep,
        open_position_use_case,
        long_signal,
        trade_settings,
        mock_exchange_registry,
    ):
        """Test that use case waits for position to be confirmed."""
        exchange = mock_exchange_registry.get_exchange("binance")

        # Mock wait_for_position_ready to simulate waiting
        exchange.wait_for_position_ready = AsyncMock(return_value=True)

        result = await open_position_use_case.execute(long_signal, trade_settings)

        assert result.success is True
        assert exchange.wait_for_position_ready.call_count == 1
        exchange.wait_for_position_ready.assert_called_once_with(
            symbol="BTCUSDT",
            side=TradeSide.LONG,
            timeout=10.0,
            check_interval=0.5,
        )

    @pytest.mark.asyncio
    @patch("asyncio.sleep", new_callable=AsyncMock)
    @patch("time.time")
    async def test_position_timeout_handling(
        self,
        mock_time,
        mock_sleep,
        open_position_use_case,
        long_signal,
        trade_settings,
        mock_exchange_registry,
        mock_notification_gateway,
    ):
        """Test handling when position doesn't appear within timeout."""
        exchange = mock_exchange_registry.get_exchange("binance")

        # Mock wait_for_position_ready to return False (timeout)
        exchange.wait_for_position_ready = AsyncMock(return_value=False)

        result = await open_position_use_case.execute(long_signal, trade_settings)

        # Should still return success (order placed) but without SL/TP
        assert result.success is True
        assert result.sl_tp_res == {}
        assert result.final_sl is None

        # Should send critical notification
        mock_notification_gateway.send_message.assert_called()
        call_args = mock_notification_gateway.send_message.call_args_list
        assert any("CRITICAL" in str(call) for call in call_args)

    @pytest.mark.asyncio
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_balance_query_failure(
        self,
        mock_sleep,
        open_position_use_case,
        long_signal,
        trade_settings,
        mock_exchange_registry,
    ):
        """Test handling of balance query failure."""
        exchange = mock_exchange_registry.get_exchange("binance")
        exchange.get_balance.side_effect = Exception("Balance query error")

        result = await open_position_use_case.execute(long_signal, trade_settings)

        assert result.success is False
        assert "Invalid qty" in result.reason
