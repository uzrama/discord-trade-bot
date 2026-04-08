from typing import ClassVar

from pydantic import BaseModel, SecretStr, field_validator
from pydantic_settings import SettingsConfigDict

from discord_trade_bot.main.config.env.base import EnvSettings


class ExchangeAccount(BaseModel):
    """Single exchange account credentials."""

    name: str
    token: SecretStr
    secret_key: SecretStr

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate that name is lowercase and alphanumeric."""
        if not v:
            raise ValueError("Account name cannot be empty")
        return v


class ExchangesConfig(EnvSettings, env_prefix="EXCHANGES_"):
    """Configuration for multiple exchange accounts loaded from .env file.

    Supports JSON array format in .env:
        EXCHANGES_BYBIT_ACCOUNTS=[{"name":"bybit1","token":"key1","secret_key":"secret1"}]
        EXCHANGES_BINANCE_ACCOUNTS=[{"name":"binance1","token":"key1","secret_key":"secret1"}]

    Or empty lists if no accounts configured:
        EXCHANGES_BYBIT_ACCOUNTS=[]
    """

    bybit_accounts: list[ExchangeAccount] = []
    binance_accounts: list[ExchangeAccount] = []

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    @field_validator("bybit_accounts", "binance_accounts")
    @classmethod
    def validate_unique_names(cls, accounts: list[ExchangeAccount]) -> list[ExchangeAccount]:
        """Ensure all account names are unique."""
        names = [acc.name for acc in accounts]
        if len(names) != len(set(names)):
            duplicates = [name for name in names if names.count(name) > 1]
            raise ValueError(f"Duplicate account names found: {set(duplicates)}")
        return accounts
