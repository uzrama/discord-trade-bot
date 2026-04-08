import asyncio
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
        if message.channel.id not in self._watched_channel_ids:
            return
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
        """Extract full text from message including embeds and fields."""
        parts = []

        # 1. Add message content (contains symbol and side)
        if message.content:
            parts.append(message.content)

        # 2. Process first embed only
        if message.embeds:
            embed = message.embeds[0]

            # Add description (contains signal type and leverage)
            if embed.description:
                parts.append(embed.description)

            # 3. Extract and format fields (contains entry, TP, SL)
            for field in embed.fields:
                field_name = field.name or ""
                field_value = field.value or ""

                # Skip empty fields and separator fields
                if not field_value.strip() or field_value.strip().startswith("━"):
                    continue

                # Skip fields we don't need (STATS, STATUS, TRADE NOW)
                field_name_upper = field_name.upper()
                if any(skip in field_name_upper for skip in ["STATS", "STATUS", "TRADE NOW"]):
                    continue

                # Add field name and value
                # Format: "ENTRY\n$0.057620 Triggered"
                parts.append(f"{field_name}\n{field_value}")

        extracted_text = "\n".join(parts)
        logger.debug(f"Extracted text from message {message.id}: {extracted_text}")
        return extracted_text

    async def stop_client(self):
        await self.close()
