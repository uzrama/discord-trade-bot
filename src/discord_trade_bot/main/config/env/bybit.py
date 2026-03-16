from pydantic import SecretStr

from discord_trade_bot.main.config.env.base import EnvSettings


class BybitConfig(EnvSettings, env_prefix="BYBIT_"):
    token: SecretStr | None = None
    secret_key: SecretStr | None = None
