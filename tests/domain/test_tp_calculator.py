"""Tests for TP quantity calculation utilities."""

import pytest

from discord_trade_bot.core.domain.services.tp_calculator import calculate_tp_quantities


class TestCalculateTpQuantities:
    """Test suite for calculate_tp_quantities function."""

    def test_exact_match_4_tps(self):
        """Test with exact match: 4 TPs with config for 4 TPs."""
        config = {
            4: [
                {"label": "tp1", "close_pct": 40},
                {"label": "tp2", "close_pct": 30},
                {"label": "tp3", "close_pct": 20},
                {"label": "tp4", "close_pct": 10},
            ]
        }

        result = calculate_tp_quantities(total_qty=100.0, num_tps=4, tp_distributions=config)

        assert len(result) == 4
        assert result[0] == pytest.approx(40.0)
        assert result[1] == pytest.approx(30.0)
        assert result[2] == pytest.approx(20.0)
        assert result[3] == pytest.approx(10.0)
        assert sum(result) == pytest.approx(100.0)

    def test_exact_match_3_tps(self):
        """Test with exact match: 3 TPs with config for 3 TPs."""
        config = {
            3: [
                {"label": "tp1", "close_pct": 50},
                {"label": "tp2", "close_pct": 30},
                {"label": "tp3", "close_pct": 20},
            ]
        }

        result = calculate_tp_quantities(total_qty=100.0, num_tps=3, tp_distributions=config)

        assert len(result) == 3
        assert result[0] == pytest.approx(50.0)
        assert result[1] == pytest.approx(30.0)
        assert result[2] == pytest.approx(20.0)
        assert sum(result) == pytest.approx(100.0)

    def test_exact_match_5_tps(self):
        """Test with exact match: 5 TPs with config for 5 TPs."""
        config = {
            5: [
                {"label": "tp1", "close_pct": 30},
                {"label": "tp2", "close_pct": 25},
                {"label": "tp3", "close_pct": 20},
                {"label": "tp4", "close_pct": 15},
                {"label": "tp5", "close_pct": 10},
            ]
        }

        result = calculate_tp_quantities(total_qty=100.0, num_tps=5, tp_distributions=config)

        assert len(result) == 5
        assert result[0] == pytest.approx(30.0)
        assert result[1] == pytest.approx(25.0)
        assert result[2] == pytest.approx(20.0)
        assert result[3] == pytest.approx(15.0)
        assert result[4] == pytest.approx(10.0)
        assert sum(result) == pytest.approx(100.0)

    def test_no_config_fallback_to_equal_distribution(self):
        """Test fallback to equal distribution when no config exists."""
        config = {}

        result = calculate_tp_quantities(total_qty=100.0, num_tps=4, tp_distributions=config)

        assert len(result) == 4
        assert all(qty == pytest.approx(25.0) for qty in result)
        assert sum(result) == pytest.approx(100.0)

    def test_no_matching_config_fallback_to_equal_distribution(self):
        """Test fallback when config exists but not for requested number of TPs."""
        config = {
            4: [
                {"label": "tp1", "close_pct": 40},
                {"label": "tp2", "close_pct": 30},
                {"label": "tp3", "close_pct": 20},
                {"label": "tp4", "close_pct": 10},
            ]
        }

        # Request 6 TPs but only have config for 4
        result = calculate_tp_quantities(total_qty=100.0, num_tps=6, tp_distributions=config)

        assert len(result) == 6
        assert all(qty == pytest.approx(100.0 / 6) for qty in result)
        assert sum(result) == pytest.approx(100.0)

    def test_auto_normalize_when_sum_not_100(self):
        """Test auto-normalization when percentages don't sum to 100%."""
        config = {
            3: [
                {"label": "tp1", "close_pct": 50},
                {"label": "tp2", "close_pct": 30},
                {"label": "tp3", "close_pct": 10},  # Sum = 90%, not 100%
            ]
        }

        result = calculate_tp_quantities(total_qty=100.0, num_tps=3, tp_distributions=config)

        assert len(result) == 3
        # Should normalize to 100%: 50/90*100 = 55.56, 30/90*100 = 33.33, 10/90*100 = 11.11
        assert result[0] == pytest.approx(55.555555, rel=1e-5)
        assert result[1] == pytest.approx(33.333333, rel=1e-5)
        assert result[2] == pytest.approx(11.111111, rel=1e-5)
        assert sum(result) == pytest.approx(100.0)

    def test_config_mismatch_length_fallback(self):
        """Test fallback when config length doesn't match number of TPs."""
        config = {
            4: [
                {"label": "tp1", "close_pct": 40},
                {"label": "tp2", "close_pct": 30},
                # Only 2 entries but key says 4
            ]
        }

        result = calculate_tp_quantities(total_qty=100.0, num_tps=4, tp_distributions=config)

        # Should fallback to equal distribution
        assert len(result) == 4
        assert all(qty == pytest.approx(25.0) for qty in result)

    def test_with_different_total_quantity(self):
        """Test with different total quantity values."""
        config = {
            4: [
                {"label": "tp1", "close_pct": 40},
                {"label": "tp2", "close_pct": 30},
                {"label": "tp3", "close_pct": 20},
                {"label": "tp4", "close_pct": 10},
            ]
        }

        # Test with 50.0
        result = calculate_tp_quantities(total_qty=50.0, num_tps=4, tp_distributions=config)
        assert result[0] == pytest.approx(20.0)
        assert result[1] == pytest.approx(15.0)
        assert result[2] == pytest.approx(10.0)
        assert result[3] == pytest.approx(5.0)
        assert sum(result) == pytest.approx(50.0)

        # Test with 1000.0
        result = calculate_tp_quantities(total_qty=1000.0, num_tps=4, tp_distributions=config)
        assert result[0] == pytest.approx(400.0)
        assert result[1] == pytest.approx(300.0)
        assert result[2] == pytest.approx(200.0)
        assert result[3] == pytest.approx(100.0)
        assert sum(result) == pytest.approx(1000.0)

    def test_single_tp(self):
        """Test with single TP level."""
        config = {
            1: [
                {"label": "tp1", "close_pct": 100},
            ]
        }

        result = calculate_tp_quantities(total_qty=100.0, num_tps=1, tp_distributions=config)

        assert len(result) == 1
        assert result[0] == pytest.approx(100.0)

    def test_empty_config_dict(self):
        """Test with empty config dictionary."""
        result = calculate_tp_quantities(total_qty=100.0, num_tps=3, tp_distributions={})

        assert len(result) == 3
        assert all(qty == pytest.approx(100.0 / 3) for qty in result)

    def test_fractional_quantities(self):
        """Test that fractional quantities are handled correctly."""
        config = {
            3: [
                {"label": "tp1", "close_pct": 33.33},
                {"label": "tp2", "close_pct": 33.33},
                {"label": "tp3", "close_pct": 33.34},
            ]
        }

        result = calculate_tp_quantities(total_qty=100.0, num_tps=3, tp_distributions=config)

        assert len(result) == 3
        assert result[0] == pytest.approx(33.33)
        assert result[1] == pytest.approx(33.33)
        assert result[2] == pytest.approx(33.34)
        assert sum(result) == pytest.approx(100.0)
