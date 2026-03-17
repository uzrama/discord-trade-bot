from typing import final

from dishka import Provider, Scope, provide

from discord_trade_bot.core.application.trading.interfaces import ExchangeGatewayProtocol
from discord_trade_bot.main.runners.tracker import PositionTrackerRunner


@final
class TrackerProvider(Provider):
    @provide(scope=Scope.APP)
    def get_tracker_runner(self, exchange_gateway: ExchangeGatewayProtocol) -> PositionTrackerRunner:
        return PositionTrackerRunner(exchange_gateway=exchange_gateway)
