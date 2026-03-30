from dataclasses import dataclass
from enum import StrEnum


class TradeSide(StrEnum):
    LONG = "long"
    SHORT = "short"


class EntryMode(StrEnum):
    CMP = "cmp"
    EXACT_PRICE = "exact_price"


class SignalStatus(StrEnum):
    WAITING_UPDATE = "waiting_update"
    SLTP_ATTACHED = "sltp_attached"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"


class PositionStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    PARTIALLY_FILLED = "partially_filled"
    WAITING_UPDATE = "waiting_update"  # Position opened but waiting for SL/TP from signal update


class SignalType(StrEnum):
    """Type of trading signal."""

    UNKNOWN = "unknown"
    PRIMARY_SIGNAL = "primary_signal"
    SIGNAL_UPDATE = "signal_update"


class BreakevenMoveResult(StrEnum):
    """Result of attempting to move SL to breakeven."""

    SUCCESS = "success"
    SUCCESS_FALLBACK = "success_fallback"
    POSITION_CLOSED = "position_closed"
    POSITION_ALREADY_CLOSED = "position_already_closed"


@dataclass(slots=True, kw_only=True)
class TPDistributionRow:
    label: str
    close_pct: float
