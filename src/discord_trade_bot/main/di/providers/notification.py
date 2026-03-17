from collections.abc import AsyncIterable
from typing import final

from dishka import Provider, Scope, provide

from discord_trade_bot.core.application.common.interfaces.notification import NotificationGatewayProtocol
from discord_trade_bot.infrastructure.notifications.telegram import TelegramNotificationAdapter
from discord_trade_bot.main.config.app import AppConfig


@final
class NotificationProvider(Provider):
    @provide(scope=Scope.APP)
    async def get_notification_gateway(self, config: AppConfig) -> AsyncIterable[NotificationGatewayProtocol]:
        token = config.telegram.token.get_secret_value()
        chat_id = str(config.yaml.telegram.chat_id)
        adapter = TelegramNotificationAdapter(token=token, chat_id=chat_id)
        yield adapter
        await adapter.close()
