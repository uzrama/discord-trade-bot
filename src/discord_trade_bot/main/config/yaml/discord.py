from pydantic import BaseModel, Field, field_validator, model_validator


class TpDistribution(BaseModel):
    label: str
    close_pct: float


class ExchangeSettings(BaseModel):
    """Configuration for a single exchange within a watch source."""

    name: str  # e.g., "l", "l2", "l3", "l4", "mark"
    position_size_pct: float

    @field_validator("position_size_pct")
    @classmethod
    def validate_position_size(cls, v: float) -> float:
        if v < 0.1 or v > 100:
            raise ValueError(f"position_size_pct must be between 0.1 and 100, got {v}")
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Exchange name cannot be empty")
        return v.strip()


class Source(BaseModel):
    source_id: str
    enabled: bool = True
    channel_id: int
    exchanges: list[ExchangeSettings]
    fixed_leverage: int
    free_balance_pct: float = 10.0
    default_sl_percent: float
    tp_distributions: dict[int, list[TpDistribution]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_exchanges(self):
        """Validate that at least one exchange is configured."""
        if not self.exchanges:
            raise ValueError(f"At least one exchange must be configured for source '{self.source_id}'")

        # Check for duplicate exchange names
        names = [ex.name for ex in self.exchanges]
        if len(names) != len(set(names)):
            duplicates = [name for name in names if names.count(name) > 1]
            raise ValueError(f"Duplicate exchange names in source '{self.source_id}': {set(duplicates)}")

        return self


class DiscordYamlConfig(BaseModel):
    watch_sources: list[Source] = Field(default_factory=list)
