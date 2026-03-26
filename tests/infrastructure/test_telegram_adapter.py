"""Integration tests for TelegramNotificationAdapter."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from discord_trade_bot.infrastructure.notifications.telegram import (
    TelegramNotificationAdapter,
)


@pytest.fixture
def mock_bot():
    """Create a mock aiogram Bot."""
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=True)
    bot.session = MagicMock()
    bot.session.close = AsyncMock()
    return bot


@pytest.fixture
def telegram_adapter(mock_bot):
    """Create TelegramNotificationAdapter with mocked bot."""
    with patch("discord_trade_bot.infrastructure.notifications.telegram.Bot", return_value=mock_bot):
        adapter = TelegramNotificationAdapter(token="test_token", chat_id="123456")
        adapter._bot = mock_bot
        return adapter


class TestTelegramNotificationAdapter:
    """Test TelegramNotificationAdapter."""

    def test_init_creates_bot(self):
        """Test that initialization creates Bot instance."""
        with patch("discord_trade_bot.infrastructure.notifications.telegram.Bot") as MockBot:
            adapter = TelegramNotificationAdapter(token="test_token", chat_id="123456")

            MockBot.assert_called_once_with(token="test_token")
            assert adapter._chat_id == "123456"

    @pytest.mark.asyncio
    async def test_send_message_success(self, telegram_adapter, mock_bot):
        """Test successful message sending."""
        result = await telegram_adapter.send_message("Test message")

        assert result is True
        mock_bot.send_message.assert_called_once_with(chat_id="123456", text="Test message")

    @pytest.mark.asyncio
    async def test_send_message_with_long_text(self, telegram_adapter, mock_bot):
        """Test sending long message."""
        long_message = "A" * 1000

        result = await telegram_adapter.send_message(long_message)

        assert result is True
        mock_bot.send_message.assert_called_once()
        call_args = mock_bot.send_message.call_args
        assert len(call_args.kwargs["text"]) == 1000

    @pytest.mark.asyncio
    async def test_send_message_with_special_characters(self, telegram_adapter, mock_bot):
        """Test sending message with special characters."""
        message = "🚀 Position opened! Price: $50,000 📈"

        result = await telegram_adapter.send_message(message)

        assert result is True
        mock_bot.send_message.assert_called_once_with(chat_id="123456", text=message)

    @pytest.mark.asyncio
    async def test_send_message_failure_returns_false(self, telegram_adapter, mock_bot):
        """Test that send_message returns False on failure."""
        mock_bot.send_message.side_effect = Exception("Network error")

        result = await telegram_adapter.send_message("Test message")

        assert result is False

    @pytest.mark.asyncio
    async def test_send_message_logs_error(self, telegram_adapter, mock_bot, caplog):
        """Test that errors are logged."""
        mock_bot.send_message.side_effect = Exception("API error")

        with caplog.at_level("ERROR"):
            await telegram_adapter.send_message("Test message")

        assert "Telegram error" in caplog.text
        assert "API error" in caplog.text

    @pytest.mark.asyncio
    async def test_send_message_handles_timeout(self, telegram_adapter, mock_bot):
        """Test handling of timeout errors."""
        mock_bot.send_message.side_effect = TimeoutError("Request timeout")

        result = await telegram_adapter.send_message("Test message")

        assert result is False

    @pytest.mark.asyncio
    async def test_send_message_handles_connection_error(self, telegram_adapter, mock_bot):
        """Test handling of connection errors."""
        mock_bot.send_message.side_effect = ConnectionError("Connection failed")

        result = await telegram_adapter.send_message("Test message")

        assert result is False

    @pytest.mark.asyncio
    async def test_close_closes_session(self, telegram_adapter, mock_bot):
        """Test that close() closes the bot session."""
        await telegram_adapter.close()

        mock_bot.session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_multiple_messages_sequential(self, telegram_adapter, mock_bot):
        """Test sending multiple messages sequentially."""
        messages = ["Message 1", "Message 2", "Message 3"]

        for msg in messages:
            result = await telegram_adapter.send_message(msg)
            assert result is True

        assert mock_bot.send_message.call_count == 3

    @pytest.mark.asyncio
    async def test_send_empty_message(self, telegram_adapter, mock_bot):
        """Test sending empty message."""
        result = await telegram_adapter.send_message("")

        assert result is True
        mock_bot.send_message.assert_called_once_with(chat_id="123456", text="")

    @pytest.mark.asyncio
    async def test_send_message_with_newlines(self, telegram_adapter, mock_bot):
        """Test sending message with newlines."""
        message = "Line 1\nLine 2\nLine 3"

        result = await telegram_adapter.send_message(message)

        assert result is True
        call_args = mock_bot.send_message.call_args
        assert "\n" in call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_send_message_preserves_formatting(self, telegram_adapter, mock_bot):
        """Test that message formatting is preserved."""
        message = "**Bold** _Italic_ `Code`"

        result = await telegram_adapter.send_message(message)

        assert result is True
        call_args = mock_bot.send_message.call_args
        assert call_args.kwargs["text"] == message
