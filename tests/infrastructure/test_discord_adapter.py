"""Integration tests for DiscordSelfAdapter."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from discord_trade_bot.core.application.signal.dto import ProcessSignalDTO
from discord_trade_bot.infrastructure.discord.client import DiscordSelfAdapter


@pytest.fixture
def mock_discord_message():
    """Create a mock Discord message."""
    message = MagicMock()
    message.id = 123456789
    message.content = "BTCUSDT LONG Entry: 50000"
    message.channel = MagicMock()
    message.channel.id = 999888777
    return message


@pytest.fixture
def mock_callback():
    """Create a mock callback function."""
    return AsyncMock()


@pytest.fixture
def discord_adapter(mock_callback):
    """Create DiscordSelfAdapter with mocked dependencies."""
    watched_channels = {999888777, 111222333}
    adapter = DiscordSelfAdapter(
        token="test_token",
        on_message_callback=mock_callback,
        watched_channel_ids=watched_channels,
    )
    return adapter


class TestDiscordSelfAdapter:
    """Test DiscordSelfAdapter."""

    def test_init_with_parameters(self, mock_callback):
        """Test initialization with all parameters."""
        watched_channels = {123, 456, 789}

        adapter = DiscordSelfAdapter(
            token="my_token",
            on_message_callback=mock_callback,
            watched_channel_ids=watched_channels,
        )

        assert adapter._token == "my_token"
        assert adapter._on_message_callback == mock_callback
        assert adapter._watched_channel_ids == watched_channels

    def test_init_with_empty_watched_channels(self, mock_callback):
        """Test initialization with empty watched channels."""
        adapter = DiscordSelfAdapter(
            token="test_token",
            on_message_callback=mock_callback,
            watched_channel_ids=set(),
        )

        assert adapter._watched_channel_ids == set()

    @pytest.mark.asyncio
    async def test_on_message_from_watched_channel(self, discord_adapter, mock_discord_message, mock_callback):
        """Test that messages from watched channels are processed."""
        await discord_adapter.on_message(mock_discord_message)

        # Callback should be called
        mock_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_message_from_unwatched_channel_ignored(self, discord_adapter, mock_discord_message, mock_callback):
        """Test that messages from unwatched channels are ignored."""
        # Set channel ID to unwatched value
        mock_discord_message.channel.id = 999999999

        await discord_adapter.on_message(mock_discord_message)

        # Callback should NOT be called
        mock_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_message_creates_correct_dto(self, discord_adapter, mock_discord_message, mock_callback):
        """Test that on_message creates correct ProcessSignalDTO."""
        await discord_adapter.on_message(mock_discord_message)

        # Verify callback was called with correct DTO
        mock_callback.assert_called_once()
        call_args = mock_callback.call_args[0]
        dto = call_args[0]

        assert isinstance(dto, ProcessSignalDTO)
        assert dto.channel_id == "999888777"
        assert dto.message_id == "123456789"
        assert dto.text == "BTCUSDT LONG Entry: 50000"

    @pytest.mark.asyncio
    async def test_on_message_calls_callback(self, discord_adapter, mock_discord_message, mock_callback):
        """Test that callback is called with DTO."""
        await discord_adapter.on_message(mock_discord_message)

        assert mock_callback.called
        assert mock_callback.call_count == 1

    @pytest.mark.asyncio
    async def test_on_message_with_empty_content(self, discord_adapter, mock_callback):
        """Test handling message with empty content."""
        message = MagicMock()
        message.id = 111
        message.content = ""
        message.channel = MagicMock()
        message.channel.id = 999888777

        await discord_adapter.on_message(message)

        # Should still call callback with empty text
        mock_callback.assert_called_once()
        dto = mock_callback.call_args[0][0]
        assert dto.text == ""

    @pytest.mark.asyncio
    async def test_on_message_with_multiline_content(self, discord_adapter, mock_callback):
        """Test handling message with multiline content."""
        message = MagicMock()
        message.id = 222
        message.content = "Line 1\nLine 2\nLine 3"
        message.channel = MagicMock()
        message.channel.id = 999888777

        await discord_adapter.on_message(message)

        mock_callback.assert_called_once()
        dto = mock_callback.call_args[0][0]
        assert "Line 1" in dto.text
        assert "\n" in dto.text

    @pytest.mark.asyncio
    async def test_on_message_with_special_characters(self, discord_adapter, mock_callback):
        """Test handling message with special characters."""
        message = MagicMock()
        message.id = 333
        message.content = "🚀 BTCUSDT 📈 Entry: $50,000"
        message.channel = MagicMock()
        message.channel.id = 999888777

        await discord_adapter.on_message(message)

        mock_callback.assert_called_once()
        dto = mock_callback.call_args[0][0]
        assert "🚀" in dto.text
        assert "$50,000" in dto.text

    @pytest.mark.asyncio
    async def test_on_message_multiple_watched_channels(self, mock_callback):
        """Test processing messages from multiple watched channels."""
        watched_channels = {111, 222, 333}
        adapter = DiscordSelfAdapter(
            token="test_token",
            on_message_callback=mock_callback,
            watched_channel_ids=watched_channels,
        )

        # Create messages from different channels
        for channel_id in watched_channels:
            message = MagicMock()
            message.id = channel_id
            message.content = f"Message from {channel_id}"
            message.channel = MagicMock()
            message.channel.id = channel_id

            await adapter.on_message(message)

        # All should be processed
        assert mock_callback.call_count == 3

    @pytest.mark.asyncio
    async def test_on_ready_can_be_called(self, discord_adapter):
        """Test that on_ready can be called without errors."""
        # Mock get_channel to return None (private/unknown channels)
        discord_adapter.get_channel = MagicMock(return_value=None)

        # Should not raise any errors
        await discord_adapter.on_ready()

    @pytest.mark.asyncio
    async def test_stop_client(self, discord_adapter):
        """Test that stop_client closes the connection."""
        discord_adapter.close = AsyncMock()

        await discord_adapter.stop_client()

        discord_adapter.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_message_preserves_message_id_type(self, discord_adapter, mock_callback):
        """Test that message IDs are converted to strings."""
        message = MagicMock()
        message.id = 987654321  # Integer
        message.content = "Test"
        message.channel = MagicMock()
        message.channel.id = 999888777

        await discord_adapter.on_message(message)

        dto = mock_callback.call_args[0][0]
        assert isinstance(dto.message_id, str)
        assert dto.message_id == "987654321"

    @pytest.mark.asyncio
    async def test_on_message_preserves_channel_id_type(self, discord_adapter, mock_callback):
        """Test that channel IDs are converted to strings."""
        message = MagicMock()
        message.id = 111
        message.content = "Test"
        message.channel = MagicMock()
        message.channel.id = 999888777  # Integer

        await discord_adapter.on_message(message)

        dto = mock_callback.call_args[0][0]
        assert isinstance(dto.channel_id, str)
        assert dto.channel_id == "999888777"
