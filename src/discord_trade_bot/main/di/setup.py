import logging

from dishka import AsyncContainer, make_async_container

from .providers.config import ConfigProvider
from .providers.discord import DiscordProvider
from .providers.notification import NotificationProvider
from .providers.state import StateProvider
from .providers.taskiq import TaskiqProvider
from .providers.tracker import TrackerProvider
from .providers.trading import TradingProvider

logger = logging.getLogger(__name__)


def setup_di() -> AsyncContainer:
    logger.info("Initializing DI Container...")
    _container = make_async_container(
        ConfigProvider(),
        DiscordProvider(),
        NotificationProvider(),
        StateProvider(),
        TrackerProvider(),
        TradingProvider(),
        TaskiqProvider(),
    )
    return _container
