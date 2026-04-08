from dataclasses import dataclass, field
from datetime import UTC, datetime

from discord_trade_bot.core.domain.value_objects.trading import EntryMode, SignalType, TradeSide


def _now_utc() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True, kw_only=True)
class ParsedSignalEntity:
    source_id: str
    message_id: str
    message_hash: str
    message_text: str
    symbol: str | None = None
    side: TradeSide | None = None
    entry_mode: EntryMode | None = None
    entry_price: float | None = None
    leverage: int | None = None
    stop_loss: float | None = None
    take_profits: list[float] = field(default_factory=list)
    signal_type: SignalType = SignalType.UNKNOWN
    is_signal: bool = False
    seen_at: datetime = field(default_factory=_now_utc)
    contains_tp1_hit: bool = False
    entry_triggered: bool = False
    awaiting_entry: bool = False
    enter_on_trigger: bool = False
