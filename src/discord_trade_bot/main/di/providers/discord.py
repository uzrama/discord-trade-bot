from collections.abc import AsyncIterable
from typing import final

from dishka import Provider, Scope, provide

from discord_trade_bot.core.application.signal.dto import ProcessSignalDTO
from discord_trade_bot.infrastructure.discord.client import DiscordSelfAdapter
from discord_trade_bot.infrastructure.taskiq.tasks import process_signal_task
from discord_trade_bot.main.config.app import AppConfig
from discord_trade_bot.main.runners.discord import DiscordRunner


@final
class DiscordProvider(Provider):
    @provide(scope=Scope.APP)
    async def get_discord_client(self, config: AppConfig) -> AsyncIterable[DiscordSelfAdapter]:
        watch_sources = config.yaml.discord.watch_sources
        watched_channel_ids: set[int] = {s.channel_id for s in watch_sources if s.enabled}
        token = config.discord.token.get_secret_value()

        async def on_message_wrapper(dto: ProcessSignalDTO):
            # Send task to Redis queue (pass as separate parameters for MSGPack serialization)
            await process_signal_task.kiq(channel_id=dto.channel_id, message_id=dto.message_id, text=dto.text)

        client = DiscordSelfAdapter(token=token, on_message_callback=on_message_wrapper, watched_channel_ids=watched_channel_ids)
        yield client
        await client.stop_client()

    @provide(scope=Scope.APP)
    def get_discord_runner(self, config: AppConfig, discord_client: DiscordSelfAdapter) -> DiscordRunner:
        return DiscordRunner(discord_client=discord_client, config=config)
