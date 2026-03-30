import logging

from dishka.integrations.taskiq import setup_dishka
from taskiq import TaskiqEvents

from discord_trade_bot.main.config.app import AppConfig
from discord_trade_bot.main.config.logging import setup_logging
from discord_trade_bot.main.di.setup import setup_di

from .broker import broker

logger = logging.getLogger(__name__)


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def startup_event(state):
    setup_logging()
    logger.info("Starting Taskiq worker...")

    container = setup_di()
    await container.get(AppConfig)
    setup_dishka(container=container, broker=broker)
    state.dishka_container = container


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def shutdown_event(state):
    logger.info("Shutting down Taskiq worker...")
    if hasattr(state, "dishka_container"):
        await state.dishka_container.close()
