from pydantic import Field
from pydantic_settings import BaseSettings


class FeesConfig(BaseSettings):
    """Configuration for exchange fees used in breakeven calculations."""

    maker: float = Field(default=0.0002, description="Maker fee rate (e.g., 0.0002 for 0.02%)")
    taker: float = Field(default=0.00055, description="Taker fee rate (e.g., 0.00055 for 0.055%)")
    break_even_fee_mode: str = Field(default="taker", description="Fee mode for breakeven calculation: 'maker' or 'taker'")
    break_even_extra_buffer: float = Field(default=0.0, description="Additional buffer to add to the fee rate")

    def get_break_even_fee_rate(self) -> float:
        """Get the fee rate to use for breakeven calculations.

        Returns:
            Combined fee rate including base fee and extra buffer
        """
        base = self.taker if self.break_even_fee_mode == "taker" else self.maker
        return max(0.0, base + self.break_even_extra_buffer)
