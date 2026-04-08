import asyncio
import logging
from typing import Protocol, TypeVar

from discord_trade_bot.main.config.logging import setup_logging
from discord_trade_bot.main.di import setup_di

logger = logging.getLogger(__name__)


class ApplicationRunner(Protocol):
    async def run(self) -> None: ...


TRunner = TypeVar("TRunner", bound=ApplicationRunner)


async def run_application(runner_type: type[TRunner], process_name: str) -> None:
    """
    Universal application loader that handles:
    1. Logging setup
    2. DI container initialization and cleanup
    3. Global error handling and graceful shutdown
    """
    setup_logging()
    container = setup_di()
    try:
        # Resolve the requested runner (Discord or Tracker) from the container
        runner = await container.get(runner_type)
        logger.info(f"🟢 Starting: {process_name}...")
        await runner.run()
    except asyncio.CancelledError:
        logger.info(f"🛑 Stopping: {process_name} (Cancelled)...")
    except Exception as e:
        logger.exception(f"❌ Fatal error in {process_name}: {e}")
    finally:
        logger.info(f"🧹 Cleaning up resources for {process_name}...")
        await container.close()
