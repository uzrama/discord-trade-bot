import logging
from typing import final, override

from aiogram import Bot

from discord_trade_bot.core.application.common.interfaces.notification import (
    NotificationGatewayProtocol,
)

logger = logging.getLogger(__name__)


@final
class TelegramNotificationAdapter(NotificationGatewayProtocol):
    def __init__(self, token: str, chat_id: str):
        self._bot = Bot(token=token)
        self._chat_id = chat_id

    @override
    async def send_message(self, text: str) -> bool:
        try:
            await self._bot.send_message(chat_id=self._chat_id, text=text)
            return True
        except Exception as e:
            logger.error(f"Telegram error: {e}")
            return False

    async def close(self):
        await self._bot.session.close()
