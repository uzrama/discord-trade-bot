from dataclasses import dataclass, field
from datetime import UTC, datetime

from discord_trade_bot.core.domain.value_objects.trading import (
    EntryMode,
    SignalStatus,
    TPDistributionRow,
    TradeSide,
)


def _now_utc() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True, kw_only=True)
class ActiveSignalEntity:
    source_id: str
    message_id: str
    symbol: str
    side: TradeSide
    exchange: str
    qty: float
    entry_mode: EntryMode
    status: SignalStatus
    message_hash: str
    order_id: str | None = None
    entry_price: float | None = None
    leverage: int | None = None
    created_at: datetime = field(default_factory=_now_utc)
    updated_at: datetime = field(default_factory=_now_utc)
    stop_loss: float | None = None
    take_profits: list[float] = field(default_factory=list)
    tp_distribution: list[TPDistributionRow] = field(default_factory=list)
    tp1_hit: bool = False
    breakeven_applied: bool = False
    skip_reason: str | None = None
    entry_price_effective: float | None = None
    temporary_stop: float | None = None
    exchange_stop_order_id: str | None = None
    entry_partially_filled: bool = False
    pending_entry_remaining_qty: float = 0.0
    needs_message_watch: bool = False

    def update_timestamp(self) -> None:
        self.updated_at = datetime.now(UTC)
