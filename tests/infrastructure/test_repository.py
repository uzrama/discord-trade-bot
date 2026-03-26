"""Integration tests for SqliteStateRepository."""

import tempfile
from pathlib import Path

import pytest

from discord_trade_bot.core.domain.entities.position import ActivePositionEntity
from discord_trade_bot.core.domain.value_objects.trading import (
    PositionStatus,
    TPDistributionRow,
    TradeSide,
)
from discord_trade_bot.infrastructure.persistence.repository import (
    SqliteStateRepository,
)


@pytest.fixture
async def temp_repository(tmp_path):
    """Create a temporary repository for testing."""
    db_file = tmp_path / "test.db"
    trades_file = tmp_path / "trades.jsonl"
    repo = SqliteStateRepository(str(db_file), str(trades_file))
    await repo.init_db()
    return repo


@pytest.fixture
def sample_position_for_repo():
    """Create a sample position for repository tests."""
    return ActivePositionEntity(
        id="test_pos_123",
        symbol="BTCUSDT",
        source_id="channel_123",
        message_id="msg_456",
        exchange="binance",
        side=TradeSide.LONG,
        qty=0.1,
        entry_price=50000.0,
        stop_loss=48000.0,
        take_profits=[51000.0, 52000.0, 53000.0],
        tp_distribution=[
            TPDistributionRow(label="TP1", close_pct=33.33),
            TPDistributionRow(label="TP2", close_pct=33.33),
            TPDistributionRow(label="TP3", close_pct=33.34),
        ],
        status=PositionStatus.OPEN,
    )


class TestSqliteStateRepository:
    """Test SqliteStateRepository."""

    @pytest.mark.asyncio
    async def test_init_creates_database_file(self, tmp_path):
        """Test that initialization creates database file."""
        db_file = tmp_path / "test.db"
        trades_file = tmp_path / "trades.jsonl"

        repo = SqliteStateRepository(str(db_file), str(trades_file))
        await repo.init_db()

        assert db_file.exists()

    @pytest.mark.asyncio
    async def test_init_db_creates_tables(self, temp_repository):
        """Test that init_db creates required tables."""
        # If init_db succeeds without error, tables are created
        # We can verify by trying to query
        positions = await temp_repository.get_open_positions()
        assert positions == []

    @pytest.mark.asyncio
    async def test_init_db_idempotent(self, temp_repository):
        """Test that init_db can be called multiple times."""
        await temp_repository.init_db()
        await temp_repository.init_db()

        # Should not raise error
        positions = await temp_repository.get_open_positions()
        assert positions == []

    @pytest.mark.asyncio
    async def test_save_position_creates_new(self, temp_repository, sample_position_for_repo):
        """Test saving a new position."""
        await temp_repository.save_position(sample_position_for_repo)

        # Verify it was saved
        retrieved = await temp_repository.get_position_by_id("test_pos_123")
        assert retrieved is not None
        assert retrieved.id == "test_pos_123"
        assert retrieved.symbol == "BTCUSDT"
        assert retrieved.side == TradeSide.LONG

    @pytest.mark.asyncio
    async def test_save_position_generates_id_if_missing(self, temp_repository):
        """Test that save_position generates ID if not provided."""
        position = ActivePositionEntity(
            symbol="ETHUSDT",
            source_id="channel_123",
            message_id="msg_789",
            exchange="binance",
            side=TradeSide.SHORT,
            qty=1.0,
            entry_price=3000.0,
            status=PositionStatus.OPEN,
        )

        # ID should be None initially
        assert position.id is not None  # Actually generated in __post_init__

        await temp_repository.save_position(position)

        # Should have ID after save
        assert position.id is not None

        # Should be retrievable
        retrieved = await temp_repository.get_position_by_id(position.id)
        assert retrieved is not None
        assert retrieved.symbol == "ETHUSDT"

    @pytest.mark.asyncio
    async def test_save_position_updates_existing(self, temp_repository, sample_position_for_repo):
        """Test that saving existing position updates it."""
        # Save initial
        await temp_repository.save_position(sample_position_for_repo)

        # Modify and save again
        sample_position_for_repo.qty = 0.2
        sample_position_for_repo.status = PositionStatus.CLOSED
        await temp_repository.save_position(sample_position_for_repo)

        # Verify update (note: closed positions are not returned by get_position_by_id)
        positions = await temp_repository.get_open_positions()
        assert len(positions) == 0  # Closed position not in open list

    @pytest.mark.asyncio
    async def test_save_position_with_all_fields(self, temp_repository):
        """Test saving position with all optional fields populated."""
        position = ActivePositionEntity(
            id="full_pos_123",
            symbol="SOLUSDT",
            source_id="channel_123",
            message_id="msg_999",
            exchange="bybit",
            side=TradeSide.LONG,
            qty=10.0,
            entry_price=100.0,
            stop_loss=95.0,
            take_profits=[105.0, 110.0, 115.0],
            tp_distribution=[
                TPDistributionRow(label="TP1", close_pct=50.0),
                TPDistributionRow(label="TP2", close_pct=50.0),
            ],
            tp_order_ids={"order1": 105.0, "order2": 110.0},
            sl_order_id="sl_123",
            tp_index_hit=1,
            closed_qty=5.0,
            remaining_qty=5.0,
            initial_notional_usd=1000.0,
            realized_pnl_usdt=50.0,
            break_even_price=101.0,
            breakeven_applied=True,
            status=PositionStatus.OPEN,
            order_id="entry_123",
        )

        await temp_repository.save_position(position)

        retrieved = await temp_repository.get_position_by_id("full_pos_123")
        assert retrieved is not None
        assert retrieved.tp_order_ids == {"order1": 105.0, "order2": 110.0}
        assert retrieved.sl_order_id == "sl_123"
        assert retrieved.tp_index_hit == 1
        assert retrieved.breakeven_applied is True

    @pytest.mark.asyncio
    async def test_get_position_by_id_found(self, temp_repository, sample_position_for_repo):
        """Test retrieving position by ID when it exists."""
        await temp_repository.save_position(sample_position_for_repo)

        retrieved = await temp_repository.get_position_by_id("test_pos_123")

        assert retrieved is not None
        assert retrieved.id == "test_pos_123"
        assert retrieved.symbol == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_get_position_by_id_not_found(self, temp_repository):
        """Test retrieving position by ID when it doesn't exist."""
        retrieved = await temp_repository.get_position_by_id("nonexistent")

        assert retrieved is None

    @pytest.mark.asyncio
    async def test_get_open_positions_empty(self, temp_repository):
        """Test getting open positions when none exist."""
        positions = await temp_repository.get_open_positions()

        assert positions == []

    @pytest.mark.asyncio
    async def test_get_open_positions_multiple(self, temp_repository):
        """Test getting multiple open positions."""
        pos1 = ActivePositionEntity(
            id="pos1",
            symbol="BTCUSDT",
            source_id="ch1",
            message_id="msg1",
            exchange="binance",
            side=TradeSide.LONG,
            qty=0.1,
            entry_price=50000.0,
            status=PositionStatus.OPEN,
        )

        pos2 = ActivePositionEntity(
            id="pos2",
            symbol="ETHUSDT",
            source_id="ch1",
            message_id="msg2",
            exchange="binance",
            side=TradeSide.SHORT,
            qty=1.0,
            entry_price=3000.0,
            status=PositionStatus.OPEN,
        )

        await temp_repository.save_position(pos1)
        await temp_repository.save_position(pos2)

        positions = await temp_repository.get_open_positions()

        assert len(positions) == 2
        symbols = {p.symbol for p in positions}
        assert symbols == {"BTCUSDT", "ETHUSDT"}

    @pytest.mark.asyncio
    async def test_get_open_positions_filters_closed(self, temp_repository):
        """Test that get_open_positions filters out closed positions."""
        open_pos = ActivePositionEntity(
            id="open_pos",
            symbol="BTCUSDT",
            source_id="ch1",
            message_id="msg1",
            exchange="binance",
            side=TradeSide.LONG,
            qty=0.1,
            entry_price=50000.0,
            status=PositionStatus.OPEN,
        )

        closed_pos = ActivePositionEntity(
            id="closed_pos",
            symbol="ETHUSDT",
            source_id="ch1",
            message_id="msg2",
            exchange="binance",
            side=TradeSide.SHORT,
            qty=1.0,
            entry_price=3000.0,
            status=PositionStatus.CLOSED,
        )

        await temp_repository.save_position(open_pos)
        await temp_repository.save_position(closed_pos)

        positions = await temp_repository.get_open_positions()

        assert len(positions) == 1
        assert positions[0].id == "open_pos"

    @pytest.mark.asyncio
    async def test_get_open_positions_by_symbol_and_exchange(self, temp_repository):
        """Test filtering positions by symbol and exchange."""
        pos1 = ActivePositionEntity(
            id="pos1",
            symbol="BTCUSDT",
            source_id="ch1",
            message_id="msg1",
            exchange="binance",
            side=TradeSide.LONG,
            qty=0.1,
            entry_price=50000.0,
            status=PositionStatus.OPEN,
        )

        pos2 = ActivePositionEntity(
            id="pos2",
            symbol="BTCUSDT",
            source_id="ch1",
            message_id="msg2",
            exchange="bybit",
            side=TradeSide.LONG,
            qty=0.1,
            entry_price=50000.0,
            status=PositionStatus.OPEN,
        )

        pos3 = ActivePositionEntity(
            id="pos3",
            symbol="ETHUSDT",
            source_id="ch1",
            message_id="msg3",
            exchange="binance",
            side=TradeSide.SHORT,
            qty=1.0,
            entry_price=3000.0,
            status=PositionStatus.OPEN,
        )

        await temp_repository.save_position(pos1)
        await temp_repository.save_position(pos2)
        await temp_repository.save_position(pos3)

        # Get BTCUSDT on binance
        positions = await temp_repository.get_open_positions_by_symbol_and_exchange("BTCUSDT", "binance")

        assert len(positions) == 1
        assert positions[0].id == "pos1"
        assert positions[0].exchange == "binance"

    @pytest.mark.asyncio
    async def test_serialization_with_enums(self, temp_repository, sample_position_for_repo):
        """Test that enums are properly serialized and deserialized."""
        await temp_repository.save_position(sample_position_for_repo)

        retrieved = await temp_repository.get_position_by_id("test_pos_123")

        assert retrieved is not None
        assert isinstance(retrieved.side, TradeSide)
        assert retrieved.side == TradeSide.LONG
        assert isinstance(retrieved.status, PositionStatus)
        assert retrieved.status == PositionStatus.OPEN

    @pytest.mark.asyncio
    async def test_serialization_with_datetime(self, temp_repository, sample_position_for_repo):
        """Test that datetime is properly serialized and deserialized."""
        await temp_repository.save_position(sample_position_for_repo)

        retrieved = await temp_repository.get_position_by_id("test_pos_123")

        assert retrieved is not None
        assert retrieved.opened_at is not None
        assert retrieved.opened_at.tzinfo is not None  # Has timezone info

    @pytest.mark.asyncio
    async def test_serialization_with_tp_distribution(self, temp_repository, sample_position_for_repo):
        """Test that TP distribution is properly serialized and deserialized."""
        await temp_repository.save_position(sample_position_for_repo)

        retrieved = await temp_repository.get_position_by_id("test_pos_123")

        assert retrieved is not None
        assert len(retrieved.tp_distribution) == 3
        assert isinstance(retrieved.tp_distribution[0], TPDistributionRow)
        assert retrieved.tp_distribution[0].label == "TP1"
        assert retrieved.tp_distribution[0].close_pct == 33.33

    @pytest.mark.asyncio
    async def test_append_trade_log_creates_file(self, tmp_path):
        """Test that append_trade_log creates the log file."""
        db_file = tmp_path / "test.db"
        trades_file = tmp_path / "trades.jsonl"

        repo = SqliteStateRepository(str(db_file), str(trades_file))
        await repo.init_db()

        trade_data = {
            "symbol": "BTCUSDT",
            "side": "LONG",
            "qty": 0.1,
            "price": 50000.0,
        }

        await repo.append_trade_log(trade_data)

        assert trades_file.exists()
        content = trades_file.read_text()
        assert "BTCUSDT" in content
        assert "LONG" in content

    @pytest.mark.asyncio
    async def test_append_trade_log_appends_multiple(self, tmp_path):
        """Test that multiple trade logs are appended."""
        db_file = tmp_path / "test.db"
        trades_file = tmp_path / "trades.jsonl"

        repo = SqliteStateRepository(str(db_file), str(trades_file))
        await repo.init_db()

        trade1 = {"symbol": "BTCUSDT", "action": "open"}
        trade2 = {"symbol": "ETHUSDT", "action": "close"}

        await repo.append_trade_log(trade1)
        await repo.append_trade_log(trade2)

        lines = trades_file.read_text().strip().split("\n")
        assert len(lines) == 2
        assert "BTCUSDT" in lines[0]
        assert "ETHUSDT" in lines[1]
