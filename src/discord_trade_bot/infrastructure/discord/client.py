import logging
from collections.abc import Awaitable, Callable
from typing import final

import discord

from discord_trade_bot.core.application.signal.dto import ProcessSignalDTO

logger = logging.getLogger(__name__)


@final
class DiscordSelfAdapter(discord.Client):
    def __init__(
        self,
        token: str,
        on_message_callback: Callable[[ProcessSignalDTO], Awaitable[None]],
        watched_channel_ids: set[int],
        channel_to_source_map: dict[int, str],
        **options,
    ):
        super().__init__(**options)
        self._token = token
        self._on_message_callback = on_message_callback
        self._watched_channel_ids = watched_channel_ids
        self._channel_to_source_map = channel_to_source_map

    async def start_client(self):
        await self.start(self._token)

    async def on_ready(self):
        if self.user:
            logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        else:
            logger.info("Logged in as Unknown User")

        logger.info(f"Watching {len(self._watched_channel_ids)} channels:")
        for cid in self._watched_channel_ids:
            channel = self.get_channel(cid)
            name = getattr(channel, "name", "Unknown/Private") if channel else "Unknown/Private"
            logger.info(f"  - {cid} ({name})")

    async def on_message(self, message: discord.Message):
        text = ""
        text = self._extract_full_text(message)

        source_id = self._channel_to_source_map.get(message.channel.id, str(message.channel.id))
        dto = ProcessSignalDTO(source_id=source_id, channel_id=str(message.channel.id), message_id=str(message.id), text=text)

        await self._on_message_callback(dto)

    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        """Handle message edits to process signal updates (e.g., added SL/TP)."""
        if after.channel.id not in self._watched_channel_ids:
            return
        before_text = self._extract_full_text(before)
        after_text = self._extract_full_text(after)
        # Only process if content actually changed
        if before_text == after_text:
            return

        logger.info(f"Message edited in channel {after.channel.id}: {after.id}")

        source_id = self._channel_to_source_map.get(after.channel.id, str(after.channel.id))
        dto = ProcessSignalDTO(
            source_id=source_id,
            channel_id=str(after.channel.id),
            message_id=str(after.id),
            text=after_text,
        )

        await self._on_message_callback(dto)

    def _extract_full_text(self, message: discord.Message) -> str:
        """Extract full text from message including embeds."""
        text = message.content or ""
        if message.embeds:
            embed_text = message.embeds[0].description or ""
            if embed_text:
                text = f"{text}\n{embed_text}" if text else embed_text
        return text

    async def stop_client(self):
        await self.close()
