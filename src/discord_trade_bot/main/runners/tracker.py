import asyncio
import logging
from typing import Any, final

from discord_trade_bot.core.application.trading.interfaces import ExchangeGatewayProtocol
from discord_trade_bot.infrastructure.taskiq.tasks import process_tracker_event_task

logger = logging.getLogger(__name__)


@final
class PositionTrackerRunner:
    def __init__(self, exchange_gateway: ExchangeGatewayProtocol):
        self._exchange_gateway = exchange_gateway
        self._is_running = False

    async def run(self):
        self._is_running = True
        logger.info("🔄 PositionTracker: Starting WebSocket listener (Lightweight)...")
        while self._is_running:
            try:
                await self._exchange_gateway.listen_user_stream(self._on_ws_update)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ PositionTracker WS error: {e}")
                await asyncio.sleep(5)

    def stop(self):
        self._is_running = False

    async def _on_ws_update(self, event: dict[str, Any]):
        # Filter only necessary events

        if event.get("e") != "ORDER_TRADE_UPDATE":
            return
        order_info = event.get("o", {})
        status = order_info.get("X", "")

        if status in ["FILLED", "Rejected"]:
            logger.info("📡 [WS] FILLED event captured, sending to Taskiq...")
            await process_tracker_event_task.kiq(event)
