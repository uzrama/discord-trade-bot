from pydantic import BaseModel, Field


class TpDistribution(BaseModel):
    label: str
    close_pct: float


class Source(BaseModel):
    source_id: str
    enabled: bool = True
    channel_id: int
    exchange: str = "binance"
    fixed_leverage: int
    free_balance_pct: float = 10.0
    position_size_pct: float = 10.0
    stale_signal_seconds: int = 120
    max_price_deviation_pct: float = 2.0
    default_sl_percent: float
    move_to_breakeven_on_tp1: bool = True
    cancel_reentry_on_tp2: bool = True
    place_reentry_after_tp1: bool = True
    move_stop_to_tp1_on_tp3: bool = True
    tp_distribution: list[TpDistribution] = Field(default_factory=list)


class DiscordYamlConfig(BaseModel):
    watch_sources: list[Source] = Field(default_factory=list)
