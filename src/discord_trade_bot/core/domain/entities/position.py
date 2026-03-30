import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from discord_trade_bot.core.domain.value_objects.trading import (
    PositionStatus,
    TPDistributionRow,
    TradeSide,
)


def _now_utc() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True, kw_only=True)
class ActivePositionEntity:
    id: str | None = None
    symbol: str
    source_id: str
    message_id: str
    exchange: str
    side: TradeSide
    qty: float
    entry_price: float
    opened_at: datetime = field(default_factory=_now_utc)
    stop_loss: float | None = None
    take_profits: list[float] = field(default_factory=list)
    tp_distribution: list[TPDistributionRow] = field(default_factory=list)
    tp_order_ids: dict[str, float] = field(default_factory=dict)
    sl_order_id: str | None = None
    tp_index_hit: int = 0
    tp_hits: list[dict[str, Any]] = field(default_factory=list)
    tp_qty_basis: float = 0.0
    closed_qty: float = 0.0
    remaining_qty: float = 0.0
    initial_notional_usd: float = 0.0
    closed_notional_usd: float = 0.0
    realized_pnl_usdt: float = 0.0
    break_even_price: float | None = None
    break_even_stop_price: float | None = None
    reentry_order_id: str | None = None
    reentry_qty: float = 0.0
    breakeven_applied: bool = False
    status: PositionStatus = PositionStatus.OPEN
    order_id: str | None = None

    # Fields for tracking signal updates (like bot_fixed)
    message_hash: str | None = None
    needs_signal_stop_update: bool = False
    needs_signal_tp_update: bool = False
    temporary_stop: float | None = None

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())
