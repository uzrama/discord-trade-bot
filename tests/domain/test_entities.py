"""Tests for core.domain.entities module."""

from datetime import UTC, datetime

import pytest

from discord_trade_bot.core.domain.entities.position import ActivePositionEntity
from discord_trade_bot.core.domain.entities.signal import ParsedSignalEntity
from discord_trade_bot.core.domain.value_objects.trading import (
    EntryMode,
    PositionStatus,
    SignalType,
    TPDistributionRow,
    TradeSide,
)


class TestParsedSignalEntity:
    """Test ParsedSignalEntity."""

    def test_create_minimal_signal(self):
        """Test creating signal with minimal required fields."""
        signal = ParsedSignalEntity(
            source_id="channel_123",
            message_id="msg_456",
            message_hash="abc123",
            message_text="BTC LONG",
        )

        assert signal.source_id == "channel_123"
        assert signal.message_id == "msg_456"
        assert signal.message_hash == "abc123"
        assert signal.message_text == "BTC LONG"
        assert signal.symbol is None
        assert signal.side is None
        assert signal.entry_mode is None
        assert signal.entry_price is None
        assert signal.leverage is None
        assert signal.stop_loss is None
        assert signal.take_profits == []
        assert signal.signal_type == SignalType.UNKNOWN
        assert signal.is_signal is False
        assert isinstance(signal.seen_at, datetime)
        assert signal.contains_tp1_hit is False
        assert signal.entry_triggered is False

    def test_create_full_signal(self):
        """Test creating signal with all fields."""
        seen_at = datetime.now(UTC)
        signal = ParsedSignalEntity(
            source_id="channel_123",
            message_id="msg_456",
            message_hash="abc123",
            message_text="BTC LONG Entry: 50000",
            symbol="BTCUSDT",
            side=TradeSide.LONG,
            entry_mode=EntryMode.EXACT_PRICE,
            entry_price=50000.0,
            leverage=10,
            stop_loss=49000.0,
            take_profits=[51000.0, 52000.0, 53000.0],
            signal_type=SignalType.PRIMARY_SIGNAL,
            is_signal=True,
            seen_at=seen_at,
            contains_tp1_hit=False,
            entry_triggered=True,
        )

        assert signal.symbol == "BTCUSDT"
        assert signal.side == TradeSide.LONG
        assert signal.entry_mode == EntryMode.EXACT_PRICE
        assert signal.entry_price == 50000.0
        assert signal.leverage == 10
        assert signal.stop_loss == 49000.0
        assert signal.take_profits == [51000.0, 52000.0, 53000.0]
        assert signal.signal_type == SignalType.PRIMARY_SIGNAL
        assert signal.is_signal is True
        assert signal.seen_at == seen_at
        assert signal.entry_triggered is True

    def test_long_signal(self):
        """Test creating a LONG signal."""
        signal = ParsedSignalEntity(
            source_id="channel_123",
            message_id="msg_456",
            message_hash="abc123",
            message_text="BTC LONG",
            symbol="BTCUSDT",
            side=TradeSide.LONG,
            entry_price=50000.0,
            stop_loss=49000.0,
            take_profits=[51000.0, 52000.0],
        )

        assert signal.side == TradeSide.LONG
        assert signal.stop_loss < signal.entry_price
        assert all(tp > signal.entry_price for tp in signal.take_profits)

    def test_short_signal(self):
        """Test creating a SHORT signal."""
        signal = ParsedSignalEntity(
            source_id="channel_123",
            message_id="msg_456",
            message_hash="abc123",
            message_text="BTC SHORT",
            symbol="BTCUSDT",
            side=TradeSide.SHORT,
            entry_price=50000.0,
            stop_loss=51000.0,
            take_profits=[49000.0, 48000.0],
        )

        assert signal.side == TradeSide.SHORT
        assert signal.stop_loss > signal.entry_price
        assert all(tp < signal.entry_price for tp in signal.take_profits)

    def test_default_seen_at_is_utc(self):
        """Test that default seen_at is in UTC."""
        signal = ParsedSignalEntity(
            source_id="channel_123",
            message_id="msg_456",
            message_hash="abc123",
            message_text="BTC LONG",
        )

        assert signal.seen_at.tzinfo == UTC

    def test_signal_types(self):
        """Test different signal types."""
        for signal_type in [SignalType.UNKNOWN, SignalType.PRIMARY_SIGNAL, SignalType.SIGNAL_UPDATE]:
            signal = ParsedSignalEntity(
                source_id="channel_123",
                message_id="msg_456",
                message_hash="abc123",
                message_text="test",
                signal_type=signal_type,
            )
            assert signal.signal_type == signal_type

    def test_entry_modes(self):
        """Test different entry modes."""
        for entry_mode in [EntryMode.CMP, EntryMode.EXACT_PRICE]:
            signal = ParsedSignalEntity(
                source_id="channel_123",
                message_id="msg_456",
                message_hash="abc123",
                message_text="test",
                entry_mode=entry_mode,
            )
            assert signal.entry_mode == entry_mode


class TestActivePositionEntity:
    """Test ActivePositionEntity."""

    def test_create_minimal_position(self):
        """Test creating position with minimal required fields."""
        position = ActivePositionEntity(
            symbol="BTCUSDT",
            source_id="channel_123",
            message_id="msg_456",
            exchange="binance",
            side=TradeSide.LONG,
            qty=0.1,
            entry_price=50000.0,
        )

        assert position.symbol == "BTCUSDT"
        assert position.source_id == "channel_123"
        assert position.message_id == "msg_456"
        assert position.exchange == "binance"
        assert position.side == TradeSide.LONG
        assert position.qty == 0.1
        assert position.entry_price == 50000.0
        assert position.id is not None  # Auto-generated UUID
        assert isinstance(position.opened_at, datetime)
        assert position.stop_loss is None
        assert position.take_profits == []
        assert position.tp_distribution == []
        assert position.tp_order_ids == {}
        assert position.sl_order_id is None
        assert position.tp_index_hit == 0
        assert position.tp_hits == []
        assert position.tp_qty_basis == 0.0
        assert position.closed_qty == 0.0
        assert position.remaining_qty == 0.0
        assert position.initial_notional_usd == 0.0
        assert position.closed_notional_usd == 0.0
        assert position.realized_pnl_usdt == 0.0
        assert position.break_even_price is None
        assert position.break_even_stop_price is None
        assert position.reentry_order_id is None
        assert position.reentry_qty == 0.0
        assert position.breakeven_applied is False
        assert position.status == PositionStatus.OPEN
        assert position.order_id is None

    def test_create_full_position(self):
        """Test creating position with all fields."""
        opened_at = datetime.now(UTC)
        tp_distribution = [
            TPDistributionRow(label="TP1", close_pct=0.5),
            TPDistributionRow(label="TP2", close_pct=0.5),
        ]

        position = ActivePositionEntity(
            symbol="BTCUSDT",
            source_id="channel_123",
            message_id="msg_456",
            exchange="binance",
            side=TradeSide.LONG,
            qty=0.1,
            entry_price=50000.0,
            id="custom_id_123",
            opened_at=opened_at,
            stop_loss=49000.0,
            take_profits=[51000.0, 52000.0],
            tp_distribution=tp_distribution,
            tp_order_ids={"order1": 51000.0},
            sl_order_id="sl_order_123",
            tp_index_hit=1,
            tp_hits=[{"price": 51000.0, "qty": 0.05}],
            tp_qty_basis=0.1,
            closed_qty=0.05,
            remaining_qty=0.05,
            initial_notional_usd=5000.0,
            closed_notional_usd=2550.0,
            realized_pnl_usdt=50.0,
            break_even_price=50100.0,
            break_even_stop_price=50050.0,
            reentry_order_id="reentry_123",
            reentry_qty=0.02,
            breakeven_applied=True,
            status=PositionStatus.PARTIALLY_FILLED,
            order_id="order_123",
        )

        assert position.id == "custom_id_123"
        assert position.opened_at == opened_at
        assert position.stop_loss == 49000.0
        assert position.take_profits == [51000.0, 52000.0]
        assert position.tp_distribution == tp_distribution
        assert position.tp_order_ids == {"order1": 51000.0}
        assert position.sl_order_id == "sl_order_123"
        assert position.tp_index_hit == 1
        assert position.tp_hits == [{"price": 51000.0, "qty": 0.05}]
        assert position.tp_qty_basis == 0.1
        assert position.closed_qty == 0.05
        assert position.remaining_qty == 0.05
        assert position.initial_notional_usd == 5000.0
        assert position.closed_notional_usd == 2550.0
        assert position.realized_pnl_usdt == 50.0
        assert position.break_even_price == 50100.0
        assert position.break_even_stop_price == 50050.0
        assert position.reentry_order_id == "reentry_123"
        assert position.reentry_qty == 0.02
        assert position.breakeven_applied is True
        assert position.status == PositionStatus.PARTIALLY_FILLED
        assert position.order_id == "order_123"

    def test_auto_generated_id(self):
        """Test that ID is auto-generated if not provided."""
        position1 = ActivePositionEntity(
            symbol="BTCUSDT",
            source_id="channel_123",
            message_id="msg_456",
            exchange="binance",
            side=TradeSide.LONG,
            qty=0.1,
            entry_price=50000.0,
        )

        position2 = ActivePositionEntity(
            symbol="BTCUSDT",
            source_id="channel_123",
            message_id="msg_456",
            exchange="binance",
            side=TradeSide.LONG,
            qty=0.1,
            entry_price=50000.0,
        )

        assert position1.id is not None
        assert position2.id is not None
        assert position1.id != position2.id  # Should be unique

    def test_long_position(self):
        """Test creating a LONG position."""
        position = ActivePositionEntity(
            symbol="BTCUSDT",
            source_id="channel_123",
            message_id="msg_456",
            exchange="binance",
            side=TradeSide.LONG,
            qty=0.1,
            entry_price=50000.0,
            stop_loss=49000.0,
            take_profits=[51000.0, 52000.0],
        )

        assert position.side == TradeSide.LONG
        assert position.stop_loss < position.entry_price
        assert all(tp > position.entry_price for tp in position.take_profits)

    def test_short_position(self):
        """Test creating a SHORT position."""
        position = ActivePositionEntity(
            symbol="BTCUSDT",
            source_id="channel_123",
            message_id="msg_456",
            exchange="binance",
            side=TradeSide.SHORT,
            qty=0.1,
            entry_price=50000.0,
            stop_loss=51000.0,
            take_profits=[49000.0, 48000.0],
        )

        assert position.side == TradeSide.SHORT
        assert position.stop_loss > position.entry_price
        assert all(tp < position.entry_price for tp in position.take_profits)

    def test_default_opened_at_is_utc(self):
        """Test that default opened_at is in UTC."""
        position = ActivePositionEntity(
            symbol="BTCUSDT",
            source_id="channel_123",
            message_id="msg_456",
            exchange="binance",
            side=TradeSide.LONG,
            qty=0.1,
            entry_price=50000.0,
        )

        assert position.opened_at.tzinfo == UTC

    def test_position_statuses(self):
        """Test different position statuses."""
        for status in [PositionStatus.OPEN, PositionStatus.CLOSED, PositionStatus.PARTIALLY_FILLED]:
            position = ActivePositionEntity(
                symbol="BTCUSDT",
                source_id="channel_123",
                message_id="msg_456",
                exchange="binance",
                side=TradeSide.LONG,
                qty=0.1,
                entry_price=50000.0,
                status=status,
            )
            assert position.status == status

    def test_tp_distribution(self):
        """Test TP distribution rows."""
        tp_distribution = [
            TPDistributionRow(label="TP1", close_pct=0.3),
            TPDistributionRow(label="TP2", close_pct=0.3),
            TPDistributionRow(label="TP3", close_pct=0.4),
        ]

        position = ActivePositionEntity(
            symbol="BTCUSDT",
            source_id="channel_123",
            message_id="msg_456",
            exchange="binance",
            side=TradeSide.LONG,
            qty=0.1,
            entry_price=50000.0,
            tp_distribution=tp_distribution,
        )

        assert len(position.tp_distribution) == 3
        assert sum(row.close_pct for row in position.tp_distribution) == 1.0

    def test_multiple_exchanges(self):
        """Test positions on different exchanges."""
        for exchange in ["binance", "bybit", "okx"]:
            position = ActivePositionEntity(
                symbol="BTCUSDT",
                source_id="channel_123",
                message_id="msg_456",
                exchange=exchange,
                side=TradeSide.LONG,
                qty=0.1,
                entry_price=50000.0,
            )
            assert position.exchange == exchange
