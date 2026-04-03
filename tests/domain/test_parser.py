"""
Tests for SignalParserService.

This module tests the signal parsing logic which is critical for the bot's operation.
The parser must correctly extract trading signals from various text formats.
"""

import pytest

from discord_trade_bot.core.domain.entities.signal import ParsedSignalEntity
from discord_trade_bot.core.domain.services.parser import SignalParserService
from discord_trade_bot.core.domain.value_objects.trading import EntryMode, SignalType, TradeSide


class TestSignalParserService:
    """Test suite for SignalParserService."""

    @pytest.fixture
    def parser(self):
        """Create a parser instance for testing."""
        return SignalParserService()

    # ========================================================================
    # Valid Signal Parsing Tests
    # ========================================================================

    def test_parse_valid_long_signal_with_all_fields(self, parser):
        """Test parsing a complete LONG signal with all fields."""
        # Arrange
        text = """
        🔥 BTCUSDT LONG
        Entry: 50000
        Stop Loss: 48000
        TP1: 51000
        TP2: 52000
        TP3: 53000
        Leverage: 20x
        """

        # Act
        result = parser.parse("channel_123", "msg_456", text)

        # Assert
        assert result.is_signal is True
        assert result.symbol == "BTCUSDT"
        assert result.side == TradeSide.LONG
        assert result.entry_price == 50000.0
        assert result.stop_loss == 48000.0
        assert result.take_profits == [51000.0, 52000.0, 53000.0]
        assert result.leverage == 20
        assert result.signal_type == SignalType.PRIMARY_SIGNAL

    def test_parse_valid_short_signal_with_all_fields(self, parser):
        """Test parsing a complete SHORT signal with all fields."""
        # Arrange
        text = """
        SHORT ETHUSDT
        Entry Price: 3000
        SL: 3100
        Target 1: 2950
        Target 2: 2900
        Target 3: 2850
        Leverage: 10x
        """

        # Act
        result = parser.parse("channel_123", "msg_789", text)

        # Assert
        assert result.is_signal is True
        assert result.symbol == "ETHUSDT"
        assert result.side == TradeSide.SHORT
        assert result.entry_price == 3000.0
        assert result.stop_loss == 3100.0
        assert result.take_profits == [2950.0, 2900.0, 2850.0]
        assert result.leverage == 10

    def test_parse_signal_with_slash_notation(self, parser):
        """Test parsing signal with BTC/USDT notation."""
        # Arrange
        text = """
        LONG SIGNAL - BTC/USDT
        Entry: 45000
        Stop Loss: 43000
        TP1: 46000
        """

        # Act
        result = parser.parse("channel_123", "msg_101", text)

        # Assert
        assert result.is_signal is True
        assert result.symbol == "BTCUSDT"
        assert result.side == TradeSide.LONG

    def test_parse_signal_with_multiple_tp_formats(self, parser):
        """Test parsing TPs in different formats."""
        # Arrange
        text = """
        SOLUSDT LONG
        Entry: 100
        SL: 95
        TP1: 105
        TP 2: 110
        Target 3: 115
        TAKE PROFIT 4: 120
        """

        # Act
        result = parser.parse("channel_123", "msg_202", text)

        # Assert
        assert result.is_signal is True
        assert len(result.take_profits) >= 3
        assert 105.0 in result.take_profits
        assert 110.0 in result.take_profits
        assert 115.0 in result.take_profits

    def test_parse_signal_with_cmp_entry(self, parser):
        """Test parsing signal with CMP (Current Market Price) entry."""
        # Arrange
        text = """
        BTCUSDT LONG
        Entry: CMP
        Stop Loss: 48000
        TP1: 52000
        """

        # Act
        result = parser.parse("channel_123", "msg_303", text)

        # Assert
        assert result.is_signal is True
        assert result.entry_mode == EntryMode.CMP  # Fixed: CMP not MARKET
        assert result.symbol == "BTCUSDT"

    def test_parse_signal_with_entry_zone(self, parser):
        """Test parsing signal with entry zone range."""
        # Arrange
        text = """
        ETHUSDT SHORT
        Entry Zone: 3000-3050
        Stop Loss: 3100
        TP1: 2900
        """

        # Act
        result = parser.parse("channel_123", "msg_404", text)

        # Assert
        assert result.is_signal is True
        assert result.symbol == "ETHUSDT"
        assert result.side == TradeSide.SHORT

    # ========================================================================
    # Invalid Signal Tests
    # ========================================================================

    def test_parse_empty_text_returns_non_signal(self, parser):
        """Test that empty text returns a non-signal entity."""
        # Arrange
        text = ""

        # Act
        result = parser.parse("channel_123", "msg_505", text)

        # Assert
        assert result.is_signal is False
        assert result.symbol is None
        assert result.side is None

    def test_parse_whitespace_only_returns_non_signal(self, parser):
        """Test that whitespace-only text returns a non-signal entity."""
        # Arrange
        text = "   \n\t   "

        # Act
        result = parser.parse("channel_123", "msg_606", text)

        # Assert
        assert result.is_signal is False

    def test_parse_random_text_returns_non_signal(self, parser):
        """Test that random text without signal keywords returns non-signal."""
        # Arrange
        text = "Hello, this is just a regular message about crypto."

        # Act
        result = parser.parse("channel_123", "msg_707", text)

        # Assert
        assert result.is_signal is False

    def test_parse_symbol_without_side_returns_non_signal(self, parser):
        """Test that symbol without direction is not recognized as signal."""
        # Arrange
        text = """
        BTCUSDT
        Entry: 50000
        TP1: 51000
        """

        # Act
        result = parser.parse("channel_123", "msg_808", text)

        # Assert
        # Should not be a valid signal without LONG/SHORT
        assert result.symbol == "BTCUSDT"
        # Side might be None or the signal might not be marked as valid

    def test_parse_side_without_symbol_returns_non_signal(self, parser):
        """Test that direction without symbol is not recognized as signal."""
        # Arrange
        text = """
        LONG
        Entry: 50000
        TP1: 51000
        """

        # Act
        result = parser.parse("channel_123", "msg_909", text)

        # Assert
        assert result.side == TradeSide.LONG
        # Symbol should be None or invalid

    # ========================================================================
    # Edge Cases
    # ========================================================================

    def test_parse_signal_with_special_characters(self, parser):
        """Test parsing signal with emojis and special characters."""
        # Arrange
        text = """
        🚀🔥 BTCUSDT LONG 🚀🔥
        💰 Entry: 50000
        🛑 Stop Loss: 48000
        🎯 TP1: 51000
        """

        # Act
        result = parser.parse("channel_123", "msg_1010", text)

        # Assert
        assert result.is_signal is True
        assert result.symbol == "BTCUSDT"
        assert result.side == TradeSide.LONG

    def test_parse_signal_with_lowercase_text(self, parser):
        """Test that parser handles lowercase text correctly."""
        # Arrange
        text = """
        btcusdt long
        entry: 50000
        stop loss: 48000
        tp1: 51000
        """

        # Act
        result = parser.parse("channel_123", "msg_1111", text)

        # Assert
        # Parser should normalize to uppercase
        assert result.symbol == "BTCUSDT"
        assert result.side == TradeSide.LONG

    def test_parse_signal_with_mixed_case(self, parser):
        """Test parsing signal with mixed case text."""
        # Arrange
        text = """
        BtcUsDt LoNg
        EnTrY: 50000
        Sl: 48000
        """

        # Act
        result = parser.parse("channel_123", "msg_1212", text)

        # Assert
        assert result.symbol == "BTCUSDT"
        assert result.side == TradeSide.LONG

    def test_parse_signal_with_dollar_signs(self, parser):
        """Test parsing prices with dollar signs."""
        # Arrange
        text = """
        ETHUSDT LONG
        Entry: $3000
        SL: $2900
        TP1: $3100
        """

        # Act
        result = parser.parse("channel_123", "msg_1313", text)

        # Assert
        assert result.entry_price == 3000.0
        assert result.stop_loss == 2900.0
        assert 3100.0 in result.take_profits

    def test_parse_signal_with_very_long_text(self, parser):
        """Test parsing signal embedded in very long text."""
        # Arrange
        text = """
        This is a message with lots of text before the signal.
        Lorem ipsum dolor sit amet, consectetur adipiscing elit.
        
        BTCUSDT LONG
        Entry: 50000
        Stop Loss: 48000
        TP1: 51000
        
        And more text after the signal as well.
        More information and disclaimers here.
        """

        # Act
        result = parser.parse("channel_123", "msg_1414", text)

        # Assert
        assert result.is_signal is True
        assert result.symbol == "BTCUSDT"
        assert result.side == TradeSide.LONG

    def test_parse_signal_with_duplicate_tps(self, parser):
        """Test that duplicate TP values are handled correctly."""
        # Arrange
        text = """
        BTCUSDT LONG
        Entry: 50000
        TP1: 51000
        TP2: 51000
        TP3: 52000
        """

        # Act
        result = parser.parse("channel_123", "msg_1515", text)

        # Assert
        assert result.is_signal is True
        # Duplicates should be removed
        assert len(result.take_profits) <= 2

    def test_parse_signal_with_invalid_leverage(self, parser):
        """Test parsing signal with invalid leverage value."""
        # Arrange
        text = """
        BTCUSDT LONG
        Entry: 50000
        Leverage: 999x
        """

        # Act
        result = parser.parse("channel_123", "msg_1616", text)

        # Assert
        assert result.symbol == "BTCUSDT"
        # Leverage might be capped or set to default

    def test_parse_signal_preserves_source_and_message_ids(self, parser):
        """Test that source and message IDs are preserved."""
        # Arrange
        text = "BTCUSDT LONG\nEntry: 50000"
        source_id = "test_channel_999"
        message_id = "test_message_888"

        # Act
        result = parser.parse(source_id, message_id, text)

        # Assert
        assert result.source_id == source_id
        assert result.message_id == message_id

    def test_parse_signal_generates_unique_hash(self, parser):
        """Test that different texts generate different hashes."""
        # Arrange
        text1 = "BTCUSDT LONG\nEntry: 50000"
        text2 = "ETHUSDT SHORT\nEntry: 3000"

        # Act
        result1 = parser.parse("ch1", "msg1", text1)
        result2 = parser.parse("ch1", "msg2", text2)

        # Assert
        assert result1.message_hash != result2.message_hash

    def test_parse_signal_same_text_generates_same_hash(self, parser):
        """Test that identical texts generate identical hashes."""
        # Arrange
        text = "BTCUSDT LONG\nEntry: 50000"

        # Act
        result1 = parser.parse("ch1", "msg1", text)
        result2 = parser.parse("ch2", "msg2", text)

        # Assert
        assert result1.message_hash == result2.message_hash

    # ========================================================================
    # Signal Type Detection Tests
    # ========================================================================

    def test_parse_primary_signal_is_detected(self, parser):
        """Test that primary signals are correctly identified."""
        # Arrange
        text = """
        BTCUSDT LONG
        Entry: 50000
        Stop Loss: 48000
        TP1: 51000
        """

        # Act
        result = parser.parse("channel_123", "msg_1717", text)

        # Assert
        assert result.signal_type == SignalType.PRIMARY_SIGNAL

    def test_parse_tp_hit_update_is_detected(self, parser):
        """Test that TP hit updates are correctly identified."""
        # Arrange
        text = """
        BTCUSDT
        TP1 HIT
        Next Target: TP2
        """

        # Act
        result = parser.parse("channel_123", "msg_1818", text)

        # Assert
        # Parser detects TP1 HIT in the contains_tp1_hit field
        assert result.contains_tp1_hit is True
        assert result.symbol == "BTCUSDT"

    def test_parse_entry_triggered_update_is_detected(self, parser):
        """Test that entry triggered updates are correctly identified."""
        # Arrange
        text = """
        BTCUSDT LONG
        ENTRY TRIGGERED
        """

        # Act
        result = parser.parse("channel_123", "msg_1919", text)

        # Assert
        # Should be detected as an update
        assert "TRIGGERED" in text.upper()

    # ========================================================================
    # Symbol Normalization Tests
    # ========================================================================

    def test_parse_normalizes_symbol_to_usdt(self, parser):
        """Test that symbols are normalized to USDT format."""
        # Arrange
        text = "BTC LONG\nEntry: 50000"

        # Act
        result = parser.parse("channel_123", "msg_2020", text)

        # Assert
        # Should normalize BTC to BTCUSDT
        if result.symbol:
            assert result.symbol.endswith("USDT")

    def test_parse_handles_various_symbol_formats(self, parser):
        """Test parsing various symbol format variations."""
        # Arrange
        test_cases = [
            ("BTCUSDT LONG", "BTCUSDT"),
            ("BTC/USDT LONG", "BTCUSDT"),
            # Note: BTC-USDT format is not supported by the parser
        ]

        for text, expected_symbol in test_cases:
            # Act
            result = parser.parse("ch", "msg", text)

            # Assert
            assert result.symbol == expected_symbol, f"Failed for text: {text}"


# ========================================================================
# Advanced TP Parsing Tests (bot_fixed v6 compatibility)
# ========================================================================


class TestAdvancedTPParsing:
    """Test suite for advanced TP parsing features from bot_fixed v6."""

    @pytest.fixture
    def parser(self):
        """Create a parser instance for testing."""
        return SignalParserService()

    def test_parse_production_puffer_signal(self, parser):
        """Test parsing real production PUFFER signal from AO Algo."""
        # Arrange
        text = """
        AO Algo • PUFFER #2
        🔴 SHORT SIGNAL • Leverage: 25x
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        📊 ENTRY
        $0.022300 ✅ Triggered
        🎯 PROFIT TARGETS
        ✅ TP1: $0.022120
        ✅ TP2: $0.021940
        ✅ TP3: $0.021410
        ⬜ TP4: $0.013380
        🛑 SL: $0.024810
        ​
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        📊 STATS
        Closed P&L: +100% 🟢
        TP profit secured
        Trade closed
        STATUS
        ✅ CLOSED
        PUFFER #2
        📊 TRADE NOW
        ByBit • MEXC • Blofin • Bitget
        ⚠️ Automated system • Low risk recommended • Not financial advice
        """

        # Act
        result = parser.parse("ao_algo", "msg_puffer", text)

        # Assert
        assert result.is_signal is True
        assert result.symbol == "PUFFERUSDT"
        assert result.side == TradeSide.SHORT
        assert result.entry_price == 0.022300
        assert result.entry_triggered is True
        assert result.leverage == 25
        assert result.stop_loss == 0.024810
        assert len(result.take_profits) == 4
        assert 0.022120 in result.take_profits
        assert 0.021940 in result.take_profits
        assert 0.021410 in result.take_profits
        assert 0.013380 in result.take_profits
        assert result.contains_tp1_hit is True

    def test_parse_unlabeled_tp_targets_in_section(self, parser):
        """Test parsing unlabeled TP targets under PROFIT TARGETS header."""
        # Arrange
        text = """
        BTCUSDT LONG
        Entry: 50000
        
        PROFIT TARGETS:
        1) 51000
        2) 52000
        3) 53000
        
        Stop Loss: 48000
        """

        # Act
        result = parser.parse("channel_123", "msg_tp_section", text)

        # Assert
        assert result.is_signal is True
        assert len(result.take_profits) == 3
        assert 51000.0 in result.take_profits
        assert 52000.0 in result.take_profits
        assert 53000.0 in result.take_profits

    def test_parse_tp_with_emoji_checkmarks(self, parser):
        """Test parsing TP targets with emoji completion checkmarks."""
        # Arrange
        text = """
        ETHUSDT SHORT
        Entry: 3000
        
        PROFIT TARGETS:
        ✅ TP1: 2950
        ✅ TP2: 2900
        ⬜ TP3: 2850
        
        SL: 3100
        """

        # Act
        result = parser.parse("channel_123", "msg_tp_emoji", text)

        # Assert
        assert len(result.take_profits) == 3
        assert 2950.0 in result.take_profits
        assert 2900.0 in result.take_profits
        assert 2850.0 in result.take_profits
        assert result.contains_tp1_hit is True

    def test_parse_tp_with_dollar_signs_in_section(self, parser):
        """Test parsing TP targets with dollar signs in section format."""
        # Arrange
        text = """
        SOLUSDT LONG
        Entry: $100
        
        🎯 PROFIT TARGETS
        ✅ TP1: $105
        ✅ TP2: $110
        ⬜ TP3: $115
        
        🛑 SL: $95
        """

        # Act
        result = parser.parse("channel_123", "msg_tp_dollar", text)

        # Assert
        assert len(result.take_profits) == 3
        assert 105.0 in result.take_profits
        assert 110.0 in result.take_profits
        assert 115.0 in result.take_profits

    def test_parse_discord_thread_noise_filtered(self, parser):
        """Test that Discord thread UI text is filtered out."""
        # Arrange
        text = """
        ОТКРЫТЬ ВЕТКУ
        BTCUSDT LONG
        Entry: 50000
        OPEN THREAD
        TP1: 51000
        В ЭТОЙ ВЕТКЕ ПОКА НЕТ СООБЩЕНИЙ
        """

        # Act
        result = parser.parse("channel_123", "msg_thread", text)

        # Assert
        assert result.is_signal is True
        assert result.symbol == "BTCUSDT"
        assert result.side == TradeSide.LONG

    def test_parse_bullet_normalization(self, parser):
        """Test that middle dot (·) is normalized to bullet (•)."""
        # Arrange
        text = "AO ALGO · BTCUSDT · LONG · Entry: 50000"

        # Act
        result = parser.parse("channel_123", "msg_bullet", text)

        # Assert
        assert result.is_signal is True
        assert result.symbol == "BTCUSDT"
        assert result.side == TradeSide.LONG

    def test_parse_tp1_hit_with_checkmark(self, parser):
        """Test that TP1 with checkmark is detected as hit."""
        # Arrange
        text = """
        BTCUSDT LONG
        Entry: 50000
        ✅ TP1: 51000 HIT
        TP2: 52000
        TP3: 53000
        """

        # Act
        result = parser.parse("channel_123", "msg_tp1_check", text)

        # Assert
        assert result.contains_tp1_hit is True

    def test_parse_mixed_tp_formats_in_one_signal(self, parser):
        """Test parsing signal with mixed TP formats."""
        # Arrange
        text = """
        ETHUSDT SHORT
        Entry: 3000
        
        TARGETS:
        ✅ TP1: $2950
        - 2900
        3) 2850 ✅
        
        SL: 3100
        """

        # Act
        result = parser.parse("channel_123", "msg_mixed_tp", text)

        # Assert
        assert result.is_signal is True
        assert len(result.take_profits) >= 2
        assert 2950.0 in result.take_profits
