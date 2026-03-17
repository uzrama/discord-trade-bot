import logging
from typing import final

from discord_trade_bot.infrastructure.discord.client import DiscordSelfAdapter
from discord_trade_bot.main.config.app import AppConfig

logger = logging.getLogger(__name__)


@final
class DiscordRunner:
    def __init__(self, discord_client: DiscordSelfAdapter, config: AppConfig):
        self._discord_client = discord_client
        self._config = config
        self._is_running = False

    async def run(self):
        self._is_running = True
        logger.info("Starting Discord Self Client...")
        try:
            await self._discord_client.start_client()
        except Exception as e:
            logger.error(f"Discord Runner error: {e}")

    def stop(self):
        self._is_running = False
        # The container will close the client via stop_client in provider
