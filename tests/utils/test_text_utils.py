"""Tests for core.shared.utils.text module."""

import pytest

from discord_trade_bot.core.shared.utils.text import normalize_symbol, sha1_text


class TestSha1Text:
    """Test sha1_text function."""

    def test_simple_string(self):
        """Test hashing a simple string."""
        result = sha1_text("hello")
        assert isinstance(result, str)
        assert len(result) == 40  # SHA1 produces 40 hex characters
        assert result == "aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d"

    def test_empty_string(self):
        """Test hashing an empty string."""
        result = sha1_text("")
        assert isinstance(result, str)
        assert len(result) == 40
        assert result == "da39a3ee5e6b4b0d3255bfef95601890afd80709"

    def test_unicode_string(self):
        """Test hashing unicode characters."""
        result = sha1_text("привет")
        assert isinstance(result, str)
        assert len(result) == 40

    def test_special_characters(self):
        """Test hashing strings with special characters."""
        result = sha1_text("!@#$%^&*()")
        assert isinstance(result, str)
        assert len(result) == 40

    def test_multiline_string(self):
        """Test hashing multiline strings."""
        result = sha1_text("line1\nline2\nline3")
        assert isinstance(result, str)
        assert len(result) == 40

    def test_deterministic(self):
        """Test that same input produces same hash."""
        text = "test string"
        hash1 = sha1_text(text)
        hash2 = sha1_text(text)
        assert hash1 == hash2

    def test_different_inputs_different_hashes(self):
        """Test that different inputs produce different hashes."""
        hash1 = sha1_text("test1")
        hash2 = sha1_text("test2")
        assert hash1 != hash2


class TestNormalizeSymbol:
    """Test normalize_symbol function."""

    def test_simple_symbol(self):
        """Test normalizing a simple symbol."""
        assert normalize_symbol("BTC") == "BTCUSDT"
        assert normalize_symbol("ETH") == "ETHUSDT"
        assert normalize_symbol("SOL") == "SOLUSDT"

    def test_lowercase_symbol(self):
        """Test that lowercase is converted to uppercase."""
        assert normalize_symbol("btc") == "BTCUSDT"
        assert normalize_symbol("eth") == "ETHUSDT"

    def test_mixed_case_symbol(self):
        """Test mixed case conversion."""
        assert normalize_symbol("BtC") == "BTCUSDT"
        assert normalize_symbol("EtH") == "ETHUSDT"

    def test_symbol_with_slash(self):
        """Test symbol with slash separator."""
        assert normalize_symbol("BTC/USDT") == "BTCUSDT"
        assert normalize_symbol("btc/usdt") == "BTCUSDT"
        assert normalize_symbol("ETH/USDT") == "ETHUSDT"

    def test_symbol_with_dash(self):
        """Test symbol with dash separator."""
        assert normalize_symbol("BTC-USDT") == "BTCUSDT"
        assert normalize_symbol("ETH-USDT") == "ETHUSDT"

    def test_symbol_already_normalized(self):
        """Test symbol that's already normalized."""
        assert normalize_symbol("BTCUSDT") == "BTCUSDT"
        assert normalize_symbol("ETHUSDT") == "ETHUSDT"

    def test_symbol_with_spaces(self):
        """Test symbol with spaces."""
        assert normalize_symbol("BTC USDT") == "BTCUSDT"
        assert normalize_symbol("  BTC  USDT  ") == "BTCUSDT"

    def test_symbol_with_multiple_separators(self):
        """Test symbol with multiple special characters."""
        assert normalize_symbol("BTC/USDT-PERP") == "BTCUSDTPERPUSDT"  # PERP doesn't end with USDT, so suffix is added
        assert normalize_symbol("BTC_USDT") == "BTCUSDT"

    def test_custom_suffix(self):
        """Test with custom suffix."""
        assert normalize_symbol("BTC", suffix="BUSD") == "BTCBUSD"
        assert normalize_symbol("ETH", suffix="EUR") == "ETHEUR"

    def test_symbol_already_has_custom_suffix(self):
        """Test symbol that already has the custom suffix."""
        assert normalize_symbol("BTCBUSD", suffix="BUSD") == "BTCBUSD"
        assert normalize_symbol("ETHEUR", suffix="EUR") == "ETHEUR"

    def test_empty_string(self):
        """Test empty string input."""
        assert normalize_symbol("") == ""
        assert normalize_symbol("   ") == ""

    def test_none_input(self):
        """Test None input."""
        assert normalize_symbol(None) == ""

    def test_numeric_symbols(self):
        """Test symbols with numbers."""
        assert normalize_symbol("1INCH") == "1INCHUSDT"
        assert normalize_symbol("1000SATS") == "1000SATSUSDT"

    def test_special_characters_removed(self):
        """Test that all special characters are removed."""
        assert normalize_symbol("BTC@#$%USDT") == "BTCUSDT"
        assert normalize_symbol("BTC!!!") == "BTCUSDT"

    def test_suffix_not_duplicated(self):
        """Test that suffix is not duplicated if already present."""
        assert normalize_symbol("BTCUSDT") == "BTCUSDT"
        assert normalize_symbol("BTCUSDT", suffix="USDT") == "BTCUSDT"
        # But if different suffix, it should be added
        assert normalize_symbol("BTC", suffix="BUSD") == "BTCBUSD"
