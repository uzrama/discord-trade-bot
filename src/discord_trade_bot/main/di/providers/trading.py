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
from discord_trade_bot.infrastructure.exchanges.bybit import BybitFuturesAdapter
from discord_trade_bot.infrastructure.exchanges.composite import CompositeExchangeGateway
from discord_trade_bot.main.config.app import AppConfig
from discord_trade_bot.main.config.yaml.general import AppMode

logger = logging.getLogger(__name__)


@final
class TradingProvider(Provider):
    @provide(scope=Scope.APP)
    async def get_exchange_composite(self, config: AppConfig) -> AsyncIterable[CompositeExchangeGateway]:
        exchanges = {}

        # Binance
        if config.binance.token and config.binance.secret_key:
            binance_api_key = config.binance.token.get_secret_value()
            binance_secret = config.binance.secret_key.get_secret_value()

            if binance_api_key and binance_secret:
                binance_config = config.yaml.exchanges.get("binance")
                binance_testnet = binance_config.testnet if binance_config and binance_config.testnet is not None else config.yaml.general.mode == AppMode.TESTNET
                exchanges["binance"] = BinanceFuturesAdapter(binance_api_key, binance_secret, testnet=binance_testnet)
                logger.info("✅ Binance exchange configured")
            else:
                logger.warning("⚠️ Binance API keys are empty, skipping Binance exchange")
        else:
            logger.warning("⚠️ Binance API keys not configured, skipping Binance exchange")

        # Bybit
        if config.bybit.token and config.bybit.secret_key:
            bybit_api_key = config.bybit.token.get_secret_value()
            bybit_secret = config.bybit.secret_key.get_secret_value()

            if bybit_api_key and bybit_secret:
                bybit_config = config.yaml.exchanges.get("bybit")
                bybit_testnet = bybit_config.testnet if bybit_config and bybit_config.testnet is not None else config.yaml.general.mode == AppMode.TESTNET
                exchanges["bybit"] = BybitFuturesAdapter(bybit_api_key, bybit_secret, testnet=bybit_testnet)
                logger.info("✅ Bybit exchange configured")
            else:
                logger.warning("⚠️ Bybit API keys are empty, skipping Bybit exchange")
        else:
            logger.warning("⚠️ Bybit API keys not configured, skipping Bybit exchange")

        # Validate at least one exchange is configured
        if not exchanges:
            raise RuntimeError("❌ No exchange adapters configured. Please provide API keys for at least one exchange (Binance or Bybit) in your .env file.")

        logger.info(f"📊 Active exchanges: {', '.join(exchanges.keys())}")

        composite = CompositeExchangeGateway(exchanges)
        yield composite
        await composite.close()

    @provide(scope=Scope.APP)
    def get_process_tracker_event_use_case(
        self,
        exchange_registry: ExchangeRegistryProtocol,
        state_repository: StateRepositoryProtocol,
        notification_gateway: NotificationGatewayProtocol,
    ) -> ProcessTrackerEventUseCase:
        return ProcessTrackerEventUseCase(
            exchange_registry=exchange_registry,
            state_repository=state_repository,
            notification_gateway=notification_gateway,
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
    ) -> OpenPositionUseCase:
        return OpenPositionUseCase(exchange_registry=exchange_registry, notification_gateway=notification_gateway)

    @provide(scope=Scope.APP)
    def get_process_signal_use_case(
        self,
        config: AppConfig,
        exchange_gateway: ExchangeGatewayProtocol,
        notification_gateway: NotificationGatewayProtocol,
        state_repository: StateRepositoryProtocol,
        open_position_use_case: OpenPositionUseCase,
    ) -> ProcessSignalUseCase:
        return ProcessSignalUseCase(
            exchange_gateway=exchange_gateway,
            notification_gateway=notification_gateway,
            state_repository=state_repository,
            open_position_use_case=open_position_use_case,
            config=config,
        )
