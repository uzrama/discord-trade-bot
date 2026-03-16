from pydantic import SecretStr

from discord_trade_bot.main.config.env.base import EnvSettings


class BinanceConfig(EnvSettings, env_prefix="BINANCE_"):
    token: SecretStr | None = None
    secret_key: SecretStr | None = None
