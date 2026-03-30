from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TradeSettingsDTO:
    exchange: str
    fixed_leverage: int
    free_balance_pct: float
    default_sl_percent: float | None = None
    tp_distribution: dict[int, list[dict[str, Any]]] = field(default_factory=dict)


@dataclass(slots=True)
class OpenPositionResultDTO:
    success: bool
    reason: str | None = None
    order: dict[str, Any] | None = None
    sl_tp_res: dict[str, Any] | None = None
    qty: float = 0.0
    entry_price: float = 0.0
    final_sl: float | None = None
    exchange_name: str | None = None
    pending: bool = False  # True if limit order placed, False if market order filled
