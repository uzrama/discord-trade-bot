from collections.abc import AsyncIterable
from typing import final

from dishka import Provider, Scope, provide
from taskiq import AsyncBroker

from discord_trade_bot.infrastructure.taskiq.broker import broker


@final
class TaskiqProvider(Provider):
    @provide(scope=Scope.APP)
    async def get_broker(self) -> AsyncIterable[AsyncBroker]:
        await broker.startup()

        yield broker

        await broker.shutdown()
