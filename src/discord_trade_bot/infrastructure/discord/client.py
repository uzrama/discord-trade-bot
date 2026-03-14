import logging
from collections.abc import Awaitable, Callable
from typing import final

import discord

from discord_trade_bot.core.application.signal.dto import ProcessSignalDTO

logger = logging.getLogger(__name__)


@final
class DiscordSelfAdapter(discord.Client):
    def __init__(self, token: str, on_message_callback: Callable[[ProcessSignalDTO], Awaitable[None]], watched_channel_ids: set[int], **options):
        super().__init__(**options)
        self._token = token
        self._on_message_callback = on_message_callback
        self._watched_channel_ids = watched_channel_ids

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
            name = channel.name if channel and hasattr(channel, "name") else "Unknown/Private"
            logger.info(f"  - {cid} ({name})")

    async def on_message(self, message: discord.Message):
        if message.channel.id not in self._watched_channel_ids:
            return

        dto = ProcessSignalDTO(channel_id=str(message.channel.id), message_id=str(message.id), text=message.content)

        await self._on_message_callback(dto)

    async def stop_client(self):
        await self.close()
