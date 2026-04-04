from pydantic import BaseModel, Field, model_validator


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
    position_size_pct: float
    default_sl_percent: float
    tp_distributions: dict[int, list[TpDistribution]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_position_sizing(self):
        """Validate that required position sizing parameters are provided."""

        if self.position_size_pct < 0.1 or self.position_size_pct > 100:
            raise ValueError(f"position_size_pct must be between 1 and 100 for source '{self.source_id}'")

        return self


class DiscordYamlConfig(BaseModel):
    watch_sources: list[Source] = Field(default_factory=list)
