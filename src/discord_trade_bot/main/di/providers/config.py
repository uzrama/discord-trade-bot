from typing import final

from dishka import Provider, Scope, provide

from discord_trade_bot.main.config.app import AppConfig


@final
class ConfigProvider(Provider):
    @provide(scope=Scope.APP)
    def get_config(self) -> AppConfig:
        return AppConfig()
