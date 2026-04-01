"""Tests for entry order decision logic with stop loss validation."""

import pytest

from discord_trade_bot.core.domain.services.entry_order_decider import (
    OrderType,
    decide_entry_order,
)
from discord_trade_bot.core.domain.value_objects.trading import EntryMode, TradeSide


class TestDecideEntryOrderWithStopLoss:
    """Tests for stop loss validation in entry order decision."""

    # ========== LONG TESTS ==========

    def test_long_market_entry_sl_hit_should_skip(self):
        """LONG: market < entry, market <= SL → SKIP"""
        decision = decide_entry_order(
            entry_mode=EntryMode.EXACT_PRICE,
            entry_price=50000.0,
            market_price=48500.0,  # Below entry
            side=TradeSide.LONG,
            stop_loss=49000.0,  # market <= SL
        )
        assert decision.order_type == OrderType.SKIP
        assert "stop_loss_already_hit" in decision.reason

    def test_long_market_entry_sl_not_hit_should_enter(self):
        """LONG: market < entry, market > SL → MARKET"""
        decision = decide_entry_order(
            entry_mode=EntryMode.EXACT_PRICE,
            entry_price=50000.0,
            market_price=49500.0,  # Below entry
            side=TradeSide.LONG,
            stop_loss=49000.0,  # market > SL
        )
        assert decision.order_type == OrderType.MARKET
        assert decision.limit_price is None

    def test_long_market_entry_no_sl_should_enter(self):
        """LONG: market < entry, no SL → MARKET"""
        decision = decide_entry_order(
            entry_mode=EntryMode.EXACT_PRICE,
            entry_price=50000.0,
            market_price=49500.0,
            side=TradeSide.LONG,
            stop_loss=None,  # No SL
        )
        assert decision.order_type == OrderType.MARKET

    def test_long_market_exactly_at_sl(self):
        """LONG: market == SL → SKIP"""
        decision = decide_entry_order(
            entry_mode=EntryMode.EXACT_PRICE,
            entry_price=50000.0,
            market_price=49000.0,  # Exactly at SL
            side=TradeSide.LONG,
            stop_loss=49000.0,
        )
        assert decision.order_type == OrderType.SKIP
        assert "stop_loss_already_hit" in decision.reason

    def test_long_limit_order_not_affected_by_sl(self):
        """LONG: market > entry → LIMIT (SL not checked)"""
        decision = decide_entry_order(
            entry_mode=EntryMode.EXACT_PRICE,
            entry_price=50000.0,
            market_price=51000.0,  # Above entry
            side=TradeSide.LONG,
            stop_loss=49000.0,
        )
        assert decision.order_type == OrderType.LIMIT
        assert decision.limit_price == 50000.0

    # ========== SHORT TESTS ==========

    def test_short_market_entry_sl_hit_should_skip(self):
        """SHORT: market > entry, market >= SL → SKIP"""
        decision = decide_entry_order(
            entry_mode=EntryMode.EXACT_PRICE,
            entry_price=50000.0,
            market_price=51500.0,  # Above entry
            side=TradeSide.SHORT,
            stop_loss=51000.0,  # market >= SL
        )
        assert decision.order_type == OrderType.SKIP
        assert "stop_loss_already_hit" in decision.reason

    def test_short_market_entry_sl_not_hit_should_enter(self):
        """SHORT: market > entry, market < SL → MARKET"""
        decision = decide_entry_order(
            entry_mode=EntryMode.EXACT_PRICE,
            entry_price=50000.0,
            market_price=50500.0,  # Above entry
            side=TradeSide.SHORT,
            stop_loss=51000.0,  # market < SL
        )
        assert decision.order_type == OrderType.MARKET
        assert decision.limit_price is None

    def test_short_market_entry_no_sl_should_enter(self):
        """SHORT: market > entry, no SL → MARKET"""
        decision = decide_entry_order(
            entry_mode=EntryMode.EXACT_PRICE,
            entry_price=50000.0,
            market_price=50500.0,
            side=TradeSide.SHORT,
            stop_loss=None,  # No SL
        )
        assert decision.order_type == OrderType.MARKET

    def test_short_market_exactly_at_sl(self):
        """SHORT: market == SL → SKIP"""
        decision = decide_entry_order(
            entry_mode=EntryMode.EXACT_PRICE,
            entry_price=50000.0,
            market_price=51000.0,  # Exactly at SL
            side=TradeSide.SHORT,
            stop_loss=51000.0,
        )
        assert decision.order_type == OrderType.SKIP
        assert "stop_loss_already_hit" in decision.reason

    def test_short_limit_order_not_affected_by_sl(self):
        """SHORT: market < entry → LIMIT (SL not checked)"""
        decision = decide_entry_order(
            entry_mode=EntryMode.EXACT_PRICE,
            entry_price=50000.0,
            market_price=49000.0,  # Below entry
            side=TradeSide.SHORT,
            stop_loss=51000.0,
        )
        assert decision.order_type == OrderType.LIMIT
        assert decision.limit_price == 50000.0

    # ========== CMP MODE TESTS ==========

    def test_cmp_long_with_sl_hit(self):
        """CMP LONG: market <= reference, market <= SL → SKIP"""
        decision = decide_entry_order(
            entry_mode=EntryMode.CMP,
            entry_price=50000.0,
            market_price=48500.0,
            side=TradeSide.LONG,
            stop_loss=49000.0,
        )
        assert decision.order_type == OrderType.SKIP
        assert "stop_loss_already_hit" in decision.reason

    def test_cmp_long_with_sl_not_hit(self):
        """CMP LONG: market <= reference, market > SL → MARKET"""
        decision = decide_entry_order(
            entry_mode=EntryMode.CMP,
            entry_price=50000.0,
            market_price=49500.0,
            side=TradeSide.LONG,
            stop_loss=49000.0,
        )
        assert decision.order_type == OrderType.MARKET

    def test_cmp_short_with_sl_hit(self):
        """CMP SHORT: market >= reference, market >= SL → SKIP"""
        decision = decide_entry_order(
            entry_mode=EntryMode.CMP,
            entry_price=50000.0,
            market_price=51500.0,
            side=TradeSide.SHORT,
            stop_loss=51000.0,
        )
        assert decision.order_type == OrderType.SKIP
        assert "stop_loss_already_hit" in decision.reason

    def test_cmp_short_with_sl_not_hit(self):
        """CMP SHORT: market >= reference, market < SL → MARKET"""
        decision = decide_entry_order(
            entry_mode=EntryMode.CMP,
            entry_price=50000.0,
            market_price=50500.0,
            side=TradeSide.SHORT,
            stop_loss=51000.0,
        )
        assert decision.order_type == OrderType.MARKET

    def test_cmp_no_reference_price_ignores_sl(self):
        """CMP without reference price → always MARKET (ignores SL)"""
        decision = decide_entry_order(
            entry_mode=EntryMode.CMP,
            entry_price=None,
            market_price=50000.0,
            side=TradeSide.LONG,
            stop_loss=49000.0,
        )
        assert decision.order_type == OrderType.MARKET

    # ========== EDGE CASES ==========

    def test_long_sl_far_below_market(self):
        """LONG: SL far below market, should enter"""
        decision = decide_entry_order(
            entry_mode=EntryMode.EXACT_PRICE,
            entry_price=50000.0,
            market_price=49500.0,
            side=TradeSide.LONG,
            stop_loss=45000.0,  # Very far below
        )
        assert decision.order_type == OrderType.MARKET

    def test_short_sl_far_above_market(self):
        """SHORT: SL far above market, should enter"""
        decision = decide_entry_order(
            entry_mode=EntryMode.EXACT_PRICE,
            entry_price=50000.0,
            market_price=50500.0,
            side=TradeSide.SHORT,
            stop_loss=55000.0,  # Very far above
        )
        assert decision.order_type == OrderType.MARKET

    def test_reason_contains_prices(self):
        """Verify skip reason contains entry, SL, and market prices"""
        decision = decide_entry_order(
            entry_mode=EntryMode.EXACT_PRICE,
            entry_price=50000.0,
            market_price=48500.0,
            side=TradeSide.LONG,
            stop_loss=49000.0,
        )
        assert decision.order_type == OrderType.SKIP
        assert "50000.00" in decision.reason  # Entry price
        assert "49000.00" in decision.reason  # SL price
        assert "48500.00" in decision.reason  # Market price

    # ========== REALISTIC SCENARIOS ==========

    def test_btc_long_flash_crash_scenario(self):
        """BTC LONG: Flash crash below SL → SKIP"""
        decision = decide_entry_order(
            entry_mode=EntryMode.EXACT_PRICE,
            entry_price=65000.0,
            market_price=62000.0,  # Flash crash
            side=TradeSide.LONG,
            stop_loss=63000.0,
        )
        assert decision.order_type == OrderType.SKIP

    def test_eth_short_pump_scenario(self):
        """ETH SHORT: Pump above SL → SKIP"""
        decision = decide_entry_order(
            entry_mode=EntryMode.EXACT_PRICE,
            entry_price=3000.0,
            market_price=3200.0,  # Pump
            side=TradeSide.SHORT,
            stop_loss=3100.0,
        )
        assert decision.order_type == OrderType.SKIP

    def test_btc_long_normal_dip_scenario(self):
        """BTC LONG: Normal dip, SL not hit → MARKET"""
        decision = decide_entry_order(
            entry_mode=EntryMode.EXACT_PRICE,
            entry_price=65000.0,
            market_price=64000.0,  # Normal dip
            side=TradeSide.LONG,
            stop_loss=63000.0,
        )
        assert decision.order_type == OrderType.MARKET
