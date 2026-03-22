"""
Tests for trading calculation functions.

This module tests the trading calculation utilities used for PnL calculations
and percentage computations.
"""

import pytest

from discord_trade_bot.core.domain.services.trading_calculations import (
    calc_realized_pnl_for_partial,
    pct,
)


class TestPercentageCalculation:
    """Test suite for percentage calculation function."""

    def test_pct_with_valid_values(self):
        """Test percentage calculation with valid inputs."""
        # Arrange & Act & Assert
        assert pct(50, 100) == 50.0
        assert pct(25, 200) == 12.5
        assert pct(75, 100) == 75.0
        assert pct(1, 4) == 25.0

    def test_pct_with_zero_denominator(self):
        """Test that zero denominator returns 0.0."""
        # Arrange & Act
        result = pct(10, 0)

        # Assert
        assert result == 0.0

    def test_pct_with_zero_numerator(self):
        """Test percentage calculation with zero numerator."""
        # Arrange & Act
        result = pct(0, 100)

        # Assert
        assert result == 0.0

    def test_pct_with_both_zero(self):
        """Test percentage calculation with both values zero."""
        # Arrange & Act
        result = pct(0, 0)

        # Assert
        assert result == 0.0

    def test_pct_with_negative_values(self):
        """Test percentage calculation with negative values."""
        # Arrange & Act & Assert
        assert pct(-50, 100) == -50.0
        assert pct(50, -100) == -50.0
        assert pct(-50, -100) == 50.0

    def test_pct_with_decimal_values(self):
        """Test percentage calculation with decimal values."""
        # Arrange & Act & Assert
        assert pct(33.33, 100) == 33.33
        assert pct(0.5, 2) == 25.0
        assert pytest.approx(pct(1, 3), rel=1e-2) == 33.33


class TestRealizedPnLCalculation:
    """Test suite for realized PnL calculation function."""

    # ========================================================================
    # LONG Position Tests
    # ========================================================================

    def test_calc_pnl_long_position_with_profit(self):
        """Test PnL calculation for profitable LONG position."""
        # Arrange
        entry_price = 100.0
        exit_price = 110.0
        qty_closed = 1.0
        side = "long"

        # Act
        pnl = calc_realized_pnl_for_partial(entry_price, exit_price, qty_closed, side)

        # Assert
        assert pnl == 10.0

    def test_calc_pnl_long_position_with_loss(self):
        """Test PnL calculation for losing LONG position."""
        # Arrange
        entry_price = 100.0
        exit_price = 90.0
        qty_closed = 1.0
        side = "long"

        # Act
        pnl = calc_realized_pnl_for_partial(entry_price, exit_price, qty_closed, side)

        # Assert
        assert pnl == -10.0

    def test_calc_pnl_long_position_breakeven(self):
        """Test PnL calculation for breakeven LONG position."""
        # Arrange
        entry_price = 100.0
        exit_price = 100.0
        qty_closed = 1.0
        side = "long"

        # Act
        pnl = calc_realized_pnl_for_partial(entry_price, exit_price, qty_closed, side)

        # Assert
        assert pnl == 0.0

    def test_calc_pnl_long_position_with_multiple_qty(self):
        """Test PnL calculation for LONG position with multiple quantity."""
        # Arrange
        entry_price = 50000.0
        exit_price = 51000.0
        qty_closed = 0.5
        side = "long"

        # Act
        pnl = calc_realized_pnl_for_partial(entry_price, exit_price, qty_closed, side)

        # Assert
        assert pnl == 500.0  # (51000 - 50000) * 0.5

    # ========================================================================
    # SHORT Position Tests
    # ========================================================================

    def test_calc_pnl_short_position_with_profit(self):
        """Test PnL calculation for profitable SHORT position."""
        # Arrange
        entry_price = 100.0
        exit_price = 90.0
        qty_closed = 1.0
        side = "short"

        # Act
        pnl = calc_realized_pnl_for_partial(entry_price, exit_price, qty_closed, side)

        # Assert
        assert pnl == 10.0  # Price went down, SHORT profits

    def test_calc_pnl_short_position_with_loss(self):
        """Test PnL calculation for losing SHORT position."""
        # Arrange
        entry_price = 100.0
        exit_price = 110.0
        qty_closed = 1.0
        side = "short"

        # Act
        pnl = calc_realized_pnl_for_partial(entry_price, exit_price, qty_closed, side)

        # Assert
        assert pnl == -10.0  # Price went up, SHORT loses

    def test_calc_pnl_short_position_breakeven(self):
        """Test PnL calculation for breakeven SHORT position."""
        # Arrange
        entry_price = 100.0
        exit_price = 100.0
        qty_closed = 1.0
        side = "short"

        # Act
        pnl = calc_realized_pnl_for_partial(entry_price, exit_price, qty_closed, side)

        # Assert
        assert pnl == 0.0

    def test_calc_pnl_short_position_with_multiple_qty(self):
        """Test PnL calculation for SHORT position with multiple quantity."""
        # Arrange
        entry_price = 3000.0
        exit_price = 2900.0
        qty_closed = 2.0
        side = "short"

        # Act
        pnl = calc_realized_pnl_for_partial(entry_price, exit_price, qty_closed, side)

        # Assert
        assert pnl == 200.0  # (3000 - 2900) * 2.0

    # ========================================================================
    # Edge Cases
    # ========================================================================

    def test_calc_pnl_with_zero_quantity(self):
        """Test PnL calculation with zero quantity."""
        # Arrange
        entry_price = 100.0
        exit_price = 110.0
        qty_closed = 0.0
        side = "long"

        # Act
        pnl = calc_realized_pnl_for_partial(entry_price, exit_price, qty_closed, side)

        # Assert
        assert pnl == 0.0

    def test_calc_pnl_with_very_small_quantity(self):
        """Test PnL calculation with very small quantity."""
        # Arrange
        entry_price = 50000.0
        exit_price = 51000.0
        qty_closed = 0.001
        side = "long"

        # Act
        pnl = calc_realized_pnl_for_partial(entry_price, exit_price, qty_closed, side)

        # Assert
        assert pnl == 1.0  # (51000 - 50000) * 0.001

    def test_calc_pnl_with_large_price_difference(self):
        """Test PnL calculation with large price difference."""
        # Arrange
        entry_price = 10000.0
        exit_price = 50000.0
        qty_closed = 1.0
        side = "long"

        # Act
        pnl = calc_realized_pnl_for_partial(entry_price, exit_price, qty_closed, side)

        # Assert
        assert pnl == 40000.0

    def test_calc_pnl_with_decimal_prices(self):
        """Test PnL calculation with decimal prices."""
        # Arrange
        entry_price = 100.55
        exit_price = 105.75
        qty_closed = 1.5
        side = "long"

        # Act
        pnl = calc_realized_pnl_for_partial(entry_price, exit_price, qty_closed, side)

        # Assert
        expected = (105.75 - 100.55) * 1.5
        assert pytest.approx(pnl, rel=1e-6) == expected

    # ========================================================================
    # Real-world Scenarios
    # ========================================================================

    def test_calc_pnl_btc_long_realistic_scenario(self):
        """Test PnL calculation for realistic BTC LONG trade."""
        # Arrange - Entry at 50k, exit at 51k, 0.1 BTC
        entry_price = 50000.0
        exit_price = 51000.0
        qty_closed = 0.1
        side = "long"

        # Act
        pnl = calc_realized_pnl_for_partial(entry_price, exit_price, qty_closed, side)

        # Assert
        assert pnl == 100.0  # $100 profit

    def test_calc_pnl_eth_short_realistic_scenario(self):
        """Test PnL calculation for realistic ETH SHORT trade."""
        # Arrange - Entry at 3000, exit at 2900, 1 ETH
        entry_price = 3000.0
        exit_price = 2900.0
        qty_closed = 1.0
        side = "short"

        # Act
        pnl = calc_realized_pnl_for_partial(entry_price, exit_price, qty_closed, side)

        # Assert
        assert pnl == 100.0  # $100 profit

    def test_calc_pnl_partial_close_scenario(self):
        """Test PnL calculation for partial position close."""
        # Arrange - Close 25% of position
        entry_price = 40000.0
        exit_price = 42000.0
        qty_closed = 0.025  # 25% of 0.1 BTC
        side = "long"

        # Act
        pnl = calc_realized_pnl_for_partial(entry_price, exit_price, qty_closed, side)

        # Assert
        assert pnl == 50.0  # (42000 - 40000) * 0.025
