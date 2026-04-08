import logging
from collections.abc import AsyncIterable
from typing import final

from dishka import Provider, Scope, provide

from discord_trade_bot.core.application.common.interfaces.notification import NotificationGatewayProtocol
from discord_trade_bot.core.application.common.interfaces.repository import StateRepositoryProtocol
from discord_trade_bot.core.application.signal.use_cases import ProcessSignalUseCase
from discord_trade_bot.core.application.trading.interfaces import ExchangeGatewayProtocol, ExchangeRegistryProtocol
from discord_trade_bot.core.application.trading.use_cases import OpenPositionUseCase, ProcessTrackerEventUseCase
from discord_trade_bot.infrastructure.exchanges.binance import BinanceFuturesAdapter
from discord_trade_bot.infrastructure.exchanges.bybit import BybitAdapter
from discord_trade_bot.infrastructure.exchanges.composite import CompositeExchangeGateway
from discord_trade_bot.main.config.app import AppConfig
from discord_trade_bot.main.config.yaml.general import AppMode

logger = logging.getLogger(__name__)


@final
class TradingProvider(Provider):
    @provide(scope=Scope.APP)
    async def get_exchange_composite(self, config: AppConfig) -> AsyncIterable[CompositeExchangeGateway]:
        exchanges = {}

        # Binance accounts
        for account in config.exchanges.binance_accounts:
            api_key = account.token.get_secret_value()
            secret = account.secret_key.get_secret_value()

            if api_key and secret:
                binance_config = config.yaml.exchanges.get("binance")
                testnet = binance_config.testnet if binance_config and binance_config.testnet is not None else config.yaml.general.mode == AppMode.TESTNET
                exchanges[account.name] = BinanceFuturesAdapter(api_key, secret, testnet=testnet)
            else:
                logger.warning(f"⚠️ Binance account '{account.name}' has empty credentials, skipping")

        # Bybit accounts
        for account in config.exchanges.bybit_accounts:
            api_key = account.token.get_secret_value()
            secret = account.secret_key.get_secret_value()

            if api_key and secret:
                bybit_config = config.yaml.exchanges.get("bybit")
                testnet = bybit_config.testnet if bybit_config and bybit_config.testnet is not None else config.yaml.general.mode == AppMode.TESTNET
                demo = bybit_config.demo if bybit_config and bybit_config.demo is not None else False
                exchanges[account.name] = BybitAdapter(account.name, api_key, secret, testnet=testnet, demo=demo)
                logger.info(f"✅ Bybit account '{account.name}' configured")
            else:
                logger.warning(f"⚠️ Bybit account '{account.name}' has empty credentials, skipping")

        # Validate at least one exchange is configured
        if not exchanges:
            raise RuntimeError("❌ No exchange adapters configured. Please provide API keys for at least one exchange account in your .env file.")

        logger.info(f"📊 Active exchange accounts: {', '.join(exchanges.keys())}")

        composite = CompositeExchangeGateway(exchanges)
        yield composite
        await composite.close()

    @provide(scope=Scope.APP)
    def get_process_tracker_event_use_case(
        self,
        exchange_registry: ExchangeRegistryProtocol,
        state_repository: StateRepositoryProtocol,
        notification_gateway: NotificationGatewayProtocol,
        config: AppConfig,
    ) -> ProcessTrackerEventUseCase:
        return ProcessTrackerEventUseCase(
            exchange_registry=exchange_registry,
            state_repository=state_repository,
            notification_gateway=notification_gateway,
            config=config,
        )

    @provide(scope=Scope.APP)
    def get_exchange_gateway(self, composite: CompositeExchangeGateway) -> ExchangeGatewayProtocol:
        return composite

    @provide(scope=Scope.APP)
    def get_exchange_registry(self, composite: CompositeExchangeGateway) -> ExchangeRegistryProtocol:
        return composite

    @provide(scope=Scope.APP)
    def get_open_position_use_case(
        self,
        exchange_registry: ExchangeRegistryProtocol,
        notification_gateway: NotificationGatewayProtocol,
        state_repository: StateRepositoryProtocol,
    ) -> OpenPositionUseCase:
        return OpenPositionUseCase(
            exchange_registry=exchange_registry,
            notification_gateway=notification_gateway,
            state_repository=state_repository,
        )

    @provide(scope=Scope.APP)
    def get_process_signal_use_case(
        self,
        config: AppConfig,
        exchange_registry: ExchangeRegistryProtocol,
        notification_gateway: NotificationGatewayProtocol,
        state_repository: StateRepositoryProtocol,
        open_position_use_case: OpenPositionUseCase,
    ) -> ProcessSignalUseCase:
        return ProcessSignalUseCase(
            exchange_registry=exchange_registry,
            notification_gateway=notification_gateway,
            state_repository=state_repository,
            open_position_use_case=open_position_use_case,
            config=config,
        )
