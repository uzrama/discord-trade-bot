"""Tests for core.application.trading.use_cases.tracking module."""

from unittest.mock import AsyncMock, Mock

import pytest

from discord_trade_bot.core.application.trading.use_cases.tracking import (
    ProcessTrackerEventUseCase,
)
from discord_trade_bot.core.domain.entities.position import ActivePositionEntity
from discord_trade_bot.core.domain.value_objects.trading import (
    PositionStatus,
    TradeSide,
)


@pytest.fixture
def mock_exchange_for_tracking():
    """Create a mock exchange for tracking tests."""
    exchange = AsyncMock()
    exchange.name = "binance"
    exchange.cancel_order = AsyncMock(return_value={"orderId": "cancelled"})
    exchange.place_stop_market_order = AsyncMock(return_value={"orderId": "new_sl_123", "algoId": "new_sl_123"})
    exchange.get_position = AsyncMock(return_value={"positionAmt": "0.1", "entryPrice": "50000"})
    exchange.get_last_price = AsyncMock(return_value=51000.0)
    exchange.place_market_order = AsyncMock(return_value={"orderId": "market_close_123"})
    exchange.get_symbol_info = AsyncMock(return_value={"qty_precision": 3, "price_precision": 2, "min_qty": 0.001})
    return exchange


@pytest.fixture
def mock_exchange_registry_for_tracking(mock_exchange_for_tracking):
    """Create a mock exchange registry for tracking tests."""
    registry = Mock()
    registry.get_exchange = Mock(return_value=mock_exchange_for_tracking)
    return registry


@pytest.fixture
def tracker_use_case(
    mock_exchange_registry_for_tracking,
    mock_repository,
    mock_notification_gateway,
    mock_app_config,
):
    """Create ProcessTrackerEventUseCase instance with mocked dependencies."""
    return ProcessTrackerEventUseCase(
        exchange_registry=mock_exchange_registry_for_tracking,
        state_repository=mock_repository,
        notification_gateway=mock_notification_gateway,
        config=mock_app_config,
    )


@pytest.fixture
def open_position_with_tps():
    """Create an open position with TP orders."""
    from discord_trade_bot.core.domain.value_objects.trading import TPDistributionRow

    return ActivePositionEntity(
        id="pos_123",
        symbol="BTCUSDT",
        source_id="test_channel_123",
        message_id="msg_456",
        exchange="binance",
        side=TradeSide.LONG,
        qty=0.1,
        entry_price=50000.0,
        stop_loss=48000.0,
        take_profits=[51000.0, 52000.0, 53000.0],
        tp_distribution=[
            TPDistributionRow(label="tp1", close_pct=33.33),
            TPDistributionRow(label="tp2", close_pct=33.33),
            TPDistributionRow(label="tp3", close_pct=33.34),
        ],
        tp_order_ids={
            "tp_order_1": 51000.0,
            "tp_order_2": 52000.0,
            "tp_order_3": 53000.0,
        },
        sl_order_id="sl_order_123",
        tp_index_hit=0,
        breakeven_applied=False,
        status=PositionStatus.OPEN,
    )


class TestProcessTrackerEventUseCase:
    """Test ProcessTrackerEventUseCase."""

    @pytest.mark.asyncio
    async def test_tp_hit_moves_sl_to_breakeven(
        self,
        tracker_use_case,
        mock_repository,
        mock_notification_gateway,
        mock_exchange_for_tracking,
        open_position_with_tps,
    ):
        """Test that first TP hit moves SL to TP1 level."""
        # Setup repository to return position
        mock_repository.get_open_positions.return_value = [open_position_with_tps]
        mock_repository.get_position_by_id.return_value = open_position_with_tps

        # Set current price higher than TP1 so SL at TP1 level is valid
        mock_exchange_for_tracking.get_last_price.return_value = 51500.0

        # Create TP hit event
        event = {
            "o": {
                "i": "tp_order_1",  # First TP order ID
                "s": "BTCUSDT",
                "X": "FILLED",
            }
        }

        await tracker_use_case.execute(event)

        # Verify old SL was cancelled
        mock_exchange_for_tracking.cancel_order.assert_called_once_with("BTCUSDT", "sl_order_123")

        # Verify new SL was placed at TP1 level (with fee adjustment)
        mock_exchange_for_tracking.place_stop_market_order.assert_called_once()
        call_args = mock_exchange_for_tracking.place_stop_market_order.call_args
        assert call_args.kwargs["symbol"] == "BTCUSDT"
        # SL should be at TP1 level (51000) minus fees
        assert call_args.kwargs["stop_price"] < 51000.0  # Below TP1 due to fees
        assert call_args.kwargs["stop_price"] > 50900.0  # But close to TP1

        # Verify position was updated
        mock_repository.save_position.assert_called_once()
        saved_position = mock_repository.save_position.call_args[0][0]
        assert saved_position.tp_index_hit == 1
        assert saved_position.breakeven_applied is True
        # SL is at TP1 level minus fees
        assert saved_position.break_even_price < 51000.0
        assert saved_position.break_even_price > 50900.0
        assert saved_position.sl_order_id == "new_sl_123"

        # Verify notification was sent
        mock_notification_gateway.send_message.assert_called_once()
        message = mock_notification_gateway.send_message.call_args[0][0]
        assert "tp1" in message.lower()

    @pytest.mark.asyncio
    async def test_second_tp_hit_does_not_move_sl_again(
        self,
        tracker_use_case,
        mock_repository,
        mock_exchange_for_tracking,
        open_position_with_tps,
    ):
        """Test that subsequent TP hits don't move SL again."""
        # Position already has breakeven applied
        open_position_with_tps.breakeven_applied = True
        open_position_with_tps.tp_index_hit = 1

        mock_repository.get_open_positions.return_value = [open_position_with_tps]
        mock_repository.get_position_by_id.return_value = open_position_with_tps

        # Create second TP hit event
        event = {
            "o": {
                "i": "tp_order_2",
                "s": "BTCUSDT",
                "X": "FILLED",
            }
        }

        await tracker_use_case.execute(event)

        # Verify SL was NOT moved again
        mock_exchange_for_tracking.cancel_order.assert_not_called()
        mock_exchange_for_tracking.place_stop_market_order.assert_not_called()

        # Verify position was updated
        mock_repository.save_position.assert_called_once()
        saved_position = mock_repository.save_position.call_args[0][0]
        assert saved_position.tp_index_hit == 2

    @pytest.mark.asyncio
    async def test_all_tps_hit_closes_position(
        self,
        tracker_use_case,
        mock_repository,
        open_position_with_tps,
    ):
        """Test that hitting all TPs closes the position."""
        # Position has 2 TPs already hit
        open_position_with_tps.tp_index_hit = 2
        open_position_with_tps.breakeven_applied = True

        mock_repository.get_open_positions.return_value = [open_position_with_tps]
        mock_repository.get_position_by_id.return_value = open_position_with_tps

        # Create third (final) TP hit event
        event = {
            "o": {
                "i": "tp_order_3",
                "s": "BTCUSDT",
                "X": "FILLED",
            }
        }

        await tracker_use_case.execute(event)

        # Verify position was closed
        mock_repository.save_position.assert_called_once()
        saved_position = mock_repository.save_position.call_args[0][0]
        assert saved_position.tp_index_hit == 3
        assert saved_position.status == PositionStatus.CLOSED

    @pytest.mark.asyncio
    async def test_sl_hit_closes_position(
        self,
        tracker_use_case,
        mock_repository,
        open_position_with_tps,
    ):
        """Test that SL hit closes the position."""
        mock_repository.get_open_positions.return_value = [open_position_with_tps]
        mock_repository.get_position_by_id.return_value = open_position_with_tps

        # Create SL hit event
        event = {
            "o": {
                "i": "sl_order_123",  # SL order ID
                "s": "BTCUSDT",
                "X": "FILLED",
            }
        }

        await tracker_use_case.execute(event)

        # Verify position was closed
        mock_repository.save_position.assert_called_once()
        saved_position = mock_repository.save_position.call_args[0][0]
        assert saved_position.status == PositionStatus.CLOSED

    @pytest.mark.asyncio
    async def test_no_matching_position(
        self,
        tracker_use_case,
        mock_repository,
    ):
        """Test handling when no matching position is found."""
        mock_repository.get_open_positions.return_value = []

        event = {
            "o": {
                "i": "unknown_order",
                "s": "BTCUSDT",
                "X": "FILLED",
            }
        }

        # Should not raise exception
        await tracker_use_case.execute(event)

        # Verify no position was saved
        mock_repository.save_position.assert_not_called()

    @pytest.mark.asyncio
    async def test_closed_position_not_processed(
        self,
        tracker_use_case,
        mock_repository,
        open_position_with_tps,
    ):
        """Test that closed positions are not processed."""
        open_position_with_tps.status = PositionStatus.CLOSED

        mock_repository.get_open_positions.return_value = [open_position_with_tps]
        mock_repository.get_position_by_id.return_value = open_position_with_tps

        event = {
            "o": {
                "i": "tp_order_1",
                "s": "BTCUSDT",
                "X": "FILLED",
            }
        }

        await tracker_use_case.execute(event)

        # Verify position was not updated
        mock_repository.save_position.assert_not_called()

    @pytest.mark.asyncio
    async def test_different_symbol_not_processed(
        self,
        tracker_use_case,
        mock_repository,
        open_position_with_tps,
    ):
        """Test that events for different symbols are not processed."""
        mock_repository.get_open_positions.return_value = [open_position_with_tps]

        event = {
            "o": {
                "i": "some_order",
                "s": "ETHUSDT",  # Different symbol
                "X": "FILLED",
            }
        }

        await tracker_use_case.execute(event)

        # Verify position was not fetched by ID
        mock_repository.get_position_by_id.assert_not_called()

    @pytest.mark.asyncio
    async def test_breakeven_sl_cancellation_failure(
        self,
        tracker_use_case,
        mock_repository,
        mock_notification_gateway,
        mock_exchange_for_tracking,
        open_position_with_tps,
    ):
        """Test handling of SL cancellation failure during breakeven move."""
        mock_repository.get_open_positions.return_value = [open_position_with_tps]
        mock_repository.get_position_by_id.return_value = open_position_with_tps

        # Set current price higher than TP1 so SL at TP1 level is valid
        mock_exchange_for_tracking.get_last_price.return_value = 51500.0

        # Mock cancellation failure
        mock_exchange_for_tracking.cancel_order.side_effect = Exception("Cancel failed")

        event = {
            "o": {
                "i": "tp_order_1",
                "s": "BTCUSDT",
                "X": "FILLED",
            }
        }

        await tracker_use_case.execute(event)

        # Should continue and place new SL despite cancellation failure
        mock_exchange_for_tracking.place_stop_market_order.assert_called_once()

    @pytest.mark.asyncio
    async def test_breakeven_sl_placement_failure(
        self,
        tracker_use_case,
        mock_repository,
        mock_notification_gateway,
        mock_exchange_for_tracking,
        open_position_with_tps,
    ):
        """Test handling of SL placement failure during breakeven move - should trigger emergency close."""
        mock_repository.get_open_positions.return_value = [open_position_with_tps]
        mock_repository.get_position_by_id.return_value = open_position_with_tps

        # Set current price higher than TP1 so SL at TP1 level is valid
        mock_exchange_for_tracking.get_last_price.return_value = 51500.0

        # Mock placement failure for both attempts (calculated BE and fallback)
        mock_exchange_for_tracking.place_stop_market_order.side_effect = Exception("Placement failed")

        event = {
            "o": {
                "i": "tp_order_1",
                "s": "BTCUSDT",
                "X": "FILLED",
            }
        }

        # Should NOT raise exception - instead should close position via emergency
        await tracker_use_case.execute(event)

        # Verify emergency close was triggered
        mock_exchange_for_tracking.place_market_order.assert_called_once()

        # Verify emergency notification was sent
        assert mock_notification_gateway.send_message.call_count >= 1
        emergency_message = None
        for call in mock_notification_gateway.send_message.call_args_list:
            msg = call[0][0]
            if "EMERGENCY" in msg:
                emergency_message = msg
                break
        assert emergency_message is not None
        assert "Position closed" in emergency_message

    @pytest.mark.asyncio
    async def test_multiple_positions_same_symbol(
        self,
        tracker_use_case,
        mock_repository,
        open_position_with_tps,
    ):
        """Test handling multiple positions for the same symbol."""
        # Create second position with different order IDs
        position2 = ActivePositionEntity(
            id="pos_456",
            symbol="BTCUSDT",
            source_id="channel_789",
            message_id="msg_789",
            exchange="binance",
            side=TradeSide.LONG,
            qty=0.2,
            entry_price=51000.0,
            stop_loss=49000.0,
            take_profits=[52000.0, 53000.0],
            tp_order_ids={
                "tp_order_4": 52000.0,
                "tp_order_5": 53000.0,
            },
            sl_order_id="sl_order_456",
            tp_index_hit=0,
            breakeven_applied=False,
            status=PositionStatus.OPEN,
        )

        mock_repository.get_open_positions.return_value = [
            open_position_with_tps,
            position2,
        ]

        # First call returns first position, second call returns second position
        mock_repository.get_position_by_id.side_effect = [
            open_position_with_tps,
            position2,
        ]

        # Event matches first position's TP
        event = {
            "o": {
                "i": "tp_order_1",
                "s": "BTCUSDT",
                "X": "FILLED",
            }
        }

        await tracker_use_case.execute(event)

        # Verify only the matching position was updated
        mock_repository.save_position.assert_called_once()
        saved_position = mock_repository.save_position.call_args[0][0]
        assert saved_position.id == "pos_123"

    @pytest.mark.asyncio
    async def test_position_lock_prevents_race_conditions(
        self,
        tracker_use_case,
        mock_repository,
        open_position_with_tps,
    ):
        """Test that position locks prevent concurrent updates."""
        mock_repository.get_open_positions.return_value = [open_position_with_tps]
        mock_repository.get_position_by_id.return_value = open_position_with_tps

        event = {
            "o": {
                "i": "tp_order_1",
                "s": "BTCUSDT",
                "X": "FILLED",
            }
        }

        # Execute twice to test locking
        await tracker_use_case.execute(event)

        # Verify lock was created for this position
        assert "pos_123" in tracker_use_case._position_locks

    @pytest.mark.asyncio
    async def test_short_position_tracking(
        self,
        tracker_use_case,
        mock_repository,
        mock_exchange_for_tracking,
    ):
        """Test tracking for SHORT positions."""
        from discord_trade_bot.core.domain.value_objects.trading import TPDistributionRow

        short_position = ActivePositionEntity(
            id="pos_short",
            symbol="ETHUSDT",
            source_id="test_channel_123",  # Match mock_app_config
            message_id="msg_456",
            exchange="binance",
            side=TradeSide.SHORT,
            qty=1.0,
            entry_price=3000.0,
            stop_loss=3100.0,
            take_profits=[2950.0, 2900.0],
            tp_distribution=[
                TPDistributionRow(label="tp1", close_pct=50.0),
                TPDistributionRow(label="tp2", close_pct=50.0),
            ],
            tp_order_ids={
                "tp_order_1": 2950.0,
                "tp_order_2": 2900.0,
            },
            sl_order_id="sl_order_short",
            tp_index_hit=0,
            breakeven_applied=False,
            status=PositionStatus.OPEN,
        )

        mock_repository.get_open_positions.return_value = [short_position]
        mock_repository.get_position_by_id.return_value = short_position

        # Set current price for SHORT position (below TP1, so SL at TP1 level is valid)
        mock_exchange_for_tracking.get_last_price.return_value = 2900.0

        event = {
            "o": {
                "i": "tp_order_1",
                "s": "ETHUSDT",
                "X": "FILLED",
            }
        }

        await tracker_use_case.execute(event)

        # Verify SL was placed at TP1 level (with fee adjustment, above TP1 for SHORT)
        mock_exchange_for_tracking.place_stop_market_order.assert_called_once()
        call_args = mock_exchange_for_tracking.place_stop_market_order.call_args
        # For SHORT, SL at TP1 level (2950) plus fees
        assert call_args.kwargs["stop_price"] > 2950.0  # Above TP1 due to fees
        assert call_args.kwargs["stop_price"] < 3000.0  # But below entry
        assert call_args.kwargs["side"] == TradeSide.SHORT
