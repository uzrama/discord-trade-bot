"""Tests for core.shared.utils.parsing module."""

import pytest

from discord_trade_bot.core.shared.utils.parsing import safe_float


class TestSafeFloat:
    """Test safe_float function."""

    def test_none_returns_none(self):
        """Test that None input returns None."""
        assert safe_float(None) is None

    def test_int_converts_to_float(self):
        """Test that integer converts to float."""
        assert safe_float(123) == 123.0
        assert safe_float(0) == 0.0
        assert safe_float(-456) == -456.0

    def test_float_returns_float(self):
        """Test that float returns as is."""
        assert safe_float(123.45) == 123.45
        assert safe_float(0.0) == 0.0
        assert safe_float(-67.89) == -67.89

    def test_string_number_converts(self):
        """Test that string numbers convert correctly."""
        assert safe_float("123.45") == 123.45
        assert safe_float("0") == 0.0
        assert safe_float("-67.89") == -67.89

    def test_string_with_comma_separator(self):
        """Test that comma separators are handled."""
        assert safe_float("1,234.56") == 1234.56
        assert safe_float("1,000,000") == 1000000.0
        assert safe_float("12,34") == 1234.0

    def test_string_with_dollar_sign(self):
        """Test that dollar signs are removed."""
        assert safe_float("$123.45") == 123.45
        assert safe_float("$1,234.56") == 1234.56

    def test_string_with_usdt_suffix(self):
        """Test that USDT suffix is removed."""
        assert safe_float("100 USDT") == 100.0
        assert safe_float("123.45USDT") == 123.45
        assert safe_float("1,234.56 USDT") == 1234.56

    def test_string_with_whitespace(self):
        """Test that whitespace is handled."""
        assert safe_float("  123.45  ") == 123.45
        assert safe_float("\t100\n") == 100.0

    def test_combined_formatting(self):
        """Test strings with multiple formatting elements."""
        assert safe_float("$1,234.56 USDT") == 1234.56
        assert safe_float("  $100 USDT  ") == 100.0

    def test_invalid_string_returns_none(self):
        """Test that invalid strings return None."""
        assert safe_float("invalid") is None
        assert safe_float("abc123") is None
        assert safe_float("") is None
        assert safe_float("   ") is None

    def test_special_float_values(self):
        """Test special float values."""
        assert safe_float("inf") == float("inf")
        assert safe_float("-inf") == float("-inf")
        # NaN is special - it's not equal to itself
        result = safe_float("nan")
        assert result is not None and result != result  # NaN check

    def test_scientific_notation(self):
        """Test scientific notation strings."""
        assert safe_float("1e3") == 1000.0
        assert safe_float("1.23e-4") == 0.000123
        assert safe_float("5E2") == 500.0

    def test_edge_cases(self):
        """Test edge cases."""
        assert safe_float(0.0) == 0.0
        assert safe_float("0.0") == 0.0
        assert safe_float("-0") == 0.0
        assert safe_float("+123") == 123.0
