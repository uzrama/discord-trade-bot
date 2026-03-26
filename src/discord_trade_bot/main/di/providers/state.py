from typing import final

from dishka import Provider, Scope, provide

from discord_trade_bot.core.application.common.interfaces.repository import StateRepositoryProtocol
from discord_trade_bot.infrastructure.persistence.repository import SqliteStateRepository
from discord_trade_bot.main.config.app import AppConfig


@final
class StateProvider(Provider):
    @provide(scope=Scope.APP)
    async def get_state_repository(self, config: AppConfig) -> StateRepositoryProtocol:
        db_file = config.yaml.state.file
        trades_file = config.yaml.state.trades_file
        repo = SqliteStateRepository(db_file=db_file, trades_file=trades_file)
        await repo.init_db()
        return repo
