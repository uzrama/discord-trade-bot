from typing import Any

from dishka.integrations.taskiq import FromDishka, inject

from discord_trade_bot.core.application.signal.dto import ProcessSignalDTO
from discord_trade_bot.core.application.signal.use_cases import ProcessSignalUseCase
from discord_trade_bot.core.application.signal.use_cases.update import SignalUpdateUseCase
from discord_trade_bot.core.application.trading.use_cases import ProcessTrackerEventUseCase
from discord_trade_bot.infrastructure.taskiq.broker import broker


@broker.task(retry_count=1)
@inject
async def process_signal_task(
    source_id: str,
    channel_id: str,
    message_id: str,
    text: str,
    use_case: FromDishka[ProcessSignalUseCase],
) -> None:
    # Reconstruct DTO from parameters
    dto = ProcessSignalDTO(source_id=source_id, channel_id=channel_id, message_id=message_id, text=text)
    await use_case.execute(dto)


@broker.task(retry_count=1)
@inject
async def update_signal_task(
    source_id: str,
    channel_id: str,
    message_id: str,
    text: str,
    use_case: FromDishka[SignalUpdateUseCase],
) -> None:
    # Reconstruct DTO from parameters
    dto = ProcessSignalDTO(source_id=source_id, channel_id=channel_id, message_id=message_id, text=text)
    await use_case.execute(dto)


@broker.task(retry_count=1)
@inject
async def process_tracker_event_task(
    event: dict[str, Any],
    use_case: FromDishka[ProcessTrackerEventUseCase],
) -> None:
    await use_case.execute(event)
