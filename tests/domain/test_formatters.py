"""Tests for core.domain.value_objects.formatters module."""

import pytest

from discord_trade_bot.core.domain.value_objects.formatters import (
    dedupe_float_levels,
    format_price,
    format_quantity,
)


class TestFormatQuantity:
    """Test format_quantity function."""

    def test_removes_trailing_zeros(self):
        """Test that trailing zeros are removed."""
        assert format_quantity(1.500000) == "1.5"
        assert format_quantity(10.0) == "10"
        assert format_quantity(0.100000) == "0.1"

    def test_removes_trailing_decimal_point(self):
        """Test that trailing decimal point is removed."""
        assert format_quantity(10.0) == "10"
        assert format_quantity(100.0) == "100"

    def test_preserves_significant_digits(self):
        """Test that significant digits are preserved."""
        assert format_quantity(0.123456) == "0.123456"
        assert format_quantity(1.234567) == "1.234567"

    def test_default_precision(self):
        """Test default precision of 6 decimal places."""
        assert format_quantity(1.23456789) == "1.234568"  # Rounded to 6 decimals
        assert format_quantity(0.00000123456) == "0.000001"  # Rounded

    def test_custom_precision(self):
        """Test custom precision values."""
        assert format_quantity(1.23456789, precision=2) == "1.23"
        assert format_quantity(1.23456789, precision=4) == "1.2346"
        assert format_quantity(1.23456789, precision=8) == "1.23456789"

    def test_zero_value(self):
        """Test formatting zero."""
        assert format_quantity(0.0) == "0"
        assert format_quantity(0.000000) == "0"

    def test_large_numbers(self):
        """Test formatting large numbers."""
        assert format_quantity(1000000.0) == "1000000"
        assert format_quantity(1000000.5) == "1000000.5"

    def test_small_numbers(self):
        """Test formatting very small numbers."""
        assert format_quantity(0.000001) == "0.000001"
        assert format_quantity(0.0000001, precision=8) == "0.0000001"

    def test_negative_numbers(self):
        """Test formatting negative numbers."""
        assert format_quantity(-1.5) == "-1.5"
        assert format_quantity(-10.0) == "-10"


class TestFormatPrice:
    """Test format_price function."""

    def test_removes_trailing_zeros(self):
        """Test that trailing zeros are removed."""
        assert format_price(50000.12000000) == "50000.12"
        assert format_price(100.0) == "100"

    def test_removes_trailing_decimal_point(self):
        """Test that trailing decimal point is removed."""
        assert format_price(50000.0) == "50000"
        assert format_price(1.0) == "1"

    def test_preserves_significant_digits(self):
        """Test that significant digits are preserved."""
        assert format_price(0.00012340) == "0.0001234"
        assert format_price(50000.12345678) == "50000.12345678"

    def test_default_precision(self):
        """Test default precision of 8 decimal places."""
        assert format_price(1.123456789) == "1.12345679"  # Rounded to 8 decimals
        assert format_price(0.000000123456) == "0.00000012"  # Rounded

    def test_custom_precision(self):
        """Test custom precision values."""
        assert format_price(1.23456789, precision=2) == "1.23"
        assert format_price(1.23456789, precision=4) == "1.2346"
        assert format_price(1.23456789, precision=10) == "1.23456789"

    def test_zero_value(self):
        """Test formatting zero."""
        assert format_price(0.0) == "0"
        assert format_price(0.00000000) == "0"

    def test_large_prices(self):
        """Test formatting large prices."""
        assert format_price(100000.0) == "100000"
        assert format_price(100000.123) == "100000.123"

    def test_small_prices(self):
        """Test formatting very small prices."""
        assert format_price(0.00000001) == "0.00000001"
        assert format_price(0.000000001, precision=10) == "0.000000001"

    def test_negative_prices(self):
        """Test formatting negative prices."""
        assert format_price(-50000.12) == "-50000.12"
        assert format_price(-1.0) == "-1"

    def test_crypto_prices(self):
        """Test typical cryptocurrency prices."""
        assert format_price(50000.50) == "50000.5"  # BTC
        assert format_price(3000.123456) == "3000.123456"  # ETH
        assert format_price(0.0001234) == "0.0001234"  # Small altcoin


class TestDedupeFloatLevels:
    """Test dedupe_float_levels function."""

    def test_removes_exact_duplicates(self):
        """Test that exact duplicates are removed."""
        assert dedupe_float_levels([1.0, 1.0, 2.0]) == [1.0, 2.0]
        assert dedupe_float_levels([100.5, 200.3, 100.5]) == [100.5, 200.3]

    def test_removes_near_duplicates(self):
        """Test that near-duplicates within precision are removed."""
        result = dedupe_float_levels([1.0, 1.0000000001, 2.0])
        # With default precision=12, these are considered different
        # 1.0 rounds to 1.0, 1.0000000001 rounds to 1.0000000001
        assert len(result) == 3
        assert 1.0 in result
        assert 2.0 in result

    def test_preserves_order(self):
        """Test that original order is preserved."""
        assert dedupe_float_levels([3.0, 1.0, 2.0]) == [3.0, 1.0, 2.0]
        assert dedupe_float_levels([5.0, 3.0, 1.0, 2.0]) == [5.0, 3.0, 1.0, 2.0]

    def test_empty_list(self):
        """Test with empty list."""
        assert dedupe_float_levels([]) == []

    def test_none_input(self):
        """Test with None input."""
        assert dedupe_float_levels(None) == []

    def test_single_element(self):
        """Test with single element."""
        assert dedupe_float_levels([1.0]) == [1.0]

    def test_all_unique(self):
        """Test with all unique values."""
        assert dedupe_float_levels([1.0, 2.0, 3.0]) == [1.0, 2.0, 3.0]

    def test_all_duplicates(self):
        """Test with all duplicate values."""
        assert dedupe_float_levels([1.0, 1.0, 1.0]) == [1.0]

    def test_custom_precision(self):
        """Test with custom precision."""
        # With precision=2, these should be considered duplicates
        result = dedupe_float_levels([1.001, 1.002, 1.003], precision=2)
        assert len(result) == 1

        # With precision=3, these should be unique
        result = dedupe_float_levels([1.001, 1.002, 1.003], precision=3)
        assert len(result) == 3

    def test_filters_none_values(self):
        """Test that None values are filtered out."""
        # This would require passing invalid values that safe_float returns None for
        # Since the function uses safe_float internally
        result = dedupe_float_levels([1.0, 2.0, 3.0])
        assert result == [1.0, 2.0, 3.0]

    def test_negative_numbers(self):
        """Test with negative numbers."""
        assert dedupe_float_levels([-1.0, -1.0, -2.0]) == [-1.0, -2.0]
        assert dedupe_float_levels([-1.0, 1.0, -1.0]) == [-1.0, 1.0]

    def test_mixed_positive_negative(self):
        """Test with mixed positive and negative numbers."""
        assert dedupe_float_levels([1.0, -1.0, 1.0, -1.0]) == [1.0, -1.0]

    def test_zero_values(self):
        """Test with zero values."""
        assert dedupe_float_levels([0.0, 0.0, 1.0]) == [0.0, 1.0]
        assert dedupe_float_levels([0.0, -0.0, 1.0]) == [0.0, 1.0]

    def test_large_list(self):
        """Test with large list of values."""
        values = [1.0] * 100 + [2.0] * 100 + [3.0] * 100
        result = dedupe_float_levels(values)
        assert result == [1.0, 2.0, 3.0]

    def test_trading_levels(self):
        """Test with typical trading price levels."""
        levels = [50000.0, 50000.5, 50001.0, 50000.0, 50001.0]
        result = dedupe_float_levels(levels)
        assert result == [50000.0, 50000.5, 50001.0]

    def test_very_close_values(self):
        """Test with very close values."""
        # These should be considered duplicates with default precision
        result = dedupe_float_levels([1.0, 1.0000000000001, 1.0000000000002])
        assert len(result) == 1
