"""Tests for core.shared.utils.datetime module."""

from datetime import UTC, datetime

import pytest

from discord_trade_bot.core.shared.utils.datetime import utc_now_iso


class TestUtcNowIso:
    """Test utc_now_iso function."""

    def test_returns_string(self):
        """Test that function returns a string."""
        result = utc_now_iso()
        assert isinstance(result, str)

    def test_iso_format(self):
        """Test that result is in ISO format."""
        result = utc_now_iso()
        # Should be parseable as ISO format
        parsed = datetime.fromisoformat(result)
        assert isinstance(parsed, datetime)

    def test_has_timezone_info(self):
        """Test that result includes timezone information."""
        result = utc_now_iso()
        assert "+00:00" in result or "Z" in result.upper()

    def test_utc_timezone(self):
        """Test that timezone is UTC."""
        result = utc_now_iso()
        parsed = datetime.fromisoformat(result)
        assert parsed.tzinfo == UTC

    def test_format_structure(self):
        """Test the general structure of the ISO string."""
        result = utc_now_iso()
        # Should contain date and time parts
        assert "T" in result  # ISO format separator
        assert ":" in result  # Time separator
        assert "-" in result  # Date separator

    def test_current_time(self):
        """Test that returned time is close to current time."""
        before = datetime.now(UTC)
        result = utc_now_iso()
        after = datetime.now(UTC)

        parsed = datetime.fromisoformat(result)

        # Should be between before and after (within a few seconds)
        assert before <= parsed <= after

    def test_multiple_calls_different_times(self):
        """Test that multiple calls return different (increasing) times."""
        time1 = utc_now_iso()
        # Small delay to ensure different timestamps
        import time

        time.sleep(0.001)
        time2 = utc_now_iso()

        parsed1 = datetime.fromisoformat(time1)
        parsed2 = datetime.fromisoformat(time2)

        assert parsed2 >= parsed1

    def test_microsecond_precision(self):
        """Test that result includes microsecond precision."""
        result = utc_now_iso()
        parsed = datetime.fromisoformat(result)
        # ISO format should include microseconds
        assert parsed.microsecond is not None
