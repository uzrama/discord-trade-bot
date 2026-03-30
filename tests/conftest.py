"""
Global pytest configuration and fixtures.

This module provides shared fixtures and configuration for all tests.
"""

import asyncio
from datetime import datetime, UTC
from typing import AsyncGenerator
from unittest.mock import AsyncMock, Mock

import pytest
from faker import Faker

from discord_trade_bot.core.domain.entities.position import ActivePositionEntity
from discord_trade_bot.core.domain.entities.signal import ParsedSignalEntity
from discord_trade_bot.core.domain.value_objects.trading import (
    EntryMode,
    PositionStatus,
    SignalType,
    TradeSide,
    TPDistributionRow,
)

# Initialize Faker for generating test data
fake = Faker()


# ============================================================================
# Pytest Configuration
# ============================================================================


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# ============================================================================
# Domain Entity Fixtures
# ============================================================================


@pytest.fixture
def sample_signal() -> ParsedSignalEntity:
    """Create a sample valid trading signal."""
    return ParsedSignalEntity(
        source_id="test_channel_123",
        message_id="test_message_456",
        text_hash="abc123def456",
        symbol="BTCUSDT",
        side=TradeSide.LONG,
        entry_price=50000.0,
        stop_loss=48000.0,
        take_profits=[51000.0, 52000.0, 53000.0],
        leverage=20,
        entry_mode=EntryMode.MARKET,
        signal_type=SignalType.PRIMARY_SIGNAL,
        is_signal=True,
    )


@pytest.fixture
def sample_short_signal() -> ParsedSignalEntity:
    """Create a sample SHORT trading signal."""
    return ParsedSignalEntity(
        source_id="test_channel_123",
        message_id="test_message_789",
        text_hash="xyz789abc123",
        symbol="ETHUSDT",
        side=TradeSide.SHORT,
        entry_price=3000.0,
        stop_loss=3100.0,
        take_profits=[2950.0, 2900.0, 2850.0],
        leverage=10,
        entry_mode=EntryMode.MARKET,
        signal_type=SignalType.PRIMARY_SIGNAL,
        is_signal=True,
    )


@pytest.fixture
def sample_position() -> ActivePositionEntity:
    """Create a sample active position."""
    return ActivePositionEntity(
        symbol="BTCUSDT",
        source_id="test_channel_123",
        message_id="test_message_456",
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
        tp_order_ids={"order_1": 51000.0, "order_2": 52000.0, "order_3": 53000.0},
        sl_order_id="sl_order_1",
        status=PositionStatus.OPEN,
        order_id="entry_order_1",
    )


# ============================================================================
# Mock Fixtures
# ============================================================================


@pytest.fixture
def mock_exchange():
    """Create a mock exchange adapter."""
    exchange = AsyncMock()
    exchange.name = "binance"
    exchange.get_last_price = AsyncMock(return_value=50000.0)
    exchange.get_balance = AsyncMock(return_value=1000.0)
    exchange.place_market_order = AsyncMock(return_value={"orderId": "12345", "status": "FILLED"})
    exchange.place_limit_order = AsyncMock(return_value={"orderId": "12346", "status": "NEW"})
    exchange.place_stop_market_order = AsyncMock(return_value={"orderId": "12347", "status": "NEW"})
    exchange.set_leverage = AsyncMock(return_value={"leverage": 20})
    exchange.get_symbol_info = AsyncMock(
        return_value={
            "qty_precision": 3,
            "price_precision": 2,
            "min_qty": 0.001,
        }
    )
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
    exchange.cancel_order = AsyncMock(return_value={"orderId": "12345", "status": "CANCELED"})
    exchange.get_position = AsyncMock(return_value={"positionAmt": "0.1", "entryPrice": "50000"})
    exchange.cancel_all_orders = AsyncMock(return_value=[])
    exchange.close = AsyncMock()
    return exchange


@pytest.fixture
def mock_exchange_registry(mock_exchange):
    """Create a mock exchange registry."""
    registry = Mock()
    registry.get_exchange = Mock(return_value=mock_exchange)
    return registry


@pytest.fixture
def mock_repository():
    """Create a mock state repository."""
    repo = AsyncMock()
    repo.save_position = AsyncMock()
    repo.get_position_by_id = AsyncMock(return_value=None)
    repo.get_open_positions = AsyncMock(return_value=[])
    repo.get_open_positions_by_symbol_and_exchange = AsyncMock(return_value=[])
    repo.update_position = AsyncMock()
    repo.close_position = AsyncMock()
    return repo


@pytest.fixture
def mock_notification_gateway():
    """Create a mock notification gateway."""
    gateway = AsyncMock()
    gateway.send_message = AsyncMock()
    return gateway


# ============================================================================
# Configuration Fixtures
# ============================================================================


@pytest.fixture
def test_config():
    """Create a test configuration object."""
    from discord_trade_bot.main.config.yaml.general import AppMode, GeneralYamlConfig
    from discord_trade_bot.main.config.yaml.exchange import ExchangeYamlConfig

    return {
        "general": GeneralYamlConfig(mode=AppMode.TESTNET),
        "exchanges": {
            "binance": ExchangeYamlConfig(timeout_seconds=15, testnet=True),
            "bybit": ExchangeYamlConfig(timeout_seconds=15, testnet=True),
        },
    }


@pytest.fixture
def mock_app_config():
    """Create a mock AppConfig for testing."""
    from unittest.mock import Mock
    from discord_trade_bot.main.config.yaml.discord import Source, DiscordYamlConfig
    from discord_trade_bot.main.config.yaml.fee import FeesConfig

    # Create mock source config
    mock_source = Source(
        source_id="test_channel_123",
        channel_id=123456789,
        exchange="binance",
        fixed_leverage=20,
        default_sl_percent=2.0,
        move_to_breakeven_on_tp1=True,
    )

    # Create mock discord config
    mock_discord = DiscordYamlConfig(watch_sources=[mock_source])

    # Create mock fees config
    mock_fees = FeesConfig(
        maker=0.0002,
        taker=0.00055,
        break_even_fee_mode="taker",
        break_even_extra_buffer=0.0,
    )

    # Create mock yaml config
    mock_yaml = Mock()
    mock_yaml.discord = mock_discord

    # Create mock app config
    mock_config = Mock()
    mock_config.yaml = mock_yaml
    mock_config.fees = mock_fees

    return mock_config


# ============================================================================
# Test Data Fixtures
# ============================================================================


@pytest.fixture
def valid_signal_texts():
    """Provide various valid signal text formats."""
    return [
        """
        🔥 BTCUSDT LONG
        Entry: 50000
        Stop Loss: 48000
        TP1: 51000
        TP2: 52000
        TP3: 53000
        Leverage: 20x
        """,
        """
        SHORT ETHUSDT
        Entry Price: 3000
        SL: 3100
        Target 1: 2950
        Target 2: 2900
        Target 3: 2850
        """,
        """
        #SOLUSDT
        Direction: LONG
        Entry Zone: 100-102
        Stop: 95
        Targets: 105, 110, 115
        """,
    ]


@pytest.fixture
def invalid_signal_texts():
    """Provide various invalid signal text formats."""
    return [
        "Just a random message",
        "BTCUSDT without direction",
        "LONG without symbol",
        "",
        "   ",
    ]


# ============================================================================
# Time Fixtures
# ============================================================================


@pytest.fixture
def fixed_datetime():
    """Provide a fixed datetime for testing."""
    return datetime(2026, 3, 25, 12, 0, 0, tzinfo=UTC)


# ============================================================================
# Async Fixtures
# ============================================================================


@pytest.fixture
async def async_mock_exchange() -> AsyncGenerator:
    """Create an async mock exchange that can be used in async tests."""
    exchange = AsyncMock()
    exchange.name = "binance"
    exchange.get_last_price = AsyncMock(return_value=50000.0)
    exchange.get_balance = AsyncMock(return_value=1000.0)
    yield exchange
    await exchange.close()
